"""Attendance correction requests.

Employees never edit attendance directly. They ask for a correction of one day; the attendance
record changes only when an administrator approves, and every decision is audited with the original
and corrected values.

Rules
-----
* One pending request per employee and day (database constraint + friendly validation).
* The date must be today or earlier, on or after the joining date, within
  ``settings.ATTENDANCE_CORRECTION_WINDOW_DAYS`` and in a month whose payroll is not finalised.
* Requested times may not be in the future; check-out must be after check-in and within 24 hours
  (check-out may fall on the next day for overnight shifts).
* MISSED_CHECK_IN needs a check-in time and no recorded check-in; MISSED_CHECK_OUT needs a recorded
  check-in, no check-out and a check-out time; WRONG_TIMES needs a recorded check-in and at least one
  changed time; MISSED_DAY needs no recorded check-in and both times.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit import record_audit
from .models import AttendanceCorrectionRequest as Correction, AttendanceRecord, Employee
from .notifications import notify_admins, notify_user
from .pagination import maybe_paginate
from .permissions import IsAdminUserRole
from .utils import is_admin_user

MAX_SHIFT = timedelta(hours=24)


def window_days():
    return int(getattr(settings, 'ATTENDANCE_CORRECTION_WINDOW_DAYS', 60))


def _aware(day, value):
    return timezone.make_aware(datetime.combine(day, value), timezone.get_current_timezone())


def _clock(value):
    return timezone.localtime(value).strftime('%H:%M') if value else '—'


def _clock_full(value):
    return timezone.localtime(value).strftime('%d %b %H:%M') if value else '—'


class CorrectionSerializer(serializers.ModelSerializer):
    employee_user_id = serializers.ReadOnlyField(source='employee_id')
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()
    correction_type_label = serializers.CharField(source='get_correction_type_display', read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    current_check_in = serializers.SerializerMethodField()
    current_check_out = serializers.SerializerMethodField()
    corrected_check_in = serializers.SerializerMethodField()
    corrected_check_out = serializers.SerializerMethodField()

    class Meta:
        model = Correction
        fields = [
            'id', 'employee_user_id', 'employee_name', 'employee_code', 'department', 'date', 'correction_type',
            'correction_type_label', 'requested_check_in', 'requested_check_out', 'original_check_in',
            'original_check_out', 'current_check_in', 'current_check_out', 'corrected_check_in', 'corrected_check_out',
            'reason', 'status', 'review_note', 'reviewed_by_name', 'reviewed_at', 'created_at',
        ]
        read_only_fields = fields

    def _employee(self, obj):
        return getattr(obj.employee, 'employee', None)

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() or obj.employee.username

    def get_employee_code(self, obj):
        employee = self._employee(obj)
        return employee.employee_id if employee else ''

    def get_department(self, obj):
        employee = self._employee(obj)
        return employee.department if employee else ''

    def get_reviewed_by_name(self, obj):
        return (obj.reviewed_by.get_full_name() or obj.reviewed_by.username) if obj.reviewed_by else ''

    def _current(self, obj):
        return obj.attendance if obj.attendance_id else None

    def get_current_check_in(self, obj):
        record = self._current(obj)
        return record.check_in_at if record else None

    def get_current_check_out(self, obj):
        record = self._current(obj)
        return record.check_out_at if record else None

    def get_corrected_check_in(self, obj):
        return obj.requested_check_in or obj.original_check_in

    def get_corrected_check_out(self, obj):
        return obj.requested_check_out or obj.original_check_out


class CorrectionCreateSerializer(serializers.Serializer):
    date = serializers.DateField()
    correction_type = serializers.ChoiceField(choices=Correction.TYPE_CHOICES)
    check_in = serializers.TimeField(required=False, allow_null=True)
    check_out = serializers.TimeField(required=False, allow_null=True)
    check_out_next_day = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(max_length=1000, trim_whitespace=True)

    def validate_reason(self, value):
        if len(value.strip()) < 5:
            raise serializers.ValidationError('Explain the correction in a few words.')
        return value.strip()

    def validate(self, data):
        user = self.context['request'].user
        day = data['date']
        today = timezone.localdate()
        now = timezone.now()
        kind = data['correction_type']
        errors = {}

        if day > today:
            raise serializers.ValidationError({'date': 'You cannot request a correction for a future date.'})
        if day < today - timedelta(days=window_days()):
            raise serializers.ValidationError({'date': f'Corrections can only be requested for the last {window_days()} days.'})
        employee = Employee.objects.filter(user=user).first()
        if employee is None:
            raise serializers.ValidationError({'detail': 'Only employees with an employee record can request corrections.'})
        if day < employee.joining_date:
            raise serializers.ValidationError({'date': 'This date is before your joining date.'})
        from workforce.services import payroll_locked
        if payroll_locked(user, day):
            raise serializers.ValidationError({'date': 'Payroll for this month is already finalised, so its attendance can no longer change. Contact an administrator.'})
        if Correction.objects.filter(employee=user, date=day, status=Correction.PENDING).exists():
            raise serializers.ValidationError({'date': 'You already have a pending correction request for this date. Cancel it first to send a new one.'})

        record = AttendanceRecord.objects.filter(employee=user, date=day).first()
        has_in = bool(record and record.check_in_at)
        has_out = bool(record and record.check_out_at)
        check_in = _aware(day, data['check_in']) if data.get('check_in') else None
        check_out = None
        if data.get('check_out'):
            check_out = _aware(day + timedelta(days=1) if data.get('check_out_next_day') else day, data['check_out'])

        if kind == Correction.MISSED_CHECK_IN:
            if has_in:
                errors['correction_type'] = 'A check-in is already recorded for this day. Choose "Incorrect check-in or check-out time".'
            if not check_in:
                errors['check_in'] = 'Enter the time you started work.'
        elif kind == Correction.MISSED_CHECK_OUT:
            if not has_in:
                errors['correction_type'] = 'There is no check-in for this day. Choose "Worked but no attendance recorded" or "Missed check-in".'
            elif has_out:
                errors['correction_type'] = 'A check-out is already recorded. Choose "Incorrect check-in or check-out time".'
            if not check_out:
                errors['check_out'] = 'Enter the time you finished work.'
            check_in = None
        elif kind == Correction.WRONG_TIMES:
            if not has_in:
                errors['correction_type'] = 'There is no attendance recorded for this day to correct.'
            if not check_in and not check_out:
                errors['check_in'] = 'Enter the correct check-in time, check-out time, or both.'
            elif record and check_in == record.check_in_at and check_out in (None, record.check_out_at):
                errors['check_in'] = 'These times are the same as the recorded ones.'
        elif kind == Correction.MISSED_DAY:
            if has_in:
                errors['correction_type'] = 'Attendance is already recorded for this day. Choose "Incorrect check-in or check-out time".'
            if not check_in:
                errors['check_in'] = 'Enter the time you started work.'
            if not check_out:
                errors['check_out'] = 'Enter the time you finished work.'
        if errors:
            raise serializers.ValidationError(errors)

        for name, value in (('check_in', check_in), ('check_out', check_out)):
            if value and value > now:
                raise serializers.ValidationError({name: 'This time is in the future.'})
        effective_in = check_in or (record.check_in_at if record else None)
        effective_out = check_out or (record.check_out_at if record else None)
        if effective_in and effective_out:
            if effective_out <= effective_in:
                raise serializers.ValidationError({'check_out': 'Check-out must be after check-in. Tick "next day" for an overnight shift.'})
            if effective_out - effective_in > MAX_SHIFT:
                raise serializers.ValidationError({'check_out': 'Check-out must be within 24 hours of check-in.'})
        data.update({'record': record, 'requested_check_in': check_in, 'requested_check_out': check_out})
        return data


def _describe_change(correction, record_in, record_out):
    parts = []
    if correction.requested_check_in:
        parts.append(f'check-in {_clock(record_in)} → {_clock(correction.requested_check_in)}')
    if correction.requested_check_out:
        parts.append(f'check-out {_clock_full(record_out) if record_out else "—"} → {_clock_full(correction.requested_check_out)}')
    return ', '.join(parts)


def _queryset(company_id=None):
    return Correction.objects.select_related('employee', 'employee__employee', 'reviewed_by', 'attendance').filter(employee__userprofile__company_id=company_id)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def correction_list_create(request):
    admin = is_admin_user(request.user)
    if request.method == 'GET':
        items = _queryset(request.user.userprofile.company_id)
        params = request.query_params
        if not admin:
            items = items.filter(employee=request.user)
        else:
            if params.get('employee'):
                items = items.filter(employee_id=params['employee']) if str(params['employee']).isdigit() else items.none()
            if params.get('department'):
                items = items.filter(employee__employee__department__iexact=params['department'])
            search = params.get('search', '').strip()
            if search:
                items = items.filter(
                    Q(employee__username__icontains=search) | Q(employee__first_name__icontains=search)
                    | Q(employee__last_name__icontains=search) | Q(employee__employee__employee_id__icontains=search)
                )
        if params.get('status') in dict(Correction.STATUS_CHOICES):
            items = items.filter(status=params['status'])
        if params.get('correction_type') in dict(Correction.TYPE_CHOICES):
            items = items.filter(correction_type=params['correction_type'])
        for param, lookup in (('from', 'date__gte'), ('to', 'date__lte')):
            if params.get(param):
                parsed = parse_date(params[param])
                if parsed is None:
                    return Response({'detail': f'Invalid {param} date. Use YYYY-MM-DD.'}, status=status.HTTP_400_BAD_REQUEST)
                items = items.filter(**{lookup: parsed})
        return maybe_paginate(request, items.order_by('-created_at', '-id'), CorrectionSerializer)

    if admin:
        return Response({'detail': 'Administrators review correction requests; employees submit them.'}, status=status.HTTP_403_FORBIDDEN)
    serializer = CorrectionCreateSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    record = data['record']
    try:
        with transaction.atomic():
            correction = Correction.objects.create(
                employee=request.user, date=data['date'], correction_type=data['correction_type'],
                requested_check_in=data['requested_check_in'], requested_check_out=data['requested_check_out'],
                reason=data['reason'], attendance=record,
                original_check_in=record.check_in_at if record else None,
                original_check_out=record.check_out_at if record else None,
            )
    except IntegrityError:
        return Response({'date': ['You already have a pending correction request for this date.']}, status=status.HTTP_400_BAD_REQUEST)
    notify_admins(
        'CORRECTION', 'Attendance correction requested',
        f'{request.user.username} asked to correct attendance for {correction.date:%d %b %Y} ({correction.get_correction_type_display().lower()}).',
        'admin-corrections.html', actor=request.user,
    )
    return Response(CorrectionSerializer(_queryset(request.user.userprofile.company_id).get(pk=correction.pk)).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def correction_cancel(request, pk):
    with transaction.atomic():
        correction = Correction.objects.select_for_update().filter(pk=pk, employee=request.user, employee__userprofile__company_id=request.user.userprofile.company_id).first()
        if correction is None:
            return Response({'detail': 'Correction request not found.'}, status=status.HTTP_404_NOT_FOUND)
        if correction.status != Correction.PENDING:
            return Response({'detail': 'Only pending requests can be cancelled.'}, status=status.HTTP_409_CONFLICT)
        correction.status = Correction.CANCELLED
        correction.save(update_fields=['status', 'updated_at'])
    notify_admins('CORRECTION', 'Attendance correction cancelled',
                  f'{request.user.username} cancelled the correction request for {correction.date:%d %b %Y}.',
                  'admin-corrections.html', actor=request.user)
    return Response(CorrectionSerializer(_queryset(request.user.userprofile.company_id).get(pk=pk)).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def correction_review(request, pk):
    from workforce.services import late_minutes, payroll_locked, scheduled_start, shift_for

    decision = request.data.get('status')
    note = str(request.data.get('review_note', '')).strip()[:1000]
    if decision not in (Correction.APPROVED, Correction.REJECTED):
        return Response({'status': ['Choose APPROVED or REJECTED.']}, status=status.HTTP_400_BAD_REQUEST)
    if decision == Correction.REJECTED and not note:
        return Response({'review_note': ['Give a reason for rejecting the request.']}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        correction = _queryset(request.user.userprofile.company_id).select_for_update(of=('self',)).filter(pk=pk).first()
        if correction is None:
            return Response({'detail': 'Correction request not found.'}, status=status.HTTP_404_NOT_FOUND)
        if correction.status != Correction.PENDING:
            return Response({'detail': 'This request has already been processed.'}, status=status.HTTP_409_CONFLICT)
        employee = correction.employee
        record = AttendanceRecord.objects.select_for_update().filter(employee=employee, date=correction.date).first()
        before_in = record.check_in_at if record else None
        before_out = record.check_out_at if record else None
        change = _describe_change(correction, before_in, before_out)

        if decision == Correction.APPROVED:
            if payroll_locked(employee, correction.date):
                return Response({'detail': 'Payroll for this month is finalised, so this attendance can no longer be changed. Reject the request instead.'},
                                status=status.HTTP_409_CONFLICT)
            new_in = correction.requested_check_in or before_in
            new_out = correction.requested_check_out or before_out
            if new_in is None:
                return Response({'detail': 'There is no check-in for this day any more, so the correction cannot be applied.'}, status=status.HTTP_409_CONFLICT)
            if new_out and (new_out <= new_in or new_out - new_in > MAX_SHIFT):
                return Response({'detail': 'With the times now recorded, check-out would not be after check-in. Reject the request and ask for a new one.'},
                                status=status.HTTP_409_CONFLICT)
            if record is None:
                record = AttendanceRecord(employee=employee, date=correction.date)
            record.check_in_at, record.check_out_at = new_in, new_out
            if correction.requested_check_in or record.late_minutes is None:
                shift = shift_for(employee, correction.date)
                record.shift = shift
                record.shift_name = shift.name if shift else ''
                record.scheduled_start = scheduled_start(shift, correction.date) if shift else None
                record.late_minutes = late_minutes(shift, correction.date, new_in)
            record.is_corrected = True
            record.save()
            correction.attendance = record

        correction.original_check_in, correction.original_check_out = before_in, before_out
        correction.status = decision
        correction.review_note = note
        correction.reviewed_by = request.user
        correction.reviewed_at = timezone.now()
        correction.save()
        verb = 'Approved' if decision == Correction.APPROVED else 'Rejected'
        record_audit(
            request, 'APPROVE' if decision == Correction.APPROVED else 'REJECT', 'AttendanceCorrection', correction.pk,
            f'{verb} attendance correction for {employee.username} on {correction.date}: {change or "no time change"}. '
            f'Reason: {correction.reason[:80]}{f" Note: {note[:60]}" if note else ""}',
            subject=employee,
        )

    detail = f' Note: {note}' if note else ''
    notify_user(employee, 'CORRECTION', f'Attendance correction {decision.lower()}',
                f'Your correction for {correction.date:%d %b %Y} was {decision.lower()}.{detail}',
                'employee-attendance.html', actor=request.user)
    return Response(CorrectionSerializer(_queryset(request.user.userprofile.company_id).get(pk=pk)).data)

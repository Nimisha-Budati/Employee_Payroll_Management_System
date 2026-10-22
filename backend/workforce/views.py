from datetime import timedelta
from decimal import ROUND_FLOOR, Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.audit import record_audit
from accounts.models import AttendanceRecord, UserProfile
from accounts.notifications import notify_admins, notify_user
from accounts.pagination import StandardPagination, maybe_paginate
from accounts.permissions import IsAdminUserRole
from accounts.utils import is_admin_user

from .models import OvertimeRecord, Shift, ShiftAssignment
from .serializers import (
    OvertimeCreateSerializer, OvertimeRecordSerializer, ShiftAssignmentSerializer, ShiftSerializer,
    overlapping_assignments,
)
from .services import attendance_overtime, default_rate, month_bounds, payroll_locked, shift_for

ADMIN = [IsAuthenticated, IsAdminUserRole]
ACTIVE_OVERTIME = (OvertimeRecord.PENDING, OvertimeRecord.APPROVED, OvertimeRecord.REJECTED)


def _company_id(user):
    return UserProfile.objects.filter(user=user).values_list('company_id', flat=True).first()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _shift_label(shift):
    return f'{shift.name} ({shift.start_time:%H:%M}-{shift.end_time:%H:%M})'


# --- Shifts -----------------------------------------------------------------

@api_view(['GET', 'POST'])
@permission_classes(ADMIN)
def shift_list_create(request):
    company_id = _company_id(request.user)
    context = {'today': timezone.localdate(), 'company_id': company_id}
    if request.method == 'GET':
        shifts = Shift.objects.filter(company_id=company_id)
        if request.query_params.get('active') == 'true':
            shifts = shifts.filter(is_active=True)
        return Response(ShiftSerializer(shifts, many=True, context=context).data)

    serializer = ShiftSerializer(data=request.data, context=context)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        if serializer.validated_data.get('is_default'):
            Shift.objects.filter(company_id=company_id, is_default=True).update(is_default=False)
        shift = serializer.save(company_id=company_id)
        record_audit(request, 'CREATE', 'Shift', shift.pk, f'Created shift {_shift_label(shift)}.')
    return Response(ShiftSerializer(shift, context=context).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes(ADMIN)
def shift_detail(request, pk):
    company_id = _company_id(request.user)
    context = {'today': timezone.localdate(), 'company_id': company_id}
    shift = Shift.objects.filter(pk=pk, company_id=company_id).first()
    if shift is None:
        return Response({'detail': 'Shift not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'GET':
        return Response(ShiftSerializer(shift, context=context).data)
    if request.method == 'DELETE':
        if shift.assignments.exists():
            return Response(
                {'detail': 'This shift has employee assignments, so it is kept for their records. Deactivate it instead.'},
                status=status.HTTP_409_CONFLICT,
            )
        label = _shift_label(shift)
        shift.delete()
        record_audit(request, 'DELETE', 'Shift', pk, f'Deleted shift {label}.')
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = ShiftSerializer(shift, data=request.data, partial=request.method == 'PATCH', context=context)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        if serializer.validated_data.get('is_default'):
            Shift.objects.exclude(pk=shift.pk).filter(company_id=company_id, is_default=True).update(is_default=False)
        if serializer.validated_data.get('is_active') is False:
            serializer.validated_data['is_default'] = False
        shift = serializer.save()
        record_audit(request, 'UPDATE', 'Shift', shift.pk, f'Updated shift {_shift_label(shift)}.')
    return Response(ShiftSerializer(shift, context=context).data)


# --- Shift assignments (employee shift records) -------------------------------

def _assignment_queryset(company_id=None):
    return ShiftAssignment.objects.select_related('shift', 'employee', 'employee__employee').filter(employee__userprofile__company_id=company_id)


@api_view(['GET', 'POST'])
@permission_classes(ADMIN)
def assignment_list_create(request):
    if request.method == 'GET':
        assignments = _assignment_queryset(_company_id(request.user))
        params = request.query_params
        if _int(params.get('employee')):
            assignments = assignments.filter(employee_id=_int(params['employee']))
        if _int(params.get('shift')):
            assignments = assignments.filter(shift_id=_int(params['shift']))
        on = parse_date(params.get('on', '') or '')
        if on:
            assignments = assignments.filter(start_date__lte=on).filter(Q(end_date__isnull=True) | Q(end_date__gte=on))
        search = params.get('search', '').strip()
        if search:
            assignments = assignments.filter(
                Q(employee__username__icontains=search) | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search) | Q(employee__employee__employee_id__icontains=search)
                | Q(shift__name__icontains=search)
            )
        return maybe_paginate(request, assignments, ShiftAssignmentSerializer)

    data = request.data
    raw_ids = data.get('employee_ids')
    if not isinstance(raw_ids, list) or not raw_ids:
        return Response({'employee_ids': ['Choose at least one employee.']}, status=status.HTTP_400_BAD_REQUEST)
    ids = {value for value in (_int(item) for item in raw_ids) if value}
    company_id = _company_id(request.user)
    employees = list(User.objects.filter(pk__in=ids, userprofile__role='EMPLOYEE', userprofile__company_id=company_id, is_active=True))
    if len(employees) != len(ids):
        return Response({'employee_ids': ['One or more employees were not found or are inactive.']}, status=status.HTTP_400_BAD_REQUEST)

    serializer = ShiftAssignmentSerializer(data=data, context={'company_id': company_id})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    values = serializer.validated_data
    start, end, shift = values['start_date'], values.get('end_date'), values['shift']
    if shift.company_id != company_id:
        return Response({'shift_id': ['Choose a shift belonging to your company.']}, status=status.HTTP_400_BAD_REQUEST)
    replace = bool(data.get('replace'))

    created = []
    with transaction.atomic():
        for employee in employees:
            conflicts = list(overlapping_assignments(employee, start, end).select_for_update())
            if conflicts and not replace:
                transaction.set_rollback(True)
                return Response({'detail': f'{employee.get_full_name() or employee.username} already has a shift for part of these dates. '
                                           'Tick "Replace current shift" to end the earlier assignment the day before.'},
                                status=status.HTTP_409_CONFLICT)
            for conflict in conflicts:
                if conflict.start_date >= start:
                    transaction.set_rollback(True)
                    return Response({'detail': f'{employee.get_full_name() or employee.username} has a shift starting on or after '
                                               f'{start}. Edit or delete that assignment first.'},
                                    status=status.HTTP_409_CONFLICT)
                conflict.end_date = start - timedelta(days=1)
                conflict.save(update_fields=['end_date', 'updated_at'])
            created.append(ShiftAssignment.objects.create(
                employee=employee, shift=shift, start_date=start, end_date=end,
                notes=values.get('notes', ''), assigned_by=request.user,
            ))
        record_audit(request, 'ASSIGN', 'ShiftAssignment', shift.pk,
                     f'Assigned {len(created)} employee(s) to {_shift_label(shift)} from {start}'
                     f'{f" to {end}" if end else ""}.')

    period = f'from {start:%d %b %Y}' + (f' to {end:%d %b %Y}' if end else '')
    for assignment in created:
        notify_user(assignment.employee, 'SHIFT', 'Shift assigned',
                    f'You are on the {_shift_label(shift)} shift {period}.', 'employee-attendance.html', actor=request.user)
    return Response(ShiftAssignmentSerializer(created, many=True).data, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'DELETE'])
@permission_classes(ADMIN)
def assignment_detail(request, pk):
    company_id = _company_id(request.user)
    assignment = _assignment_queryset(company_id).filter(pk=pk).first()
    if assignment is None:
        return Response({'detail': 'Shift assignment not found.'}, status=status.HTTP_404_NOT_FOUND)
    if request.method == 'DELETE':
        summary = f'Removed {assignment.employee.username} from {_shift_label(assignment.shift)} ({assignment.start_date}).'
        assignment.delete()
        record_audit(request, 'DELETE', 'ShiftAssignment', pk, summary)
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = ShiftAssignmentSerializer(assignment, data=request.data, partial=True, context={'company_id': company_id})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    start = serializer.validated_data.get('start_date', assignment.start_date)
    end = serializer.validated_data['end_date'] if 'end_date' in serializer.validated_data else assignment.end_date
    if overlapping_assignments(assignment.employee, start, end, exclude_pk=assignment.pk).exists():
        return Response({'detail': 'These dates overlap another shift assignment for this employee.'}, status=status.HTTP_409_CONFLICT)
    assignment = serializer.save()
    record_audit(request, 'UPDATE', 'ShiftAssignment', pk,
                 f'Updated {assignment.employee.username}: {_shift_label(assignment.shift)} {assignment.start_date} to {assignment.end_date or "open"}.')
    notify_user(assignment.employee, 'SHIFT', 'Shift updated',
                f'Your shift assignment changed: {_shift_label(assignment.shift)} from {assignment.start_date:%d %b %Y}.',
                'employee-attendance.html', actor=request.user)
    return Response(ShiftAssignmentSerializer(assignment).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_shift(request):
    today = timezone.localdate()
    shift = shift_for(request.user, today)
    assignments = _assignment_queryset(_company_id(request.user)).filter(employee=request.user)[:20]
    today_assignment = next((item for item in assignments if item.covers(today)), None)
    return Response({
        'date': today,
        'shift': ShiftSerializer(shift).data if shift else None,
        'source': 'ASSIGNED' if today_assignment else ('DEFAULT' if shift else None),
        'assignments': ShiftAssignmentSerializer(assignments, many=True).data,
    })


# --- Overtime ---------------------------------------------------------------

def _overtime_queryset(company_id=None):
    return OvertimeRecord.objects.select_related('employee', 'employee__employee', 'reviewed_by').filter(employee__userprofile__company_id=company_id)


def _filtered_overtime(request):
    records = _overtime_queryset(_company_id(request.user))
    admin = is_admin_user(request.user)
    if not admin:
        records = records.filter(employee=request.user)
    params = request.query_params
    if params.get('status') in dict(OvertimeRecord.STATUS_CHOICES):
        records = records.filter(status=params['status'])
    if params.get('source') in dict(OvertimeRecord.SOURCE_CHOICES):
        records = records.filter(source=params['source'])
    year, month = _int(params.get('year')), _int(params.get('month'))
    if year and month and 1 <= month <= 12:
        records = records.filter(date__range=month_bounds(year, month))
    for param, lookup in (('from', 'date__gte'), ('to', 'date__lte')):
        parsed = parse_date(params.get(param, '') or '')
        if parsed:
            records = records.filter(**{lookup: parsed})
    if admin:
        if _int(params.get('employee')):
            records = records.filter(employee_id=_int(params['employee']))
        search = params.get('search', '').strip()
        if search:
            records = records.filter(
                Q(employee__username__icontains=search) | Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search) | Q(employee__employee__employee_id__icontains=search)
            )
    return records


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def overtime_list_create(request):
    admin = is_admin_user(request.user)
    if request.method == 'GET':
        records = _filtered_overtime(request)
        totals = records.aggregate(
            count=Count('id'),
            pending=Count('id', filter=Q(status=OvertimeRecord.PENDING)),
            approved_hours=Sum('hours', filter=Q(status=OvertimeRecord.APPROVED)),
            approved_amount=Sum('amount', filter=Q(status=OvertimeRecord.APPROVED)),
        )
        totals = {key: value if value is not None else 0 for key, value in totals.items()}
        if 'page' in request.query_params:
            paginator = StandardPagination()
            page = paginator.paginate_queryset(records, request)
            response = paginator.get_paginated_response(OvertimeRecordSerializer(page, many=True).data)
            response.data['totals'] = totals
            return response
        return Response({'results': OvertimeRecordSerializer(records, many=True).data, 'totals': totals})

    serializer = OvertimeCreateSerializer(data=request.data, context={'company_id': _company_id(request.user)})
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if admin:
        employee = data.get('employee_id')
        if employee is None:
            return Response({'employee_id': ['Choose an employee.']}, status=status.HTTP_400_BAD_REQUEST)
    else:
        if not hasattr(request.user, 'employee'):
            return Response({'detail': 'Your employee record has not been created yet.'}, status=status.HTTP_409_CONFLICT)
        employee = request.user
    if data['date'] > timezone.localdate():
        return Response({'date': ['Overtime can only be recorded for days that have already started.']}, status=status.HTTP_400_BAD_REQUEST)
    if payroll_locked(employee, data['date']):
        return Response({'detail': 'Payroll for that month has been finalised, so its overtime can no longer change.'}, status=status.HTTP_409_CONFLICT)
    if OvertimeRecord.objects.filter(employee=employee, date=data['date'], status__in=(OvertimeRecord.PENDING, OvertimeRecord.APPROVED)).exists():
        return Response({'date': ['There is already a pending or approved overtime record for this day.']}, status=status.HTTP_400_BAD_REQUEST)

    approve = admin and data.get('approve')
    record = OvertimeRecord.objects.create(
        employee=employee, date=data['date'], hours=data['hours'],
        rate=data['rate'] if admin and data.get('rate') is not None else default_rate(employee),
        reason=data['reason'].strip(), source='MANUAL' if admin else 'REQUEST',
        status=OvertimeRecord.APPROVED if approve else OvertimeRecord.PENDING,
        reviewed_by=request.user if approve else None, reviewed_at=timezone.now() if approve else None,
        created_by=request.user,
    )
    if admin:
        record_audit(request, 'CREATE', 'Overtime', record.pk,
                     f'Recorded {record.hours} h overtime for {employee.username} on {record.date} ({record.get_status_display().lower()}).')
        notify_user(employee, 'OVERTIME', 'Overtime recorded',
                    f'{record.hours} h of overtime on {record.date:%d %b %Y} was recorded ({record.get_status_display().lower()}).',
                    'overtime.html', actor=request.user)
    else:
        notify_admins('OVERTIME', 'Overtime claim submitted',
                      f'{request.user.username} claimed {record.hours} h of overtime for {record.date:%d %b %Y}.',
                      'overtime.html', actor=request.user)
    return Response(OvertimeRecordSerializer(record).data, status=status.HTTP_201_CREATED)


@api_view(['PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def overtime_detail(request, pk):
    admin = is_admin_user(request.user)
    record = _overtime_queryset(_company_id(request.user)).filter(pk=pk).first()
    if record is None or not (admin or record.employee_id == request.user.pk):
        return Response({'detail': 'Overtime record not found.'}, status=status.HTTP_404_NOT_FOUND)
    if record.status != OvertimeRecord.PENDING:
        return Response({'detail': 'Only pending overtime can be changed.'}, status=status.HTTP_409_CONFLICT)

    if request.method == 'DELETE':
        record.status = OvertimeRecord.CANCELLED
        record.save(update_fields=['status', 'updated_at'])
        if admin:
            record_audit(request, 'CANCEL', 'Overtime', pk, f'Cancelled overtime for {record.employee.username} on {record.date}.')
        return Response(OvertimeRecordSerializer(record).data)

    serializer = OvertimeRecordSerializer(record, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    if not admin:
        serializer.validated_data.pop('rate', None)
    new_date = serializer.validated_data.get('date', record.date)
    if new_date > timezone.localdate():
        return Response({'date': ['Overtime can only be recorded for days that have already started.']}, status=status.HTTP_400_BAD_REQUEST)
    if payroll_locked(record.employee, new_date):
        return Response({'detail': 'Payroll for that month has been finalised.'}, status=status.HTTP_409_CONFLICT)
    if OvertimeRecord.objects.filter(employee=record.employee, date=new_date,
                                     status__in=(OvertimeRecord.PENDING, OvertimeRecord.APPROVED)).exclude(pk=pk).exists():
        return Response({'date': ['There is already a pending or approved overtime record for this day.']}, status=status.HTTP_400_BAD_REQUEST)
    record = serializer.save()
    if admin:
        record_audit(request, 'UPDATE', 'Overtime', pk, f'Edited overtime for {record.employee.username} on {record.date}: {record.hours} h at {record.rate}/h.')
    return Response(OvertimeRecordSerializer(record).data)


@api_view(['PUT'])
@permission_classes(ADMIN)
def overtime_review(request, pk):
    new_status = request.data.get('status')
    note = str(request.data.get('review_note', '')).strip()
    if new_status not in (OvertimeRecord.APPROVED, OvertimeRecord.REJECTED):
        return Response({'detail': 'Status must be APPROVED or REJECTED.'}, status=status.HTTP_400_BAD_REQUEST)
    if new_status == OvertimeRecord.REJECTED and not note:
        return Response({'detail': 'A reason is required when rejecting overtime.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        record = _overtime_queryset(_company_id(request.user)).select_for_update(of=('self',)).filter(pk=pk).first()
        if record is None:
            return Response({'detail': 'Overtime record not found.'}, status=status.HTTP_404_NOT_FOUND)
        if record.status != OvertimeRecord.PENDING:
            return Response({'detail': 'This overtime record has already been processed.'}, status=status.HTTP_400_BAD_REQUEST)
        if payroll_locked(record.employee, record.date):
            return Response({'detail': 'Payroll for that month has been finalised.'}, status=status.HTTP_409_CONFLICT)
        record.status, record.review_note = new_status, note
        record.reviewed_by, record.reviewed_at = request.user, timezone.now()
        record.save()
        record_audit(request, 'APPROVE' if new_status == OvertimeRecord.APPROVED else 'REJECT', 'Overtime', pk,
                     f'{record.get_status_display()} {record.hours} h overtime for {record.employee.username} on {record.date} '
                     f'(amount {record.amount}).', subject=record.employee)
    decision = record.get_status_display().lower()
    notify_user(record.employee, 'OVERTIME', f'Overtime {decision}',
                f'Your {record.hours} h of overtime on {record.date:%d %b %Y} was {decision}.{f" Note: {note}" if note else ""}',
                'overtime.html', actor=request.user)
    return Response(OvertimeRecordSerializer(_overtime_queryset(_company_id(request.user)).get(pk=pk)).data)


def _quarter_hours(hours):
    return (Decimal(hours) * 4).to_integral_value(rounding=ROUND_FLOOR) / 4


@api_view(['POST'])
@permission_classes(ADMIN)
def overtime_generate(request):
    """Create PENDING overtime records from attendance time beyond each employee's standard day."""
    year, month = _int(request.data.get('year')), _int(request.data.get('month'))
    if not year or not month or not 1 <= month <= 12:
        return Response({'detail': 'Provide a valid year and month.'}, status=status.HTTP_400_BAD_REQUEST)
    start, end = month_bounds(year, month)
    end = min(end, timezone.localdate())
    if start > end:
        return Response({'detail': 'That month has not started yet.'}, status=status.HTTP_400_BAD_REQUEST)

    records = AttendanceRecord.objects.select_related('employee', 'shift').filter(
        date__range=(start, end), check_in_at__isnull=False, check_out_at__isnull=False,
        employee__is_active=True, employee__userprofile__role='EMPLOYEE', employee__userprofile__company_id=_company_id(request.user),
    )
    existing = set(OvertimeRecord.objects.filter(employee__userprofile__company_id=_company_id(request.user), date__range=(start, end), status__in=ACTIVE_OVERTIME)
                   .values_list('employee_id', 'date'))
    created = skipped_locked = 0
    with transaction.atomic():
        for record in records:
            hours = _quarter_hours(attendance_overtime(record))
            if hours < Decimal('0.25') or (record.employee_id, record.date) in existing:
                continue
            if payroll_locked(record.employee, record.date):
                skipped_locked += 1
                continue
            OvertimeRecord.objects.create(
                employee=record.employee, date=record.date, hours=min(hours, Decimal('16')),
                rate=default_rate(record.employee), source='ATTENDANCE',
                reason=f'Worked beyond the standard day ({record.shift_name or "standard hours"}).',
                created_by=request.user,
            )
            existing.add((record.employee_id, record.date))
            created += 1
        if created:
            record_audit(request, 'GENERATE', 'Overtime', f'{year}-{month:02d}',
                         f'Generated {created} pending overtime record(s) from attendance for {start:%B %Y}.')
    return Response({'created': created, 'skipped_finalised': skipped_locked},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

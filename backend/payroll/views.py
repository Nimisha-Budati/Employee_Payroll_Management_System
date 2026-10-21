import calendar
import csv
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.audit import record_audit
from accounts.models import Employee
from accounts.notifications import notify_user
from accounts.pagination import StandardPagination
from accounts.permissions import IsAdminUserRole
from accounts.utils import is_admin_user

from .calculator import apply_amounts, build_payslip_values, month_bounds
from .models import Payslip, SalaryStructure
from .pdf import render_payslip_pdf
from .variance import review_is_current
from .serializers import (
    FinalizeSerializer, PayslipAdjustmentSerializer, PayslipSerializer, RunPayrollSerializer,
    SalaryStructureSerializer,
)

ADMIN = [IsAuthenticated, IsAdminUserRole]


def _period_label(year, month):
    return f'{calendar.month_name[month]} {year}'


def _employee_or_404(pk):
    return Employee.objects.select_related('user').filter(pk=pk).first()


# --- Salary structures ------------------------------------------------------

@api_view(['GET'])
@permission_classes(ADMIN)
def salary_structure_list(request):
    """Every employee with their salary structure (or null when none is set yet)."""
    employees = Employee.objects.select_related('user', 'user__salary_structure').order_by('employee_id')
    params = request.query_params
    if params.get('status') in ('ACTIVE', 'INACTIVE'):
        employees = employees.filter(status=params['status'])
    if params.get('configured') == 'false':
        employees = employees.filter(user__salary_structure__isnull=True)
    elif params.get('configured') == 'true':
        employees = employees.filter(user__salary_structure__isnull=False)
    search = params.get('search', '').strip()
    if search:
        employees = employees.filter(
            Q(employee_id__icontains=search) | Q(user__username__icontains=search)
            | Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search)
            | Q(department__icontains=search)
        )

    def serialize(employee):
        try:
            structure = SalaryStructureSerializer(employee.user.salary_structure).data
        except SalaryStructure.DoesNotExist:
            structure = None
        return {
            'employee_pk': employee.pk,
            'employee_id': employee.employee_id,
            'full_name': employee.user.get_full_name() or employee.user.username,
            'department': employee.department,
            'designation': employee.designation,
            'status': employee.status,
            'structure': structure,
        }

    if 'page' in params:
        paginator = StandardPagination()
        page = paginator.paginate_queryset(employees, request)
        return paginator.get_paginated_response([serialize(employee) for employee in page])
    return Response([serialize(employee) for employee in employees])


@api_view(['GET', 'PUT'])
@permission_classes(ADMIN)
def salary_structure_detail(request, employee_pk):
    employee = _employee_or_404(employee_pk)
    if employee is None:
        return Response({'detail': 'Employee not found.'}, status=status.HTTP_404_NOT_FOUND)
    structure = SalaryStructure.objects.filter(employee=employee.user).first()

    if request.method == 'GET':
        if structure is None:
            return Response({'detail': 'No salary structure has been set for this employee.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(SalaryStructureSerializer(structure).data)

    serializer = SalaryStructureSerializer(structure, data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        created = structure is None
        structure = serializer.save(employee=employee.user, updated_by=request.user)
        record_audit(
            request, 'CREATE' if created else 'UPDATE', 'SalaryStructure', employee.pk,
            f'{"Set" if created else "Updated"} salary structure for {employee.employee_id} '
            f'(gross {structure.gross_monthly}/month).', subject=employee.user,
        )
    from accounts.onboarding import refresh as refresh_onboarding
    refresh_onboarding(employee)
    notify_user(
        employee.user, 'EMPLOYEE', 'Salary structure updated',
        'Your salary structure was updated by an administrator.', 'employee-payslips.html', actor=request.user,
    )
    return Response(SalaryStructureSerializer(structure).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['GET'])
def my_salary_structure(request):
    structure = SalaryStructure.objects.filter(employee=request.user).first()
    if structure is None:
        return Response({'detail': 'No salary structure has been set for you yet.'}, status=status.HTTP_404_NOT_FOUND)
    return Response(SalaryStructureSerializer(structure).data)


# --- Payslips ---------------------------------------------------------------

def _payslip_queryset(request):
    """Administrators see every payslip; employees only their own finalised ones."""
    queryset = Payslip.objects.all()
    if not is_admin_user(request.user):
        return queryset.filter(employee=request.user, status=Payslip.PAID)
    return queryset


@api_view(['GET'])
def payslip_list(request):
    queryset = _payslip_queryset(request)
    params = request.query_params
    for field in ('year', 'month'):
        if params.get(field):
            try:
                queryset = queryset.filter(**{field: int(params[field])})
            except ValueError:
                return Response({'detail': f'Invalid {field}.'}, status=status.HTTP_400_BAD_REQUEST)
    if params.get('status') in (Payslip.DRAFT, Payslip.PAID):
        queryset = queryset.filter(status=params['status'])
    if is_admin_user(request.user):
        search = params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(employee_code__icontains=search) | Q(employee_name__icontains=search)
                | Q(department__icontains=search)
            )
        if params.get('department'):
            queryset = queryset.filter(department__iexact=params['department'])

    totals = queryset.aggregate(
        count=Count('id'), gross=Sum('gross_earnings'), deductions=Sum('total_deductions'), net=Sum('net_salary'),
        drafts=Count('id', filter=Q(status=Payslip.DRAFT)), paid=Count('id', filter=Q(status=Payslip.PAID)),
    )
    totals = {key: (value if value is not None else 0) for key, value in totals.items()}

    if 'page' in params:
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request)
        response = paginator.get_paginated_response(PayslipSerializer(page, many=True).data)
        response.data['totals'] = totals
        return response
    return Response({'results': PayslipSerializer(queryset, many=True).data, 'totals': totals})


def _payslip_for_admin(pk, for_update=False):
    queryset = Payslip.objects.select_for_update() if for_update else Payslip.objects
    return queryset.filter(pk=pk).first()


@api_view(['GET', 'PATCH', 'DELETE'])
def payslip_detail(request, pk):
    payslip = Payslip.objects.filter(pk=pk).first()
    admin = is_admin_user(request.user)
    if payslip is None or not (admin or (payslip.employee_id == request.user.pk and payslip.status == Payslip.PAID)):
        return Response({'detail': 'Payslip not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(PayslipSerializer(payslip).data)

    if not admin:
        return Response({'detail': 'Access denied. Administrator access is required.'}, status=status.HTTP_403_FORBIDDEN)
    if payslip.status != Payslip.DRAFT:
        return Response({'detail': 'Only draft payslips can be changed.'}, status=status.HTTP_409_CONFLICT)

    if request.method == 'DELETE':
        label = f'{payslip.employee_code} {_period_label(payslip.year, payslip.month)}'
        payslip.delete()
        record_audit(request, 'DELETE', 'Payslip', pk, f'Deleted draft payslip {label}.')
        return Response(status=status.HTTP_204_NO_CONTENT)

    serializer = PayslipAdjustmentSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    if 'lop_days' in data and data['lop_days'] > payslip.working_days:
        return Response({'lop_days': [f'Cannot exceed the {payslip.working_days} working days in the month.']}, status=status.HTTP_400_BAD_REQUEST)
    for field, value in data.items():
        setattr(payslip, field, value)
    apply_amounts(payslip)
    if payslip.net_salary < 0:
        return Response({'detail': 'These adjustments would make the net salary negative.'}, status=status.HTTP_400_BAD_REQUEST)
    payslip.save()
    record_audit(
        request, 'ADJUST', 'Payslip', pk,
        f'Adjusted draft payslip {payslip.employee_code} {_period_label(payslip.year, payslip.month)}: '
        f'{", ".join(sorted(data))}.', subject=payslip.employee,
    )
    return Response(PayslipSerializer(payslip).data)


@api_view(['POST'])
@permission_classes(ADMIN)
def payslip_recalculate(request, pk):
    """Rebuild a draft payslip from the current salary structure and attendance, discarding manual edits."""
    with transaction.atomic():
        payslip = _payslip_for_admin(pk, for_update=True)
        if payslip is None:
            return Response({'detail': 'Payslip not found.'}, status=status.HTTP_404_NOT_FOUND)
        if payslip.status != Payslip.DRAFT:
            return Response({'detail': 'Only draft payslips can be recalculated.'}, status=status.HTTP_409_CONFLICT)
        employee = Employee.objects.select_related('user').filter(user_id=payslip.employee_id).first()
        structure = SalaryStructure.objects.filter(employee_id=payslip.employee_id).first()
        if employee is None or structure is None:
            return Response({'detail': 'This employee no longer has a salary structure.'}, status=status.HTTP_409_CONFLICT)
        values = build_payslip_values(employee, structure, payslip.year, payslip.month)
        if values['net_salary'] < 0:
            return Response({'detail': 'Deductions exceed earnings for this employee.'}, status=status.HTTP_400_BAD_REQUEST)
        for field, value in values.items():
            setattr(payslip, field, value)
        payslip.save()
        record_audit(request, 'RECALCULATE', 'Payslip', pk,
                     f'Recalculated draft payslip {payslip.employee_code} {_period_label(payslip.year, payslip.month)}.')
    return Response(PayslipSerializer(payslip).data)


@api_view(['POST'])
@permission_classes(ADMIN)
def payroll_run(request):
    serializer = RunPayrollSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    year, month = serializer.validated_data['year'], serializer.validated_data['month']
    lop_mode = serializer.validated_data['lop_mode']
    _, period_end = month_bounds(year, month)
    if period_end >= timezone.localdate():
        return Response(
            {'detail': f'Payroll for {_period_label(year, month)} can only be run after the month has ended.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    employees = Employee.objects.filter(status='ACTIVE', user__is_active=True).select_related('user', 'user__salary_structure')
    if serializer.validated_data.get('employee_ids'):
        employees = employees.filter(pk__in=serializer.validated_data['employee_ids'])
    employees = list(employees.order_by('employee_id'))
    existing = set(Payslip.objects.filter(year=year, month=month).values_list('employee_id', flat=True))

    created, skipped = [], []
    with transaction.atomic():
        for employee in employees:
            label = f'{employee.employee_id} - {employee.user.get_full_name() or employee.user.username}'
            if employee.user_id in existing:
                skipped.append({'employee': label, 'reason': 'A payslip already exists for this month.'})
                continue
            try:
                structure = employee.user.salary_structure
            except SalaryStructure.DoesNotExist:
                skipped.append({'employee': label, 'reason': 'No salary structure has been set.'})
                continue
            if employee.joining_date > period_end:
                skipped.append({'employee': label, 'reason': 'Joined after this month.'})
                continue
            values = build_payslip_values(employee, structure, year, month, lop_mode)
            if values['net_salary'] < 0:
                skipped.append({'employee': label, 'reason': 'Deductions exceed earnings.'})
                continue
            payslip = Payslip.objects.create(
                employee=employee.user, year=year, month=month, generated_by=request.user, **values,
            )
            created.append(payslip.pk)
        if created:
            record_audit(request, 'RUN', 'Payroll', f'{year}-{month:02d}',
                         f'Generated {len(created)} draft payslip(s) for {_period_label(year, month)} '
                         f'(attendance mode: {lop_mode}).')

    from workforce.models import OvertimeRecord

    pending_overtime = OvertimeRecord.objects.filter(
        status=OvertimeRecord.PENDING, date__year=year, date__month=month,
    ).count()
    return Response(
        {'period': _period_label(year, month), 'created': len(created), 'skipped': skipped,
         'pending_overtime': pending_overtime},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes(ADMIN)
def payroll_finalize(request):
    serializer = FinalizeSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    year, month = serializer.validated_data['year'], serializer.validated_data['month']

    with transaction.atomic():
        drafts = Payslip.objects.select_for_update().filter(year=year, month=month, status=Payslip.DRAFT)
        if serializer.validated_data.get('payslip_ids'):
            drafts = drafts.filter(pk__in=serializer.validated_data['payslip_ids'])
        drafts = list(drafts.select_related('employee'))
        if not drafts:
            return Response({'detail': 'There are no draft payslips to finalise.'}, status=status.HTTP_400_BAD_REQUEST)
        if not review_is_current(year, month):
            return Response({'detail': f'Review the variance preview for {_period_label(year, month)} before finalising. '
                                       'Drafts changed after the last review need a new review.',
                             'code': 'review_required'}, status=status.HTTP_409_CONFLICT)
        now = timezone.now()
        Payslip.objects.filter(pk__in=[payslip.pk for payslip in drafts]).update(status=Payslip.PAID, paid_at=now, updated_at=now)
        record_audit(request, 'FINALIZE', 'Payroll', f'{year}-{month:02d}',
                     f'Finalised {len(drafts)} payslip(s) for {_period_label(year, month)} as paid.')

    for payslip in drafts:
        notify_user(
            payslip.employee, 'EMPLOYEE', 'Payslip available',
            f'Your payslip for {_period_label(year, month)} is ready.', 'employee-payslips.html', actor=request.user,
        )
    return Response({'finalized': len(drafts), 'period': _period_label(year, month)})


@api_view(['GET'])
def payslip_pdf(request, pk):
    payslip = Payslip.objects.filter(pk=pk).first()
    admin = is_admin_user(request.user)
    if payslip is None or not (admin or (payslip.employee_id == request.user.pk and payslip.status == Payslip.PAID)):
        return Response({'detail': 'Payslip not found.'}, status=status.HTTP_404_NOT_FOUND)
    filename = f'payslip_{payslip.employee_code}_{payslip.year}-{payslip.month:02d}.pdf'
    response = HttpResponse(render_payslip_pdf(payslip), content_type='application/pdf')
    disposition = 'inline' if request.query_params.get('inline') else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    response['Cache-Control'] = 'private, no-store'
    return response


# --- Reports and exports ----------------------------------------------------

def _safe_cell(value):
    """Neutralise spreadsheet formulas in exported text."""
    text = str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


@api_view(['GET'])
@permission_classes(ADMIN)
def payroll_export(request):
    try:
        year, month = int(request.query_params['year']), int(request.query_params['month'])
        if not 1 <= month <= 12:
            raise ValueError
    except (KeyError, ValueError):
        return Response({'detail': 'Provide a valid year and month.'}, status=status.HTTP_400_BAD_REQUEST)
    payslips = Payslip.objects.filter(year=year, month=month).order_by('employee_code')
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="payroll_{year}-{month:02d}.csv"'
    response.write('﻿')
    writer = csv.writer(response)
    writer.writerow([
        'Employee ID', 'Name', 'Department', 'Designation', 'Working days', 'LOP days', 'Basic', 'HRA', 'DA',
        'Conveyance', 'Medical', 'Special', 'Other allowance', 'Overtime hours', 'Overtime', 'Bonus', 'Gross', 'PF',
        'Professional tax', 'TDS', 'Other deductions', 'LOP deduction', 'Total deductions', 'Net salary', 'Status',
    ])
    for slip in payslips:
        writer.writerow([
            _safe_cell(slip.employee_code), _safe_cell(slip.employee_name), _safe_cell(slip.department),
            _safe_cell(slip.designation), slip.working_days, slip.lop_days, slip.basic, slip.hra, slip.da,
            slip.conveyance_allowance, slip.medical_allowance, slip.special_allowance, slip.other_allowance,
            slip.overtime_hours, slip.overtime_pay, slip.bonus, slip.gross_earnings, slip.pf, slip.professional_tax, slip.tds,
            slip.other_deduction, slip.lop_deduction, slip.total_deductions, slip.net_salary, slip.get_status_display(),
        ])
    record_audit(request, 'EXPORT', 'Payroll', f'{year}-{month:02d}', f'Exported payroll register for {_period_label(year, month)}.')
    return response


@api_view(['GET'])
@permission_classes(ADMIN)
def payroll_reports(request):
    """Monthly payroll totals for a year, plus a department breakdown for one month."""
    try:
        year = int(request.query_params.get('year', timezone.localdate().year))
    except ValueError:
        return Response({'detail': 'Invalid year.'}, status=status.HTTP_400_BAD_REQUEST)

    rows = {
        row['month']: row for row in Payslip.objects.filter(year=year).values('month').annotate(
            count=Count('id'), gross=Sum('gross_earnings'), deductions=Sum('total_deductions'), net=Sum('net_salary'),
            drafts=Count('id', filter=Q(status=Payslip.DRAFT)), paid=Count('id', filter=Q(status=Payslip.PAID)),
        )
    }
    monthly = []
    for month in range(1, 13):
        row = rows.get(month)
        monthly.append({
            'month': month, 'label': calendar.month_abbr[month],
            'count': row['count'] if row else 0,
            'gross': row['gross'] if row else Decimal('0'),
            'deductions': row['deductions'] if row else Decimal('0'),
            'net': row['net'] if row else Decimal('0'),
            'drafts': row['drafts'] if row else 0,
            'paid': row['paid'] if row else 0,
        })

    try:
        month = int(request.query_params.get('month') or max((m for m in rows), default=0))
    except ValueError:
        month = 0
    departments = []
    if 1 <= month <= 12:
        departments = list(
            Payslip.objects.filter(year=year, month=month).values('department').annotate(
                headcount=Count('id'), gross=Sum('gross_earnings'), net=Sum('net_salary'),
            ).order_by('-net')
        )
        for item in departments:
            item['department'] = item['department'] or 'Unassigned'
    return Response({'year': year, 'month': month or None, 'monthly': monthly, 'departments': departments})

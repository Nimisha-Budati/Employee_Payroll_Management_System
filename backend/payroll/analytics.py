"""Advanced analytics: payroll cost, overtime, attendance and lateness, leave, absenteeism and headcount.

Every figure is computed from stored records for a range of months (at most 24) and an optional
department, and compared with the previous range of the same length.

Definitions
-----------
* Payroll cost = gross earnings of the payslips for the month (drafts included and counted separately).
* Overtime cost = approved overtime records dated in the month (paid or about to be paid).
* Absenteeism = loss-of-pay days ÷ working days on the month's payslips.
* Late rate = late check-ins ÷ check-ins.
* Leave days are approved leave days falling in the month (a leave spanning two months is split).
* Headcount = employees who had joined by the month's end and were not deactivated by then
  (employees deactivated before deactivation dates were recorded are counted as gone throughout and
  reported in ``notes``).
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import AttendanceRecord, Employee, EmployeeLeaveBalance, LeaveRequest, LeaveType
from accounts.leave_policy import leave_year_bounds, leave_year_label, leave_year_of, policy_settings
from accounts.permissions import IsAdminUserRole

from .models import Payslip

MAX_MONTHS = 24
ZERO = Decimal('0')


class AnalyticsError(Exception):
    pass


def _parse_month(value, name):
    try:
        year, month = (int(part) for part in str(value).split('-')[:2])
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            raise ValueError
        return year, month
    except (TypeError, ValueError):
        raise AnalyticsError(f'Use YYYY-MM for {name}.')


def month_list(first, last):
    months, (year, month) = [], first
    while (year, month) <= last:
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def shift_months(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _pct(part, whole, places='0.1'):
    part, whole = Decimal(part or 0), Decimal(whole or 0)
    return (part / whole * 100).quantize(Decimal(places), rounding=ROUND_HALF_UP) if whole else None


def change(previous, current):
    previous, current = Decimal(previous or 0), Decimal(current or 0)
    return {
        'previous': previous, 'current': current, 'change': current - previous,
        'percent': ((current - previous) / abs(previous) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) if previous else None,
    }


def resolve_range(params):
    today = timezone.localdate()
    last = _parse_month(params['to'], 'the end month') if params.get('to') else (today.year, today.month)
    first = _parse_month(params['from'], 'the start month') if params.get('from') else shift_months(*last, -5)
    if first > last:
        raise AnalyticsError('The start month must be before the end month.')
    months = month_list(first, last)
    if len(months) > MAX_MONTHS:
        raise AnalyticsError(f'Choose at most {MAX_MONTHS} months.')
    return months


def _series(months, department):
    """Monthly figures for a list of (year, month)."""
    start, end = _bounds(*months[0])[0], _bounds(*months[-1])[1]
    by_month = {key: defaultdict(lambda: ZERO) for key in months}

    payslips = Payslip.objects.filter(
        Q(year__gt=months[0][0]) | Q(year=months[0][0], month__gte=months[0][1]),
    ).filter(Q(year__lt=months[-1][0]) | Q(year=months[-1][0], month__lte=months[-1][1]))
    if department:
        payslips = payslips.filter(department__iexact=department)
    for row in payslips.values('year', 'month').annotate(
        count=Count('id'), drafts=Count('id', filter=Q(status=Payslip.DRAFT)), gross=Sum('gross_earnings'),
        net=Sum('net_salary'), deductions=Sum('total_deductions'), overtime_pay=Sum('overtime_pay'), bonus=Sum('bonus'),
        lop_days=Sum('lop_days'), working_days=Sum('working_days'),
    ):
        bucket = by_month.get((row['year'], row['month']))
        if bucket is not None:
            for key in ('count', 'drafts', 'gross', 'net', 'deductions', 'overtime_pay', 'bonus', 'lop_days', 'working_days'):
                bucket[key] = Decimal(row[key] or 0)

    from workforce.models import OvertimeRecord

    overtime = OvertimeRecord.objects.filter(status=OvertimeRecord.APPROVED, date__range=(start, end))
    attendance = AttendanceRecord.objects.filter(date__range=(start, end), check_in_at__isnull=False)
    leaves = LeaveRequest.objects.filter(status='APPROVED', start_date__lte=end, end_date__gte=start)
    if department:
        overtime = overtime.filter(employee__employee__department__iexact=department)
        attendance = attendance.filter(employee__employee__department__iexact=department)
        leaves = leaves.filter(employee__employee__department__iexact=department)
    for record_date, hours, amount in overtime.values_list('date', 'hours', 'amount'):
        bucket = by_month[(record_date.year, record_date.month)]
        bucket['overtime_hours'] += Decimal(hours)
        bucket['overtime_amount'] += Decimal(amount)
    for row in attendance.values('date__year', 'date__month').annotate(
        present=Count('id'), late=Count('id', filter=Q(late_minutes__gt=0)), late_minutes=Sum('late_minutes'),
        corrected=Count('id', filter=Q(is_corrected=True)),
    ):
        bucket = by_month.get((row['date__year'], row['date__month']))
        if bucket is not None:
            for key in ('present', 'late', 'late_minutes', 'corrected'):
                bucket[key] = Decimal(row[key] or 0)
    for first, last, leave_type in leaves.values_list('start_date', 'end_date', 'leave_type'):
        day = max(first, start)
        while day <= min(last, end):
            by_month[(day.year, day.month)]['leave_days'] += 1
            day += timedelta(days=1)

    employees = Employee.objects.all()
    if department:
        employees = employees.filter(department__iexact=department)
    people = list(employees.values_list('joining_date', 'deactivated_at', 'status'))
    rows = []
    for year, month in months:
        month_start, month_end = _bounds(year, month)
        bucket = by_month[(year, month)]

        def active_on(day):
            return sum(1 for joined, left, state in people if joined <= day and (
                (left is None and state == 'ACTIVE') or (left is not None and left > day)))

        rows.append({
            'year': year, 'month': month, 'label': f'{calendar.month_abbr[month]} {str(year)[2:]}',
            'payroll': {key: bucket[key] for key in ('gross', 'net', 'deductions', 'overtime_pay', 'bonus')},
            'payslips': int(bucket['count']), 'drafts': int(bucket['drafts']),
            'overtime': {'hours': bucket['overtime_hours'], 'amount': bucket['overtime_amount']},
            'attendance': {
                'present': int(bucket['present']), 'late': int(bucket['late']), 'late_minutes': int(bucket['late_minutes']),
                'average_late_minutes': int((bucket['late_minutes'] / bucket['late']).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if bucket['late'] else 0,
                'late_rate': _pct(bucket['late'], bucket['present']), 'corrected': int(bucket['corrected']),
            },
            'leave_days': int(bucket['leave_days']),
            'absenteeism': {'lop_days': bucket['lop_days'], 'working_days': int(bucket['working_days']),
                            'rate': _pct(bucket['lop_days'], bucket['working_days'])},
            'headcount': {
                'end': active_on(month_end),
                'joined': sum(1 for joined, _, _ in people if month_start <= joined <= month_end),
                'left': sum(1 for _, left, _ in people if left is not None and month_start <= left <= month_end),
            },
        })
    unknown = sum(1 for _, left, state in people if state != 'ACTIVE' and left is None)
    return rows, unknown


def _totals(rows):
    gross = sum((row['payroll']['gross'] for row in rows), ZERO)
    lop = sum((row['absenteeism']['lop_days'] for row in rows), ZERO)
    working = sum(row['absenteeism']['working_days'] for row in rows)
    present = sum(row['attendance']['present'] for row in rows)
    late = sum(row['attendance']['late'] for row in rows)
    return {
        'payroll_cost': gross,
        'net_pay': sum((row['payroll']['net'] for row in rows), ZERO),
        'average_monthly_cost': (gross / len(rows)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if rows else ZERO,
        'overtime_cost': sum((row['overtime']['amount'] for row in rows), ZERO),
        'overtime_hours': sum((row['overtime']['hours'] for row in rows), ZERO),
        'present_days': present, 'late_checkins': late, 'late_rate': _pct(late, present),
        'leave_days': sum(row['leave_days'] for row in rows),
        'absenteeism_rate': _pct(lop, working), 'lop_days': lop,
        'joined': sum(row['headcount']['joined'] for row in rows),
        'left': sum(row['headcount']['left'] for row in rows),
        'headcount_end': rows[-1]['headcount']['end'] if rows else 0,
    }


def _departments(months, department):
    first, last = months[0], months[-1]
    start, end = _bounds(*first)[0], _bounds(*last)[1]
    payslips = Payslip.objects.filter(Q(year__gt=first[0]) | Q(year=first[0], month__gte=first[1])) \
        .filter(Q(year__lt=last[0]) | Q(year=last[0], month__lte=last[1]))
    result = defaultdict(lambda: {'gross': ZERO, 'net': ZERO, 'overtime_amount': ZERO, 'late': 0, 'leave_days': 0, 'headcount': 0, 'payslips': 0})
    for row in payslips.values('department').annotate(gross=Sum('gross_earnings'), net=Sum('net_salary'), count=Count('id')):
        item = result[row['department'] or 'Unassigned']
        item['gross'], item['net'], item['payslips'] = row['gross'] or ZERO, row['net'] or ZERO, row['count']
    from workforce.models import OvertimeRecord

    for row in OvertimeRecord.objects.filter(status=OvertimeRecord.APPROVED, date__range=(start, end)) \
            .values('employee__employee__department').annotate(amount=Sum('amount')):
        result[row['employee__employee__department'] or 'Unassigned']['overtime_amount'] = row['amount'] or ZERO
    for row in AttendanceRecord.objects.filter(date__range=(start, end), late_minutes__gt=0) \
            .values('employee__employee__department').annotate(late=Count('id')):
        result[row['employee__employee__department'] or 'Unassigned']['late'] = row['late']
    for dept, first_day, last_day in LeaveRequest.objects.filter(status='APPROVED', start_date__lte=end, end_date__gte=start) \
            .values_list('employee__employee__department', 'start_date', 'end_date'):
        result[dept or 'Unassigned']['leave_days'] += (min(last_day, end) - max(first_day, start)).days + 1
    for row in Employee.objects.filter(status='ACTIVE').values('department').annotate(count=Count('id')):
        result[row['department'] or 'Unassigned']['headcount'] = row['count']
    rows = [{'department': name, **values} for name, values in result.items()]
    if department:
        rows = [row for row in rows if row['department'].lower() == department.lower()]
    return sorted(rows, key=lambda row: (-row['gross'], row['department']))


def _leave_utilisation(department):
    rules = policy_settings()
    year = leave_year_of(timezone.localdate(), rules)
    start, end = leave_year_bounds(year, rules)
    employees = Employee.objects.filter(status='ACTIVE', user__is_active=True)
    if department:
        employees = employees.filter(department__iexact=department)
    user_ids = list(employees.values_list('user_id', flat=True))
    rows = []
    for leave_type in LeaveType.objects.filter(is_active=True).order_by('sort_order', 'name'):
        requests = LeaveRequest.objects.filter(employee_id__in=user_ids, policy=leave_type, start_date__lte=end, end_date__gte=start)
        used = sum((min(last, end) - max(first, start)).days + 1 for first, last in
                   requests.filter(status='APPROVED').values_list('start_date', 'end_date'))
        pending = sum((min(last, end) - max(first, start)).days + 1 for first, last in
                      requests.filter(status='PENDING').values_list('start_date', 'end_date'))
        entitled = None
        if leave_type.annual_days is not None:
            extra = EmployeeLeaveBalance.objects.filter(employee_id__in=user_ids, leave_type=leave_type, year=year) \
                .aggregate(carried=Sum('carried_forward'), adjustment=Sum('adjustment'))
            entitled = leave_type.annual_days * len(user_ids) + (extra['carried'] or 0) + (extra['adjustment'] or 0)
        rows.append({
            'leave_type': leave_type.name, 'is_paid': leave_type.is_paid, 'used_days': used, 'pending_days': pending,
            'entitled_days': entitled, 'utilisation': _pct(used, entitled) if entitled else None,
        })
    return {'year': year, 'label': leave_year_label(year, rules), 'employees': len(user_ids), 'types': rows}


def build_analytics(params):
    months = resolve_range(params)
    department = (params.get('department') or '').strip()
    rows, unknown = _series(months, department)
    previous_months = month_list(shift_months(*months[0], -len(months)), shift_months(*months[0], -1))
    previous_rows, _ = _series(previous_months, department)
    current, previous = _totals(rows), _totals(previous_rows)
    comparison = {key: change(previous[key], current[key]) for key in (
        'payroll_cost', 'net_pay', 'overtime_cost', 'late_checkins', 'leave_days', 'joined', 'left', 'headcount_end')}
    for key in ('absenteeism_rate', 'late_rate'):
        comparison[key] = {'previous': previous[key], 'current': current[key],
                           'change': (current[key] - previous[key]) if current[key] is not None and previous[key] is not None else None,
                           'percent': None}
    notes = []
    if unknown:
        notes.append(f'{unknown} inactive employee(s) have no recorded deactivation date, so they are left out of headcount for every month.')
    if any(row['drafts'] for row in rows):
        notes.append('Some months include draft payslips that are not finalised yet.')
    has_data = any(row['payslips'] or row['attendance']['present'] or row['leave_days'] or row['overtime']['hours'] for row in rows)
    return {
        'from': f'{months[0][0]}-{months[0][1]:02d}', 'to': f'{months[-1][0]}-{months[-1][1]:02d}',
        'previous_from': f'{previous_months[0][0]}-{previous_months[0][1]:02d}',
        'previous_to': f'{previous_months[-1][0]}-{previous_months[-1][1]:02d}',
        'department': department or None, 'has_data': has_data,
        'summary': current, 'comparison': comparison, 'monthly': rows,
        'departments': _departments(months, department), 'leave_utilisation': _leave_utilisation(department),
        'notes': notes,
    }


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def analytics_report(request):
    try:
        return Response(build_analytics(request.query_params))
    except AnalyticsError as error:
        return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)

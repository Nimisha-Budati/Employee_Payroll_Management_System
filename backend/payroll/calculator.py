"""Payroll calculation rules.

All money maths lives here so it can be tested in isolation. Amounts are
``Decimal`` values rounded half-up to two places.

Rules
-----
* A working day is a weekday in ``settings.PAYROLL_WORKING_WEEKDAYS`` that is not
  on the holiday calendar.
* An employee is *covered* on a working day (no loss of pay) when they have
  checked in, are on approved paid leave, or have an approved work-from-home day.
  Approved leave of a type the administrator marked *unpaid* is always loss of pay. Working days before the
  joining date are not payable.
* ``lop_mode='NONE'`` skips the attendance check and only applies unpaid leave and
  the joining-date proration, for organisations that do not use attendance.
* Loss-of-pay deduction = fixed monthly gross x lop_days / working_days. The fixed gross is
  basic + HRA + DA + the other allowances.
* Provident fund = pf_percent of the *earned* PF wage, i.e. basic + DA reduced for loss of pay
  (the statutory EPF wage definition).
* Overtime pay = the sum of the employee's APPROVED overtime records dated in the month
  (hours x the rate on each record). Unapproved attendance time is never paid automatically.
* The salary structure's monthly bonus is paid in full (no loss-of-pay reduction, not part of the
  PF wage); an administrator can change the bonus on a draft payslip for one-off awards.
* Tax (TDS) and professional tax are fixed monthly amounts set on the salary
  structure (the system does not compute income-tax slabs). They are pro-rated for
  loss of pay, so an employee with no paid days is not charged tax on zero pay.
  "Other deductions" (for example a loan instalment) are never pro-rated.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings

from accounts.models import AttendanceRecord, Holiday, LeaveRequest, WorkFromHomeRequest
from accounts.leave_policy import unpaid_leave_filter
from workforce.services import approved_overtime, attendance_overtime

CENT = Decimal('0.01')
EARNING_FIELDS = ('basic', 'hra', 'da', 'conveyance_allowance', 'medical_allowance', 'special_allowance', 'other_allowance')


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def iter_days(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def working_dates(year, month):
    start, end = month_bounds(year, month)
    holidays = set(Holiday.objects.filter(date__range=(start, end)).values_list('date', flat=True))
    weekdays = set(settings.PAYROLL_WORKING_WEEKDAYS)
    return {day for day in iter_days(start, end) if day.weekday() in weekdays and day not in holidays}


def _expand(ranges, start, end):
    days = set()
    for range_start, range_end in ranges:
        for day in iter_days(max(range_start, start), min(range_end, end)):
            days.add(day)
    return days


def attendance_detail(user, joining_date, year, month, lop_mode='ATTENDANCE'):
    """The day sets behind loss of pay: working, covered, unpaid leave, absent and before-joining days."""
    start, end = month_bounds(year, month)
    working = working_dates(year, month)
    covered, unpaid_leave, payable = _covered_days(user, joining_date, start, end, working, lop_mode)
    return {
        'working': working,
        'covered': covered,
        'before_joining': working - payable,
        'unpaid_leave': unpaid_leave & payable,
        'absent': payable - covered - unpaid_leave,
    }


def _covered_days(user, joining_date, start, end, working, lop_mode):
    unpaid_leave = _expand(
        LeaveRequest.objects.filter(
            unpaid_leave_filter(), employee=user, status='APPROVED', start_date__lte=end, end_date__gte=start,
        ).values_list('start_date', 'end_date'),
        start, end,
    )
    payable = {day for day in working if joining_date is None or day >= joining_date}
    if lop_mode == 'NONE':
        covered = set(payable)
    else:
        present = set(
            AttendanceRecord.objects.filter(
                employee=user, date__range=(start, end), check_in_at__isnull=False,
            ).values_list('date', flat=True)
        )
        paid_leave = _expand(
            LeaveRequest.objects.filter(
                employee=user, status='APPROVED', start_date__lte=end, end_date__gte=start,
            ).exclude(unpaid_leave_filter()).values_list('start_date', 'end_date'),
            start, end,
        )
        wfh = _expand(
            WorkFromHomeRequest.objects.filter(
                employee=user, status='APPROVED', start_date__lte=end, end_date__gte=start,
            ).values_list('start_date', 'end_date'),
            start, end,
        )
        covered = (present | paid_leave | wfh) & payable
    covered -= unpaid_leave
    return covered, unpaid_leave, payable


def attendance_summary(user, joining_date, year, month, lop_mode='ATTENDANCE'):
    """Return (working_days, lop_days, overtime_hours) for one employee and month."""
    start, end = month_bounds(year, month)
    working = working_dates(year, month)
    covered, _, _ = _covered_days(user, joining_date, start, end, working, lop_mode)

    lop_days = Decimal(len(working) - len(covered))

    # Candidate overtime from attendance (beyond each day's shift or standard hours). It is reported
    # here for information; payroll pays only APPROVED overtime records (see build_payslip_values).
    overtime_hours = sum(
        (attendance_overtime(record) for record in AttendanceRecord.objects.select_related('employee', 'shift').filter(
            employee=user, date__range=(start, end), check_in_at__isnull=False, check_out_at__isnull=False,
        )),
        Decimal('0'),
    ).quantize(CENT, rounding=ROUND_HALF_UP)
    return len(working), lop_days, overtime_hours


def compute_amounts(components, working_days, lop_days, bonus=Decimal('0'), other_deduction=Decimal('0')):
    """Derive totals from a mapping of salary components.

    ``components`` needs: the earning fields, overtime_pay, pf_percent,
    professional_tax_base and tds_base. ``da`` may be omitted (treated as 0).
    """
    lop_days = Decimal(lop_days)
    fixed_gross = sum((Decimal(components.get(field, 0)) for field in EARNING_FIELDS), Decimal('0'))
    if working_days > 0:
        lop_ratio = min(Decimal(1), lop_days / Decimal(working_days))
    else:
        lop_ratio = Decimal(0)

    lop_deduction = money(fixed_gross * lop_ratio)
    earned_pf_wage = (Decimal(components['basic']) + Decimal(components.get('da', 0))) * (Decimal(1) - lop_ratio)
    pf = money(earned_pf_wage * Decimal(components['pf_percent']) / Decimal(100))

    paid_ratio = Decimal(1) - lop_ratio
    professional_tax = money(Decimal(components['professional_tax_base']) * paid_ratio)
    tds = money(Decimal(components['tds_base']) * paid_ratio)

    gross = money(fixed_gross + Decimal(components['overtime_pay']) + Decimal(bonus))
    total_deductions = money(pf + professional_tax + tds + Decimal(other_deduction) + lop_deduction)
    return {
        'lop_deduction': lop_deduction,
        'pf': pf,
        'professional_tax': professional_tax,
        'tds': tds,
        'gross_earnings': gross,
        'total_deductions': total_deductions,
        'net_salary': money(gross - total_deductions),
    }


def build_payslip_values(employee, structure, year, month, lop_mode='ATTENDANCE'):
    """Full set of Payslip field values for an Employee, their structure and a month."""
    working_days, lop_days, _ = attendance_summary(
        employee.user, employee.joining_date, year, month, lop_mode,
    )
    overtime_hours, overtime_pay = approved_overtime(employee.user, year, month)
    bonus = money(structure.bonus)
    components = {field: getattr(structure, field) for field in EARNING_FIELDS}
    components.update({
        'overtime_pay': overtime_pay,
        'pf_percent': structure.pf_percent,
        'professional_tax_base': structure.professional_tax,
        'tds_base': structure.tds,
    })
    amounts = compute_amounts(components, working_days, lop_days, bonus, structure.other_deduction)
    return {
        'employee_code': employee.employee_id,
        'employee_name': employee.user.get_full_name() or employee.user.username,
        'department': employee.department,
        'designation': employee.designation,
        'working_days': working_days,
        'lop_days': lop_days,
        'overtime_hours': overtime_hours,
        'bonus': bonus,
        'other_deduction': money(structure.other_deduction),
        **{field: money(value) for field, value in components.items() if field not in ('pf_percent', 'professional_tax_base', 'tds_base')},
        'pf_percent': structure.pf_percent,
        'professional_tax_base': money(structure.professional_tax),
        'tds_base': money(structure.tds),
        **amounts,
    }


def apply_amounts(payslip):
    """Recompute derived amounts on a Payslip instance from its own stored inputs."""
    components = {field: getattr(payslip, field) for field in EARNING_FIELDS}
    components.update({
        'overtime_pay': payslip.overtime_pay,
        'pf_percent': payslip.pf_percent,
        'professional_tax_base': payslip.professional_tax_base,
        'tds_base': payslip.tds_base,
    })
    amounts = compute_amounts(
        components, payslip.working_days, payslip.lop_days, payslip.bonus, payslip.other_deduction,
    )
    for field, value in amounts.items():
        setattr(payslip, field, value)
    return payslip

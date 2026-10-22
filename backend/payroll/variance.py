"""Payroll variance analysis: compare a month's payslips with the previous month before finalising.

Nothing here changes a salary. It reads the payslips (draft or paid) of a month and the month before,
compares every component, flags unusual changes and explains them from recorded data: salary-structure
changes, loss-of-pay days (unpaid leave, days with no attendance/leave/WFH, days before joining),
approved overtime, bonus, holidays, manual adjustments and records that changed after the draft was made.

An administrator must review the preview (``PayrollReview``) before drafts can be finalised; editing,
recalculating or generating a draft after the review requires a new review.

Flags (severity)
----------------
* NET_CHANGE (medium / high): net salary changed by at least ``PAYROLL_VARIANCE_THRESHOLD_PERCENT``
  (default 10%) / twice that.
* NET_ZERO (high): net salary is zero.
* MISSING (high): paid last month, still active, but no payslip this month. LEFT (info): paid last month, now inactive.
* LOP_HIGH (medium / high): loss-of-pay days rose by 2+ / reached half the working days.
* OVERTIME_HIGH (medium): overtime pay above 25% of the fixed monthly gross.
* STALE (medium): a draft no longer matches current records (recalculate to apply them).
* MANUAL (info): a draft was adjusted by hand. STRUCTURE (info): fixed components changed.
* NEW (info): no payslip last month to compare with.
"""

import calendar
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Max, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.audit import record_audit
from accounts.models import AuditLog, Employee, Holiday
from accounts.permissions import IsAdminUserRole

from .calculator import EARNING_FIELDS, attendance_detail, build_payslip_values, month_bounds
from .models import Payslip, PayrollReview, SalaryStructure

COMPONENTS = [
    ('basic', 'Basic'), ('hra', 'HRA'), ('da', 'Dearness allowance'), ('conveyance_allowance', 'Conveyance'),
    ('medical_allowance', 'Medical'), ('special_allowance', 'Special allowance'), ('other_allowance', 'Other allowance'),
    ('overtime_pay', 'Overtime pay'), ('bonus', 'Bonus'), ('gross_earnings', 'Gross earnings'),
    ('pf', 'Provident fund'), ('professional_tax', 'Professional tax'), ('tds', 'Income tax (TDS)'),
    ('other_deduction', 'Other deductions'), ('lop_deduction', 'Loss of pay'), ('total_deductions', 'Total deductions'),
    ('net_salary', 'Net salary'),
]
QUANTITIES = [('working_days', 'Working days'), ('lop_days', 'Loss-of-pay days'), ('overtime_hours', 'Overtime hours')]
SEVERITY_ORDER = {'high': 0, 'medium': 1, 'info': 2}


def threshold():
    return Decimal(str(getattr(settings, 'PAYROLL_VARIANCE_THRESHOLD_PERCENT', 10)))


def previous_period(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _label(year, month):
    return f'{calendar.month_name[month]} {year}'


def _rupees(value):
    value = Decimal(value or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return f'₹{value:,}'


def _num(value):
    value = Decimal(value or 0).normalize()
    return f'{value:f}' if value != value.to_integral() else f'{int(value)}'


def percent(previous, current):
    previous, current = Decimal(previous or 0), Decimal(current or 0)
    if previous == 0:
        return None
    return ((current - previous) / abs(previous) * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


def _flag(code, severity, message):
    return {'code': code, 'severity': severity, 'message': message}


def _days_text(days):
    days = sorted(days)
    if not days:
        return ''
    return ', '.join(day.strftime('%d %b') for day in days[:6]) + (f' and {len(days) - 6} more' if len(days) > 6 else '')


def _lop_reason(employee, year, month, slip):
    detail = attendance_detail(employee.user, employee.joining_date, year, month)
    parts = []
    if detail['unpaid_leave']:
        parts.append(f'{len(detail["unpaid_leave"])} unpaid leave day(s) ({_days_text(detail["unpaid_leave"])})')
    if detail['absent']:
        parts.append(f'{len(detail["absent"])} working day(s) with no check-in, approved leave or WFH ({_days_text(detail["absent"])})')
    if detail['before_joining']:
        parts.append(f'{len(detail["before_joining"])} working day(s) before joining on {employee.joining_date:%d %b %Y}')
    recorded = len(detail['unpaid_leave']) + len(detail['absent']) + len(detail['before_joining'])
    if not parts:
        return 'Current records show no loss-of-pay days' + (' (the payslip was adjusted by hand or uses the full-month mode).' if slip.lop_days else '.')
    note = '' if Decimal(recorded) == Decimal(slip.lop_days) else f' Current records give {recorded} day(s); the payslip has {_num(slip.lop_days)}.'
    return 'Loss of pay comes from ' + '; '.join(parts) + '.' + note


def _overtime_reason(user, year, month):
    from workforce.models import OvertimeRecord

    start, end = month_bounds(year, month)
    records = OvertimeRecord.objects.filter(employee=user, status=OvertimeRecord.APPROVED, date__range=(start, end))
    totals = records.aggregate(hours=Sum('hours'), amount=Sum('amount'))
    count = records.count()
    if not count:
        return 'No approved overtime records in this month.'
    return f'{count} approved overtime record(s): {_num(totals["hours"])} h, {_rupees(totals["amount"])}.'


def _adjustments(slip):
    return list(AuditLog.objects.filter(entity_type='Payslip', entity_id=str(slip.pk), action='ADJUST').order_by('created_at'))


def _structure_text(structure):
    if structure is None:
        return ''
    who = structure.updated_by.get_full_name() or structure.updated_by.username if structure.updated_by else 'an administrator'
    return (f'Salary structure last updated {timezone.localtime(structure.updated_at):%d %b %Y} by {who} '
            f'(effective {structure.effective_from:%d %b %Y}).')


def _compare(previous, current):
    rows = []
    for field, label in COMPONENTS + QUANTITIES:
        before = getattr(previous, field) if previous else None
        after = getattr(current, field) if current else None
        change = (Decimal(after or 0) - Decimal(before or 0)) if previous and current else None
        rows.append({
            'field': field, 'label': label, 'previous': before, 'current': after, 'change': change,
            'percent': percent(before, after) if previous and current else None,
            'kind': 'quantity' if field in dict(QUANTITIES) else ('deduction' if field in (
                'pf', 'professional_tax', 'tds', 'other_deduction', 'lop_deduction', 'total_deductions') else 'earning'),
        })
    return rows


def analyse_employee(employee, structure, year, month, current, previous):
    flags, reasons = [], []
    prev_year, prev_month = previous_period(year, month)
    if current is None:
        if employee.status != 'ACTIVE' or not employee.user.is_active:
            left = f' on {employee.deactivated_at:%d %b %Y}' if employee.deactivated_at else ''
            flags.append(_flag('LEFT', 'info', f'Deactivated{left}, so not paid for {_label(year, month)} '
                                               f'(paid {_label(prev_year, prev_month)}).'))
            return flags, reasons
        why = 'no salary structure is set' if structure is None else ''
        flags.append(_flag('MISSING', 'high', f'Paid in {_label(prev_year, prev_month)} but has no payslip for {_label(year, month)}'
                           + (f' ({why}).' if why else '. Run payroll for this employee.')))
        return flags, reasons

    fixed_gross = sum((Decimal(getattr(current, field)) for field in EARNING_FIELDS), Decimal('0'))
    if current.net_salary <= 0:
        flags.append(_flag('NET_ZERO', 'high', 'Net salary is zero.'))
    if previous is None:
        joined = employee.joining_date
        start, end = month_bounds(year, month)
        if start <= joined <= end:
            flags.append(_flag('NEW', 'info', f'Joined on {joined:%d %b %Y}; no previous payslip to compare.'))
        else:
            flags.append(_flag('NEW', 'info', f'No payslip for {_label(prev_year, prev_month)} to compare with.'))
    else:
        change = percent(previous.net_salary, current.net_salary)
        limit = threshold()
        if change is not None and abs(change) >= limit:
            severity = 'high' if abs(change) >= limit * 2 else 'medium'
            direction = 'rose' if change > 0 else 'fell'
            flags.append(_flag('NET_CHANGE', severity,
                               f'Net salary {direction} {abs(change)}% ({_rupees(previous.net_salary)} → {_rupees(current.net_salary)}).'))
        if Decimal(current.lop_days) - Decimal(previous.lop_days) >= 2:
            flags.append(_flag('LOP_HIGH', 'medium', f'Loss-of-pay days rose from {_num(previous.lop_days)} to {_num(current.lop_days)}.'))

        changed = [label for field, label in COMPONENTS if field in EARNING_FIELDS
                   and getattr(previous, field) != getattr(current, field)]
        if changed or previous.pf_percent != current.pf_percent or previous.professional_tax_base != current.professional_tax_base \
                or previous.tds_base != current.tds_base:
            details = [f'{label} {_rupees(getattr(previous, field))} → {_rupees(getattr(current, field))}'
                       for field, label in COMPONENTS if field in EARNING_FIELDS and getattr(previous, field) != getattr(current, field)]
            if previous.pf_percent != current.pf_percent:
                details.append(f'PF {_num(previous.pf_percent)}% → {_num(current.pf_percent)}%')
            if previous.professional_tax_base != current.professional_tax_base:
                details.append(f'professional tax {_rupees(previous.professional_tax_base)} → {_rupees(current.professional_tax_base)}')
            if previous.tds_base != current.tds_base:
                details.append(f'monthly TDS {_rupees(previous.tds_base)} → {_rupees(current.tds_base)}')
            flags.append(_flag('STRUCTURE', 'info', 'Fixed salary components changed.'))
            reasons.append('Salary components changed: ' + '; '.join(details) + '. ' + _structure_text(structure))
        if previous.working_days != current.working_days:
            start, end = month_bounds(year, month)
            holidays = list(Holiday.objects.filter(company=employee.company, date__range=(start, end)).order_by('date'))
            text = f'Working days {previous.working_days} → {current.working_days}'
            if holidays:
                text += ' (holidays this month: ' + ', '.join(f'{h.name} on {h.date:%d %b}' for h in holidays) + ')'
            reasons.append(text + '.')
        if previous.lop_days != current.lop_days:
            reasons.append(f'Loss-of-pay days {_num(previous.lop_days)} → {_num(current.lop_days)} '
                           f'(deduction {_rupees(previous.lop_deduction)} → {_rupees(current.lop_deduction)}).')
        if previous.overtime_pay != current.overtime_pay or previous.overtime_hours != current.overtime_hours:
            reasons.append(f'Overtime {_num(previous.overtime_hours)} h ({_rupees(previous.overtime_pay)}) → '
                           f'{_num(current.overtime_hours)} h ({_rupees(current.overtime_pay)}). '
                           + _overtime_reason(employee.user, year, month))
        if previous.bonus != current.bonus:
            source = ''
            if structure is not None:
                source = (' (the salary structure bonus)' if Decimal(structure.bonus) == Decimal(current.bonus)
                          else f' (the salary structure bonus is {_rupees(structure.bonus)}, so this was set on the payslip)')
            reasons.append(f'Bonus {_rupees(previous.bonus)} → {_rupees(current.bonus)}{source}.')
        if previous.other_deduction != current.other_deduction:
            reasons.append(f'Other deductions {_rupees(previous.other_deduction)} → {_rupees(current.other_deduction)}.')
        if previous.department != current.department or previous.designation != current.designation:
            reasons.append(f'Role changed from {previous.designation or "—"}, {previous.department or "—"} to '
                           f'{current.designation or "—"}, {current.department or "—"}.')

    if current.lop_days:
        reasons.append(_lop_reason(employee, year, month, current))
        if current.working_days and Decimal(current.lop_days) * 2 >= current.working_days:
            flags.append(_flag('LOP_HIGH', 'high', f'{_num(current.lop_days)} of {current.working_days} working days are loss of pay.'))
    if fixed_gross and Decimal(current.overtime_pay) > fixed_gross * Decimal('0.25'):
        flags.append(_flag('OVERTIME_HIGH', 'medium', f'Overtime pay {_rupees(current.overtime_pay)} is over 25% of the fixed gross {_rupees(fixed_gross)}.'))

    if current.status == Payslip.DRAFT:
        edits = _adjustments(current)
        if edits:
            flags.append(_flag('MANUAL', 'info', f'Adjusted by hand {len(edits)} time(s); last by {edits[-1].actor_name or "an administrator"} '
                                                  f'on {timezone.localtime(edits[-1].created_at):%d %b %H:%M}.'))
            reasons.append('Manual adjustment: ' + edits[-1].summary)
        elif structure is not None:
            expected = build_payslip_values(employee, structure, year, month)
            differs = [label for field, label in (('lop_days', 'loss-of-pay days'), ('overtime_pay', 'approved overtime'),
                                                  ('working_days', 'working days'), ('net_salary', 'net salary'))
                       if Decimal(expected[field]) != Decimal(getattr(current, field))]
            # A full-month (no attendance) run legitimately ignores absences, so only flag other differences then.
            if differs and not (differs == ['loss-of-pay days', 'net salary'] and Decimal(current.lop_days) < Decimal(expected['lop_days'])
                                and not current.lop_days):
                flags.append(_flag('STALE', 'medium', 'Records changed after this draft was generated ('
                                   + ', '.join(differs) + '). Recalculate the draft to apply them.'))
    if current.notes:
        reasons.append(f'Payslip note: {current.notes}')
    return flags, reasons


def latest_review(year, month, company_id=None):
    return PayrollReview.objects.select_related('reviewed_by').filter(year=year, month=month, company_id=company_id).first()


def review_is_current(year, month, drafts=None, company_id=None):
    """True when the latest review is newer than every draft change for the month."""
    review = latest_review(year, month, company_id)
    if review is None:
        return False
    drafts = drafts if drafts is not None else Payslip.objects.filter(year=year, month=month, status=Payslip.DRAFT, employee__userprofile__company_id=company_id)
    last_change = drafts.aggregate(value=Max('updated_at'))['value']
    return last_change is None or last_change <= review.reviewed_at


def build_variance(year, month, flagged_only=False, company_id=None):
    prev_year, prev_month = previous_period(year, month)
    current = {slip.employee_id: slip for slip in Payslip.objects.filter(year=year, month=month, employee__userprofile__company_id=company_id)}
    previous = {slip.employee_id: slip for slip in Payslip.objects.filter(year=prev_year, month=prev_month, employee__userprofile__company_id=company_id)}
    # Everyone paid in either month, so the totals reconcile (leavers are listed as information).
    user_ids = set(current) | set(previous)
    employees = {employee.user_id: employee for employee in Employee.objects.select_related('user').filter(user_id__in=user_ids, company_id=company_id)}
    structures = {structure.employee_id: structure for structure in
                  SalaryStructure.objects.select_related('updated_by').filter(employee_id__in=user_ids)}

    rows = []
    for user_id in user_ids:
        employee = employees.get(user_id)
        slip, before = current.get(user_id), previous.get(user_id)
        if employee is None:
            continue
        flags, reasons = analyse_employee(employee, structures.get(user_id), year, month, slip, before)
        flags.sort(key=lambda item: SEVERITY_ORDER[item['severity']])
        severity = flags[0]['severity'] if flags else None
        rows.append({
            'employee_user_id': user_id,
            'employee_code': (slip or before).employee_code,
            'employee_name': (slip or before).employee_name,
            'department': (slip or before).department,
            'payslip_id': slip.pk if slip else None,
            'status': slip.status if slip else None,
            'previous_net': before.net_salary if before else None,
            'current_net': slip.net_salary if slip else None,
            'net_change': (slip.net_salary - before.net_salary) if slip and before else None,
            'net_percent': percent(before.net_salary, slip.net_salary) if slip and before else None,
            'components': _compare(before, slip),
            'flags': flags,
            'severity': severity,
            'anomaly': severity in ('high', 'medium'),
            'reasons': reasons,
        })
    rows.sort(key=lambda row: (SEVERITY_ORDER.get(row['severity'], 3), row['employee_code']))

    def total(slips, field):
        return sum((Decimal(getattr(slip, field)) for slip in slips), Decimal('0'))

    totals = {}
    for field in ('gross_earnings', 'total_deductions', 'net_salary', 'overtime_pay', 'bonus', 'lop_deduction'):
        before, after = total(previous.values(), field), total(current.values(), field)
        totals[field] = {'previous': before, 'current': after, 'change': after - before, 'percent': percent(before, after)}
    drafts = Payslip.objects.filter(year=year, month=month, status=Payslip.DRAFT, employee__userprofile__company_id=company_id)
    review = latest_review(year, month, company_id)
    data = {
        'year': year, 'month': month, 'period': _label(year, month),
        'previous_period': _label(prev_year, prev_month),
        'threshold_percent': threshold(),
        'counts': {
            'employees': len(rows), 'current': len(current), 'previous': len(previous),
            'drafts': drafts.count(), 'paid': len(current) - drafts.count(),
            'high': sum(1 for row in rows if row['severity'] == 'high'),
            'medium': sum(1 for row in rows if row['severity'] == 'medium'),
            'flagged': sum(1 for row in rows if row['anomaly']),
        },
        'totals': totals,
        'review': {
            'reviewed_at': review.reviewed_at, 'reviewed_by': (review.reviewed_by.get_full_name() or review.reviewed_by.username)
            if review.reviewed_by else '', 'note': review.note, 'flagged_count': review.flagged_count,
            'is_current': review_is_current(year, month, drafts, company_id),
        } if review else None,
        'rows': [row for row in rows if row['anomaly']] if flagged_only else rows,
    }
    return data


def _period_params(source):
    try:
        year, month = int(source.get('year')), int(source.get('month'))
    except (TypeError, ValueError):
        return None
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return year, month


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def payroll_variance(request):
    period = _period_params(request.query_params)
    if period is None:
        return Response({'detail': 'Provide a valid year and month.'}, status=status.HTTP_400_BAD_REQUEST)
    company_id = request.user.userprofile.company_id
    return Response(build_variance(*period, flagged_only=request.query_params.get('flagged') == 'true', company_id=company_id))


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def payroll_variance_review(request):
    period = _period_params(request.data)
    if period is None:
        return Response({'detail': 'Provide a valid year and month.'}, status=status.HTTP_400_BAD_REQUEST)
    year, month = period
    company_id = request.user.userprofile.company_id
    drafts = Payslip.objects.filter(year=year, month=month, status=Payslip.DRAFT, employee__userprofile__company_id=company_id)
    if not drafts.exists():
        return Response({'detail': 'There are no draft payslips to review for this month.'}, status=status.HTTP_400_BAD_REQUEST)
    data = build_variance(year, month, company_id=company_id)
    note = str(request.data.get('note', '')).strip()[:300]
    flagged = data['counts']['flagged']
    if flagged and not note and request.data.get('acknowledge_flags') is not True:
        return Response({'detail': f'{flagged} employee(s) are flagged. Confirm that you checked them (or add a note) to record the review.',
                         'code': 'acknowledge_flags'}, status=status.HTTP_400_BAD_REQUEST)
    review = PayrollReview.objects.create(
        company_id=company_id, year=year, month=month, reviewed_by=request.user, draft_count=data['counts']['drafts'], flagged_count=flagged,
        net_total=data['totals']['net_salary']['current'], note=note,
    )
    record_audit(request, 'REVIEW', 'PayrollReview', f'{year}-{month:02d}',
                 f'Reviewed payroll variance for {_label(year, month)}: {data["counts"]["drafts"]} draft(s), {flagged} flagged'
                 f'{f". Note: {note}" if note else ""}.')
    return Response({'reviewed_at': review.reviewed_at, 'flagged_count': flagged, 'draft_count': review.draft_count},
                    status=status.HTTP_201_CREATED)

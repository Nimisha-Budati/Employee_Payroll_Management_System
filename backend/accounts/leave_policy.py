"""Database-driven leave policy: leave years, balances and carry-forward.

All limits come from ``LeaveType`` rows and ``LeavePolicySettings`` that administrators manage;
nothing about leave types or day counts is fixed in code.

Balance per leave type and leave year:
    total     = annual days + days carried forward + manual adjustment
    used      = days in APPROVED requests starting in the leave year
    pending   = days in PENDING requests (shown separately, never counted as used)
    available = total − used                     (what the employee actually has left)
    remaining = available − pending              (what can still be requested, so pending requests
                                                  cannot be used to exceed the allowance)
Rejected and cancelled requests are ignored. Types without an annual limit are "unlimited".
"""

from datetime import date

from django.db import transaction
from django.db.models import Q, Sum

from .models import EmployeeLeaveBalance, LeavePolicySettings, LeaveRequest, LeaveType


def policy_settings():
    return LeavePolicySettings.load()


def leave_year_bounds(year, settings_row=None):
    """First and last day of leave year ``year`` (the year in which it starts)."""
    month = (settings_row or policy_settings()).leave_year_start_month or 1
    start = date(year, month, 1)
    end = date(year + 1, month, 1) if month > 1 else date(year + 1, 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def leave_year_of(day, settings_row=None):
    month = (settings_row or policy_settings()).leave_year_start_month or 1
    return day.year if day.month >= month else day.year - 1


def leave_year_label(year, settings_row=None):
    start, end = leave_year_bounds(year, settings_row)
    return str(year) if start.month == 1 else f'{start:%d %b %Y} – {end:%d %b %Y}'


def resolve_leave_type(value):
    """Find a configured leave type from an id or a name (case-insensitive; "casual" matches "Casual Leave")."""
    if isinstance(value, LeaveType):
        return value
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        return LeaveType.objects.filter(pk=int(value)).first()
    if not isinstance(value, str) or not value.strip():
        return None
    name = ' '.join(value.split())
    return (LeaveType.objects.filter(name__iexact=name).first()
            or LeaveType.objects.filter(name__iexact=f'{name} leave').first())


def _days_by_type(user, start, end, status):
    rows = (LeaveRequest.objects.filter(employee=user, status=status, start_date__range=(start, end))
            .values('policy_id').annotate(days=Sum('number_of_days')))
    return {row['policy_id']: row['days'] or 0 for row in rows}


def leave_balance_for(user, year):
    """{leave type name: balance dict} for the leave year ``year``, from the configured policy and real requests."""
    settings_row = policy_settings()
    start, end = leave_year_bounds(year, settings_row)
    approved = _days_by_type(user, start, end, 'APPROVED')
    pending = _days_by_type(user, start, end, 'PENDING')
    extras = {row.leave_type_id: row for row in EmployeeLeaveBalance.objects.filter(employee=user, year=year)}
    used_ids = set(approved) | set(pending)
    types = LeaveType.objects.filter(Q(is_active=True) | Q(pk__in=used_ids))
    balance = {}
    for leave_type in types:
        extra = extras.get(leave_type.pk)
        carried = extra.carried_forward if extra else 0
        adjustment = extra.adjustment if extra else 0
        used = approved.get(leave_type.pk, 0)
        waiting = pending.get(leave_type.pk, 0)
        if leave_type.annual_days is None:
            total = available = remaining = None
        else:
            total = max(0, leave_type.annual_days + carried + adjustment)
            available = max(0, total - used)
            remaining = max(0, available - waiting)
        balance[leave_type.name] = {
            'id': leave_type.pk,
            'entitled': leave_type.annual_days,
            'carried_forward': carried,
            'adjustment': adjustment,
            'total': total,
            'approved': used,
            'pending': waiting,
            'available': available,
            'remaining': remaining,
            'is_paid': leave_type.is_paid,
            'is_active': leave_type.is_active,
            'unlimited': leave_type.annual_days is None,
            'allow_carry_forward': leave_type.allow_carry_forward,
        }
    return balance


def unpaid_leave_filter():
    """Q for approved-leave rows that are unpaid (loss of pay) under the current policy."""
    unpaid_names = list(LeaveType.objects.filter(is_paid=False).values_list('name', flat=True))
    return Q(policy__is_paid=False) | Q(policy__isnull=True, leave_type__in=unpaid_names)


@transaction.atomic
def carry_forward(year, actor=None, employees=None):
    """Write the days carried into leave year ``year`` from ``year - 1`` for every type that allows it.

    carried = min(type's maximum, unused days left at the end of the previous leave year). Re-running
    recalculates the same values, so it is safe to repeat. Returns the number of balances written.
    """
    from django.contrib.auth.models import User

    types = list(LeaveType.objects.filter(allow_carry_forward=True, annual_days__isnull=False))
    if employees is None:
        employees = User.objects.filter(userprofile__role='EMPLOYEE', employee__isnull=False)
    written = 0
    for user in employees:
        previous = leave_balance_for(user, year - 1)
        for leave_type in types:
            left = previous.get(leave_type.name, {}).get('available') or 0
            days = min(leave_type.max_carry_forward_days, left)
            row, created = EmployeeLeaveBalance.objects.get_or_create(
                employee=user, leave_type=leave_type, year=year, defaults={'carried_forward': days, 'updated_by': actor},
            )
            if not created and row.carried_forward != days:
                row.carried_forward, row.updated_by = days, actor
                row.save(update_fields=['carried_forward', 'updated_by', 'updated_at'])
            written += 1
    return written

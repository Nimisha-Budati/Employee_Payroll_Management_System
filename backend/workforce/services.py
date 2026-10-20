"""Shift look-ups, late-minute calculation and overtime totals shared by attendance, payroll and reports.

Rules
-----
* An employee's shift on a day is the assignment covering that day; otherwise the active
  *default* shift; otherwise none (late minutes are then not applicable).
* Late minutes are counted from the scheduled shift start. Arriving within the shift's grace
  period counts as on time (0); arriving after it counts the full minutes since the start.
* Standard daily time is the shift length minus its unpaid break, or
  ``settings.PAYROLL_STANDARD_DAILY_HOURS`` when no shift applies. Time worked beyond it is
  *candidate* overtime: it only becomes payable once an administrator approves an overtime record.
"""

import calendar
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db.models import Q, Sum
from django.utils import timezone

from .models import OvertimeRecord, Shift, ShiftAssignment

CENT = Decimal('0.01')


def shift_for(user, day):
    assignment = (
        ShiftAssignment.objects.select_related('shift')
        .filter(employee=user, start_date__lte=day)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=day))
        .order_by('-start_date', '-id')
        .first()
    )
    if assignment is not None:
        return assignment.shift
    return Shift.objects.filter(is_default=True, is_active=True).first()


def scheduled_start(shift, day):
    return timezone.make_aware(datetime.combine(day, shift.start_time), timezone.get_current_timezone())


def late_minutes(shift, day, check_in_at):
    """Minutes late for a check-in, or None when there is no shift."""
    if shift is None or check_in_at is None:
        return None
    minutes = int((check_in_at - scheduled_start(shift, day)).total_seconds() // 60)
    return minutes if minutes > shift.grace_minutes else 0


def standard_minutes(shift):
    if shift is not None and shift.standard_minutes:
        return shift.standard_minutes
    return int(Decimal(str(settings.PAYROLL_STANDARD_DAILY_HOURS)) * 60)


def month_bounds(year, month):
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def approved_overtime(user, year, month):
    """(hours, amount) of APPROVED overtime records dated in the month."""
    start, end = month_bounds(year, month)
    totals = OvertimeRecord.objects.filter(
        employee=user, status=OvertimeRecord.APPROVED, date__range=(start, end),
    ).aggregate(hours=Sum('hours'), amount=Sum('amount'))
    return (
        (totals['hours'] or Decimal('0')).quantize(CENT, rounding=ROUND_HALF_UP),
        (totals['amount'] or Decimal('0')).quantize(CENT, rounding=ROUND_HALF_UP),
    )


def attendance_overtime(record):
    """Hours worked beyond the standard day for one attendance record (Decimal, 2 places)."""
    if not record.check_in_at or not record.check_out_at:
        return Decimal('0')
    shift = record.shift if getattr(record, 'shift_id', None) else shift_for(record.employee, record.date)
    worked = Decimal(str((record.check_out_at - record.check_in_at).total_seconds() / 60))
    extra = worked - Decimal(standard_minutes(shift))
    if extra <= 0:
        return Decimal('0')
    return (extra / 60).quantize(CENT, rounding=ROUND_HALF_UP)


def payroll_locked(user, day):
    """True when a PAID payslip already covers this employee and day (its overtime is final)."""
    from payroll.models import Payslip

    return Payslip.objects.filter(employee=user, year=day.year, month=day.month, status=Payslip.PAID).exists()


def default_rate(user):
    # A missing reverse one-to-one raises RelatedObjectDoesNotExist, an AttributeError subclass.
    structure = getattr(user, 'salary_structure', None)
    return structure.overtime_rate if structure is not None else Decimal('0')


def iter_days(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

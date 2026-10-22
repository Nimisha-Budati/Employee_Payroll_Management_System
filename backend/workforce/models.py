from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from accounts.models import Company


class Shift(models.Model):
    """A named working pattern, e.g. "General 09:30-18:30". End before start means the shift crosses midnight."""

    company = models.ForeignKey(Company, null=True, on_delete=models.CASCADE, related_name='shifts')
    name = models.CharField(max_length=60)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(240)])
    break_minutes = models.PositiveSmallIntegerField(default=60, validators=[MaxValueValidator(480)])
    is_default = models.BooleanField(
        default=False, help_text='Used for employees who have no shift assigned on a given day.',
    )
    is_active = models.BooleanField(default=True)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['start_time', 'name']
        constraints = [
            models.UniqueConstraint(fields=['company', 'name'], name='one_shift_name_per_company'),
            models.UniqueConstraint(fields=['company'], condition=models.Q(is_default=True), name='one_default_shift_per_company'),
        ]

    def __str__(self):
        return f'{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})'

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time

    @property
    def duration_minutes(self):
        start = datetime.combine(date.min, self.start_time)
        end = datetime.combine(date.min, self.end_time)
        if end <= start:
            end += timedelta(days=1)
        return int((end - start).total_seconds() // 60)

    @property
    def standard_minutes(self):
        """Paid working time per day: shift length minus the unpaid break."""
        return max(0, self.duration_minutes - self.break_minutes)


class ShiftAssignment(models.Model):
    """An employee's shift for a date range (open-ended when end_date is empty). This is the employee's shift record."""

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='shift_assignments')
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name='assignments')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date', '-id']
        indexes = [models.Index(fields=['employee', 'start_date'])]

    def __str__(self):
        return f'{self.employee.username}: {self.shift.name} from {self.start_date}'

    def covers(self, day):
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)


class OvertimeRecord(models.Model):
    PENDING, APPROVED, REJECTED, CANCELLED = 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'
    STATUS_CHOICES = [(PENDING, 'Pending'), (APPROVED, 'Approved'), (REJECTED, 'Rejected'), (CANCELLED, 'Cancelled')]
    SOURCE_CHOICES = [
        ('REQUEST', 'Employee request'),
        ('MANUAL', 'Entered by administrator'),
        ('ATTENDANCE', 'Generated from attendance'),
    ]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='overtime_records')
    date = models.DateField()
    hours = models.DecimalField(
        max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.25')), MaxValueValidator(Decimal('16'))],
    )
    rate = models.DecimalField('Pay per hour', max_digits=12, decimal_places=2, default=0,
                               validators=[MinValueValidator(Decimal('0'))])
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    reason = models.TextField(blank=True)
    source = models.CharField(max_length=12, choices=SOURCE_CHOICES, default='REQUEST')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', '-id']
        indexes = [models.Index(fields=['employee', 'date', 'status'])]

    def save(self, *args, **kwargs):
        self.amount = (Decimal(self.hours) * Decimal(self.rate)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.employee.username} {self.date} {self.hours}h ({self.status})'

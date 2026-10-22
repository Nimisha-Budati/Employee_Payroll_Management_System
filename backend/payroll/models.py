from decimal import Decimal

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from accounts.models import Company

MONEY = {'max_digits': 12, 'decimal_places': 2}
NON_NEGATIVE = [MinValueValidator(Decimal('0'))]


class SalaryStructure(models.Model):
    """Monthly salary components and fixed deductions for one employee."""

    employee = models.OneToOneField(User, on_delete=models.CASCADE, related_name='salary_structure')
    basic = models.DecimalField(validators=NON_NEGATIVE, **MONEY)
    hra = models.DecimalField('House rent allowance', default=0, validators=NON_NEGATIVE, **MONEY)
    da = models.DecimalField('Dearness allowance', default=0, validators=NON_NEGATIVE, **MONEY)
    conveyance_allowance = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    medical_allowance = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    special_allowance = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    other_allowance = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    # Fixed monthly bonus paid in full every month (not reduced for loss of pay, not part of the PF wage).
    # One-off bonuses are added per payslip by an administrator while it is a draft.
    bonus = models.DecimalField('Monthly bonus', default=0, validators=NON_NEGATIVE, **MONEY)
    pf_percent = models.DecimalField(
        'Provident fund % of basic + DA', max_digits=5, decimal_places=2, default=Decimal('12.00'),
        validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))],
    )
    professional_tax = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    tds = models.DecimalField('Income tax (TDS) per month', default=0, validators=NON_NEGATIVE, **MONEY)
    other_deduction = models.DecimalField(default=0, validators=NON_NEGATIVE, **MONEY)
    overtime_rate = models.DecimalField('Overtime pay per hour', default=0, validators=NON_NEGATIVE, **MONEY)
    effective_from = models.DateField()
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    COMPONENT_FIELDS = ('basic', 'hra', 'da', 'conveyance_allowance', 'medical_allowance', 'special_allowance', 'other_allowance')

    @property
    def gross_monthly(self):
        return sum((getattr(self, field) for field in self.COMPONENT_FIELDS), Decimal('0'))

    def __str__(self):
        return f'Salary structure for {self.employee.username}'


class Payslip(models.Model):
    DRAFT = 'DRAFT'
    PAID = 'PAID'
    STATUS_CHOICES = [(DRAFT, 'Draft'), (PAID, 'Paid')]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payslips')
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])

    # Snapshot of employee details so a payslip never changes after the fact.
    employee_code = models.CharField(max_length=20)
    employee_name = models.CharField(max_length=150)
    department = models.CharField(max_length=100, blank=True)
    designation = models.CharField(max_length=100, blank=True)

    # Attendance summary
    working_days = models.PositiveSmallIntegerField(default=0)
    lop_days = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # Earnings (full monthly amounts; loss of pay is shown as a deduction)
    basic = models.DecimalField(default=0, **MONEY)
    hra = models.DecimalField(default=0, **MONEY)
    da = models.DecimalField(default=0, **MONEY)
    conveyance_allowance = models.DecimalField(default=0, **MONEY)
    medical_allowance = models.DecimalField(default=0, **MONEY)
    special_allowance = models.DecimalField(default=0, **MONEY)
    other_allowance = models.DecimalField(default=0, **MONEY)
    overtime_pay = models.DecimalField(default=0, **MONEY)
    bonus = models.DecimalField(default=0, **MONEY)
    gross_earnings = models.DecimalField(default=0, **MONEY)

    # Deductions
    pf_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    pf = models.DecimalField(default=0, **MONEY)
    # *_base is the full monthly amount from the salary structure; professional_tax / tds are
    # what was actually deducted after pro-rating for loss of pay.
    professional_tax_base = models.DecimalField(default=0, **MONEY)
    tds_base = models.DecimalField(default=0, **MONEY)
    professional_tax = models.DecimalField(default=0, **MONEY)
    tds = models.DecimalField(default=0, **MONEY)
    other_deduction = models.DecimalField(default=0, **MONEY)
    lop_deduction = models.DecimalField(default=0, **MONEY)
    total_deductions = models.DecimalField(default=0, **MONEY)

    net_salary = models.DecimalField(default=0, **MONEY)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=DRAFT)
    notes = models.CharField(max_length=300, blank=True)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-year', '-month', 'employee_code']
        constraints = [
            models.UniqueConstraint(fields=['employee', 'year', 'month'], name='one_payslip_per_employee_month'),
        ]
        indexes = [models.Index(fields=['year', 'month', 'status'])]

    def __str__(self):
        return f'{self.employee_code} {self.year}-{self.month:02d} ({self.status})'


class PayrollReview(models.Model):
    """An administrator's sign-off of the variance preview for a payroll month (required before finalising)."""

    company = models.ForeignKey(Company, null=True, on_delete=models.CASCADE, related_name='payroll_reviews')
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='+')
    reviewed_at = models.DateTimeField(auto_now_add=True)
    draft_count = models.PositiveIntegerField(default=0)
    flagged_count = models.PositiveIntegerField(default=0)
    net_total = models.DecimalField(default=0, **MONEY)
    note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-reviewed_at', '-id']
        indexes = [models.Index(fields=['year', 'month', 'reviewed_at'])]

    def __str__(self):
        return f'Payroll review {self.year}-{self.month:02d} at {self.reviewed_at:%Y-%m-%d %H:%M}'

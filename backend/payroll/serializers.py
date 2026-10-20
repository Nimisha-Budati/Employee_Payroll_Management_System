from decimal import Decimal

from rest_framework import serializers

from .models import Payslip, SalaryStructure


class SalaryStructureSerializer(serializers.ModelSerializer):
    gross_monthly = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = SalaryStructure
        fields = [
            'basic', 'hra', 'da', 'conveyance_allowance', 'medical_allowance', 'special_allowance', 'other_allowance',
            'bonus', 'pf_percent', 'professional_tax', 'tds', 'other_deduction', 'overtime_rate',
            'effective_from', 'gross_monthly', 'updated_at',
        ]
        read_only_fields = ['gross_monthly', 'updated_at']

    def validate_basic(self, value):
        if value <= 0:
            raise serializers.ValidationError('Basic pay must be greater than zero.')
        return value

    def validate(self, data):
        gross = sum(
            (data.get(field, getattr(self.instance, field, Decimal('0'))) for field in SalaryStructure.COMPONENT_FIELDS),
            Decimal('0'),
        )
        basic = data.get('basic', getattr(self.instance, 'basic', Decimal('0')))
        da = data.get('da', getattr(self.instance, 'da', Decimal('0')))
        pf = (basic + da) * data.get('pf_percent', getattr(self.instance, 'pf_percent', Decimal('0'))) / 100
        fixed_deductions = sum(
            (data.get(field, getattr(self.instance, field, Decimal('0'))) for field in ('professional_tax', 'tds', 'other_deduction')),
            Decimal('0'),
        ) + pf
        if fixed_deductions > gross:
            raise serializers.ValidationError('Monthly deductions cannot exceed the monthly gross salary.')
        return data


class PayslipSerializer(serializers.ModelSerializer):
    employee_user_id = serializers.ReadOnlyField(source='employee_id')
    paid_days = serializers.SerializerMethodField()
    period_label = serializers.SerializerMethodField()

    class Meta:
        model = Payslip
        fields = [
            'id', 'employee_user_id', 'employee_code', 'employee_name', 'department', 'designation',
            'year', 'month', 'period_label', 'working_days', 'lop_days', 'paid_days', 'overtime_hours',
            'basic', 'hra', 'da', 'conveyance_allowance', 'medical_allowance', 'special_allowance', 'other_allowance',
            'overtime_pay', 'bonus', 'gross_earnings',
            'pf_percent', 'pf', 'professional_tax', 'tds', 'other_deduction', 'lop_deduction', 'total_deductions',
            'net_salary', 'status', 'notes', 'generated_at', 'paid_at',
        ]
        read_only_fields = fields

    def get_paid_days(self, obj):
        return max(Decimal('0'), Decimal(obj.working_days) - obj.lop_days)

    def get_period_label(self, obj):
        import calendar
        return f'{calendar.month_name[obj.month]} {obj.year}'


class PayslipAdjustmentSerializer(serializers.Serializer):
    """Manual corrections an administrator may make to a draft payslip."""

    lop_days = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, required=False)
    bonus = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    other_deduction = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)

    def validate_lop_days(self, value):
        if (value * 2) % 1 != 0:
            raise serializers.ValidationError('Loss-of-pay days must be a whole or half day (for example 1 or 1.5).')
        return value


class RunPayrollSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)
    lop_mode = serializers.ChoiceField(choices=['ATTENDANCE', 'NONE'], default='ATTENDANCE')
    employee_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False)


class FinalizeSerializer(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100)
    month = serializers.IntegerField(min_value=1, max_value=12)
    payslip_ids = serializers.ListField(child=serializers.IntegerField(), required=False, allow_empty=False)

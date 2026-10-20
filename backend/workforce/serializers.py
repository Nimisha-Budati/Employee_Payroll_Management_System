from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Q
from rest_framework import serializers

from .models import OvertimeRecord, Shift, ShiftAssignment


def _display_name(user):
    return user.get_full_name() or user.username


def _employee_code(user):
    employee = getattr(user, 'employee', None)
    return employee.employee_id if employee is not None else ''


class ShiftSerializer(serializers.ModelSerializer):
    duration_minutes = serializers.IntegerField(read_only=True)
    standard_minutes = serializers.IntegerField(read_only=True)
    crosses_midnight = serializers.BooleanField(read_only=True)
    active_assignments = serializers.SerializerMethodField()

    class Meta:
        model = Shift
        fields = [
            'id', 'name', 'start_time', 'end_time', 'grace_minutes', 'break_minutes', 'is_default', 'is_active',
            'description', 'duration_minutes', 'standard_minutes', 'crosses_midnight', 'active_assignments',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_active_assignments(self, obj):
        today = self.context.get('today')
        if today is None:
            return None
        return obj.assignments.filter(start_date__lte=today).filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).count()

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Shift name cannot be blank.')
        queryset = Shift.objects.filter(name__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('A shift with this name already exists.')
        return value

    def validate(self, data):
        start = data.get('start_time', getattr(self.instance, 'start_time', None))
        end = data.get('end_time', getattr(self.instance, 'end_time', None))
        if start is not None and end is not None and start == end:
            raise serializers.ValidationError({'end_time': 'End time must differ from start time.'})
        probe = Shift(
            start_time=start, end_time=end,
            break_minutes=data.get('break_minutes', getattr(self.instance, 'break_minutes', 0)),
        )
        if start is not None and end is not None and probe.break_minutes >= probe.duration_minutes:
            raise serializers.ValidationError({'break_minutes': 'The break must be shorter than the shift.'})
        if data.get('is_default') and data.get('is_active') is False:
            raise serializers.ValidationError({'is_default': 'An inactive shift cannot be the default shift.'})
        return data


class ShiftAssignmentSerializer(serializers.ModelSerializer):
    employee_user_id = serializers.ReadOnlyField(source='employee_id')
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    shift = ShiftSerializer(read_only=True)
    shift_id = serializers.PrimaryKeyRelatedField(queryset=Shift.objects.all(), source='shift', write_only=True)

    class Meta:
        model = ShiftAssignment
        fields = [
            'id', 'employee_user_id', 'employee_name', 'employee_code', 'shift', 'shift_id',
            'start_date', 'end_date', 'notes', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']

    def get_employee_name(self, obj):
        return _display_name(obj.employee)

    def get_employee_code(self, obj):
        return _employee_code(obj.employee)

    def validate_shift_id(self, shift):
        if not shift.is_active:
            raise serializers.ValidationError('This shift is inactive.')
        return shift

    def validate(self, data):
        start = data.get('start_date', getattr(self.instance, 'start_date', None))
        end = data.get('end_date', getattr(self.instance, 'end_date', None))
        if start and end and end < start:
            raise serializers.ValidationError({'end_date': 'End date cannot be before start date.'})
        return data


def overlapping_assignments(employee, start, end, exclude_pk=None):
    queryset = ShiftAssignment.objects.filter(employee=employee).filter(Q(end_date__isnull=True) | Q(end_date__gte=start))
    if end is not None:
        queryset = queryset.filter(start_date__lte=end)
    if exclude_pk is not None:
        queryset = queryset.exclude(pk=exclude_pk)
    return queryset


class OvertimeRecordSerializer(serializers.ModelSerializer):
    employee_user_id = serializers.ReadOnlyField(source='employee_id')
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = OvertimeRecord
        fields = [
            'id', 'employee_user_id', 'employee_name', 'employee_code', 'date', 'hours', 'rate', 'amount', 'reason',
            'source', 'status', 'review_note', 'reviewed_by_name', 'reviewed_at', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'amount', 'source', 'status', 'review_note', 'reviewed_at', 'created_at', 'updated_at']

    def get_employee_name(self, obj):
        return _display_name(obj.employee)

    def get_employee_code(self, obj):
        return _employee_code(obj.employee)

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.username if obj.reviewed_by_id else ''

    def validate_hours(self, value):
        if (value * 4) % 1 != 0:
            raise serializers.ValidationError('Use quarter-hour steps (for example 1.25 or 2.5).')
        return value


class OvertimeCreateSerializer(serializers.Serializer):
    """Admins may record overtime for any employee and approve it straight away."""

    employee_id = serializers.IntegerField(required=False)
    date = serializers.DateField()
    hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal('0.25'), max_value=Decimal('16'))
    rate = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0'), required=False)
    reason = serializers.CharField(max_length=500, allow_blank=False)
    approve = serializers.BooleanField(required=False, default=False)

    def validate_hours(self, value):
        if (value * 4) % 1 != 0:
            raise serializers.ValidationError('Use quarter-hour steps (for example 1.25 or 2.5).')
        return value

    def validate_employee_id(self, value):
        user = User.objects.filter(pk=value, userprofile__role='EMPLOYEE', is_active=True).first()
        if user is None:
            raise serializers.ValidationError('Active employee not found.')
        return user

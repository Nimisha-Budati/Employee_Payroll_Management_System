from rest_framework import serializers
from django.contrib.auth.models import User
from .models import AttendanceRecord, AttendanceSettings, Employee, EmployeeDocument, Holiday, LeaveRequest, UserProfile, WorkFromHomeRequest


class EmployeeSerializer(serializers.ModelSerializer):
    username = serializers.ReadOnlyField(source='user.username')
    email = serializers.ReadOnlyField(source='user.email')
    is_active = serializers.ReadOnlyField(source='user.is_active')

    class Meta:
        model = Employee
        fields = ['id', 'employee_id', 'username', 'email', 'phone', 'department', 'designation', 'joining_date', 'status', 'is_active']
        read_only_fields = ['id', 'username', 'email', 'is_active']


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_id = serializers.ReadOnlyField(source='employee.id')

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee_id', 'employee_username',
            'leave_type', 'start_date', 'end_date', 'number_of_days',
            'reason', 'status', 'rejection_reason', 'applied_at', 'updated_at'
        ]
        read_only_fields = ['id', 'employee_id', 'employee_username', 'number_of_days', 'applied_at', 'updated_at']

    def validate(self, data):
        start_date = data.get('start_date')
        end_date = data.get('end_date')

        if start_date and end_date:
            if end_date < start_date:
                raise serializers.ValidationError({"end_date": "End date cannot be before start date."})

        request = self.context.get('request')
        if request and request.method == 'POST':
            user = request.user
            overlapping = LeaveRequest.objects.filter(
                employee=user,
                status='PENDING',
                start_date__lte=end_date,
                end_date__gte=start_date
            ).exists()
            if overlapping:
                raise serializers.ValidationError("You already have an overlapping pending leave request for these dates.")

        return data


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_id = serializers.ReadOnlyField(source='employee.id')
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = [
            'id', 'employee_id', 'employee_username', 'title', 'document_type', 'custom_document_type',
            'file', 'file_url', 'status', 'review_note', 'uploaded_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'employee_id', 'employee_username', 'file_url', 'status',
            'review_note', 'uploaded_at', 'updated_at',
        ]

    def get_file_url(self, obj):
        request = self.context.get('request')
        url = obj.file.url
        return request.build_absolute_uri(url) if request else url

    def validate_file(self, value):
        allowed_types = {'application/pdf', 'image/jpeg', 'image/png'}
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 5 MB.')
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        return value

    def validate(self, data):
        if data.get('document_type') == 'OTHER' and not data.get('custom_document_type', '').strip():
            raise serializers.ValidationError({'custom_document_type': 'Please specify the document type.'})
        return data


class ProfileSerializer(serializers.ModelSerializer):
    first_name = serializers.CharField(source='user.first_name', max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(source='user.last_name', max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(source='user.email')
    username = serializers.ReadOnlyField(source='user.username')
    profile_photo_url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'phone', 'address', 'profile_photo', 'profile_photo_url']
        read_only_fields = ['username', 'role', 'profile_photo_url']

    def get_profile_photo_url(self, obj):
        if not obj.profile_photo:
            return None
        request = self.context.get('request')
        url = obj.profile_photo.url
        return request.build_absolute_uri(url) if request else url

    def validate_email(self, value):
        user_id = self.instance.user_id if self.instance else None
        if User.objects.exclude(pk=user_id).filter(email__iexact=value).exists():
            raise serializers.ValidationError('This email address is already in use.')
        return value

    def validate_profile_photo(self, value):
        if value.size > 2 * 1024 * 1024:
            raise serializers.ValidationError('Profile photo must not exceed 2 MB.')
        if value.content_type not in {'image/jpeg', 'image/png'}:
            raise serializers.ValidationError('Only JPG and PNG profile photos are allowed.')
        return value

    def update(self, instance, validated_data):
        user_data = validated_data.pop('user', {})
        for field, value in user_data.items():
            setattr(instance.user, field, value)
        instance.user.save()
        return super().update(instance, validated_data)


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = ['id', 'name', 'date', 'holiday_type', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class AttendanceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceSettings
        fields = ['latitude', 'longitude', 'radius_meters', 'is_enabled', 'updated_at']
        read_only_fields = ['updated_at']

    def validate(self, data):
        latitude = data.get('latitude', getattr(self.instance, 'latitude', None))
        longitude = data.get('longitude', getattr(self.instance, 'longitude', None))
        enabled = data.get('is_enabled', getattr(self.instance, 'is_enabled', False))
        if enabled and (latitude is None or longitude is None):
            raise serializers.ValidationError('Set an office latitude and longitude before enabling attendance.')
        if latitude is not None and not -90 <= latitude <= 90:
            raise serializers.ValidationError({'latitude': 'Latitude must be between -90 and 90.'})
        if longitude is not None and not -180 <= longitude <= 180:
            raise serializers.ValidationError({'longitude': 'Longitude must be between -180 and 180.'})
        return data


class AttendanceRecordSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_name = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    worked_minutes = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'employee_username', 'employee_name', 'date', 'check_in_at', 'check_out_at',
            'check_in_distance_meters', 'check_out_distance_meters', 'status', 'worked_minutes',
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() or obj.employee.username

    def get_status(self, obj):
        return 'CHECKED_OUT' if obj.check_out_at else 'CHECKED_IN'

    def get_worked_minutes(self, obj):
        if not obj.check_in_at or not obj.check_out_at:
            return None
        return max(0, round((obj.check_out_at - obj.check_in_at).total_seconds() / 60))


class WorkFromHomeSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    number_of_days = serializers.SerializerMethodField()

    class Meta:
        model = WorkFromHomeRequest
        fields = ['id', 'employee_username', 'start_date', 'end_date', 'number_of_days', 'reason', 'status', 'admin_note', 'applied_at', 'updated_at']
        read_only_fields = ['id', 'employee_username', 'number_of_days', 'status', 'admin_note', 'applied_at', 'updated_at']

    def get_number_of_days(self, obj):
        return (obj.end_date - obj.start_date).days + 1

    def validate(self, data):
        start_date, end_date = data.get('start_date'), data.get('end_date')
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'End date cannot be before start date.'})
        request = self.context.get('request')
        if request and request.method == 'POST' and start_date and end_date:
            overlapping = WorkFromHomeRequest.objects.filter(employee=request.user, status__in=['PENDING', 'APPROVED'], start_date__lte=end_date, end_date__gte=start_date).exists()
            if overlapping:
                raise serializers.ValidationError('You already have a pending or approved WFH request for these dates.')
        return data

import re

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ObjectDoesNotExist, ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework import serializers
from .models import Company, ReminderSettings, AuditLog, Announcement, NotificationBroadcast, LeavePolicySettings, LeaveType, AttendanceRecord, AttendanceSettings, ChatConversation, ChatMessage, Employee, EmployeeDocument, Holiday, LeaveRequest, Notification, UserProfile, WorkFromHomeRequest


PHONE_RE = re.compile(r'^[0-9+\-() ]{7,15}$')
EMPLOYEE_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9\-_/]{1,19}$')


def validate_phone_number(value):
    value = (value or '').strip()
    if not PHONE_RE.match(value):
        raise serializers.ValidationError('Enter a valid phone number (7-15 digits; + - ( ) and spaces allowed).')
    return value


def validate_employee_code(value):
    value = (value or '').strip().upper()
    if not EMPLOYEE_ID_RE.match(value):
        raise serializers.ValidationError('Employee ID must be 2-20 characters: letters, numbers, - _ / only.')
    return value


class EmployeeSerializer(serializers.ModelSerializer):
    user_id = serializers.ReadOnlyField()
    username = serializers.ReadOnlyField(source='user.username')
    email = serializers.ReadOnlyField(source='user.email')
    first_name = serializers.ReadOnlyField(source='user.first_name')
    last_name = serializers.ReadOnlyField(source='user.last_name')
    full_name = serializers.SerializerMethodField()
    is_active = serializers.ReadOnlyField(source='user.is_active')
    has_salary_structure = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = [
            'id', 'user_id', 'employee_id', 'username', 'email', 'first_name', 'last_name', 'full_name',
            'phone', 'department', 'designation', 'joining_date', 'status', 'is_active', 'has_salary_structure',
            'deactivated_at', 'onboarding_status',
        ]
        read_only_fields = fields

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_has_salary_structure(self, obj):
        try:
            return obj.user.salary_structure is not None
        except ObjectDoesNotExist:
            return False


class EmployeeWriteSerializer(serializers.Serializer):
    """Validates admin input when creating or editing an employee record."""

    # Account fields (only used when creating a brand-new account)
    username = serializers.CharField(max_length=150, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, trim_whitespace=False)
    user_id = serializers.IntegerField(required=False)
    # Shared fields
    email = serializers.EmailField(required=False)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    employee_id = serializers.CharField(max_length=20, required=False)
    phone = serializers.CharField(max_length=15, required=False)
    department = serializers.CharField(max_length=100, required=False)
    designation = serializers.CharField(max_length=100, required=False)
    joining_date = serializers.DateField(required=False)
    status = serializers.ChoiceField(choices=['ACTIVE', 'INACTIVE'], required=False)

    CREATE_REQUIRED = ['employee_id', 'phone', 'department', 'designation', 'joining_date']

    def validate_employee_id(self, value):
        value = validate_employee_code(value)
        queryset = Employee.objects.filter(employee_id__iexact=value, company_id=self.context.get('company_id'))
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('Employee ID already exists.')
        return value

    def validate_phone(self, value):
        return validate_phone_number(value)

    def validate_department(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Department cannot be blank.')
        return value

    def validate_designation(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Designation cannot be blank.')
        return value

    def validate_username(self, value):
        value = value.strip()
        try:
            User.username_validator(value)
        except DjangoValidationError:
            raise serializers.ValidationError('Username may only contain letters, numbers and @/./+/-/_ characters.')
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Username already exists.')
        return value

    def validate_email(self, value):
        value = value.strip().lower()
        queryset = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.user_id)
        user_id = self.initial_data.get('user_id') if hasattr(self, 'initial_data') else None
        if user_id not in (None, ''):
            queryset = queryset.exclude(pk=user_id)
        if queryset.exists():
            raise serializers.ValidationError('Email already exists.')
        return value

    def validate(self, data):
        if self.instance is None:
            missing = {field: 'This field is required.' for field in self.CREATE_REQUIRED if field not in data}
            if 'user_id' in data:
                try:
                    user = User.objects.select_related('userprofile').get(pk=data['user_id'])
                except User.DoesNotExist:
                    raise serializers.ValidationError({'user_id': 'Account not found.'})
                profile = getattr(user, 'userprofile', None)
                if profile is None or profile.role != 'EMPLOYEE' or hasattr(user, 'employee'):
                    raise serializers.ValidationError({'user_id': 'This account cannot be onboarded as an employee.'})
                company_id = self.context.get('company_id')
                if profile.company_id not in (None, company_id):
                    raise serializers.ValidationError({'user_id': 'This account belongs to another company.'})
                data['existing_user'] = user
            else:
                for field in ('username', 'email', 'password'):
                    if field not in data:
                        missing[field] = 'This field is required.'
            if missing:
                raise serializers.ValidationError(missing)
            if 'password' in data:
                try:
                    validate_password(data['password'], User(username=data.get('username', ''), email=data.get('email', '')))
                except DjangoValidationError as error:
                    raise serializers.ValidationError({'password': list(error.messages)})
        return data


from .leave_policy import leave_balance_for, leave_year_of, policy_settings, resolve_leave_type  # noqa: E402 (re-exported)


class LeaveTypeSerializer(serializers.ModelSerializer):
    is_limited = serializers.BooleanField(read_only=True)
    request_count = serializers.SerializerMethodField()

    class Meta:
        model = LeaveType
        fields = ['id', 'name', 'description', 'annual_days', 'is_paid', 'is_active', 'allow_carry_forward',
                  'max_carry_forward_days', 'sort_order', 'is_limited', 'request_count', 'created_at', 'updated_at']
        read_only_fields = ['id', 'is_limited', 'request_count', 'created_at', 'updated_at']

    def get_request_count(self, obj):
        return getattr(obj, 'request_count', None)

    def validate_name(self, value):
        value = ' '.join(value.split())
        if not value:
            raise serializers.ValidationError('Enter a name for the leave type.')
        queryset = LeaveType.objects.filter(name__iexact=value, company_id=self.context.get('company_id'))
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError('A leave type with this name already exists.')
        return value

    def validate_annual_days(self, value):
        if value is not None and value > 366:
            raise serializers.ValidationError('Use 366 days or fewer.')
        return value

    def validate(self, data):
        annual = data.get('annual_days', getattr(self.instance, 'annual_days', None))
        carry = data.get('allow_carry_forward', getattr(self.instance, 'allow_carry_forward', False))
        max_carry = data.get('max_carry_forward_days', getattr(self.instance, 'max_carry_forward_days', 0))
        if carry and annual is None:
            raise serializers.ValidationError({'allow_carry_forward': 'Only leave types with an annual limit can carry days forward.'})
        if carry and not max_carry:
            raise serializers.ValidationError({'max_carry_forward_days': 'Set how many unused days may be carried forward.'})
        if max_carry and max_carry > 366:
            raise serializers.ValidationError({'max_carry_forward_days': 'Use 366 days or fewer.'})
        if not carry:
            data['max_carry_forward_days'] = 0
        return data


class LeavePolicySettingsSerializer(serializers.ModelSerializer):
    updated_by_username = serializers.ReadOnlyField(source='updated_by.username')

    class Meta:
        model = LeavePolicySettings
        fields = ['leave_year_start_month', 'min_notice_days', 'max_days_per_request', 'allow_past_dates',
                  'updated_by_username', 'updated_at']
        read_only_fields = ['updated_by_username', 'updated_at']

    def validate_leave_year_start_month(self, value):
        if not 1 <= value <= 12:
            raise serializers.ValidationError('Choose a month from 1 (January) to 12 (December).')
        return value

    def validate_min_notice_days(self, value):
        if value > 365:
            raise serializers.ValidationError('Use 365 days or fewer.')
        return value

    def validate_max_days_per_request(self, value):
        if value is not None and not 1 <= value <= 366:
            raise serializers.ValidationError('Use between 1 and 366 days, or leave it empty for no limit.')
        return value


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_id = serializers.ReadOnlyField(source='employee.id')
    employee_code = serializers.SerializerMethodField()
    leave_type = serializers.CharField(max_length=50)
    is_paid = serializers.SerializerMethodField()

    class Meta:
        model = LeaveRequest
        fields = [
            'id', 'employee_id', 'employee_code', 'employee_username',
            'leave_type', 'policy', 'is_paid', 'start_date', 'end_date', 'number_of_days',
            'reason', 'status', 'rejection_reason', 'applied_at', 'updated_at'
        ]
        read_only_fields = ['id', 'employee_id', 'employee_code', 'employee_username', 'policy', 'is_paid',
                            'number_of_days', 'status', 'rejection_reason', 'applied_at', 'updated_at']

    def get_employee_code(self, obj):
        try:
            return obj.employee.employee.employee_id
        except Exception:
            return f'EMP-{obj.employee_id}'

    def get_is_paid(self, obj):
        return obj.policy.is_paid if obj.policy_id else None

    def validate_leave_type(self, value):
        leave_type = resolve_leave_type(value, Company.objects.filter(pk=self.context.get('company_id')).first())
        if leave_type is None:
            raise serializers.ValidationError('Choose one of the leave types configured by your administrator.')
        if not leave_type.is_active:
            raise serializers.ValidationError(f'{leave_type.name} is no longer offered. Choose another leave type.')
        self._leave_type = leave_type
        return leave_type.name

    def validate(self, data):
        from django.utils import timezone

        start_date = data.get('start_date')
        end_date = data.get('end_date')
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError({'end_date': 'End date cannot be before start date.'})

        request = self.context.get('request')
        if request and request.method == 'POST':
            user = request.user
            leave_type = self._leave_type
            company = Company.objects.filter(pk=self.context.get('company_id')).first()
            rules = policy_settings(company)
            requested = (end_date - start_date).days + 1
            today = timezone.localdate()
            if not rules.allow_past_dates and start_date < today:
                raise serializers.ValidationError({'start_date': 'Leave cannot start in the past under the current leave policy.'})
            if rules.min_notice_days and start_date >= today and (start_date - today).days < rules.min_notice_days:
                raise serializers.ValidationError({'start_date': f'Apply at least {rules.min_notice_days} day(s) before the leave starts.'})
            if rules.max_days_per_request and requested > rules.max_days_per_request:
                raise serializers.ValidationError({'end_date': f'A single request can be at most {rules.max_days_per_request} day(s).'})
            overlapping = LeaveRequest.objects.filter(
                employee=user, status__in=['PENDING', 'APPROVED'], start_date__lte=end_date, end_date__gte=start_date,
            ).exists()
            if overlapping:
                raise serializers.ValidationError("You already have an overlapping pending or approved leave request for these dates.")
            if leave_type.annual_days is not None:
                year = leave_year_of(start_date, rules)
                entry = leave_balance_for(user, year).get(leave_type.name)
                remaining = entry['remaining'] if entry else 0
                if requested > remaining:
                    pending = entry['pending'] if entry else 0
                    unpaid = LeaveType.objects.filter(company=company, is_active=True, is_paid=False, annual_days__isnull=True).first()
                    hint = f' or apply as "{unpaid.name}" (unpaid leave)' if unpaid else ''
                    raise serializers.ValidationError({
                        'leave_type': f'You asked for {requested} day(s) of {leave_type.name}, but only {remaining} day(s) can be requested '
                                      f'for this leave year'
                                      + (f' ({pending} day(s) are already waiting for approval)' if pending else '')
                                      + f'. Choose fewer days{hint}.'
                    })
            data['policy'] = leave_type
        return data


FILE_SIGNATURES = (b'%PDF-', b'\xff\xd8\xff', b'\x89PNG\r\n\x1a\n')


IMAGE_SIGNATURES = FILE_SIGNATURES[1:]


def has_allowed_signature(uploaded_file, signatures=FILE_SIGNATURES):
    """Check the real file header, not just the client-supplied content type."""
    position = uploaded_file.tell() if hasattr(uploaded_file, 'tell') else 0
    header = uploaded_file.read(8)
    uploaded_file.seek(position)
    return header.startswith(signatures)


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_id = serializers.ReadOnlyField(source='employee.id')
    file_url = serializers.SerializerMethodField()

    expiry_status = serializers.SerializerMethodField()
    days_to_expiry = serializers.SerializerMethodField()
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeDocument
        fields = [
            'id', 'employee_id', 'employee_username', 'employee_name', 'title', 'document_type', 'custom_document_type',
            'file', 'file_url', 'status', 'review_note', 'expiry_date', 'expiry_status', 'days_to_expiry',
            'uploaded_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'employee_id', 'employee_username', 'employee_name', 'file_url', 'status',
            'review_note', 'expiry_status', 'days_to_expiry', 'uploaded_at', 'updated_at',
        ]

    def _warn_days(self, obj):
        if 'warn_days' in self.context:
            return self.context['warn_days']
        company = getattr(getattr(obj.employee, 'userprofile', None), 'company', None)
        cache = self.context.setdefault('_warn_days_by_company', {})
        company_key = getattr(company, 'pk', None)
        if company_key not in cache:
            cache[company_key] = ReminderSettings.load(company).warning_window_days
        return cache[company_key]

    def get_expiry_status(self, obj):
        return obj.expiry_state(warn_days=self._warn_days(obj))

    def get_days_to_expiry(self, obj):
        return (obj.expiry_date - timezone.localdate()).days if obj.expiry_date else None

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() or obj.employee.username

    def validate_expiry_date(self, value):
        if value is not None and value < timezone.localdate():
            raise serializers.ValidationError('This document has already expired. Upload a current one.')
        return value

    def get_file_url(self, obj):
        # Documents are private: they are served by an authenticated endpoint, never from /media/.
        url = reverse('document-file', args=[obj.pk])
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def validate_file(self, value):
        allowed_types = {'application/pdf', 'image/jpeg', 'image/png'}
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError('File size must not exceed 5 MB.')
        if value.content_type not in allowed_types:
            raise serializers.ValidationError('Only PDF, JPG, and PNG files are allowed.')
        if not has_allowed_signature(value):
            raise serializers.ValidationError('The file content does not match a PDF, JPG or PNG file.')
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
    company_name = serializers.CharField(source='company.name', read_only=True, allow_null=True)

    class Meta:
        model = UserProfile
        fields = ['username', 'first_name', 'last_name', 'email', 'role', 'phone', 'address', 'profile_photo', 'profile_photo_url', 'company_name']
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
        if not has_allowed_signature(value, IMAGE_SIGNATURES):
            raise serializers.ValidationError('The file content is not a valid JPG or PNG image.')
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


class AnnouncementSerializer(serializers.ModelSerializer):
    author_username = serializers.ReadOnlyField(source='created_by.username')

    class Meta:
        model = Announcement
        fields = ['id', 'title', 'message', 'author_username', 'created_at', 'updated_at']
        read_only_fields = ['id', 'author_username', 'created_at', 'updated_at']


class ChatConversationSerializer(serializers.ModelSerializer):
    administrator_username = serializers.ReadOnlyField(source='administrator.username')
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_name = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_at = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = ChatConversation
        fields = [
            'id', 'administrator_username', 'employee_username', 'employee_name',
            'last_message', 'last_message_at', 'unread_count', 'updated_at',
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() or obj.employee.username

    def get_last_message(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        return message.body if message else ''

    def get_last_message_at(self, obj):
        message = obj.messages.order_by('-created_at', '-id').first()
        return message.created_at if message else None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request:
            return 0
        return obj.messages.filter(is_read=False).exclude(sender=request.user).count()


class ChatMessageSerializer(serializers.ModelSerializer):
    sender_id = serializers.ReadOnlyField(source='sender.id')
    sender_username = serializers.ReadOnlyField(source='sender.username')
    is_own = serializers.SerializerMethodField()

    class Meta:
        model = ChatMessage
        fields = ['id', 'sender_id', 'sender_username', 'body', 'created_at', 'is_own']
        read_only_fields = ['id', 'sender_id', 'sender_username', 'created_at', 'is_own']

    def get_is_own(self, obj):
        request = self.context.get('request')
        return bool(request and obj.sender_id == request.user.id)


class ChatEmployeeSerializer(serializers.ModelSerializer):
    employee_id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.ReadOnlyField(source='user.username')
    display_name = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ['employee_id', 'username', 'display_name', 'department']

    def get_display_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_department(self, obj):
        try:
            return obj.user.employee.department
        except Employee.DoesNotExist:
            return ''


class NotificationSerializer(serializers.ModelSerializer):
    actor_username = serializers.ReadOnlyField(source='actor.username')
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'kind', 'title', 'message', 'actor_username', 'target_url', 'created_at', 'read_at', 'is_read', 'expires_at']

    def get_is_read(self, obj):
        return obj.read_at is not None


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
    employee_user_id = serializers.ReadOnlyField(source='employee_id')
    employee_username = serializers.ReadOnlyField(source='employee.username')
    employee_name = serializers.SerializerMethodField()
    employee_code = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    worked_minutes = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = [
            'id', 'employee_user_id', 'employee_username', 'employee_name', 'employee_code', 'date', 'check_in_at',
            'check_out_at', 'check_in_distance_meters', 'check_out_distance_meters', 'status', 'worked_minutes',
            'shift_name', 'scheduled_start', 'late_minutes', 'is_corrected',
        ]

    def get_employee_name(self, obj):
        return obj.employee.get_full_name() or obj.employee.username

    def get_employee_code(self, obj):
        employee = getattr(obj.employee, 'employee', None)
        return employee.employee_id if employee is not None else ''

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


class NotificationBroadcastSerializer(serializers.ModelSerializer):
    department = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    employee_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    created_by_username = serializers.ReadOnlyField(source='created_by.username')
    read_count = serializers.IntegerField(read_only=True, default=0)
    is_expired = serializers.SerializerMethodField()

    class Meta:
        model = NotificationBroadcast
        fields = [
            'id', 'title', 'message', 'target_type', 'target_label', 'department', 'employee_ids', 'expires_at',
            'recipient_count', 'read_count', 'is_expired', 'created_by_username', 'created_at',
        ]
        read_only_fields = ['id', 'target_label', 'recipient_count', 'read_count', 'is_expired', 'created_by_username', 'created_at']

    def get_is_expired(self, obj):
        from django.utils import timezone
        return bool(obj.expires_at and obj.expires_at <= timezone.now())

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Title cannot be blank.')
        return value

    def validate_message(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('Message cannot be blank.')
        if len(value) > 2000:
            raise serializers.ValidationError('Use 2000 characters or fewer.')
        return value

    def validate_expires_at(self, value):
        from django.utils import timezone
        if value is not None and value <= timezone.now():
            raise serializers.ValidationError('The expiry must be in the future.')
        return value

    def validate(self, data):
        target = data.get('target_type')
        if target == 'DEPARTMENT' and not data.get('department', '').strip():
            raise serializers.ValidationError({'department': 'Choose a department.'})
        if target == 'EMPLOYEES' and not data.get('employee_ids'):
            raise serializers.ValidationError({'employee_ids': 'Choose at least one employee.'})
        return data


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['id', 'actor_name', 'subject_name', 'module', 'action', 'entity_type', 'entity_id', 'summary', 'ip_address', 'created_at']
        read_only_fields = fields

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('ADMIN', 'Administrator'),
        ('EMPLOYEE', 'Employee'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    phone = models.CharField(max_length=20, blank=True)
    address = models.TextField(blank=True)
    profile_photo = models.FileField(upload_to='profile_photos/', blank=True)

    def __str__(self):
        return self.user.username


class Employee(models.Model):
    STATUS_CHOICES = [('ACTIVE', 'Active'), ('INACTIVE', 'Inactive')]
    employee_id = models.CharField(max_length=20, unique=True)
    phone = models.CharField(max_length=15)
    department = models.CharField(max_length=100)
    designation = models.CharField(max_length=100)
    joining_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # Date the employee was last deactivated (cleared on reactivation); used for headcount trends.
    deactivated_at = models.DateField(null=True, blank=True)

    # Onboarding: the checklist itself is computed from the profile and documents (accounts/onboarding.py);
    # only the administrator's decision and the "ready" notification time are stored.
    ONBOARDING_PENDING = 'PENDING'
    ONBOARDING_COMPLETED = 'COMPLETED'
    ONBOARDING_CHOICES = [(ONBOARDING_PENDING, 'In progress'), (ONBOARDING_COMPLETED, 'Completed')]
    onboarding_status = models.CharField(max_length=12, choices=ONBOARDING_CHOICES, default=ONBOARDING_PENDING, db_index=True)
    onboarding_ready_at = models.DateTimeField(null=True, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    onboarding_completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    onboarding_note = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f'{self.employee_id} - {self.user.username}'


class OnboardingSettings(models.Model):
    """Singleton (pk=1): what every new employee must provide before onboarding can be completed."""

    required_document_types = models.JSONField(default=list, blank=True)   # EmployeeDocument.DOCUMENT_TYPES codes
    require_address = models.BooleanField(default=True)
    require_profile_photo = models.BooleanField(default=False)
    require_salary_structure = models.BooleanField(default=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1, defaults={'required_document_types': ['IDENTITY', 'ADDRESS']})[0]


class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps')
    reset_token = models.CharField(max_length=64, unique=True)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def is_expired(self):
        return timezone.now() >= self.expires_at


class LeaveType(models.Model):
    """A leave type and its annual allowance, managed by administrators (no limits live in code)."""

    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    # Days allowed per employee per leave year; empty means no limit (for example unpaid leave).
    annual_days = models.PositiveSmallIntegerField(null=True, blank=True)
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    allow_carry_forward = models.BooleanField(default=False)
    max_carry_forward_days = models.PositiveSmallIntegerField(default=0)
    sort_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name

    @property
    def is_limited(self):
        return self.annual_days is not None


class LeavePolicySettings(models.Model):
    """Organisation-wide leave rules (single row)."""

    leave_year_start_month = models.PositiveSmallIntegerField(default=1)   # 1 = January (calendar year)
    min_notice_days = models.PositiveSmallIntegerField(default=0)          # days between applying and the start date
    max_days_per_request = models.PositiveSmallIntegerField(null=True, blank=True)
    allow_past_dates = models.BooleanField(default=True)                   # allow applying for leave already taken
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class EmployeeLeaveBalance(models.Model):
    """Per-employee, per-leave-year additions to the allowance (days carried forward and manual adjustments)."""

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='balances')
    year = models.PositiveSmallIntegerField()
    carried_forward = models.PositiveSmallIntegerField(default=0)
    adjustment = models.SmallIntegerField(default=0)
    note = models.CharField(max_length=255, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['employee', 'leave_type', 'year'], name='one_leave_balance_per_type_year')]


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='leave_requests')
    # Name of the leave type when the request was made (kept for history); ``policy`` links the configured type.
    leave_type = models.CharField(max_length=50)
    policy = models.ForeignKey(LeaveType, on_delete=models.PROTECT, null=True, blank=True, related_name='requests')
    start_date = models.DateField()
    end_date = models.DateField()
    number_of_days = models.IntegerField(editable=False, default=1)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    rejection_reason = models.TextField(blank=True, null=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.start_date and self.end_date:
            delta = self.end_date - self.start_date
            self.number_of_days = max(1, delta.days + 1)
        if self.policy_id is None and self.leave_type:
            self.policy = LeaveType.objects.filter(name__iexact=self.leave_type).first()
        if self.policy_id and not self.leave_type:
            self.leave_type = self.policy.name
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.username} - {self.leave_type} ({self.status})"


class EmployeeDocument(models.Model):
    DOCUMENT_TYPES = [
        ('IDENTITY', 'Identity Proof'),
        ('ADDRESS', 'Address Proof'),
        ('EDUCATION', 'Education Certificate'),
        ('RESUME', 'Resume'),
        ('OTHER', 'Other'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending review'),
        ('VERIFIED', 'Verified'),
        ('REJECTED', 'Rejected'),
    ]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='documents')
    title = models.CharField(max_length=100)
    document_type = models.CharField(max_length=20, choices=DOCUMENT_TYPES)
    custom_document_type = models.CharField(max_length=100, blank=True)
    file = models.FileField(upload_to='employee_documents/%Y/%m/')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    review_note = models.TextField(blank=True)
    # Optional validity end (passport, visa, licence...). Expiry is independent of the review status.
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee.username} - {self.title} ({self.status})"

    def expiry_state(self, today=None, warn_days=None):
        """NONE, VALID, EXPIRING (within warn_days) or EXPIRED."""
        if self.expiry_date is None:
            return 'NONE'
        today = today or timezone.localdate()
        if warn_days is None:
            warn_days = ReminderSettings.load().warning_window_days
        if self.expiry_date < today:
            return 'EXPIRED'
        return 'EXPIRING' if (self.expiry_date - today).days <= warn_days else 'VALID'


class Holiday(models.Model):
    HOLIDAY_TYPES = [
        ('FIXED', 'Fixed'),
        ('TENTATIVE', 'Tentative'),
    ]

    name = models.CharField(max_length=100)
    date = models.DateField(unique=True)
    holiday_type = models.CharField(max_length=20, choices=HOLIDAY_TYPES, default='FIXED')
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.name} ({self.date})"


class Announcement(models.Model):
    title = models.CharField(max_length=120)
    message = models.TextField()
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='announcements',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ChatConversation(models.Model):
    administrator = models.ForeignKey(User, on_delete=models.CASCADE, related_name='admin_conversations')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='employee_conversations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(fields=['administrator', 'employee'], name='one_chat_per_admin_employee'),
        ]


class ChatMessage(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages')
    body = models.TextField(max_length=4000)
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at', 'id']


class Notification(models.Model):
    KIND_CHOICES = [
        ('ANNOUNCEMENT', 'Announcement'),
        ('ATTENDANCE', 'Attendance'),
        ('CHAT', 'Chat'),
        ('CORRECTION', 'Attendance correction'),
        ('DOCUMENT', 'Document'),
        ('EMPLOYEE', 'Employee'),
        ('GENERAL', 'General'),
        ('HOLIDAY', 'Holiday'),
        ('LEAVE', 'Leave'),
        ('ONBOARDING', 'Onboarding'),
        ('OVERTIME', 'Overtime'),
        ('PAYROLL', 'Payroll'),
        ('REMINDER', 'Reminder'),
        ('SECURITY', 'Security'),
        ('SHIFT', 'Shift'),
        ('WFH', 'Work from home'),
    ]
    # Kinds a user can never switch off: account security, payslips/employee record, onboarding
    # and messages an administrator sent on purpose.
    MANDATORY_KINDS = ('SECURITY', 'EMPLOYEE', 'PAYROLL', 'ONBOARDING', 'GENERAL')

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    title = models.CharField(max_length=160)
    message = models.TextField()
    target_url = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # Notifications sent by an administrator may expire; expired ones are hidden from the inbox.
    expires_at = models.DateTimeField(null=True, blank=True)
    broadcast = models.ForeignKey(
        'NotificationBroadcast', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications',
    )

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['recipient', 'read_at'])]


class NotificationPreference(models.Model):
    """A user's choice to stop receiving one optional kind of in-app notification."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notification_preferences')
    kind = models.CharField(max_length=20, choices=Notification.KIND_CHOICES)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'kind'], name='one_preference_per_user_kind')]


class ReminderSettings(models.Model):
    """Singleton (pk=1) for automatic reminders (document expiry, pending approvals, onboarding)."""

    enabled = models.BooleanField(default=True)
    # Days before a document's expiry date on which the employee and administrators are reminded.
    document_reminder_days = models.JSONField(default=list, blank=True)
    # Administrators get a digest of requests that have waited at least this many days.
    pending_after_days = models.PositiveSmallIntegerField(default=2)
    last_run_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    DEFAULT_DOCUMENT_DAYS = [30, 7, 1]

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1, defaults={'document_reminder_days': list(cls.DEFAULT_DOCUMENT_DAYS)})[0]

    @property
    def reminder_days(self):
        days = sorted({int(day) for day in (self.document_reminder_days or []) if str(day).isdigit()}, reverse=True)
        return days or list(self.DEFAULT_DOCUMENT_DAYS)

    @property
    def warning_window_days(self):
        return max(self.reminder_days)


class ReminderLog(models.Model):
    """One row per reminder sent, so a reminder is never sent twice."""

    key = models.CharField(max_length=120, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class NotificationBroadcast(models.Model):
    """A notification an administrator sent to a target group of employees."""

    TARGET_CHOICES = [
        ('ALL', 'All active employees'),
        ('DEPARTMENT', 'A department'),
        ('EMPLOYEES', 'Selected employees'),
    ]

    title = models.CharField(max_length=160)
    message = models.TextField()
    target_type = models.CharField(max_length=12, choices=TARGET_CHOICES)
    target_label = models.CharField(max_length=255, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    recipient_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title


class AttendanceSettings(models.Model):
    """The single company location used to validate employee attendance."""
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_meters = models.PositiveIntegerField(default=100)
    is_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self):
        return 'Company attendance location'


class AttendanceRecord(models.Model):
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField()
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)
    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_distance_meters = models.PositiveIntegerField(null=True, blank=True)
    check_out_distance_meters = models.PositiveIntegerField(null=True, blank=True)
    # Shift in force at check-in (snapshot) and how late the employee was against its start time.
    shift = models.ForeignKey('workforce.Shift', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    shift_name = models.CharField(max_length=60, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    late_minutes = models.PositiveIntegerField(null=True, blank=True)

    # True once an administrator approved a correction request for this day.
    is_corrected = models.BooleanField(default=False)

    class Meta:
        ordering = ['-date', '-check_in_at']
        constraints = [
            models.UniqueConstraint(fields=['employee', 'date'], name='one_attendance_record_per_employee_day'),
        ]

    def __str__(self):
        return f'{self.employee.username} - {self.date}'


class AttendanceCorrectionRequest(models.Model):
    """An employee's request to fix one day's attendance. Attendance changes only when an administrator approves."""

    MISSED_CHECK_IN = 'MISSED_CHECK_IN'
    MISSED_CHECK_OUT = 'MISSED_CHECK_OUT'
    WRONG_TIMES = 'WRONG_TIMES'
    MISSED_DAY = 'MISSED_DAY'
    TYPE_CHOICES = [
        (MISSED_CHECK_IN, 'Missed check-in'),
        (MISSED_CHECK_OUT, 'Missed check-out'),
        (WRONG_TIMES, 'Incorrect check-in or check-out time'),
        (MISSED_DAY, 'Worked but no attendance recorded'),
    ]
    PENDING, APPROVED, REJECTED, CANCELLED = 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'
    STATUS_CHOICES = [(PENDING, 'Pending'), (APPROVED, 'Approved'), (REJECTED, 'Rejected'), (CANCELLED, 'Cancelled')]

    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='attendance_corrections')
    date = models.DateField()
    correction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    requested_check_in = models.DateTimeField(null=True, blank=True)
    requested_check_out = models.DateTimeField(null=True, blank=True)
    reason = models.TextField(max_length=1000)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    # The attendance values when the request was made (refreshed when it is decided).
    original_check_in = models.DateTimeField(null=True, blank=True)
    original_check_out = models.DateTimeField(null=True, blank=True)
    attendance = models.ForeignKey(AttendanceRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='corrections')
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['employee', 'date'], condition=models.Q(status='PENDING'),
                                    name='one_pending_correction_per_employee_day'),
            models.CheckConstraint(
                condition=models.Q(requested_check_in__isnull=True) | models.Q(requested_check_out__isnull=True)
                | models.Q(requested_check_out__gt=models.F('requested_check_in')),
                name='correction_check_out_after_check_in',
            ),
        ]
        indexes = [models.Index(fields=['status', 'created_at']), models.Index(fields=['employee', 'date'])]

    def __str__(self):
        return f'{self.employee.username} correction for {self.date} ({self.status})'


class WorkFromHomeRequest(models.Model):
    STATUS_CHOICES = [('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('CANCELLED', 'Cancelled')]
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='wfh_requests')
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    admin_note = models.TextField(blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-applied_at']

    def __str__(self):
        return f'{self.employee.username} WFH ({self.start_date} to {self.end_date})'


class AuditLog(models.Model):
    """Append-only record of sensitive administrative actions (payroll, salaries, employees)."""

    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    actor_name = models.CharField(max_length=150, blank=True)
    module = models.CharField(max_length=40, blank=True, db_index=True)
    action = models.CharField(max_length=40)
    entity_type = models.CharField(max_length=40)
    entity_id = models.CharField(max_length=40, blank=True)
    # The employee the action was about (for filtering by employee), when there is one.
    subject = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_subject_logs')
    subject_name = models.CharField(max_length=150, blank=True)
    summary = models.CharField(max_length=300)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['entity_type', 'created_at']), models.Index(fields=['created_at']),
                   models.Index(fields=['action'])]

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.actor_name} {self.action} {self.entity_type}'

    def save(self, *args, **kwargs):
        if self.pk is not None and not kwargs.pop('force_audit_write', False):
            raise PermissionError('Audit log entries are append-only and cannot be changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Audit log entries are append-only and cannot be deleted.')


class GoogleIdentity(models.Model):
    """Links one Django user to one Google account (identified by Google's stable ``sub``, never by email)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='google_identity')
    google_sub = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.user.username} <{self.email}>'

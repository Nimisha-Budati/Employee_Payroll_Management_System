"""Automatic reminders: document expiry, requests waiting for approval and unfinished onboarding.

``run_reminders()`` is idempotent: every reminder has a key stored in ``ReminderLog``, so running it
again (from the ``send_reminders`` management command, the administrator's "Run now" button or the
automatic run when a dashboard is opened) never sends a reminder twice.

* Document expiry: for each document with an expiry date, the employee and administrators are
  reminded when the days left first reach one of the configured reminder days (default 30, 7 and 1),
  and once more when it has expired. Only the closest reminder day is sent if several were missed.
* Pending approvals: administrators get one digest per day listing leave, WFH, attendance corrections,
  overtime and documents that have waited at least ``pending_after_days`` days.
* Onboarding: employees with missing items get one reminder per week.
"""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .audit import record_audit
from .models import (
    AttendanceCorrectionRequest, Employee, EmployeeDocument, LeaveRequest, ReminderLog, ReminderSettings,
    WorkFromHomeRequest,
)
from .notifications import notify_admins, notify_user
from .permissions import IsAdminUserRole

AUTO_RUN_INTERVAL = timedelta(hours=6)


def _claim(key):
    """Reserve a reminder key; False when it was already sent."""
    try:
        with transaction.atomic():
            ReminderLog.objects.create(key=key[:120])
        return True
    except IntegrityError:
        return False


def _document_reminders(settings, today, company_id=None):
    sent = 0
    thresholds = sorted(settings.reminder_days)           # ascending, e.g. [1, 7, 30]
    horizon = today + timedelta(days=max(thresholds))
    documents = EmployeeDocument.objects.select_related('employee').filter(
        employee__userprofile__company_id=company_id, expiry_date__isnull=False, expiry_date__lte=horizon, employee__is_active=True,
    )
    for document in documents:
        days_left = (document.expiry_date - today).days
        if days_left < 0:
            stage, text = 'expired', f'expired on {document.expiry_date:%d %b %Y}'
        else:
            stage = next(day for day in thresholds if days_left <= day)
            text = 'expires today' if days_left == 0 else f'expires in {days_left} day{"s" if days_left != 1 else ""} ({document.expiry_date:%d %b %Y})'
        if not _claim(f'doc:{document.pk}:{document.expiry_date.isoformat()}:{stage}'):
            continue
        title = 'Document expired' if stage == 'expired' else 'Document expiring soon'
        notify_user(document.employee, 'REMINDER', title, f'Your document "{document.title}" {text}. Upload a renewed copy in Documents.',
                    'employee-documents.html')
        notify_admins('REMINDER', title, f'{document.employee.username}\'s document "{document.title}" {text}.',
                      'admin-documents.html?expiry=' + ('EXPIRED' if stage == 'expired' else 'EXPIRING'), company_id=company_id)
        sent += 1
    return sent


def pending_counts(older_than, company_id=None):
    from workforce.models import OvertimeRecord

    scope = {'employee__userprofile__company_id': company_id} if company_id is not None else {}
    return {
        'leave': LeaveRequest.objects.filter(**scope, status='PENDING', applied_at__lte=older_than).count(),
        'wfh': WorkFromHomeRequest.objects.filter(**scope, status='PENDING', applied_at__lte=older_than).count(),
        'corrections': AttendanceCorrectionRequest.objects.filter(**scope, status='PENDING', created_at__lte=older_than).count(),
        'overtime': OvertimeRecord.objects.filter(**scope, status=OvertimeRecord.PENDING, created_at__lte=older_than).count(),
        'documents': EmployeeDocument.objects.filter(**scope, status='PENDING', uploaded_at__lte=older_than).count(),
    }


LABELS = {'leave': 'leave request', 'wfh': 'work-from-home request', 'corrections': 'attendance correction',
          'overtime': 'overtime claim', 'documents': 'document'}


def _pending_digest(settings, now, today, company_id=None):
    counts = pending_counts(now - timedelta(days=settings.pending_after_days), company_id)
    parts = [f'{count} {LABELS[key]}{"s" if count != 1 else ""}' for key, count in counts.items() if count]
    if not parts or not _claim(f'pending:{company_id or "unassigned"}:{today.isoformat()}'):
        return 0
    notify_admins('REMINDER', 'Requests waiting for approval',
                  f'Waiting {settings.pending_after_days}+ day(s): {", ".join(parts)}.', 'admin-dashboard.html', company_id=company_id)
    return 1


def _onboarding_reminders(today, company_id=None):
    from .onboarding import checklist

    sent = 0
    year, week, _ = today.isocalendar()
    employees = Employee.objects.select_related('user').filter(
        company_id=company_id, onboarding_status=Employee.ONBOARDING_PENDING, status='ACTIVE', user__is_active=True,
    )
    for employee in employees:
        missing = [item['label'] for item in checklist(employee) if not item['done'] and item['owner'] == 'EMPLOYEE']
        if missing and _claim(f'onboarding:{employee.pk}:{year}-W{week}'):
            notify_user(employee.user, 'ONBOARDING', 'Onboarding items still needed',
                        f'Please complete: {", ".join(missing)}.', 'employee-dashboard.html')
            sent += 1
    return sent


def run_reminders(now=None, company=None):
    # Reminder settings and recipients are tenant-owned. A missing tenant must never
    # widen the query to unassigned users or notify administrators across companies.
    if company is None:
        return {'documents': 0, 'pending_digest': 0, 'onboarding': 0, 'enabled': False}
    company_id = getattr(company, 'pk', None)
    settings = ReminderSettings.load(company)
    now = now or timezone.now()
    today = timezone.localdate(now)
    result = {'documents': 0, 'pending_digest': 0, 'onboarding': 0, 'enabled': settings.enabled}
    if settings.enabled:
        result['documents'] = _document_reminders(settings, today, company_id)
        result['pending_digest'] = _pending_digest(settings, now, today, company_id)
        result['onboarding'] = _onboarding_reminders(today, company_id)
    ReminderSettings.objects.filter(pk=settings.pk).update(last_run_at=now)
    return result


def maybe_run_reminders(company=None):
    """Run reminders when they have not run in the last few hours (keeps them working without a scheduler)."""
    settings = ReminderSettings.load(company)
    if settings.enabled and (settings.last_run_at is None or timezone.now() - settings.last_run_at >= AUTO_RUN_INTERVAL):
        try:
            return run_reminders(company=company)
        except Exception:   # reminders must never break the page that triggered them
            return None
    return None


class ReminderSettingsSerializer(serializers.ModelSerializer):
    document_reminder_days = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=365), min_length=1, max_length=6,
    )

    class Meta:
        model = ReminderSettings
        fields = ['enabled', 'document_reminder_days', 'pending_after_days', 'last_run_at', 'updated_at']
        read_only_fields = ['last_run_at', 'updated_at']

    def validate_document_reminder_days(self, value):
        return sorted(set(value), reverse=True)

    def validate_pending_after_days(self, value):
        if not 1 <= value <= 60:
            raise serializers.ValidationError('Use between 1 and 60 days.')
        return value


@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def reminder_settings(request):
    settings = ReminderSettings.load(request.user.userprofile.company)
    if request.method == 'GET':
        return Response(ReminderSettingsSerializer(settings).data)
    serializer = ReminderSettingsSerializer(settings, data=request.data, partial=True)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    settings = serializer.save(updated_by=request.user)
    record_audit(request, 'UPDATE', 'Reminder', 1,
                 f'Reminders {"on" if settings.enabled else "off"}; document reminders {", ".join(map(str, settings.reminder_days))} day(s) '
                 f'before expiry; pending digest after {settings.pending_after_days} day(s).')
    return Response(ReminderSettingsSerializer(settings).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsAdminUserRole])
def reminder_run(request):
    result = run_reminders(company=request.user.userprofile.company)
    record_audit(request, 'RUN', 'Reminder', '', f'Ran reminders: {result["documents"]} document, {result["pending_digest"]} pending digest, '
                                                f'{result["onboarding"]} onboarding.')
    return Response(result)

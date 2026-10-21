"""Audit trail helper."""

from .models import AuditLog
from .throttling import client_ip

# Module shown in the audit log for each kind of record.
MODULES = {
    'Account': 'Authentication',
    'Announcement': 'Announcements',
    'Attendance': 'Attendance',
    'AttendanceCorrection': 'Attendance',
    'AttendanceSettings': 'Attendance',
    'Department': 'Employees',
    'Document': 'Documents',
    'Employee': 'Employees',
    'Holiday': 'Holidays',
    'Leave': 'Leave',
    'LeavePolicy': 'Leave',
    'LeaveType': 'Leave',
    'Notification': 'Notifications',
    'Onboarding': 'Employees',
    'OnboardingSettings': 'Employees',
    'Overtime': 'Overtime',
    'Payroll': 'Payroll',
    'PayrollReview': 'Payroll',
    'Payslip': 'Payroll',
    'Reminder': 'Notifications',
    'Report': 'Reports',
    'SalaryStructure': 'Payroll',
    'Shift': 'Shifts',
    'ShiftAssignment': 'Shifts',
    'WFH': 'Work from home',
    'AIKnowledge': 'AI assistance',
}


def module_for(entity_type):
    return MODULES.get(entity_type, entity_type)


def record_audit(request, action, entity_type, entity_id='', summary='', module=None, actor=None, subject=None):
    """Append an audit entry. ``subject`` is the employee (a User or Employee) the action concerns."""
    if actor is None and request is not None and getattr(request, 'user', None) is not None and request.user.is_authenticated:
        actor = request.user
    if subject is not None and not hasattr(subject, 'username'):   # an Employee was passed
        subject = getattr(subject, 'user', None)
    ip_address = None
    if request is not None:
        ip_address = client_ip(request._request if hasattr(request, '_request') else request)
    return AuditLog.objects.create(
        actor=actor,
        actor_name=actor.username if actor else '',
        module=module or module_for(entity_type),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        subject=subject,
        subject_name=subject.username if subject else '',
        summary=summary[:300],
        ip_address=ip_address,
    )

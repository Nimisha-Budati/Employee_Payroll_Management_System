"""Data migration for the onboarding, headcount and audit-filter features.

* Employees that already exist are treated as already onboarded (status COMPLETED), so administrators
  are not asked to re-review people who joined before checklists existed. New employees start PENDING.
* deactivated_at is filled for inactive employees from their latest deactivation audit entry
  (left empty when no such entry exists).
* AuditLog.subject is filled for existing entries whose record can still be traced to an employee.
Nothing is deleted and no existing value is overwritten.
"""

from django.db import migrations
from django.utils import timezone

EXISTING_NOTE = 'Employee existed before onboarding checklists were introduced.'


def forwards(apps, schema_editor):
    Employee = apps.get_model('accounts', 'Employee')
    AuditLog = apps.get_model('accounts', 'AuditLog')
    User = apps.get_model('auth', 'User')

    now = timezone.now()
    Employee.objects.filter(onboarding_status='PENDING', onboarding_completed_at__isnull=True).update(
        onboarding_status='COMPLETED', onboarding_completed_at=now, onboarding_note=EXISTING_NOTE,
    )

    for employee in Employee.objects.filter(status='INACTIVE', deactivated_at__isnull=True):
        entry = (
            AuditLog.objects.filter(entity_type='Employee', entity_id=str(employee.pk))
            .filter(action='DEACTIVATE')
            .order_by('-created_at').first()
        ) or (
            AuditLog.objects.filter(entity_type='Employee', entity_id=str(employee.pk), action='UPDATE',
                                    summary__contains='status')
            .order_by('-created_at').first()
        )
        if entry is not None:
            Employee.objects.filter(pk=employee.pk).update(deactivated_at=timezone.localtime(entry.created_at).date())

    # entity_type -> (model, field holding the employee's user id); Employee/SalaryStructure ids are Employee pks.
    sources = {
        'Leave': ('accounts', 'LeaveRequest', 'employee_id'),
        'WFH': ('accounts', 'WorkFromHomeRequest', 'employee_id'),
        'Document': ('accounts', 'EmployeeDocument', 'employee_id'),
        'Payslip': ('payroll', 'Payslip', 'employee_id'),
        'Overtime': ('workforce', 'OvertimeRecord', 'employee_id'),
        'Employee': ('accounts', 'Employee', 'user_id'),
        'SalaryStructure': ('accounts', 'Employee', 'user_id'),
    }
    names = {user.pk: user.username for user in User.objects.only('id', 'username')}
    for entity_type, (app_label, model_name, field) in sources.items():
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            continue
        logs = AuditLog.objects.filter(entity_type=entity_type, subject__isnull=True).exclude(entity_id='')
        ids = {int(value) for value in logs.values_list('entity_id', flat=True) if str(value).isdigit()}
        owners = dict(model.objects.filter(pk__in=ids).values_list('pk', field))
        for record_id, user_id in owners.items():
            if user_id:
                logs.filter(entity_id=str(record_id)).update(subject_id=user_id, subject_name=names.get(user_id, ''))
    account_logs = AuditLog.objects.filter(entity_type='Account', subject__isnull=True).exclude(entity_id='')
    for value in set(account_logs.values_list('entity_id', flat=True)):
        if str(value).isdigit() and int(value) in names:
            account_logs.filter(entity_id=value).update(subject_id=int(value), subject_name=names[int(value)])


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0022_corrections_onboarding_reminders'),
        ('payroll', '0004_payroll_review'),
        ('workforce', '0001_initial'),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]

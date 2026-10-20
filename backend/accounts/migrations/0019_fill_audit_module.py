from django.db import migrations

MODULES = {'Employee': 'Employees', 'SalaryStructure': 'Payroll', 'Payslip': 'Payroll', 'Payroll': 'Payroll'}


def fill_module(apps, schema_editor):
    AuditLog = apps.get_model('accounts', 'AuditLog')
    for entity_type, module in MODULES.items():
        AuditLog.objects.filter(entity_type=entity_type, module='').update(module=module)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0018_attendance_shift_notification_expiry_audit_module'),
    ]

    operations = [
        migrations.RunPython(fill_module, migrations.RunPython.noop),
    ]

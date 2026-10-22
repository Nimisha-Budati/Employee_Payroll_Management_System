"""Preserve the single-organisation installation inside an isolated legacy tenant.

This project had no company ownership columns before 0024, so there is no trustworthy
per-record signal from which to infer multiple historical tenants. Existing users,
employee rows, and organization-wide settings are therefore retained together under
an explicitly review-required legacy tenant. New registrations always receive a new
tenant. No business records are deleted or moved to a customer-named company.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Company = apps.get_model('accounts', 'Company')
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('accounts', 'UserProfile')
    Employee = apps.get_model('accounts', 'Employee')

    has_data = User.objects.exists() or Employee.objects.exists()
    if not has_data:
        for label, model_name in (
            ('accounts', 'Holiday'), ('accounts', 'LeaveType'), ('accounts', 'AttendanceSettings'),
            ('accounts', 'LeavePolicySettings'), ('accounts', 'Announcement'),
            ('payroll', 'Payslip'), ('payroll', 'PayrollReview'), ('workforce', 'Shift'), ('assistant', 'AIKnowledgeBase'),
        ):
            try:
                has_data = apps.get_model(label, model_name).objects.exists()
            except LookupError:
                continue
            if has_data:
                break
    if not has_data:
        return

    legacy, _ = Company.objects.get_or_create(
        is_legacy=True,
        defaults={
            'name': 'Legacy organization (review ownership)',
            'email': 'legacy-organization@invalid.local',
        },
    )
    for user in User.objects.all().only('id', 'is_staff', 'is_superuser'):
        role = 'ADMIN' if user.is_staff or user.is_superuser else 'EMPLOYEE'
        UserProfile.objects.get_or_create(user_id=user.pk, defaults={'role': role, 'company_id': legacy.pk})
        UserProfile.objects.filter(user_id=user.pk, company__isnull=True).update(company_id=legacy.pk)
    Employee.objects.filter(company__isnull=True).update(company_id=legacy.pk)

    # Former single-company configuration and histories remain together, unavailable to new tenants.
    for label, model_name in (
        ('accounts', 'Holiday'), ('accounts', 'LeaveType'), ('accounts', 'AttendanceSettings'),
        ('accounts', 'LeavePolicySettings'), ('accounts', 'Announcement'),
        ('accounts', 'NotificationBroadcast'), ('accounts', 'OnboardingSettings'), ('accounts', 'ReminderSettings'),
    ):
        try:
            model = apps.get_model(label, model_name)
        except LookupError:
            continue
        model.objects.filter(company__isnull=True).update(company_id=legacy.pk)


class Migration(migrations.Migration):
    atomic = True
    dependencies = [
        ('accounts', '0024_company_alter_employee_employee_id_and_more'),
        ('payroll', '0004_payroll_review'),
        ('workforce', '0001_initial'),
        ('assistant', '0004_conversation_pinned_at'),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

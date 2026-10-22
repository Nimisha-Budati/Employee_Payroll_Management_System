"""Align company-registration table ID sequences with their existing rows.

Some existing installations have explicit or restored IDs without matching
PostgreSQL sequence state. Company registration creates rows in these tables,
so align their sequences with their current maximum IDs before new signups.
"""

from django.core.management.color import no_style
from django.db import migrations


def reset_company_registration_sequences(apps, schema_editor):
    models = [
        apps.get_model('accounts', model_name)
        for model_name in (
            'Company', 'UserProfile', 'LeavePolicySettings', 'OnboardingSettings',
            'ReminderSettings', 'AttendanceSettings', 'LeaveType',
        )
    ]
    models.extend([
        apps.get_model('auth', 'User'),
        apps.get_model('assistant', 'AIKnowledgeBase'),
    ])
    connection = schema_editor.connection
    statements = connection.ops.sequence_reset_sql(no_style(), models)
    if statements:
        with connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0027_leavepolicysettings_one_leave_policy_per_company_and_more'),
        ('assistant', '0006_aiknowledgebase_one_ai_knowledge_per_company'),
    ]

    operations = [
        migrations.RunPython(reset_company_registration_sequences, migrations.RunPython.noop),
    ]

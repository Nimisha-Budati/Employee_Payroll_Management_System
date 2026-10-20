"""Move the leave policy from code into the database.

Before this migration the leave types and annual limits lived in ``settings.LEAVE_ENTITLEMENTS``
(overridable with the LEAVE_CASUAL_DAYS / LEAVE_SICK_DAYS / LEAVE_EARNED_DAYS environment variables)
and "Other" was hard-coded as unpaid. This one-time step creates the same policy as rows that
administrators manage from then on, and links every existing leave request to its type.
No leave request is changed apart from filling the new ``policy`` link.
"""

import os

from django.db import migrations

# The values that were configured in code at the time of this migration.
INITIAL_TYPES = [
    # name, annual days (None = no limit), paid, description
    ('Casual Leave', 'LEAVE_CASUAL_DAYS', 12, True, 'Short personal leave.'),
    ('Sick Leave', 'LEAVE_SICK_DAYS', 12, True, 'Leave when you are unwell.'),
    ('Earned Leave', 'LEAVE_EARNED_DAYS', 15, True, 'Planned leave such as holidays.'),
    ('Other', None, None, False, 'Unpaid leave; the days are loss of pay.'),
]


def _days(env_name, default):
    if env_name is None:
        return None
    try:
        return max(0, int(os.environ.get(env_name, default)))
    except ValueError:
        return default


def seed(apps, schema_editor):
    LeaveType = apps.get_model('accounts', 'LeaveType')
    LeaveRequest = apps.get_model('accounts', 'LeaveRequest')
    LeavePolicySettings = apps.get_model('accounts', 'LeavePolicySettings')

    for order, (name, env_name, default, paid, description) in enumerate(INITIAL_TYPES, start=1):
        LeaveType.objects.get_or_create(name=name, defaults={
            'annual_days': _days(env_name, default), 'is_paid': paid, 'description': description, 'sort_order': order,
        })
    # Any other leave type name already used in old requests is kept as an inactive type so history stays linked.
    known = {name.lower() for name in LeaveType.objects.values_list('name', flat=True)}
    for name in LeaveRequest.objects.values_list('leave_type', flat=True).distinct():
        if name and name.lower() not in known:
            LeaveType.objects.create(name=name[:50], annual_days=None, is_paid=True, is_active=False,
                                     description='Created from existing leave requests.', sort_order=99)
            known.add(name.lower())
    for leave_type in LeaveType.objects.all():
        LeaveRequest.objects.filter(policy__isnull=True, leave_type__iexact=leave_type.name).update(policy=leave_type)
    LeavePolicySettings.objects.get_or_create(pk=1)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_leave_policy'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]

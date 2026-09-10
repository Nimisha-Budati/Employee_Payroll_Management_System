# Generated manually to bring the leave-management model into the database.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_employee'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(
            name='Employee',
        ),
        migrations.CreateModel(
            name='LeaveRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('leave_type', models.CharField(choices=[('Casual Leave', 'Casual Leave'), ('Sick Leave', 'Sick Leave'), ('Earned Leave', 'Earned Leave'), ('Other', 'Other')], max_length=50)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('number_of_days', models.IntegerField(default=1, editable=False)),
                ('reason', models.TextField()),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING', max_length=20)),
                ('rejection_reason', models.TextField(blank=True, null=True)),
                ('applied_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leave_requests', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

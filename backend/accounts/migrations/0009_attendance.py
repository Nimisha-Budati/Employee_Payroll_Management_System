from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0008_holiday')]

    operations = [
        migrations.CreateModel(
            name='AttendanceSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('radius_meters', models.PositiveIntegerField(default=100)),
                ('is_enabled', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='AttendanceRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('check_in_at', models.DateTimeField(blank=True, null=True)),
                ('check_out_at', models.DateTimeField(blank=True, null=True)),
                ('check_in_latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('check_in_longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('check_out_latitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('check_out_longitude', models.DecimalField(blank=True, decimal_places=6, max_digits=9, null=True)),
                ('check_in_distance_meters', models.PositiveIntegerField(blank=True, null=True)),
                ('check_out_distance_meters', models.PositiveIntegerField(blank=True, null=True)),
                ('employee', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='attendance_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-date', '-check_in_at']},
        ),
        migrations.AddConstraint(
            model_name='attendancerecord',
            constraint=models.UniqueConstraint(fields=('employee', 'date'), name='one_attendance_record_per_employee_day'),
        ),
    ]

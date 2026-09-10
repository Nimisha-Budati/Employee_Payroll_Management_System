import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_leave_request'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=100)),
                ('document_type', models.CharField(choices=[('IDENTITY', 'Identity Proof'), ('ADDRESS', 'Address Proof'), ('EDUCATION', 'Education Certificate'), ('RESUME', 'Resume'), ('OTHER', 'Other')], max_length=20)),
                ('file', models.FileField(upload_to='employee_documents/%Y/%m/')),
                ('status', models.CharField(choices=[('PENDING', 'Pending review'), ('VERIFIED', 'Verified'), ('REJECTED', 'Rejected')], default='PENDING', max_length=20)),
                ('review_note', models.TextField(blank=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='documents', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]

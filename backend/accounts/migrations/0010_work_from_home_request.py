from django.conf import settings
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('accounts', '0009_attendance')]
    operations = [migrations.CreateModel(name='WorkFromHomeRequest', fields=[('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')), ('start_date', models.DateField()), ('end_date', models.DateField()), ('reason', models.TextField()), ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected'), ('CANCELLED', 'Cancelled')], default='PENDING', max_length=20)), ('admin_note', models.TextField(blank=True)), ('applied_at', models.DateTimeField(auto_now_add=True)), ('updated_at', models.DateTimeField(auto_now=True)), ('employee', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='wfh_requests', to=settings.AUTH_USER_MODEL))], options={'ordering': ['-applied_at']})]

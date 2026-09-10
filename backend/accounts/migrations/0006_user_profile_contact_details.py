from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0005_employee_document_custom_document_type')]

    operations = [
        migrations.AddField(model_name='userprofile', name='address', field=models.TextField(blank=True)),
        migrations.AddField(model_name='userprofile', name='phone', field=models.CharField(blank=True, max_length=20)),
    ]

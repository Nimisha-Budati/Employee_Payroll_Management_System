from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0004_employee_document')]

    operations = [
        migrations.AddField(
            model_name='employeedocument',
            name='custom_document_type',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]

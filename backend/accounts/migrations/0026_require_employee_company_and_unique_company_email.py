import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0025_backfill_legacy_company')]

    operations = [
        migrations.AlterField(
            model_name='employee',
            name='company',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='employees', to='accounts.company'),
        ),
        migrations.AlterField(
            model_name='company',
            name='email',
            field=models.EmailField(max_length=254),
        ),
        migrations.AddConstraint(
            model_name='company',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('email'), name='one_company_per_email_case_insensitive'),
        ),
    ]

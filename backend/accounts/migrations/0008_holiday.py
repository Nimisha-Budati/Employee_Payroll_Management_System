from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0007_user_profile_photo')]

    operations = [
        migrations.CreateModel(
            name='Holiday',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('date', models.DateField(unique=True)),
                ('holiday_type', models.CharField(choices=[('FIXED', 'Fixed'), ('TENTATIVE', 'Tentative')], default='FIXED', max_length=20)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['date']},
        ),
    ]

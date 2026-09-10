from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('accounts', '0006_user_profile_contact_details')]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='profile_photo',
            field=models.FileField(blank=True, upload_to='profile_photos/'),
        ),
    ]

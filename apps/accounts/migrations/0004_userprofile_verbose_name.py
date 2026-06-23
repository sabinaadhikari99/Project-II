from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_user_profile_picture"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="userprofile",
            options={"verbose_name": "User Profile", "verbose_name_plural": "User Profiles"},
        ),
    ]

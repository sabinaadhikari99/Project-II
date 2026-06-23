from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0002_match_notification_schema"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="notification",
            options={"ordering": ["-created_at"], "verbose_name": "Job Match Notification", "verbose_name_plural": "Job Match Notifications"},
        ),
    ]

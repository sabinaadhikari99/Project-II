from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_generic_notification_schema"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notification",
            name="is_email_sent",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name="notification",
            name="priority",
            field=models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")], db_index=True, default="medium", max_length=20),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "-created_at"], name="idx_notif_user_created"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "is_read"], name="idx_notif_user_unread"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "notification_type"], name="idx_notif_user_type"),
        ),
    ]

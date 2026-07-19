from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def delete_legacy_notifications(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_notification_verbose_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(delete_legacy_notifications, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="notification",
            name="recruiter",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sent_match_notifications", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="notification",
            name="job",
            field=models.ForeignKey(null=True, blank=True, on_delete=django.db.models.deletion.SET_NULL, related_name="match_notifications", to="jobs.jobposting"),
        ),
        migrations.AlterUniqueTogether(
            name="notification",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="notification",
            name="is_email_sent",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="notification",
            name="metadata",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name="notification",
            name="notification_type",
            field=models.CharField(choices=[("job_match", "Job Match"), ("application", "Application"), ("interview", "Interview"), ("ai_match", "AI Match"), ("resume", "Resume"), ("skill_gap", "Skill Gap"), ("recruiter", "Recruiter"), ("admin", "Admin"), ("profile", "Profile"), ("security", "Security"), ("system", "System"), ("message", "Message"), ("company", "Company"), ("verification", "Verification")], db_index=True, default="system", max_length=30),
        ),
        migrations.AddField(
            model_name="notification",
            name="priority",
            field=models.CharField(choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")], default="medium", max_length=20),
        ),
        migrations.AddField(
            model_name="notification",
            name="read_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="notification",
            name="sender",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="sent_notifications", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterModelOptions(
            name="notification",
            options={"ordering": ["-created_at"], "verbose_name": "Notification", "verbose_name_plural": "Notifications"},
        ),
        migrations.AlterField(
            model_name="notification",
            name="is_read",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name="notification",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]

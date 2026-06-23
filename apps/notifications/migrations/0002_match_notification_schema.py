from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def delete_legacy_notifications(apps, schema_editor):
    Notification = apps.get_model("notifications", "Notification")
    Notification.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0002_jobposting_company_logo_jobposting_work_mode_savedjob_recentlyviewedjob"),
        ("notifications", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="notification",
            unique_together=set(),
        ),
        migrations.DeleteModel(
            name="NotificationPreference",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="dedupe_key",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="metadata",
        ),
        migrations.RemoveField(
            model_name="notification",
            name="notification_type",
        ),
        migrations.RunPython(delete_legacy_notifications, migrations.RunPython.noop),
        migrations.AddField(
            model_name="notification",
            name="match_percentage",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="notification",
            name="job",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="match_notifications", to="jobs.jobposting"),
        ),
        migrations.AddField(
            model_name="notification",
            name="recruiter",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name="sent_match_notifications", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="notification",
            name="job",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="match_notifications", to="jobs.jobposting"),
        ),
        migrations.AlterField(
            model_name="notification",
            name="recruiter",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="sent_match_notifications", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterUniqueTogether(
            name="notification",
            unique_together={("user", "job")},
        ),
    ]

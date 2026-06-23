from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("jobs", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobposting",
            name="company_logo",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="jobposting",
            name="work_mode",
            field=models.CharField(
                choices=[("onsite", "On-site"), ("remote", "Remote"), ("hybrid", "Hybrid")],
                default="onsite",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="SavedJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_by", to="jobs.jobposting")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-created_at"],
                "unique_together": {("user", "job")},
            },
        ),
        migrations.CreateModel(
            name="RecentlyViewedJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("viewed_at", models.DateTimeField(auto_now=True)),
                ("job", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recent_views", to="jobs.jobposting")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="recently_viewed_jobs", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-viewed_at"],
                "unique_together": {("user", "job")},
            },
        ),
    ]

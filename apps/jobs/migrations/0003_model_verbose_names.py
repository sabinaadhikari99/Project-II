from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("jobs", "0002_jobposting_company_logo_jobposting_work_mode_savedjob_recentlyviewedjob"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="application",
            options={"ordering": ["-created_at"], "verbose_name": "Application", "verbose_name_plural": "Applications"},
        ),
        migrations.AlterModelOptions(
            name="jobposting",
            options={"ordering": ["-created_at"], "verbose_name": "Job Posting", "verbose_name_plural": "Job Postings"},
        ),
        migrations.AlterModelOptions(
            name="recentlyviewedjob",
            options={"ordering": ["-viewed_at"], "verbose_name": "Recently Viewed Job", "verbose_name_plural": "Recently Viewed Jobs"},
        ),
        migrations.AlterModelOptions(
            name="savedjob",
            options={"ordering": ["-created_at"], "verbose_name": "Bookmarked Job", "verbose_name_plural": "Bookmarked Jobs"},
        ),
    ]

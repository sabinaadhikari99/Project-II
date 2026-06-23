from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("admin_panel", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="systemsetting",
            options={"verbose_name": "System Setting", "verbose_name_plural": "System Settings"},
        ),
    ]

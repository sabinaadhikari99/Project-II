import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.shared.constants import ROLE_RECRUITER

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Seed recruiter user accounts from recruiters.json"

    def handle(self, *args, **options):
        path = settings.DATA_DIR / "recruiters.json"
        if not path.exists():
            raise CommandError(f"recruiters.json not found at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        required_fields = {"email", "username", "password", "company_name"}

        created = 0
        skipped = 0
        errors = []

        for i, item in enumerate(data):
            missing = required_fields - set(item.keys())
            if missing:
                errors.append(f"Entry {i}: missing fields {missing}")
                continue

            email = item["email"].strip().lower()
            user, was_created = User.objects.get_or_create(
                email=email,
                defaults={
                    "username": item["username"].strip(),
                    "role": ROLE_RECRUITER,
                },
            )
            if was_created:
                user.set_password(item["password"])
                user.save()
                created += 1
            else:
                skipped += 1

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"  {err}"))

        self.stdout.write(self.style.SUCCESS(
            f"Recruiters: {created} created, {skipped} already exist."
        ))

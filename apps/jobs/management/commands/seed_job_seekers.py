import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import UserProfile
from apps.shared.constants import ROLE_JOB_SEEKER

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Seed job seeker user accounts and empty profiles from job_seekers.json"

    def handle(self, *args, **options):
        path = settings.DATA_DIR / "job_seekers.json"
        if not path.exists():
            raise CommandError(f"job_seekers.json not found at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        required_fields = {"email", "username", "password"}

        created_users = 0
        skipped_users = 0
        created_profiles = 0
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
                    "role": ROLE_JOB_SEEKER,
                },
            )
            if was_created:
                user.set_password(item["password"])
                user.save()
                created_users += 1

                UserProfile.objects.create(user=user)
                created_profiles += 1
            else:
                skipped_users += 1
                profile, profile_created = UserProfile.objects.get_or_create(user=user)
                if profile_created:
                    created_profiles += 1

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"  {err}"))

        self.stdout.write(self.style.SUCCESS(
            f"Job Seekers: {created_users} created, {skipped_users} already exist. "
            f"Profiles: {created_profiles} created."
        ))

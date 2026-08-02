import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import UserProfile

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Update job seeker profiles with realistic data from user_profiles.json"

    def handle(self, *args, **options):
        path = settings.DATA_DIR / "user_profiles.json"
        if not path.exists():
            raise CommandError(f"user_profiles.json not found at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        required_fields = {"email", "skills", "experience_years", "education", "resume_text"}

        updated = 0
        created = 0
        not_found = 0
        errors = []

        for i, item in enumerate(data):
            missing = required_fields - set(item.keys())
            if missing:
                errors.append(f"Entry {i}: missing fields {missing}")
                continue

            email = item["email"].strip().lower()
            try:
                user = User.objects.get(email=email)
            except User.DoesNotExist:
                not_found += 1
                errors.append(f"Entry {i}: user with email '{email}' not found")
                continue

            profile, was_created = UserProfile.objects.get_or_create(user=user)
            profile.skills = item.get("skills", [])
            profile.resume_text = item.get("resume_text", "")
            profile.experience_years = item.get("experience_years", 0)
            profile.education = item.get("education", "")
            profile.location = item.get("location", "")
            profile.bio = item.get("bio", "")
            profile.headline = item.get("headline", "")
            profile.phone = item.get("phone", "")
            profile.linkedin_url = item.get("linkedin_url", "")
            profile.github_url = item.get("github_url", "")
            profile.portfolio_url = item.get("portfolio_url", "")
            profile.save()

            if was_created:
                created += 1
            else:
                updated += 1

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"  {err}"))

        self.stdout.write(self.style.SUCCESS(
            f"Profiles: {updated} updated, {created} created, {not_found} user(s) not found."
        ))

import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.jobs.models import Application, JobPosting

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Seed applications from applications.json"

    def handle(self, *args, **options):
        path = settings.DATA_DIR / "applications.json"
        if not path.exists():
            raise CommandError(f"applications.json not found at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))

        created = 0
        skipped = 0
        errors = []

        for i, item in enumerate(data):
            applicant_email = item["applicant_email"].strip().lower()
            job_title = item["job_title"]
            job_company = item["job_company"]

            try:
                applicant = User.objects.get(email=applicant_email)
            except User.DoesNotExist:
                errors.append(f"Entry {i}: applicant '{applicant_email}' not found")
                continue

            try:
                job = JobPosting.objects.get(title=job_title, company=job_company)
            except JobPosting.DoesNotExist:
                errors.append(
                    f"Entry {i}: job '{job_title}' at {job_company} not found"
                )
                continue

            application, was_created = Application.objects.get_or_create(
                job=job,
                applicant=applicant,
                defaults={
                    "cover_letter": item.get("cover_letter", ""),
                    "status": item.get("status", "submitted"),
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"  {err}"))

        self.stdout.write(self.style.SUCCESS(
            f"Applications: {created} created, {skipped} already exist."
        ))

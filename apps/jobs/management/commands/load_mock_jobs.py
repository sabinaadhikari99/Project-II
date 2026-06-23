# file path: apps/jobs/management/commands/load_mock_jobs.py
import json

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import User
from apps.shared.constants import ROLE_RECRUITER
from apps.jobs.services import create_job_with_embedding


class Command(BaseCommand):
    help = "Load mock jobs from data/mock_jobs.json"

    def handle(self, *args, **options):
        recruiter, _ = User.objects.get_or_create(
            email="recruiter@skillsync.local",
            defaults={"username": "demo_recruiter", "role": ROLE_RECRUITER},
        )
        if not recruiter.has_usable_password():
            recruiter.set_password("SkillSync123!")
            recruiter.save()
        path = settings.DATA_DIR / "mock_jobs.json"
        jobs = json.loads(path.read_text(encoding="utf-8"))
        for job_data in jobs:
            if not recruiter.job_posts.filter(title=job_data["title"], company=job_data["company"]).exists():
                create_job_with_embedding(recruiter, job_data)
        self.stdout.write(self.style.SUCCESS(f"Loaded {len(jobs)} mock jobs."))

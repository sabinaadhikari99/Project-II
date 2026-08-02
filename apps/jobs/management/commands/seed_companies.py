import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Validate and report company reference data from companies.json"

    def handle(self, *args, **options):
        path = settings.DATA_DIR / "companies.json"
        if not path.exists():
            raise CommandError(f"companies.json not found at {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        required_fields = {"name", "industry", "description", "location"}

        errors = []
        for i, company in enumerate(data):
            missing = required_fields - set(company.keys())
            if missing:
                errors.append(f"Entry {i} ({company.get('name', 'unnamed')}): missing fields {missing}")

        if errors:
            for err in errors:
                self.stderr.write(self.style.ERROR(f"  {err}"))
            raise CommandError(f"Validation failed: {len(errors)} error(s)")

        companies_by_name = {}
        for company in data:
            name = company["name"]
            if name in companies_by_name:
                self.stderr.write(self.style.WARNING(f"  Duplicate company name: {name}"))
            companies_by_name[name] = company

        self.stdout.write(self.style.SUCCESS(
            f"Companies: {len(data)} validated successfully. "
            f"Industries: {len(set(c['industry'] for c in data))} unique."
        ))

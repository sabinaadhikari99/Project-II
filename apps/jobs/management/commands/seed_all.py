import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

SEED_ORDER = [
    ("seed_companies", "Validating company reference data"),
    ("seed_recruiters", "Creating recruiter accounts"),
    ("seed_job_seekers", "Creating job seeker accounts"),
    ("seed_profiles", "Populating user profiles with resume data"),
    ("seed_jobs", "Creating job postings with embeddings"),
    ("seed_applications", "Creating applications"),
]

COMMANDS_THAT_CAN_FAIL = {"seed_companies"}


class Command(BaseCommand):
    help = "Execute all seed commands in the correct dependency order"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-companies",
            action="store_true",
            help="Skip company validation",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("=" * 60))
        self.stdout.write(self.style.NOTICE("  SkillSync AI - Database Seeding"))
        self.stdout.write(self.style.NOTICE("=" * 60))

        results = []

        for command_name, description in SEED_ORDER:
            if options.get("skip_companies") and command_name == "seed_companies":
                self.stdout.write(self.style.WARNING(f"  [SKIP] {description}"))
                continue

            self.stdout.write()
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"  [{command_name}] {description}...")
            )

            try:
                call_command(command_name)
                results.append((command_name, True, None))
            except Exception as e:
                if command_name in COMMANDS_THAT_CAN_FAIL:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Warning: {command_name} failed but continuing: {e}"
                        )
                    )
                    results.append((command_name, True, str(e)))
                else:
                    self.stderr.write(
                        self.style.ERROR(f"  FAILED: {command_name} - {e}")
                    )
                    results.append((command_name, False, str(e)))
                    self.stdout.write()
                    self.stdout.write(
                        self.style.ERROR(
                            "  Seeding stopped due to critical failure. "
                            "Fix the issue and re-run seed_all."
                        )
                    )
                    break

        self.stdout.write()
        self.stdout.write(self.style.NOTICE("=" * 60))
        self.stdout.write(self.style.NOTICE("  Seeding Summary"))
        self.stdout.write(self.style.NOTICE("=" * 60))

        all_ok = True
        for command_name, ok, error in results:
            if ok:
                self.stdout.write(
                    self.style.SUCCESS(f"  [OK] {command_name}")
                )
            else:
                self.stdout.write(self.style.ERROR(f"  [FAIL] {command_name}: {error}"))
                all_ok = False

        self.stdout.write()
        if all_ok:
            self.stdout.write(self.style.SUCCESS("  Seed completed successfully."))
        else:
            self.stdout.write(
                self.style.ERROR("  Seed completed with errors (see above).")
            )

"""TEMPORARY diagnostic command - trace and compare AI Match scoring.

Read-only: no profile, embedding or analysis session is ever written, so this is
safe to run against the live database.

    python manage.py ai_match_debug --resume-a a.pdf --resume-b b.pdf --user me@example.com

`--mode` decides which skill set is scored:

    cv      current production - each CV is scored on the skills IT contains
    legacy  the pre-fix behaviour, where the CV's skills were unioned into
            UserProfile.skills and the union was scored, so a deleted skill was
            still counted
    both    run both and print each (default); the gap between them is the
            effect of the fix
"""

import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.shared.constants import ROLE_JOB_SEEKER
from apps.shared.match_debug import (
    SEPARATOR,
    compare_traces,
    format_trace,
    trace_analysis,
    verify_against_production,
)

User = get_user_model()


class Command(BaseCommand):
    help = "Trace the AI Match pipeline for one or two resumes and diff them."

    def add_arguments(self, parser):
        parser.add_argument("--resume-a", required=True,
                            help="Path to resume A (.pdf or .txt)")
        parser.add_argument("--resume-b", help="Path to resume B (.pdf or .txt)")
        parser.add_argument("--user", help="Email of the job seeker to score as")
        parser.add_argument("--mode", choices=["cv", "legacy", "both"], default="both")
        parser.add_argument("--top", type=int, default=3,
                            help="How many jobs to print per resume (default 3)")
        parser.add_argument("--limit", type=int, default=10,
                            help="How many jobs to score (default 10)")
        parser.add_argument("--json", dest="json_path",
                            help="Also dump the raw traces to this path")
        parser.add_argument("--verify", action="store_true",
                            help="Cross-check the trace against recommend_jobs_for_user")

    # -- inputs -------------------------------------------------------------
    def _read_resume(self, path):
        target = Path(path)
        if not target.exists():
            raise CommandError(f"Resume not found: {target}")
        if target.suffix.lower() == ".pdf":
            from apps.shared.pdf_utils import extract_pdf_text
            text = extract_pdf_text(str(target))
        else:
            text = target.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < 80:
            raise CommandError(f"{target} produced almost no text ({len(text)} chars). "
                               "A scanned/image PDF will do this.")
        return text

    def _resolve_user(self, email):
        if email:
            try:
                return User.objects.select_related("profile").get(email=email.strip().lower())
            except User.DoesNotExist:
                raise CommandError(f"No user with email {email}")
        user = (User.objects.filter(role=ROLE_JOB_SEEKER, profile__isnull=False)
                .select_related("profile").first())
        if not user:
            raise CommandError("No job seeker with a profile exists. Pass --user.")
        self.stdout.write(self.style.WARNING(f"No --user given; scoring as {user.email}"))
        return user

    # -- run ----------------------------------------------------------------
    def handle(self, *args, **options):
        user = self._resolve_user(options["user"])
        if not getattr(user, "profile", None):
            raise CommandError(f"{user.email} has no UserProfile.")

        text_a = self._read_resume(options["resume_a"])
        text_b = self._read_resume(options["resume_b"]) if options["resume_b"] else None

        stored = list(user.profile.skills or [])
        self.stdout.write(SEPARATOR)
        self.stdout.write("AI MATCH DEBUG - read-only trace, nothing is saved")
        self.stdout.write(f"user={user.email}  stored profile skills={len(stored)}")
        if stored:
            self.stdout.write(f"  {', '.join(stored)}")
        self.stdout.write(SEPARATOR)

        traces = {}
        modes = ["cv", "legacy"] if options["mode"] == "both" else [options["mode"]]

        for mode in modes:
            merge = mode == "legacy"
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(f"### MODE: {mode.upper()}"))
            if merge:
                self.stdout.write("PRE-FIX behaviour: the CV's skills are unioned into "
                                  "UserProfile.skills and the union is scored.")
                prior_a = stored
            else:
                self.stdout.write("CURRENT behaviour: each CV is scored on the skills it "
                                  "contains.")
                prior_a = stored

            trace_a = trace_analysis(user, text_a, label=f"A[{mode}]", prior_skills=prior_a,
                                     limit=options["limit"], merge_prior=merge)
            self.stdout.write(format_trace(trace_a, top=options["top"]))
            traces[f"A_{mode}"] = trace_a

            if text_b:
                # In legacy mode CV B inherits what CV A left behind, which is
                # exactly how a second upload used to be scored.
                prior_b = trace_a["effective_skills"] if merge else stored
                trace_b = trace_analysis(user, text_b, label=f"B[{mode}]",
                                         prior_skills=prior_b, limit=options["limit"],
                                         merge_prior=merge)
                self.stdout.write(format_trace(trace_b, top=options["top"]))
                self.stdout.write(compare_traces(trace_a, trace_b, top=options["top"]))
                traces[f"B_{mode}"] = trace_b

                self.stdout.write("")
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"VERDICT [{mode}]: A best={trace_a['best_final']}  "
                    f"B best={trace_b['best_final']}  "
                    f"delta={trace_b['best_final'] - trace_a['best_final']:+d}"))

        if options["verify"]:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("### TRACER SELF-CHECK"))
            key = "A_cv" if "A_cv" in traces else "A_legacy"
            check = verify_against_production(user, text_a, traces[key], options["limit"])
            if check["verdict"] == "agree":
                self.stdout.write(self.style.SUCCESS(
                    "Tracer agrees with recommend_jobs_for_user on every shared job."))
            elif check["verdict"] == "tracer_bug":
                self.stdout.write(self.style.ERROR(
                    "TRACER BUG: identical skill inputs produced different scores. "
                    "Do not trust this report.\n"
                    f"  {check['mismatches']}"))
            elif check["verdict"] == "error":
                self.stdout.write(self.style.ERROR(f"Verification failed: {check['error']}"))
            else:
                self.stdout.write(self.style.WARNING(
                    "FINDING (not a tracer bug): production scored this CV from a "
                    "DIFFERENT skill set than the CV contains."))
                self.stdout.write(
                    f"  production scored from UserProfile.skills ({len(check['production_skills'])}): "
                    f"{', '.join(check['production_skills']) or '(none)'}")
                self.stdout.write(
                    f"  this CV actually contains ({len(check['traced_skills'])}): "
                    f"{', '.join(check['traced_skills']) or '(none)'}")
                if check["only_in_production"]:
                    self.stdout.write(self.style.WARNING(
                        f"  scored but NOT in this CV : {', '.join(check['only_in_production'])}"))
                if check["only_in_trace"]:
                    self.stdout.write(self.style.WARNING(
                        f"  in this CV but NOT scored : {', '.join(check['only_in_trace'])}"))
                self.stdout.write(
                    f"  best score: production={check['production_best']} "
                    f"traced={check['traced_best']}")

        if options["json_path"]:
            Path(options["json_path"]).write_text(
                json.dumps(traces, indent=2, default=str), encoding="utf-8")
            self.stdout.write(self.style.SUCCESS(f"\nRaw traces written to {options['json_path']}"))

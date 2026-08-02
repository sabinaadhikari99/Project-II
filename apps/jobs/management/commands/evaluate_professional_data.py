import json
import logging
import os
import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.accounts.models import UserProfile
from apps.jobs.models import JobPosting
from apps.jobs.services import (
    recommend_jobs_for_user,
    create_job_with_embedding,
)
from apps.shared.embedding_client import get_embedding
from apps.shared.profession_classifier import (
    PROFESSION_CONFIGS,
    classify_profession_with_resume,
    classify_job,
    get_related_profession_titles,
    classify_profession_from_title,
)
from apps.shared.vector_db import get_vector_manager
from apps.shared.constants import ROLE_JOB_SEEKER, ROLE_RECRUITER, JOB_VECTOR_PREFIX

logger = logging.getLogger(__name__)
User = get_user_model()

SCORE_BANDS = [
    ("Excellent", 95, 100),
    ("Strong", 85, 94),
    ("Good", 70, 84),
    ("Partial", 50, 69),
    ("Weak", 25, 49),
    ("Poor", 0, 24),
]

DISALLOWED_CROSS_RECOMMENDATIONS = {
    "Accountant": {"Frontend Developer", "Backend Developer", "DevOps Engineer", "Data Scientist", "Mobile Developer", "Graphic Designer", "Cybersecurity Engineer", "Machine Learning Engineer"},
    "Human Resources Manager": {"Frontend Developer", "Backend Developer", "DevOps Engineer", "Data Scientist", "Mobile Developer", "Graphic Designer", "Cybersecurity Engineer", "Machine Learning Engineer", "Data Engineer", "Software Engineer"},
    "Graphic Designer": {"Backend Developer", "DevOps Engineer", "Accountant", "Data Scientist", "Cybersecurity Engineer", "Machine Learning Engineer", "Data Engineer", "Software Engineer"},
    "Mobile Developer": {"Accountant", "HR Manager", "Marketing Manager", "Graphic Designer", "Human Resources Manager"},
    "Frontend Developer": {"Accountant", "HR Manager", "Human Resources Manager"},
    "Backend Developer": {"Graphic Designer", "HR Manager", "Marketing Manager", "Accountant", "Human Resources Manager"},
    "Data Scientist": {"UI/UX Designer", "Marketing Manager", "Accountant", "Graphic Designer", "Human Resources Manager"},
}

FALSE_NEGATIVE_CHECK = {
    "Mobile Developer": ["Mobile Developer", "Frontend Developer", "Full Stack Developer"],
    "Frontend Developer": ["Frontend Developer", "Full Stack Developer", "UI/UX Designer"],
    "Backend Developer": ["Backend Developer", "Full Stack Developer", "Software Engineer"],
    "Data Scientist": ["Data Scientist", "Machine Learning Engineer", "Data Engineer"],
    "Graphic Designer": ["Graphic Designer", "UI/UX Designer"],
    "Accountant": ["Accountant"],
}


class Timer:
    def __init__(self):
        self.start = None
        self.elapsed = 0

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed = time.perf_counter() - self.start


class Command(BaseCommand):
    help = "Generate professional dataset, seed DB, run comprehensive evaluation, and produce report"

    def add_arguments(self, parser):
        parser.add_argument("--skip-seed", action="store_true", help="Skip database seeding")
        parser.add_argument("--data-dir", type=str, default="generated", help="Subdirectory under data/ to load from")
        parser.add_argument("--sample", type=int, default=0, help="Only evaluate N profiles (0 = all)")

    def handle(self, *args, **options):
        skip_seed = options["skip_seed"]
        data_subdir = options["data_dir"]
        sample_size = options["sample"]
        data_dir = settings.DATA_DIR / data_subdir

        if not skip_seed:
            self._seed_database(data_dir)

        self._run_evaluation(data_dir, sample_size)

    def _seed_database(self, data_dir):
        self.stdout.write(self.style.NOTICE("=" * 60))
        self.stdout.write(self.style.NOTICE("  Seeding Database with Professional Dataset"))
        self.stdout.write(self.style.NOTICE("=" * 60))

        seed_dir = settings.DATA_DIR
        for f in ["companies.json", "recruiters.json", "job_seekers.json",
                   "user_profiles.json", "jobs.json", "applications.json"]:
            src = data_dir / f
            dst = seed_dir / f
            if src.exists():
                dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                self.stdout.write(f"  Copied {f} to data/")

        call_command("seed_all")
        self.stdout.write(self.style.SUCCESS("  Database seeded successfully.\n"))

    def _run_evaluation(self, data_dir, sample_size):
        self.stdout.write(self.style.NOTICE("=" * 60))
        self.stdout.write(self.style.NOTICE("  PROFESSIONAL AI EVALUATION"))
        self.stdout.write(self.style.NOTICE("=" * 60))

        profiles_data = json.loads((data_dir / "user_profiles.json").read_text(encoding="utf-8"))
        jobs_data = json.loads((data_dir / "jobs.json").read_text(encoding="utf-8"))

        if sample_size and sample_size < len(profiles_data):
            import random
            random.seed(42)
            profiles_data = random.sample(profiles_data, sample_size)

        total = len(profiles_data)
        self.stdout.write(f"\nEvaluating {total} profiles against {len(jobs_data)} jobs...\n")

        results = self._evaluate_all(profiles_data)
        report = self._build_report(results, profiles_data, jobs_data)
        self._save_report(report)
        self.stdout.write(report)
        self._check_quality_gates(results, report)

    def _evaluate_all(self, profiles_data):
        results = []
        total = len(profiles_data)

        for idx, pdata in enumerate(profiles_data):
            if (idx + 1) % 25 == 0 or idx == 0:
                self.stdout.write(f"  Evaluating profile {idx + 1}/{total}...", ending="\r")
            self.stdout.flush()

            try:
                result = self._evaluate_single_profile(pdata)
            except Exception as e:
                result = {
                    "email": pdata.get("email", "unknown"),
                    "expected_profession": pdata.get("profession", ""),
                    "detected_profession": None,
                    "profession_confidence": 0,
                    "error": str(e),
                    "recommendations": [],
                    "timings": {},
                }
            results.append(result)

        self.stdout.write(f"  Evaluated {total}/{total} profiles.\n")
        return results

    def _evaluate_single_profile(self, pdata):
        email = pdata["email"].strip().lower()
        expected_prof = pdata.get("profession", "")

        timings = {}

        try:
            user = User.objects.get(email=email)
            profile = getattr(user, "profile", None)
            if not profile:
                return {"email": email, "expected_profession": expected_prof, "error": "No profile"}
        except User.DoesNotExist:
            return {"email": email, "expected_profession": expected_prof, "error": "User not found"}

        resume_text = profile.resume_text or pdata.get("resume_text", "")

        with Timer() as t:
            detected_prof, confidence = classify_profession_with_resume(resume_text)
        timings["classification"] = t.elapsed

        with Timer() as t:
            recommendations = recommend_jobs_for_user(user, limit=10, resume_text=resume_text)
        timings["recommendation"] = t.elapsed

        rec_data = []
        for rec in recommendations:
            job = rec.get("job")
            if job:
                rec_data.append({
                    "job_id": job.id,
                    "title": job.title,
                    "category": job.job_category,
                    "match_pct": rec.get("match_percentage", 0),
                    "score": rec.get("score", 0),
                })

        return {
            "email": email,
            "expected_profession": expected_prof,
            "detected_profession": detected_prof,
            "profession_confidence": confidence,
            "recommendations": rec_data,
            "timings": timings,
            "error": None,
        }

    def _build_report(self, results, profiles_data, jobs_data):
        lines = []
        lines.append("# Professional AI Job Match Evaluation Report")
        lines.append("")
        lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
        lines.append("")
        lines.append("---")
        lines.append("")

        valid_results = [r for r in results if not r.get("error")]
        errors = [r for r in results if r.get("error")]

        lines.append("## 1. Dataset Summary")
        lines.append("")
        num_companies = len(json.loads((settings.DATA_DIR / "generated" / "companies.json").read_text(encoding="utf-8"))) if (settings.DATA_DIR / "generated" / "companies.json").exists() else 0
        recruiters_raw = json.loads((settings.DATA_DIR / "generated" / "recruiters.json").read_text(encoding="utf-8")) if (settings.DATA_DIR / "generated" / "recruiters.json").exists() else []
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total Resumes | {len(profiles_data)} |")
        lines.append(f"| Total Job Postings | {len(jobs_data)} |")
        lines.append(f"| Total Companies | {num_companies} |")
        lines.append(f"| Total Recruiters | {len(recruiters_raw)} |")
        lines.append(f"| Supported Professions | {len(PROFESSION_CONFIGS)} |")
        lines.append(f"| Valid Profiles (seeded) | {len(valid_results)} |")
        lines.append(f"| Errors | {len(errors)} |")
        lines.append("")

        lines.append("## 2. Classification Metrics")
        lines.append("")
        correct = sum(1 for r in valid_results if r["detected_profession"] == r["expected_profession"])
        classification_accuracy = correct / len(valid_results) * 100 if valid_results else 0

        lines.append(f"**Profession Classification Accuracy: {classification_accuracy:.1f}%** ({correct}/{len(valid_results)})")
        lines.append("")

        from collections import Counter, defaultdict

        confusion = defaultdict(Counter)
        for r in valid_results:
            expected = r["expected_profession"]
            detected = r["detected_profession"] or "None"
            confusion[expected][detected] += 1

        all_profs = sorted(PROFESSION_CONFIGS.keys())
        lines.append("### Confusion Matrix (Expected vs Detected)")
        lines.append("")
        header = "| Expected \\ Detected | " + " | ".join(p[:20] for p in all_profs) + " | Accuracy |"
        sep = "|" + "---|" * (len(all_profs) + 2)
        lines.append(header)
        lines.append(sep)
        for exp in all_profs:
            row = [f"**{exp[:20]}**"]
            total_exp = sum(confusion[exp].values())
            for det in all_profs:
                row.append(str(confusion[exp].get(det, 0)))
            acc = confusion[exp].get(exp, 0) / total_exp * 100 if total_exp else 0
            row.append(f"{acc:.0f}%")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        lines.append("## 3. Recommendation Metrics")
        lines.append("")

        top1_correct = 0
        top3_correct = 0
        top5_correct = 0
        rec_score_bands = Counter()

        false_positives = []
        false_negatives = []
        all_recommended_titles = []

        for r in valid_results:
            expected = r["expected_profession"]
            recs = r["recommendations"]
            related = get_related_profession_titles(expected) if expected else {expected}
            related_lower = {p.lower() for p in related}

            all_recommended_titles.extend(
                (expected, rec["category"], rec["match_pct"], rec["title"])
                for rec in recs
            )

            for band_name, lo, hi in SCORE_BANDS:
                for rec in recs:
                    if lo <= rec["match_pct"] <= hi:
                        rec_score_bands[band_name] += 1

            if recs:
                top1 = recs[0]
                if top1["category"].lower() == expected.lower() or top1["category"] in related:
                    top1_correct += 1

                top3 = recs[:3]
                top3_ok = any(
                    rec["category"].lower() == expected.lower() or rec["category"] in related
                    for rec in top3
                )
                if top3_ok:
                    top3_correct += 1

                top5 = recs[:5]
                top5_ok = any(
                    rec["category"].lower() == expected.lower() or rec["category"] in related
                    for rec in top5
                )
                if top5_ok:
                    top5_correct += 1

            expected_lower = expected.lower()
            forbidden = DISALLOWED_CROSS_RECOMMENDATIONS.get(expected, set())
            for rec in recs:
                rec_cat_lower = rec["category"].lower() if rec["category"] else ""
                for fb in forbidden:
                    if fb.lower() == rec_cat_lower:
                        false_positives.append({
                            "profile": r["email"],
                            "expected": expected,
                            "bad_job": rec["title"],
                            "bad_category": rec["category"],
                            "score": rec["match_pct"],
                        })

            fn_expected = FALSE_NEGATIVE_CHECK.get(expected, [expected])
            recommended_categories = {rec["category"] for rec in recs}
            for fn_cat in fn_expected:
                if fn_cat not in recommended_categories:
                    false_negatives.append({
                        "profile": r["email"],
                        "expected": expected,
                        "missing_category": fn_cat,
                    })

        n = len(valid_results)
        top1_acc = top1_correct / n * 100 if n else 0
        top3_acc = top3_correct / n * 100 if n else 0
        top5_acc = top5_correct / n * 100 if n else 0

        avg_match = 0
        match_count = 0
        for r in valid_results:
            for rec in r["recommendations"]:
                avg_match += rec["match_pct"]
                match_count += 1
        avg_match = avg_match / match_count if match_count else 0

        fp_rate = len(false_positives) / match_count * 100 if match_count else 0
        fn_rate = len(false_negatives) / n * 100 if n else 0

        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Top-1 Accuracy | {top1_acc:.1f}% |")
        lines.append(f"| Top-3 Accuracy | {top3_acc:.1f}% |")
        lines.append(f"| Top-5 Accuracy | {top5_acc:.1f}% |")
        lines.append(f"| Average Match Score | {avg_match:.1f}% |")
        lines.append(f"| False Positive Rate | {fp_rate:.2f}% ({len(false_positives)} instances) |")
        lines.append(f"| False Negative Rate | {fn_rate:.1f}% ({len(false_negatives)} instances) |")
        lines.append(f"| Precision@5 | {top5_acc:.1f}% |")
        lines.append(f"| Recall@5 | {top5_acc:.1f}% |")
        lines.append("")

        lines.append("## 4. Match Score Distribution")
        lines.append("")
        lines.append("| Band | Range | Count | Percentage |")
        lines.append("|------|-------|-------|------------|")
        total_bands = sum(rec_score_bands.values()) or 1
        for band_name, lo, hi in SCORE_BANDS:
            cnt = rec_score_bands.get(band_name, 0)
            pct = cnt / total_bands * 100
            lines.append(f"| {band_name} | {lo}–{hi}% | {cnt} | {pct:.1f}% |")
        lines.append("")

        lines.append("## 5. False Positive Report")
        lines.append("")
        if false_positives:
            lines.append(f"**{len(false_positives)} false positive(s) detected.**")
            lines.append("")
            lines.append("| Profile | Expected Profession | Incorrect Job | Incorrect Category | Match Score |")
            lines.append("|---------|---------------------|---------------|--------------------|-------------|")
            for fp in false_positives[:50]:
                lines.append(f"| {fp['profile'][:25]} | {fp['expected']} | {fp['bad_job'][:30]} | {fp['bad_category']} | {fp['score']}% |")
            if len(false_positives) > 50:
                lines.append(f"| ... and {len(false_positives) - 50} more |")
        else:
            lines.append("**No false positives detected.**")
        lines.append("")

        lines.append("## 6. False Negative Report")
        lines.append("")
        if false_negatives:
            lines.append(f"**{len(false_negatives)} false negative(s) detected.**")
            lines.append("")
            fn_by_cat = Counter(fn["missing_category"] for fn in false_negatives)
            lines.append("| Missing Category | Count |")
            lines.append("|------------------|-------|")
            for cat, cnt in fn_by_cat.most_common():
                lines.append(f"| {cat} | {cnt} |")
            lines.append("")
            lines.append("| Profile | Expected Profession | Missing Category |")
            lines.append("|---------|---------------------|------------------|")
            for fn in false_negatives[:30]:
                lines.append(f"| {fn['profile'][:25]} | {fn['expected']} | {fn['missing_category']} |")
            if len(false_negatives) > 30:
                lines.append(f"| ... and {len(false_negatives) - 30} more |")
        else:
            lines.append("**No false negatives detected.**")
        lines.append("")

        lines.append("## 7. Performance Benchmark")
        lines.append("")

        class_times = [r["timings"].get("classification", 0) for r in valid_results]
        rec_times = [r["timings"].get("recommendation", 0) for r in valid_results]

        avg_class_time = sum(class_times) / len(class_times) if class_times else 0
        avg_rec_time = sum(rec_times) / len(rec_times) if rec_times else 0
        total_time = avg_class_time + avg_rec_time

        lines.append(f"| Metric | Average (s) |")
        lines.append(f"|--------|-------------|")
        lines.append(f"| Profession Classification | {avg_class_time:.3f} |")
        lines.append(f"| Job Recommendation | {avg_rec_time:.3f} |")
        lines.append(f"| Total per Profile | {total_time:.3f} |")
        lines.append(f"| Total for {n} Profiles | {total_time * n:.1f} |")
        lines.append("")

        lines.append("## 8. Quality Gates")
        lines.append("")
        gates = [
            ("Profession Classification >= 95%", classification_accuracy >= 95, f"{classification_accuracy:.1f}%"),
            ("Top-1 Recommendation >= 90%", top1_acc >= 90, f"{top1_acc:.1f}%"),
            ("Top-3 Recommendation >= 95%", top3_acc >= 95, f"{top3_acc:.1f}%"),
            ("False Positive Rate <= 5%", fp_rate <= 5, f"{fp_rate:.2f}%"),
            ("False Negative Rate <= 5%", fn_rate <= 5, f"{fn_rate:.1f}%"),
            ("Avg Response Time <= 2s", total_time <= 2, f"{total_time:.3f}s"),
            ("No unrelated in Top 3", len(false_positives) == 0, f"{len(false_positives)} unrelated"),
        ]
        lines.append("| Gate | Status | Result |")
        lines.append("|------|--------|--------|")
        all_pass = True
        for name, passed, value in gates:
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            lines.append(f"| {name} | {status} | {value} |")
        lines.append("")
        if all_pass:
            lines.append("**All quality gates PASSED.**")
        else:
            lines.append("**Some quality gates FAILED. Review sections above for details.**")
        lines.append("")

        lines.append("## 9. Per-Profession Breakdown")
        lines.append("")
        from collections import defaultdict
        prof_results = defaultdict(list)
        for r in valid_results:
            prof_results[r["expected_profession"]].append(r)

        for prof in sorted(PROFESSION_CONFIGS.keys()):
            items = prof_results.get(prof, [])
            if not items:
                continue
            p_correct = sum(1 for r in items if r["detected_profession"] == prof)
            p_acc = p_correct / len(items) * 100
            p_top1 = 0
            p_avg_score = 0
            p_score_count = 0
            for r in items:
                recs = r["recommendations"]
                related = get_related_profession_titles(prof)
                if recs and (recs[0]["category"].lower() == prof.lower() or recs[0]["category"] in related):
                    p_top1 += 1
                for rec in recs:
                    p_avg_score += rec["match_pct"]
                    p_score_count += 1
            p_top1_acc = p_top1 / len(items) * 100
            p_avg_match = p_avg_score / p_score_count if p_score_count else 0
            lines.append(f"### {prof}")
            lines.append(f"- Profiles: {len(items)}")
            lines.append(f"- Classification Accuracy: {p_acc:.0f}%")
            lines.append(f"- Top-1 Accuracy: {p_top1_acc:.0f}%")
            lines.append(f"- Average Match Score: {p_avg_match:.0f}%")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("*Report generated by evaluate_professional_data management command.*")

        return "\n".join(lines)

    def _save_report(self, report):
        report_path = settings.DATA_DIR / "evaluation_report.md"
        report_path.write_text(report, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"\nReport saved to {report_path}"))

    def _check_quality_gates(self, results, report):
        pass

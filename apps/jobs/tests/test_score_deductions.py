"""Regression tests for the Phase 1 scoring fixes and the Phase 3 deduction layer.

The weighted engine in `compute_match_score` is unchanged; what these tests pin
down is that its output is now (a) correct where it used to invert, and (b)
followed by a bounded, job-specific and fully explained deduction step.
"""

import os

from django.test import TestCase

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.accounts.models import User, UserProfile
from apps.jobs.models import JobPosting
from apps.jobs.serializers import RecommendedJobSerializer
from apps.jobs.services import _build_recommendation, compute_match_score
from apps.shared.constants import ROLE_JOB_SEEKER, ROLE_RECRUITER
from apps.shared.cv_signals import extract_cv_signals
from apps.shared.deductions import MAX_TOTAL_DEDUCTION, evaluate_deductions

FLUTTER_CV = """Flutter Developer
Summary
4+ years of experience building cross-platform apps.
Skills
Flutter, Dart, Firebase, REST APIs, BLoC
Experience
2019 - 2023 mobile engineer, cut crash rate by 40%
Education
Bachelor of Engineering
Projects
- Retail app
- Delivery app
Certifications
- Google Associate Android Developer certified
github.com/example
"""

FLUTTER_SKILLS = ["Flutter", "Dart", "Firebase", "REST APIs", "BLoC"]


class DeductionScoringTests(TestCase):
    """The deduction layer must only ever charge for this posting's own asks."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="rec-deduct", email="rec-deduct@example.com",
            password="x", role=ROLE_RECRUITER,
        )
        cls.signals = extract_cv_signals(FLUTTER_CV)

    def _job(self, title="Flutter Developer", category="Mobile Developer",
             skills=None, experience=0, education=""):
        return JobPosting.objects.create(
            recruiter=self.recruiter, title=title, company="Acme",
            description="A mobile role.",
            required_skills=skills if skills is not None else ["Flutter", "Dart"],
            experience_required=experience, education_required=education,
            job_category=category,
        )

    def _score(self, job, skills=None, profession="Mobile Developer",
               specialization="Flutter Developer", signals=None, profile=None):
        return compute_match_score(
            user_skills=FLUTTER_SKILLS if skills is None else skills,
            user_profession=profession,
            profile=profile or UserProfile(experience_years=0, education=""),
            job=job,
            vector_score=0.5,
            cv_signals=self.signals if signals is None else signals,
            specialization=specialization,
        )

    # -- job specificity ---------------------------------------------------
    def test_unrequired_technology_is_never_deducted(self):
        """Docker/Kubernetes/AWS must cost nothing on a posting that never asked."""
        job = self._job(skills=["Flutter", "Dart", "Firebase", "REST APIs"])
        result = self._score(job)
        charged = {d["item"].lower() for d in result["deductions"]}
        for unrelated in ("docker", "kubernetes", "aws"):
            self.assertNotIn(unrelated, charged)

    def test_required_but_missing_skill_is_deducted_and_explained(self):
        job = self._job(skills=["Flutter", "Dart", "Docker"])
        result = self._score(job)
        docker = [d for d in result["deductions"] if d["item"].lower() == "docker"]
        self.assertEqual(len(docker), 1)
        self.assertGreater(docker[0]["points"], 0)
        self.assertIn("docker", docker[0]["reason"].lower())
        self.assertIn(docker[0]["severity"], ("critical", "medium", "minor"))

    def test_primary_technology_in_the_title_is_critical(self):
        """Missing the technology the role is named after is the worst case."""
        job = self._job(title="Senior Flutter Developer",
                        skills=["Flutter", "Dart"])
        result = self._score(job, skills=["Dart"])
        flutter = [d for d in result["deductions"] if d["item"].lower() == "flutter"]
        self.assertEqual(flutter[0]["severity"], "critical")

    # -- arithmetic --------------------------------------------------------
    def test_final_score_is_base_minus_deductions(self):
        job = self._job(skills=["Flutter", "Dart", "Docker", "CI/CD"])
        result = self._score(job)
        self.assertEqual(
            result["final_score"],
            result["base_score"] - result["total_deduction"],
        )
        self.assertEqual(result["match_explanation"]["base_score"], result["base_score"])
        self.assertEqual(result["match_explanation"]["final_score"], result["final_score"])

    def test_deductions_are_capped_and_line_items_sum_to_the_total(self):
        job = self._job(skills=[
            "Flutter", "Dart", "Firebase", "REST APIs", "Docker", "Kubernetes",
            "AWS", "GraphQL", "CI/CD", "Terraform", "Redis", "Kafka",
        ])
        result = self._score(job, skills=[])
        self.assertLessEqual(result["total_deduction"], MAX_TOTAL_DEDUCTION)
        self.assertEqual(
            sum(d["points"] for d in result["deductions"]),
            result["total_deduction"],
            "every listed deduction must be one the user was actually charged",
        )

    def test_score_never_falls_below_one(self):
        job = self._job(category="Accountant", skills=["Excel", "GAAP", "Auditing"])
        result = self._score(job, skills=[])
        self.assertGreaterEqual(result["final_score"], 1)

    # -- separation --------------------------------------------------------
    def test_stronger_cv_outscores_weaker_cv_on_the_same_posting(self):
        job = self._job(skills=["Flutter", "Dart", "Firebase", "REST APIs", "BLoC"])
        strong = self._score(job)
        weak = self._score(job, skills=["Dart"], signals=extract_cv_signals("Dart\n"))
        self.assertGreater(strong["final_score"], weak["final_score"] + 15,
                           "the ledger must separate a full match from a bare one")

    # -- strengths ---------------------------------------------------------
    def test_matched_requirements_are_reported_as_strengths(self):
        job = self._job(skills=["Flutter", "Dart", "Docker"])
        result = self._score(job)
        items = {s["item"].lower() for s in result["strengths"]}
        self.assertIn("flutter", items)
        self.assertIn("dart", items)

    def test_empty_requirements_produce_no_skill_deductions(self):
        job = self._job(skills=[])
        result = self._score(job)
        self.assertFalse([d for d in result["deductions"]
                          if d["category"] == "missing_skill"])

    def test_no_cv_text_means_no_presentation_deductions(self):
        """A profile with no parsed CV must not be charged for a CV it never gave."""
        report = evaluate_deductions(job=self._job(skills=[]), missing_skills=[],
                                     signals={}, profession="Mobile Developer")
        self.assertEqual(report["total"], 0)


class EducationScoringTests(TestCase):
    """Over-qualification must never score below exactly meeting the bar."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="rec-edu", email="rec-edu@example.com",
            password="x", role=ROLE_RECRUITER,
        )
        cls.job = JobPosting.objects.create(
            recruiter=cls.recruiter, title="Backend Developer", company="Acme",
            description="Backend role.", required_skills=["Python", "Django"],
            experience_required=0, education_required="Bachelor's Degree",
            job_category="Backend Developer",
        )

    def _education_score(self, cv_line):
        result = compute_match_score(
            user_skills=["Python", "Django"], user_profession="Backend Developer",
            profile=UserProfile(experience_years=0, education=""),
            job=self.job, vector_score=0.4,
            cv_signals=extract_cv_signals(f"{cv_line}\nPython and Django work.\n"),
        )
        return result["education_score"]

    def test_master_and_phd_are_not_penalised_against_a_bachelor_requirement(self):
        bachelor = self._education_score("Bachelor of Science")
        master = self._education_score("Master of Science")
        phd = self._education_score("PhD in Computer Science")
        self.assertEqual(bachelor, 100)
        self.assertGreaterEqual(master, bachelor)
        self.assertGreaterEqual(phd, bachelor)

    def test_below_requirement_is_graded_not_flattened(self):
        diploma = self._education_score("Diploma in IT")
        self.assertGreater(diploma, 30, "a diploma is closer to a degree than nothing is")
        self.assertLess(diploma, 100)

    def test_profile_column_is_read_through_the_same_parser(self):
        """The recommendation path has no parsed CV; it must still rank properly."""
        result = compute_match_score(
            user_skills=["Python"], user_profession="Backend Developer",
            profile=UserProfile(experience_years=0, education="Master of Science"),
            job=self.job, vector_score=0.4, cv_signals={},
        )
        self.assertEqual(result["education_score"], 100)


class ProfessionFallbackTests(TestCase):
    """An unidentified CV must not be handed a perfect profession sub-score."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="rec-prof", email="rec-prof@example.com",
            password="x", role=ROLE_RECRUITER,
        )

    def test_unknown_profession_scores_neutral_not_perfect(self):
        job = JobPosting.objects.create(
            recruiter=self.recruiter, title="Something", company="Acme",
            description="d", required_skills=["Python"], job_category="",
        )
        result = compute_match_score(
            user_skills=["Python"], user_profession=None,
            profile=UserProfile(), job=job, vector_score=0.3, cv_signals={},
        )
        self.assertLess(result["profession_match"], 100)


class LedgerSerializationTests(TestCase):
    """The ledger has to survive the API boundary for the UI to render it."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="rec-ser", email="rec-ser@example.com",
            password="x", role=ROLE_RECRUITER,
        )
        cls.seeker = User.objects.create_user(
            username="seek-ser", email="seek-ser@example.com",
            password="x", role=ROLE_JOB_SEEKER,
        )
        cls.profile, _ = UserProfile.objects.get_or_create(user=cls.seeker)

    def test_recommendation_exposes_the_ledger(self):
        job = JobPosting.objects.create(
            recruiter=self.recruiter, title="Flutter Developer", company="Acme",
            description="d", required_skills=["Flutter", "Dart", "Docker"],
            job_category="Mobile Developer",
        )
        profile = self.seeker.profile
        profile.skills = ["Flutter", "Dart"]
        profile.save()

        result = compute_match_score(
            user_skills=profile.skills, user_profession="Mobile Developer",
            profile=profile, job=job, vector_score=0.5,
            cv_signals=extract_cv_signals(FLUTTER_CV),
            specialization="Flutter Developer",
        )
        recommendation = _build_recommendation(
            user=self.seeker, profile=profile, job=job,
            vector_score=result["score"],
            match_explanation=result["match_explanation"],
            deductions=result["deductions"], strengths=result["strengths"],
        )
        data = RecommendedJobSerializer(recommendation).data

        self.assertIn("deductions", data)
        self.assertIn("strengths", data)
        self.assertEqual(data["base_score"], result["base_score"])
        self.assertEqual(data["total_deduction"], result["total_deduction"])
        self.assertEqual(
            data["match_percentage"], data["base_score"] - data["total_deduction"],
        )
        for entry in data["deductions"]:
            self.assertTrue(entry["reason"], "every deduction must be explained")

    def test_recommendation_without_a_ledger_still_serializes(self):
        """Stored analyses from before Phase 3 must keep replaying."""
        job = JobPosting.objects.create(
            recruiter=self.recruiter, title="Backend Developer", company="Acme",
            description="d", required_skills=["Python"], job_category="Backend Developer",
        )
        recommendation = _build_recommendation(
            user=self.seeker, profile=self.seeker.profile, job=job,
            vector_score=0.5, match_explanation={"final_score": 70},
        )
        data = RecommendedJobSerializer(recommendation).data
        self.assertEqual(data["match_percentage"], 70)
        self.assertEqual(data["deductions"], [])

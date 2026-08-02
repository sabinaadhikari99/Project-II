"""Regression tests for the CV-driven analysis pipeline.

These lock in the behaviour that was previously broken:
  * different CVs must produce different gaps / courses / roadmaps
  * results must never drift into another profession
  * scores must respond to what the CV actually contains
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import UserProfile
from apps.jobs.models import JobPosting
from apps.shared.cv_signals import extract_cv_signals
from apps.shared.specializations import detect_specialization
from apps.skillgap.analysis_memo import clear
from apps.skillgap.career import CareerAnalyzer
from apps.skillgap.course_service import CourseRecommendationService

User = get_user_model()

FLUTTER_CV = """Priya Sharma
Flutter Developer
Summary: Mobile engineer with 3 years building cross-platform apps.
Experience: Flutter Developer at AppWorks. Built apps in Flutter and Dart,
integrated Firebase, used BLoC for state management, shipped to Play Store.
Skills: Flutter, Dart, Firebase, BLoC, REST APIs, Git, SQLite
Education: Bachelor of Computer Engineering"""

ANALYST_CV = """Rahul Verma
Data Analyst
Summary: Analyst with 4 years turning data into dashboards and reports.
Experience: Data Analyst at FinCorp. Wrote SQL queries, built Power BI
dashboards, ran statistical analysis and A/B tests, automated Excel reporting.
Skills: SQL, Excel, Power BI, Statistics, Data Visualization
Education: Bachelor of Statistics"""

DESIGNER_CV = """Ana Costa
Graphic Designer
Summary: Visual designer with 5 years in brand and print.
Experience: Graphic Designer at StudioNine. Created brand identities, logos and
print collateral using Illustrator, Photoshop and InDesign.
Skills: Illustrator, Photoshop, InDesign, Branding, Typography, Layout
Education: Bachelor of Fine Arts"""

JOB_FIXTURES = [
    ("Senior Flutter Engineer", "Mobile Developer",
     ["Flutter", "Dart", "Firebase", "REST APIs", "State Management"]),
    ("Android Engineer", "Mobile Developer",
     ["Kotlin", "Android", "Jetpack Compose"]),
    ("React Frontend Developer", "Frontend Developer",
     ["React", "TypeScript", "Redux", "Tailwind CSS"]),
    ("Django Backend Engineer", "Backend Developer",
     ["Python", "Django", "PostgreSQL", "Celery"]),
    ("Data Analyst", "Data Analyst",
     ["SQL", "Excel", "Power BI", "Tableau", "Statistics"]),
    ("BI Analyst", "Data Analyst", ["Power BI", "DAX", "SQL"]),
    ("Graphic Designer", "Graphic Designer",
     ["Photoshop", "Illustrator", "InDesign", "Branding"]),
    ("Brand Designer", "Graphic Designer", ["Illustrator", "Branding", "Typography"]),
]


class CVDrivenAnalysisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="cvdriven_rec", email="cvdriven_rec@example.com",
            password="testpass123", role="recruiter")
        for title, category, skills in JOB_FIXTURES:
            JobPosting.objects.create(
                recruiter=cls.recruiter, title=title, company="Acme",
                location="Remote", work_mode="remote", description=f"{title} role.",
                required_skills=skills, experience_required=2,
                job_category=category, is_active=True)

    def setUp(self):
        clear()
        self._seq = 0

    def _analyze(self, cv):
        clear()
        self._seq += 1
        user = User.objects.create_user(
            username=f"cvuser{self._seq}", email=f"cvuser{self._seq}@example.com",
            password="testpass123", role="job_seeker")
        UserProfile.objects.create(user=user, skills=[], resume_text=cv,
                                   experience_years=3, education="Bachelor")
        return user, CareerAnalyzer.analyze(user)

    # -- profession + specialisation ---------------------------------------

    def test_flutter_cv_detects_flutter_specialisation(self):
        _, ctx = self._analyze(FLUTTER_CV)
        self.assertEqual(ctx.profession, "Mobile Developer")
        self.assertEqual(ctx.specialization, "Flutter Developer")

    def test_analyst_cv_detects_analyst(self):
        _, ctx = self._analyze(ANALYST_CV)
        self.assertEqual(ctx.profession, "Data Analyst")

    def test_designer_cv_detects_designer(self):
        _, ctx = self._analyze(DESIGNER_CV)
        self.assertEqual(ctx.profession, "Graphic Designer")

    # -- no cross-profession bleed -----------------------------------------

    def test_flutter_cv_never_recommends_web_or_design_roles(self):
        _, ctx = self._analyze(FLUTTER_CV)
        titles = " ".join(j["title"] for j in ctx.recommended_jobs).lower()
        self.assertIn("flutter", titles)
        for banned in ("react", "frontend", "designer", "django"):
            self.assertNotIn(banned, titles)

    def test_flutter_gaps_are_mobile_not_web(self):
        _, ctx = self._analyze(FLUTTER_CV)
        gaps = " ".join(ctx.missing_names).lower()
        for banned in ("react", "angular", "vue", "photoshop", "power bi"):
            self.assertNotIn(banned, gaps)

    def test_designer_gaps_contain_no_engineering_skills(self):
        _, ctx = self._analyze(DESIGNER_CV)
        gaps = " ".join(ctx.missing_names).lower()
        for banned in ("python", "django", "kubernetes", "flutter", "react"):
            self.assertNotIn(banned, gaps)

    def test_analyst_gaps_are_analytics_not_mobile(self):
        _, ctx = self._analyze(ANALYST_CV)
        gaps = " ".join(ctx.missing_names).lower()
        for banned in ("flutter", "dart", "kotlin", "photoshop"):
            self.assertNotIn(banned, gaps)

    # -- differentiation ----------------------------------------------------

    def test_different_cvs_produce_different_gaps_and_courses(self):
        seen_gaps, seen_courses = [], []
        for cv in (FLUTTER_CV, ANALYST_CV, DESIGNER_CV):
            user, ctx = self._analyze(cv)
            courses = CourseRecommendationService.get_or_generate(user)["courses"]
            seen_gaps.append(tuple(ctx.missing_names))
            seen_courses.append(tuple(c["skill_covered"] for c in courses))
        self.assertEqual(len(set(seen_gaps)), 3, f"gaps repeated: {seen_gaps}")
        self.assertEqual(len(set(seen_courses)), 3, f"courses repeated: {seen_courses}")

    def test_courses_only_ever_come_from_gaps(self):
        user, ctx = self._analyze(FLUTTER_CV)
        courses = CourseRecommendationService.get_or_generate(user)["courses"]
        for course in courses:
            self.assertIn(course["missing_skill"], ctx.missing_names)

    # -- score responds to the document ------------------------------------

    def test_score_responds_to_projects_and_certifications(self):
        _, plain = self._analyze(FLUTTER_CV)
        rich_cv = FLUTTER_CV + """
Projects:
- MediTrack: offline-first Flutter app, 40k+ users, cut sync time by 60%
- PayFlow: Flutter payments SDK, led a team of 4 engineers
- ShopLite: e-commerce app published to Play Store
Certifications:
- Google Associate Android Developer
- AWS Certified Cloud Practitioner
Portfolio: github.com/priyasharma
Experience: 8 years of professional experience.
"""
        _, rich = self._analyze(rich_cv)
        self.assertGreater(rich.match_score, plain.match_score)
        self.assertEqual(rich.career_level_label, "Senior")


class ExplainabilityTests(TestCase):
    """Phase 2: every number the UI shows must be explainable and CV-derived."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="exp_rec", email="exp_rec@example.com",
            password="testpass123", role="recruiter")
        for title, category, skills in JOB_FIXTURES:
            JobPosting.objects.create(
                recruiter=cls.recruiter, title=title, company="Acme",
                location="Remote", work_mode="remote", description=f"{title} role.",
                required_skills=skills, experience_required=2,
                job_category=category, is_active=True)

    def setUp(self):
        clear()

    def _analyze(self, cv, name="exp_user"):
        """Run the real AI-Match path, stubbing only the PDF text extraction."""
        import apps.jobs.services as svc
        clear()
        user = User.objects.create_user(
            username=name, email=f"{name}@example.com",
            password="testpass123", role="job_seeker")
        UserProfile.objects.create(user=user, skills=[], resume_text=cv,
                                   experience_years=3, education="Bachelor")
        original = svc.extract_pdf_text
        svc.extract_pdf_text = lambda f: cv
        try:
            return svc.analyze_resume_match(user, object())
        finally:
            svc.extract_pdf_text = original

    def test_extracted_cv_skills_reach_the_match_score(self):
        """Regression: UserProfile.objects.get_or_create() returns a fresh
        instance while recommend_jobs_for_user() reads the CACHED user.profile.
        When that cache is not primed, the skills just parsed from the CV never
        reach scoring and skills_match is 0 for every upload."""
        data = self._analyze(FLUTTER_CV, "skillcache_user")
        self.assertGreater(data["score_breakdown"]["skills_match"], 0)
        top = data["recommended_jobs"][0]
        self.assertTrue(top["matched_skills"])

    def test_score_breakdown_exposes_all_seven_components(self):
        data = self._analyze(FLUTTER_CV, "breakdown_user")
        for key in ("profession_match", "skills_match", "experience_match",
                    "education_match", "project_match", "certification_match",
                    "semantic_similarity"):
            self.assertIn(key, data["score_breakdown"])

    def test_every_recommended_job_explains_itself(self):
        data = self._analyze(FLUTTER_CV, "why_user")
        for job in data["recommended_jobs"]:
            self.assertTrue(job["why_matched"])
            self.assertTrue(job["why_not_higher"])

    def test_action_plan_entries_are_quantified(self):
        data = self._analyze(ANALYST_CV, "plan_user")
        for entry in data["skill_action_plan"]:
            self.assertIn(entry["importance"], ("High", "Medium", "Low"))
            self.assertGreaterEqual(entry["required_by_percent"], 0)
            self.assertGreater(entry["estimated_weeks"], 0)
            self.assertGreater(entry["expected_score_gain"], 0)
            self.assertTrue(entry["why"])

    def test_resume_quality_is_scored_and_explained(self):
        data = self._analyze(FLUTTER_CV, "quality_user")
        quality = data["resume_quality"]
        self.assertGreaterEqual(quality["score"], 0)
        self.assertTrue(quality["breakdown"])
        for check in quality["breakdown"]:
            self.assertTrue(check["detail"], f"{check['label']} has no explanation")

    def test_richer_cv_scores_better_on_resume_quality(self):
        plain = self._analyze(ANALYST_CV, "plainq_user")["resume_quality"]["score"]
        rich = self._analyze(ANALYST_CV + """
Projects:
- SalesPulse: Power BI dashboard used by 300+ staff, cut reporting time 40%
- ChurnLens: Python churn model, improved retention by 12%
Certifications:
- Microsoft Certified: Data Analyst Associate
Contact: rahul@example.com | +1 555 987 6543 | github.com/rahulverma
""", "richq_user")["resume_quality"]["score"]
        self.assertGreater(rich, plain)

    def test_insights_are_categorised(self):
        data = self._analyze(FLUTTER_CV, "insight_user")
        categories = {g["category"] for g in data["structured_insights"]}
        for expected in ("Strengths", "Weaknesses", "Employability"):
            self.assertIn(expected, categories)

    def test_gap_dashboard_exposes_categories_and_coverage(self):
        from apps.skillgap.services import analyze_skill_gap
        user, _ = None, None
        self._analyze(ANALYST_CV, "gapdash_user")
        clear()
        user = User.objects.get(username="gapdash_user")
        gap = analyze_skill_gap(user)
        self.assertEqual(set(gap["gap_categories"]),
                         {"critical", "important", "optional", "future"})
        for key in ("current_skill_coverage", "missing_skill_coverage",
                    "industry_readiness", "job_readiness"):
            self.assertIn(key, gap["coverage"])


class CVSignalTests(TestCase):
    def test_experience_years_parsed_from_text(self):
        self.assertEqual(
            extract_cv_signals("Engineer with 8 years of experience.")["experience_years"], 8.0)

    def test_experience_inferred_from_date_ranges(self):
        signals = extract_cv_signals("Developer at Acme 2018 - 2024")
        self.assertGreater(signals["experience_years"], 0)

    def test_education_and_evidence_flags(self):
        signals = extract_cv_signals(
            "Master of Science. AWS Certified Solutions Architect. "
            "Led a team and improved uptime by 30%. github.com/someone")
        self.assertEqual(signals["education_level"], "master")
        self.assertTrue(signals["has_certifications"])
        self.assertTrue(signals["has_metrics"])
        self.assertTrue(signals["has_leadership"])
        self.assertTrue(signals["has_portfolio"])

    def test_empty_cv_is_safe(self):
        signals = extract_cv_signals("")
        self.assertEqual(signals["experience_years"], 0.0)
        self.assertEqual(signals["education_level"], "unknown")


class SpecializationTests(TestCase):
    def test_flutter_beats_native_mobile(self):
        spec, _ = detect_specialization(
            FLUTTER_CV, ["Flutter", "Dart", "Firebase"], "Mobile Developer")
        self.assertEqual(spec, "Flutter Developer")

    def test_kotlin_cv_detects_android(self):
        spec, _ = detect_specialization(
            "Android Developer building apps with Kotlin and Jetpack Compose.",
            ["Kotlin", "Android", "Jetpack Compose"], "Mobile Developer")
        self.assertEqual(spec, "Android Developer")

    def test_specialisation_never_escapes_its_parent(self):
        spec, _ = detect_specialization(
            FLUTTER_CV, ["Flutter", "Dart"], "Data Analyst")
        self.assertIn(spec, ("Data Analyst", "Business Intelligence Analyst",
                             "Business Analyst"))
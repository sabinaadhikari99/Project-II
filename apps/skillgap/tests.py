from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.jobs.models import JobPosting
from apps.skillgap.services import analyze_skill_gap
from apps.accounts.models import UserProfile
from apps.skillgap.analysis_memo import clear
from apps.skillgap.course_service import CourseRecommendationService
from apps.skillgap.roadmap_service import LearningRoadmapService
from apps.skillgap.career import CareerAnalyzer
from apps.skillgap.models import CourseRecommendation, LearningRoadmap


User = get_user_model()


class SkillGapServiceTests(TestCase):
    def setUp(self):
        clear()
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            skills=["Python", "django"],
            resume_text="",
        )

    def test_analyze_skill_gap_with_missing_skills(self):
        JobPosting.objects.create(
            recruiter=self.user,
            title="Backend Developer",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Build APIs and backend services.",
            required_skills=["Python", "Django", "REST"],
            experience_required=2,
            is_active=True,
        )

        result = analyze_skill_gap(self.user)

        self.assertEqual(result["user_skills"], ["django", "Python"])
        # The gap is no longer only "what this one posting lists". It is the
        # requirements of the best-matched postings PLUS the canonical skills of
        # the detected specialisation (Python/Django Developer), which is what
        # makes the analysis role-correct instead of pool-shaped.
        self.assertIn("REST APIs", result["missing_skills"])
        self.assertIn("PostgreSQL", result["missing_skills"])
        # ...and it must never drift into another field.
        for off_profession in ("React", "Flutter", "Photoshop", "Kubernetes"):
            self.assertNotIn(off_profession, result["missing_skills"])
        # Every recommended resource must map to an actual gap (compared on
        # normalised keys - a resource may be filed under an alias such as
        # "drf" for "Django REST Framework").
        from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set
        missing_norm = normalize_skill_set(result["missing_skills"])
        for resource in result["recommended_resources"]:
            self.assertIn(normalize_skill(resource["skill"]), missing_norm)

    def test_frontend_job_is_not_a_gap_for_a_python_candidate(self):
        """A Python/Django candidate must NOT be told to learn React because an
        unrelated Frontend posting happens to exist in the database.

        This is the exact cross-profession bleed that made every CV produce the
        same gaps: the analyser used to union required_skills across the whole
        job pool regardless of the candidate's profession.
        """
        JobPosting.objects.create(
            recruiter=self.user,
            title="Frontend Developer",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Build modern frontends.",
            required_skills=["JavaScript", "React"],
            experience_required=1,
            job_category="Frontend Developer",
            is_active=True,
        )

        result = analyze_skill_gap(self.user)

        self.assertNotIn("React", result["missing_skills"])
        self.assertNotIn("JavaScript", result["missing_skills"])

    def test_resources_are_recommended_for_on_profession_gaps(self):
        JobPosting.objects.create(
            recruiter=self.user,
            title="Frontend Developer",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Build modern frontends.",
            required_skills=["JavaScript", "React"],
            experience_required=1,
            job_category="Frontend Developer",
            is_active=True,
        )
        self.profile.skills = ["JavaScript", "HTML", "CSS"]
        self.profile.save()

        result = analyze_skill_gap(self.user)

        self.assertIn("React", result["missing_skills"])


class ResumeGateTests(TestCase):
    """Recommendations must only appear after a CV has been uploaded and analyzed."""

    def setUp(self):
        clear()
        self.recruiter = User.objects.create_user(
            username="recruiter_gate",
            email="recruiter_gate@example.com",
            password="testpass123",
            role="recruiter",
        )
        self.job = JobPosting.objects.create(
            recruiter=self.recruiter,
            title="Mobile Developer",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Build cross-platform mobile apps with Flutter.",
            required_skills=["Firebase", "Riverpod", "Flutter"],
            experience_required=2,
            job_category="Mobile Developer",
            is_active=True,
        )
        self.user = User.objects.create_user(
            username="gate_user",
            email="gate_user@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            skills=["Flutter", "Dart"],
            resume_text="",
        )

    def test_no_courses_before_cv_upload(self):
        result = CourseRecommendationService.get_or_generate(self.user)
        self.assertIs(result["has_resume"], False)
        self.assertEqual(result["courses"], [])
        self.assertFalse(CourseRecommendation.objects.filter(user=self.user).exists())

    def test_no_roadmap_before_cv_upload(self):
        result = LearningRoadmapService.get_or_generate(self.user)
        self.assertIs(result["has_resume"], False)
        self.assertIsNone(result["roadmap"])
        self.assertIsNone(result["progress"])
        self.assertFalse(LearningRoadmap.objects.filter(user=self.user).exists())

    def test_gap_api_exposes_has_resume(self):
        gap = analyze_skill_gap(self.user)
        self.assertIs(gap["has_resume"], False)

    def test_courses_generated_only_after_cv_upload(self):
        self.profile.resume_text = (
            "Experienced Flutter developer building cross-platform mobile applications."
        )
        self.profile.save()

        result = CourseRecommendationService.get_or_generate(self.user)

        self.assertIs(result["has_resume"], True)
        self.assertEqual(result["profession"], "Mobile Developer")
        self.assertTrue(result["courses"])
        covered = {course["skill_covered"] for course in result["courses"]}
        self.assertIn("Firebase", covered)
        self.assertIn("Riverpod", covered)

    def test_roadmap_generated_only_after_cv_upload(self):
        self.profile.resume_text = (
            "Experienced Flutter developer building cross-platform mobile applications."
        )
        self.profile.save()

        result = LearningRoadmapService.get_or_generate(self.user)

        self.assertIs(result["has_resume"], True)
        self.assertIsNotNone(result["roadmap"])
        self.assertGreaterEqual(result["progress"]["total"], 1)

    def test_different_cvs_never_reuse_courses(self):
        self.profile.resume_text = (
            "Experienced Flutter developer building cross-platform mobile applications."
        )
        self.profile.save()
        flutter = CourseRecommendationService.get_or_generate(self.user)

        other = User.objects.create_user(
            username="gate_user_2",
            email="gate_user_2@example.com",
            password="testpass123",
        )
        UserProfile.objects.create(
            user=other,
            skills=["Excel", "Python"],
            resume_text="Data analyst performing statistical analysis and dashboards with Excel.",
        )
        JobPosting.objects.create(
            recruiter=self.recruiter,
            title="Data Analyst",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Analyze data, build dashboards, and produce reports.",
            required_skills=["SQL", "Power BI", "Tableau", "Statistics"],
            experience_required=2,
            job_category="Data Analyst",
            is_active=True,
        )
        analyst = CourseRecommendationService.get_or_generate(other)

        flutter_skills = {course["skill_covered"] for course in flutter["courses"]}
        analyst_skills = {course["skill_covered"] for course in analyst["courses"]}
        self.assertTrue(flutter_skills)
        self.assertTrue(analyst_skills)
        self.assertTrue(flutter_skills.isdisjoint(analyst_skills))


class JobReadyRoadmapTests(TestCase):
    """A CV with no remaining gaps must still produce a roadmap with advanced
    topics — never an empty/unavailable state after a successful analysis."""

    def setUp(self):
        clear()
        self.recruiter = User.objects.create_user(
            username="recruiter_jr",
            email="recruiter_jr@example.com",
            password="testpass123",
            role="recruiter",
        )
        JobPosting.objects.create(
            recruiter=self.recruiter,
            title="Data Analyst",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Analyze data, build dashboards, and produce reports.",
            required_skills=["SQL", "Power BI", "Tableau", "Statistics", "Excel", "Data Visualization"],
            experience_required=2,
            job_category="Data Analyst",
            is_active=True,
        )
        self.user = User.objects.create_user(
            username="jobready_user",
            email="jobready_user@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            skills=["SQL", "Power BI", "Tableau", "Statistics", "Excel", "Data Visualization"],
            resume_text=(
                "Data analyst with 4 years of experience in SQL, Power BI, Tableau, "
                "statistics, Excel and data visualization."
            ),
        )

    def test_job_ready_roadmap_generated_with_advanced_topics(self):
        result = LearningRoadmapService.get_or_generate(self.user)
        self.assertIs(result["has_resume"], True)
        roadmap = result["roadmap"]
        self.assertIsNotNone(roadmap)
        self.assertTrue(roadmap["job_ready"])
        self.assertEqual(roadmap["roadmap_type"], "job_ready")
        self.assertTrue(roadmap["steps"])
        self.assertTrue(roadmap["phases"])
        self.assertGreaterEqual(roadmap["total_steps"], 1)

    def test_job_ready_roadmap_skips_topics_already_mastered(self):
        roadmap = LearningRoadmapService.get_or_generate(self.user)["roadmap"]
        keys = {step["skill_key"] for step in roadmap["steps"]}
        self.assertNotIn("statistics", keys)
        self.assertNotIn("tableau", keys)
        self.assertIn("a/btesting", keys)
        self.assertIn("machinelearning", keys)

    def test_phases_contain_all_required_elements(self):
        roadmap = LearningRoadmapService.get_or_generate(self.user)["roadmap"]
        for phase in roadmap["phases"]:
            self.assertIn("skills", phase)
            self.assertIn("why_important", phase)
            self.assertIn("learning_resources", phase)
            self.assertIn("estimated_hours", phase)
            self.assertIn("estimated_weeks", phase)
            self.assertIn("priority", phase)
            self.assertIn("practice_project", phase)
            self.assertIn("objectives", phase)
        for phase in roadmap["phases"][:-1]:
            self.assertTrue(phase["why_important"])
            self.assertTrue(phase["learning_resources"])
            for resource in phase["learning_resources"]:
                self.assertTrue(resource["title"])
                self.assertTrue(resource["url"])
                self.assertTrue(resource["skill"])
        for step in roadmap["steps"]:
            self.assertIn("why", step)
            self.assertIn("priority", step)
            self.assertIn("estimated_hours", step)
            self.assertIn("learning_resource", step)
            self.assertTrue(step["learning_resource"]["url"])

    def test_roadmap_persisted_and_replaced_on_new_cv(self):
        first = LearningRoadmapService.get_or_generate(self.user)["roadmap"]
        self.assertTrue(LearningRoadmap.objects.filter(user=self.user).exists())

        self.profile.skills = ["Flutter", "Dart", "Riverpod", "Firebase"]
        self.profile.resume_text = (
            "Flutter mobile developer building cross-platform apps with Riverpod and Firebase."
        )
        self.profile.save()
        clear()
        result = LearningRoadmapService.get_or_generate(self.user)
        self.assertIs(result["has_resume"], True)
        self.assertIsNotNone(result["roadmap"])
        self.assertEqual(LearningRoadmap.objects.filter(user=self.user).count(), 1)
        self.assertEqual(result["roadmap"]["profession"], "Mobile Developer")
        self.assertNotEqual(
            [step["skill_key"] for step in result["roadmap"]["steps"]],
            [step["skill_key"] for step in first["steps"]],
        )


class CourseQualityTests(TestCase):
    """Top-5 relevance and quality guarantees for the course + roadmap engine."""

    def setUp(self):
        clear()
        self.recruiter = User.objects.create_user(
            username="recruiter_quality",
            email="recruiter_quality@example.com",
            password="testpass123",
            role="recruiter",
        )
        for category, title, required in [
            (
                "Mobile Developer",
                "Mobile Developer",
                ["Flutter", "Dart", "Firebase", "Riverpod", "Swift", "Kotlin"],
            ),
            (
                "Mobile Developer",
                "Mobile Developer",
                ["Flutter", "Dart", "Firebase", "Mobile Testing"],
            ),
            (
                "Frontend Developer",
                "Frontend Developer",
                ["React", "TypeScript", "JavaScript", "HTML", "CSS"],
            ),
        ]:
            JobPosting.objects.create(
                recruiter=self.recruiter,
                title=title,
                company="Acme Inc",
                location="Remote",
                work_mode="remote",
                description=f"{title} position requiring {required}.",
                required_skills=required,
                experience_required=2,
                job_category=category,
                is_active=True,
            )
        self.user = User.objects.create_user(
            username="quality_user",
            email="quality_user@example.com",
            password="testpass123",
        )
        self.profile = UserProfile.objects.create(
            user=self.user,
            skills=["Flutter", "Dart", "Riverpod", "Firebase", "Git"],
            resume_text=(
                "Flutter developer with 3 years building cross-platform apps. "
                "State management with Riverpod, Firebase backend, Git workflow."
            ),
        )

    def test_courses_capped_at_five(self):
        result = CourseRecommendationService.get_or_generate(self.user)
        self.assertLessEqual(len(result["courses"]), 5)
        self.assertTrue(result["courses"])

    def test_courses_only_from_missing_skills(self):
        missing_raw = {
            item["skill"].lower()
            for item in CareerAnalyzer.analyze(self.user).missing_skills
        }
        result = CourseRecommendationService.get_or_generate(self.user)
        for course in result["courses"]:
            self.assertIn(course["missing_skill"].lower(), missing_raw)

    def test_no_native_mobile_courses_for_flutter_dev(self):
        result = CourseRecommendationService.get_or_generate(self.user)
        covered = {course["missing_skill"].lower() for course in result["courses"]}
        self.assertFalse(covered & {"swift", "swiftui", "uikit", "ios", "kotlin", "android", "java"})
        self.assertTrue({"firebase", "riverpod", "mobile testing"} & covered)

    def test_roadmap_has_phases_and_no_native_stack(self):
        result = LearningRoadmapService.get_or_generate(self.user)
        roadmap = result["roadmap"]
        self.assertIsNotNone(roadmap)
        phases = roadmap["phases"]
        self.assertGreaterEqual(len(phases), 2)
        self.assertEqual(phases[-1]["phase_number"], "capstone")
        keys = {step["skill_key"] for step in roadmap["steps"]}
        self.assertFalse(keys & {"swift", "swiftui", "uikit", "ios", "kotlin", "android", "java"})
        for step in roadmap["steps"]:
            self.assertIn("phase_number", step)
            self.assertIn("phase_title", step)

    def test_phase_progress_hydrated(self):
        result = LearningRoadmapService.get_or_generate(self.user)
        roadmap = result["roadmap"]
        self.assertTrue(roadmap["phases"])
        for phase in roadmap["phases"]:
            self.assertIn("progress", phase)
            self.assertIn("percentage", phase["progress"])

    def test_courses_are_deterministic(self):
        first = CourseRecommendationService.get_or_generate(self.user, force=True)
        second = CourseRecommendationService.get_or_generate(self.user, force=True)
        self.assertEqual(
            [c["course_title"] for c in first["courses"]],
            [c["course_title"] for c in second["courses"]],
        )

    def test_roadmap_is_deterministic(self):
        first = LearningRoadmapService.get_or_generate(self.user, force=True)
        second = LearningRoadmapService.get_or_generate(self.user, force=True)
        self.assertEqual(
            [s["skill_key"] for s in first["roadmap"]["steps"]],
            [s["skill_key"] for s in second["roadmap"]["steps"]],
        )

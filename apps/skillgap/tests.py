from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.jobs.models import JobPosting
from apps.skillgap.services import analyze_skill_gap
from apps.accounts.models import UserProfile


User = get_user_model()


class SkillGapServiceTests(TestCase):
    def setUp(self):
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
        self.assertEqual(result["missing_skills"], ["REST"])
        self.assertEqual(len(result["recommended_resources"]), 0)

    def test_analyze_skill_gap_recommends_resources_for_missing_skills(self):
        JobPosting.objects.create(
            recruiter=self.user,
            title="Frontend Developer",
            company="Acme Inc",
            location="Remote",
            work_mode="remote",
            description="Build modern frontends.",
            required_skills=["JavaScript", "React"],
            experience_required=1,
            is_active=True,
        )

        result = analyze_skill_gap(self.user)

        self.assertIn("JavaScript", result["missing_skills"])
        self.assertTrue(any(
            resource.get("skill", "").lower() == "javascript"
            for resource in result["recommended_resources"]
        ))

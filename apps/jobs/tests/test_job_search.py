"""The job search contract: what comes back, what stays out, and in what order.

Each test here is one rule the search page promises. The rules that matter
most are the negative ones - a search that returns a Graphic Designer for
"Python" is worse than one that returns nothing.
"""

import os

from django.test import TestCase
from rest_framework.test import APIClient

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from apps.accounts.models import User
from apps.jobs.models import JobPosting, SavedJob
from apps.jobs.search import search_jobs
from apps.shared.constants import ROLE_JOB_SEEKER, ROLE_RECRUITER


class JobSearchTestCase(TestCase):
    """Shared board of jobs, plus helpers that read like the search box."""

    @classmethod
    def setUpTestData(cls):
        cls.recruiter = User.objects.create_user(
            username="recruiter", email="recruiter@example.com",
            password="pw", role=ROLE_RECRUITER,
        )
        cls.seeker = User.objects.create_user(
            username="seeker", email="seeker@example.com",
            password="pw", role=ROLE_JOB_SEEKER,
        )
        cls.jobs = {}
        for spec in cls.board():
            cls.jobs[spec["title"]] = cls.make(**spec)

    @classmethod
    def board(cls):
        return [
            # ── Python family ──
            dict(title="Python Developer", skills=["Python", "Django", "PostgreSQL"],
                 category="Software Engineering", experience=2, work_mode="remote",
                 description="Build Python services for our platform."),
            dict(title="Senior Python Engineer", skills=["Python", "Flask"],
                 category="Software Engineering", experience=5, work_mode="hybrid",
                 description="Own our Python codebase end to end."),
            dict(title="Backend Python Developer", skills=["Python", "FastAPI"],
                 category="Software Engineering", experience=3, work_mode="remote",
                 description="Backend work in Python."),
            dict(title="Django Developer", skills=["Django", "Python", "REST"],
                 category="Software Engineering", experience=2, work_mode="onsite",
                 description="Django and DRF for a growing product team."),
            dict(title="Software Engineer", skills=["Go", "Kubernetes"],
                 category="Software Engineering", experience=4, work_mode="onsite",
                 description="Generalist role; some Python scripting helps."),
            # ── React family ──
            dict(title="React Developer", skills=["React", "TypeScript"],
                 category="Frontend", experience=2, work_mode="remote",
                 description="Ship React interfaces."),
            dict(title="Frontend Developer", skills=["React", "CSS"],
                 category="Frontend", experience=1, work_mode="hybrid",
                 description="Frontend work with React."),
            dict(title="Full Stack Developer", skills=["React", "Node.js"],
                 category="Software Engineering", experience=3, work_mode="remote",
                 description="Both ends of a React and Node stack."),
            # ── ML family ──
            dict(title="ML Engineer", skills=["PyTorch", "MLOps"],
                 category="Machine Learning", experience=3, work_mode="remote",
                 description="Train and serve models."),
            dict(title="AI Engineer", skills=["Python", "Machine Learning"],
                 category="Artificial Intelligence", experience=4, work_mode="remote",
                 description="Applied AI work."),
            dict(title="Data Scientist", skills=["Machine Learning", "Statistics"],
                 category="Data", experience=3, work_mode="hybrid",
                 description="Machine learning on product data."),
            dict(title="Computer Vision Engineer", skills=["Machine Learning", "OpenCV"],
                 category="Machine Learning", experience=5, work_mode="onsite",
                 description="Vision models in production."),
            # ── Should never answer a technical search ──
            dict(title="Graphic Designer", skills=["Figma", "Illustrator"],
                 category="Design", experience=2, work_mode="onsite",
                 description="Brand and marketing collateral."),
            dict(title="HR Manager", skills=["Recruiting", "Onboarding"],
                 category="Human Resources", experience=6, work_mode="onsite",
                 description="Own hiring and people operations."),
            dict(title="Nurse", skills=["Patient Care"], category="Healthcare",
                 experience=1, work_mode="onsite",
                 description="Ward nursing on rotating shifts."),
            dict(title="Accountant", skills=["Excel", "Ledgers"], category="Finance",
                 experience=3, work_mode="onsite",
                 description="Month end close and reporting."),
            dict(title="Java Developer", skills=["Java", "Spring"],
                 category="Software Engineering", experience=4, work_mode="onsite",
                 description="Enterprise Java services."),
            dict(title="Marketing Manager", skills=["SEO", "Campaigns"],
                 category="Marketing", experience=5, work_mode="hybrid",
                 description="Own the growth funnel."),
            dict(title="UI Designer", skills=["Figma"], category="Design",
                 experience=2, work_mode="remote", description="Interface design work."),
            # ── Traps for substring matching ──
            dict(title="Retail Assistant", skills=["Merchandising"], category="Retail",
                 experience=0, work_mode="onsite",
                 description="Shop floor and stock. Training provided."),
            dict(title="Flutter Developer", skills=["Flutter", "Dart"],
                 category="Mobile", experience=2, work_mode="remote",
                 description="Cross platform apps in Flutter."),
        ]

    @classmethod
    def make(cls, title, skills, category, experience, work_mode, description,
             company="Acme", location="Kathmandu"):
        return JobPosting.objects.create(
            recruiter=cls.recruiter, title=title, company=company, location=location,
            work_mode=work_mode, description=description, required_skills=skills,
            experience_required=experience, job_category=category, is_active=True,
        )

    # ── helpers ──
    def titles(self, **kwargs):
        base = JobPosting.objects.filter(is_active=True)
        modes = [value for value, _ in JobPosting.WORK_MODE_CHOICES]
        return [job.title for job in search_jobs(base, work_modes=modes, **kwargs)]


class SearchRelevanceTests(JobSearchTestCase):
    def test_python_returns_the_python_family_only(self):
        titles = self.titles(role="Python")
        self.assertIn("Python Developer", titles)
        self.assertIn("Senior Python Engineer", titles)
        self.assertIn("Backend Python Developer", titles)
        self.assertIn("Django Developer", titles)
        for unrelated in ("Graphic Designer", "HR Manager", "Nurse", "Accountant"):
            self.assertNotIn(unrelated, titles)

    def test_python_ranks_the_titled_roles_first(self):
        titles = self.titles(role="Python")
        self.assertEqual(titles[0], "Python Developer")
        self.assertLess(titles.index("Senior Python Engineer"), titles.index("Django Developer"))
        self.assertLess(titles.index("Backend Python Developer"), titles.index("Django Developer"))
        self.assertLess(titles.index("Django Developer"), titles.index("Software Engineer"))

    def test_react_returns_the_react_family_only(self):
        titles = self.titles(role="React")
        self.assertIn("React Developer", titles)
        self.assertIn("Frontend Developer", titles)
        self.assertIn("Full Stack Developer", titles)
        self.assertNotIn("Java Developer", titles)
        self.assertNotIn("Accountant", titles)

    def test_machine_learning_reaches_ml_engineer_through_the_synonym(self):
        titles = self.titles(role="Machine Learning")
        for expected in ("ML Engineer", "AI Engineer", "Data Scientist", "Computer Vision Engineer"):
            self.assertIn(expected, titles)
        for unrelated in ("Marketing Manager", "Accountant", "UI Designer"):
            self.assertNotIn(unrelated, titles)

    def test_flutter_returns_only_flutter(self):
        self.assertEqual(self.titles(role="Flutter"), ["Flutter Developer"])

    def test_unrelated_search_returns_nothing_rather_than_something(self):
        self.assertEqual(self.titles(role="Welding"), [])
        self.assertEqual(self.titles(skill="Welding"), [])

    def test_search_covers_company_category_and_location(self):
        self.make(title="Site Lead", skills=["Ops"], category="Operations",
                  experience=1, work_mode="onsite", description="Run the site.",
                  company="Zeppelin Robotics", location="Pokhara")
        self.assertIn("Site Lead", self.titles(role="Zeppelin"))
        self.assertIn("Site Lead", self.titles(role="Pokhara"))
        self.assertIn("Site Lead", self.titles(role="Operations"))


class PartialAndCaseTests(JobSearchTestCase):
    def test_partial_prefixes_find_the_full_word(self):
        self.assertIn("Python Developer", self.titles(role="pyth"))
        self.assertIn("React Developer", self.titles(role="react"))
        self.assertIn("Computer Vision Engineer", self.titles(role="mach"))

    def test_case_is_irrelevant(self):
        lower = self.titles(role="python")
        upper = self.titles(role="PYTHON")
        title = self.titles(role="Python")
        self.assertEqual(lower, upper)
        self.assertEqual(lower, title)

    def test_a_mid_word_coincidence_is_not_a_match(self):
        # "ai" lives inside "Retail" and "Training", but the Retail Assistant
        # is not an AI job.
        titles = self.titles(role="AI")
        self.assertIn("AI Engineer", titles)
        self.assertNotIn("Retail Assistant", titles)

    def test_react_finds_react_despite_the_synonym_map(self):
        # The old normalise() rewrote "react" to "reactjs" and then matched
        # nothing, because no title contains "reactjs".
        self.assertIn("React Developer", self.titles(role="react"))


class FilterTests(JobSearchTestCase):
    def test_experience_is_a_ceiling(self):
        jobs = search_jobs(JobPosting.objects.filter(is_active=True), experience="3")
        for job in jobs:
            self.assertLessEqual(job.experience_required, 3)
        titles = [job.title for job in jobs]
        self.assertIn("Backend Python Developer", titles)   # exactly 3
        self.assertIn("Retail Assistant", titles)           # 0
        self.assertNotIn("Senior Python Engineer", titles)  # 5
        self.assertNotIn("HR Manager", titles)              # 6

    def test_work_mode_is_exact(self):
        jobs = search_jobs(
            JobPosting.objects.filter(is_active=True), work_mode="remote",
            work_modes=[value for value, _ in JobPosting.WORK_MODE_CHOICES],
        )
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(job.work_mode, "remote")

    def test_more_matched_skills_ranks_higher(self):
        titles = self.titles(skill="Python Django REST")
        self.assertEqual(titles[0], "Django Developer")     # all three
        self.assertIn("Python Developer", titles)           # two
        self.assertLess(titles.index("Django Developer"), titles.index("Senior Python Engineer"))

    def test_skills_match_individually(self):
        titles = self.titles(skill="Python Django REST")
        self.assertIn("Senior Python Engineer", titles)     # Python only
        self.assertNotIn("Graphic Designer", titles)

    def test_filters_compose_with_and(self):
        titles = self.titles(
            role="Backend Developer", experience="3", work_mode="remote",
            skill="Python Django PostgreSQL",
        )
        self.assertIn("Backend Python Developer", titles)
        for job in JobPosting.objects.filter(title__in=titles):
            self.assertLessEqual(job.experience_required, 3)
            self.assertEqual(job.work_mode, "remote")
        self.assertNotIn("Django Developer", titles)        # onsite
        self.assertNotIn("Senior Python Engineer", titles)  # 5 years, hybrid

    def test_a_skill_filter_narrows_rather_than_widens(self):
        # The old query OR-ed the two boxes, so adding a skill could only
        # ever return more jobs.
        role_only = set(self.titles(role="Developer"))
        with_skill = set(self.titles(role="Developer", skill="Flutter"))
        self.assertTrue(with_skill.issubset(role_only))
        self.assertEqual(with_skill, {"Flutter Developer"})

    def test_no_query_browses_newest_first(self):
        jobs = list(search_jobs(JobPosting.objects.filter(is_active=True)))
        self.assertEqual(len(jobs), JobPosting.objects.filter(is_active=True).count())
        stamps = [job.created_at for job in jobs]
        self.assertEqual(stamps, sorted(stamps, reverse=True))

    def test_garbage_experience_is_ignored_not_fatal(self):
        titles = self.titles(role="Python", experience="not-a-number")
        self.assertIn("Python Developer", titles)

    def test_inactive_jobs_never_surface(self):
        self.jobs["Python Developer"].is_active = False
        self.jobs["Python Developer"].save(update_fields=["is_active"])
        self.assertNotIn("Python Developer", self.titles(role="Python"))


class FilterEndpointTests(JobSearchTestCase):
    """The API contract the jobs page depends on, unchanged."""

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.seeker)

    def test_endpoint_returns_a_ranked_list_with_the_same_shape(self):
        res = self.client.get("/api/jobs/filter/", {"role": "Python"})
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.data, list)
        self.assertEqual(res.data[0]["title"], "Python Developer")
        for key in ("id", "title", "company", "company_logo", "location", "work_mode",
                    "description", "required_skills", "experience_required",
                    "salary_range", "job_category", "is_saved", "created_at"):
            self.assertIn(key, res.data[0])

    def test_title_parameter_still_works(self):
        res = self.client.get("/api/jobs/filter/", {"title": "Python"})
        self.assertEqual(res.data[0]["title"], "Python Developer")

    def test_no_match_returns_an_empty_list(self):
        res = self.client.get("/api/jobs/filter/", {"role": "Welding"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])

    def test_is_saved_is_still_correct_when_batched(self):
        SavedJob.objects.create(user=self.seeker, job=self.jobs["Python Developer"])
        res = self.client.get("/api/jobs/filter/", {"role": "Python"})
        by_title = {row["title"]: row["is_saved"] for row in res.data}
        self.assertTrue(by_title["Python Developer"])
        self.assertFalse(by_title["Django Developer"])

    def test_the_list_does_not_scale_its_query_count_with_results(self):
        with self.assertNumQueries(2):   # the jobs, plus one for every bookmark
            self.client.get("/api/jobs/filter/", {"role": "Developer"})

    def test_saved_and_recent_endpoints_are_untouched(self):
        SavedJob.objects.create(user=self.seeker, job=self.jobs["Python Developer"])
        saved = self.client.get("/api/jobs/saved/")
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.data[0]["job"]["title"], "Python Developer")
        self.assertTrue(saved.data[0]["job"]["is_saved"])

        self.client.post(f"/api/jobs/viewed/{self.jobs['Django Developer'].id}/")
        recent = self.client.get("/api/jobs/recent/")
        self.assertEqual(recent.status_code, 200)
        self.assertEqual(recent.data[0]["job"]["title"], "Django Developer")

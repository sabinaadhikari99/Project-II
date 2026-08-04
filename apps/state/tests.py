# file path: apps/state/tests.py
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.shared.fingerprint import profile_resume_fingerprint, resume_fingerprint
from apps.state.models import AnalysisSession, QuizSession, UIState
from apps.state.services import (
    AnalysisSessionService,
    QuizSessionService,
    StateKeyError,
    UIStateService,
)

User = get_user_model()

RESUME = "Senior Python engineer. 6 years experience building Django APIs. " * 5


def make_seeker(email="seeker@example.com", resume=RESUME):
    user = User.objects.create_user(
        username=email, email=email, password="pw-12345", role="job_seeker",
    )
    UserProfile.objects.create(user=user, resume_text=resume, skills=["Python", "Django"])
    user.refresh_from_db()
    return user


class StateServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()

    def test_analysis_session_survives_and_reports_currency(self):
        fingerprint = profile_resume_fingerprint(self.user)
        AnalysisSessionService.save(
            self.user,
            {"profession": "Backend Developer", "resume_score": 82, "skills_extracted": ["Python"]},
            resume_fingerprint=fingerprint,
            cv_filename="cv.pdf",
        )

        restored = AnalysisSessionService.restore(self.user)
        self.assertTrue(restored["has_analysis"])
        self.assertTrue(restored["is_current"])
        self.assertEqual(restored["analysis"]["profession"], "Backend Developer")
        self.assertEqual(restored["cv_filename"], "cv.pdf")

    def test_restore_reports_the_cv_on_record(self):
        """The page cannot read the file input after a reload, so the CV that
        produced the analysis has to come back from the server."""
        session = AnalysisSessionService.save(
            self.user, {"profession": "Backend Developer"},
            resume_fingerprint=profile_resume_fingerprint(self.user),
            cv_filename="Sabina_Adhikari_cv (6).pdf",
        )

        cv = AnalysisSessionService.restore(self.user)["cv"]
        self.assertEqual(cv["id"], session.pk)
        self.assertEqual(cv["filename"], "Sabina_Adhikari_cv (6).pdf")
        self.assertEqual(cv["uploaded_at"], session.updated_at.isoformat())

    def test_uploading_again_replaces_the_cv_on_record(self):
        AnalysisSessionService.save(
            self.user, {}, resume_fingerprint="a", cv_filename="old.pdf",
        )
        AnalysisSessionService.save(
            self.user, {}, resume_fingerprint="b", cv_filename="new.pdf",
        )
        self.assertEqual(AnalysisSessionService.restore(self.user)["cv"]["filename"], "new.pdf")

    def test_no_cv_reported_before_the_first_upload(self):
        self.assertIsNone(AnalysisSessionService.restore(self.user)["cv"])
        self.assertIsNone(AnalysisSessionService.summary(self.user)["cv"])

    def test_analysis_flagged_stale_when_cv_replaced(self):
        AnalysisSessionService.save(
            self.user, {"profession": "Backend Developer"},
            resume_fingerprint=resume_fingerprint("an older cv"),
        )
        self.assertFalse(AnalysisSessionService.restore(self.user)["is_current"])

    def test_new_analysis_replaces_the_previous_one(self):
        AnalysisSessionService.save(self.user, {"profession": "A"}, resume_fingerprint="a")
        AnalysisSessionService.save(self.user, {"profession": "B"}, resume_fingerprint="b")

        self.assertEqual(AnalysisSession.objects.filter(user=self.user).count(), 1)
        self.assertEqual(AnalysisSessionService.restore(self.user)["analysis"]["profession"], "B")

    def test_ui_state_round_trip_and_revision(self):
        UIStateService.set(self.user, "jobs.filters", {"role": "django"})
        UIStateService.set(self.user, "jobs.filters", {"role": "python"})

        row = UIStateService.get(self.user, "jobs.filters")
        self.assertEqual(row["value"], {"role": "python"})
        self.assertEqual(row["revision"], 2)
        self.assertEqual(UIState.objects.filter(user=self.user).count(), 1)

    def test_ui_state_rejects_unknown_keys(self):
        with self.assertRaises(StateKeyError):
            UIStateService.set(self.user, "arbitrary.key", {"x": 1})

    def test_ui_state_is_isolated_per_user(self):
        other = make_seeker("other@example.com")
        UIStateService.set(self.user, "jobs.filters", {"role": "django"})
        self.assertEqual(UIStateService.all(other), {})

    def test_quiz_session_resumes_and_completes(self):
        fingerprint = profile_resume_fingerprint(self.user)
        questions = [
            {"id": 1, "question": "Q1", "options": ["a", "b"], "answer": "a"},
            {"id": 2, "question": "Q2", "options": ["c", "d"], "answer": "d"},
        ]
        QuizSessionService.start(self.user, questions, fingerprint)
        QuizSessionService.save_answers(self.user, {"1": "a"})

        resumed = QuizSessionService.restore(self.user, fingerprint)
        self.assertEqual(resumed["answers"], {"1": "a"})
        self.assertNotIn("answer", resumed["questions"][0])

        QuizSessionService.complete(self.user, {"1": "a", "2": "c"}, 1, 2, 50.0, [])
        completed = QuizSessionService.restore(self.user, fingerprint)
        self.assertTrue(completed["completed"])
        self.assertEqual(completed["score"], 1)

    def test_quiz_session_discarded_when_cv_changes(self):
        QuizSessionService.start(self.user, [{"id": 1, "question": "Q", "options": [], "answer": "a"}], "old-cv")
        self.assertIsNone(QuizSessionService.restore(self.user, "new-cv"))

    def test_quiz_reset_clears_stored_work(self):
        QuizSessionService.start(self.user, [{"id": 1, "question": "Q", "options": [], "answer": "a"}], "cv")
        QuizSessionService.reset(self.user)
        self.assertFalse(QuizSession.objects.filter(user=self.user).exists())


class StateAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_bootstrap_reports_empty_state_for_a_new_user(self):
        response = self.client.get("/api/state/bootstrap/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["analysis"]["has_analysis"])
        self.assertTrue(response.data["has_resume"])

    def test_ui_state_endpoints(self):
        put = self.client.put(
            "/api/state/ui/jobs.filters/", {"value": {"role": "django"}}, format="json",
        )
        self.assertEqual(put.status_code, 200)

        got = self.client.get("/api/state/ui/jobs.filters/")
        self.assertTrue(got.data["found"])
        self.assertEqual(got.data["value"], {"role": "django"})

        bulk = self.client.post(
            "/api/state/ui/",
            {"items": {"chat.draft": "hello", "notifications.view": {"filter": "unread"}}},
            format="json",
        )
        self.assertEqual(bulk.status_code, 200)
        self.assertEqual(len(self.client.get("/api/state/ui/").data["items"]), 3)

        self.assertEqual(self.client.delete("/api/state/ui/jobs.filters/").status_code, 204)
        self.assertFalse(self.client.get("/api/state/ui/jobs.filters/").data["found"])

    def test_ui_state_requires_authentication(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get("/api/state/ui/").status_code, 401)

    def test_ai_match_get_replays_the_stored_analysis(self):
        empty = self.client.get("/api/jobs/ai-match/")
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.data["has_analysis"])

        AnalysisSessionService.save(
            self.user, {"profession": "Backend Developer", "resume_score": 77},
            resume_fingerprint=profile_resume_fingerprint(self.user),
            cv_filename="cv.pdf",
        )

        restored = self.client.get("/api/jobs/ai-match/")
        self.assertTrue(restored.data["has_analysis"])
        self.assertEqual(restored.data["analysis"]["resume_score"], 77)
        self.assertTrue(restored.data["is_current"])
        self.assertEqual(restored.data["cv"]["filename"], "cv.pdf")
        self.assertIn("uploaded_at", restored.data["cv"])


class QuizPersistenceAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.questions = [
            {"id": 1, "question": "Q1", "options": ["a", "b"], "answer": "a"},
            {"id": 2, "question": "Q2", "options": ["c", "d"], "answer": "d"},
        ]

    @patch("apps.quiz.views.generate_quiz_from_resume")
    def test_quiz_is_generated_once_and_then_resumed(self, generate):
        generate.return_value = self.questions

        first = self.client.get("/api/quiz/")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(first.data["questions"]), 2)
        self.assertFalse(first.data["restored"])

        self.client.post("/api/quiz/progress/", {"answers": {"1": "a"}}, format="json")

        second = self.client.get("/api/quiz/")
        self.assertTrue(second.data["restored"])
        self.assertEqual(second.data["answers"], {"1": "a"})
        # The AI was called for the first load only.
        self.assertEqual(generate.call_count, 1)

    @patch("apps.quiz.views.generate_quiz_from_resume")
    def test_submitted_quiz_is_restored_with_its_result(self, generate):
        generate.return_value = self.questions
        self.client.get("/api/quiz/")

        submitted = self.client.post(
            "/api/quiz/submit/", {"answers": {"1": "a", "2": "c"}}, format="json",
        )
        self.assertEqual(submitted.data["score"], 1)

        restored = self.client.get("/api/quiz/")
        self.assertTrue(restored.data["completed"])
        self.assertEqual(restored.data["score"], 1)
        self.assertEqual(restored.data["percentage"], 50.0)

    @patch("apps.quiz.views.generate_quiz_from_resume")
    def test_reset_generates_a_fresh_quiz(self, generate):
        generate.return_value = self.questions
        self.client.get("/api/quiz/")
        self.client.post("/api/quiz/reset/")

        # The cached questions are reused, but a new session replaces the old one.
        again = self.client.get("/api/quiz/")
        self.assertFalse(again.data["restored"])
        self.assertEqual(again.data["answers"], {})

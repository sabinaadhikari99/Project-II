# file path: apps/chatbot/test_interview.py
"""Tests for Interview Practice.

The feature's whole point is that it is *not* a static question list, so the
tests that matter most are the ones proving personalisation survives:

* different target roles produce different questions - including when Gemini is
  unavailable, which is when the old implementation degraded to one list;
* readiness, evaluation and report scores are computed from the user's real
  data and stay consistent;
* a session is reused rather than regenerated, so returning to the page is free.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.chatbot.gemini import build_model
from apps.chatbot.interview import (
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    InterviewReadiness,
    InterviewService,
    _compose_bank,
    _heuristic_evaluation,
    _parse_json,
    build_report,
    categories_for,
    clamp_duration,
    clamp_question_count,
    evaluate_answer,
    generate_bank,
)
from apps.chatbot.models import InterviewReport, InterviewSession, InterviewTurn
from apps.chatbot.role_profiles import (
    BEHAVIORAL,
    HR,
    SCENARIO,
    SYSTEM_DESIGN,
    TECHNICAL,
    available_categories,
    match_profile,
)
from apps.chatbot.tests import SKILL_GAP, AnalysisPatchMixin, make_recruiter, save_analysis
from apps.shared.fingerprint import profile_resume_fingerprint

User = get_user_model()

RESUME = "Flutter developer with 4 years building cross-platform apps. " * 5

#: A CV analysis rich enough to exercise every readiness component.
RICH_PAYLOAD = {
    "profession": "Mobile Developer",
    "specialization": "Flutter Developer",
    "resume_score": 78,
    "skills_extracted": ["Flutter", "Dart", "Firebase"],
    "resume_quality": {"score": 72, "breakdown": [], "recommendations": []},
    "cv_signals": {
        "experience_years": 4.0,
        "project_count": 3,
        "certification_count": 1,
        "achievement_count": 4,
        "has_leadership": True,
        "has_internship": True,
        "github_links": ["https://github.com/example"],
        "portfolio_links": [],
    },
    "matched_jobs": [
        {
            "job": {"id": 1, "title": "Senior Flutter Developer", "company": "Acme"},
            "match_percentage": 89,
            "matched_skills": ["Flutter", "Dart"],
            "missing_skills": ["Kotlin"],
        },
    ],
}

GAP_WITH_COVERAGE = dict(SKILL_GAP, coverage={"current_skill_coverage": 65,
                                              "missing_skill_coverage": 35})


def make_seeker(email="interviewee@example.com", resume=RESUME):
    user = User.objects.create_user(
        username=email, email=email, password="pw-12345", role="job_seeker",
    )
    UserProfile.objects.create(user=user, resume_text=resume, skills=["Flutter", "Dart"])
    user.refresh_from_db()
    return user


CONTEXT = {
    "cv": {"uploaded": True, "skills": ["Flutter", "Dart"],
           "specialization": "Flutter Developer", "signals": {}},
    "skill_gap": {"missing_skills": ["Kotlin"], "experience_years": 4, "skills": ["Flutter"]},
    "match": {"recommended_jobs": []},
}


# ---------------------------------------------------------------------------
# Role targeting - the defect this feature exists to fix
# ---------------------------------------------------------------------------
class RoleProfileTests(SimpleTestCase):
    def test_roles_match_their_profile(self):
        cases = {
            "Flutter Developer": "flutter",
            "Python/Django Developer": "django",
            "Senior Backend Engineer (Django)": "django",
            "Data Analyst": "data_analyst",
            "Graphic Designer": "graphic_designer",
            "React Frontend Developer": "frontend",
            "Machine Learning Engineer": "data_science",
            "DevOps Engineer": "devops",
            "QA Automation Engineer": "qa",
            "UX Designer": "ui_ux",
        }
        for role, expected in cases.items():
            with self.subTest(role=role):
                self.assertEqual(match_profile(role).key, expected)

    def test_an_unknown_role_falls_back_to_generic(self):
        self.assertEqual(match_profile("Underwater Basket Weaver").key, "generic")
        self.assertEqual(match_profile("").key, "generic")

    def test_specialization_is_used_when_no_role_is_typed(self):
        self.assertEqual(match_profile("", "Flutter Developer").key, "flutter")

    def test_system_design_is_only_offered_where_it_applies(self):
        self.assertIn(SYSTEM_DESIGN, available_categories(match_profile("Django Developer")))
        self.assertNotIn(SYSTEM_DESIGN, available_categories(match_profile("Graphic Designer")))
        self.assertNotIn(SYSTEM_DESIGN, available_categories(match_profile("QA Engineer")))


class FallbackBankTests(SimpleTestCase):
    """Without Gemini the bank must still be role-specific - the old failure."""

    def bank(self, role, count=12):
        profile = match_profile(role)
        return _compose_bank(role, profile, CONTEXT, "mixed", available_categories(profile), count)

    def test_each_role_gets_its_own_technical_questions(self):
        expected = {
            "Flutter Developer": "widget",
            "Python/Django Developer": "Django ORM",
            "Data Analyst": "SQL joins",
            "Graphic Designer": "design process",
        }
        for role, marker in expected.items():
            with self.subTest(role=role):
                technical = " ".join(
                    q["question"] for q in self.bank(role) if q["category"] == TECHNICAL
                )
                self.assertIn(marker.lower(), technical.lower())

    def test_two_roles_do_not_share_their_role_written_questions(self):
        """Only the CV-derived questions may repeat across roles.

        "Walk me through a project where you used Flutter" comes from the
        candidate's own CV, so it is the same whatever role they target. Every
        question drawn from the role profile must differ.
        """
        def role_written(role):
            return {
                q["question"] for q in self.bank(role)
                if q["category"] == TECHNICAL and not q["question"].startswith("Walk me through a project")
            }

        for left, right in (("Flutter Developer", "Data Analyst"),
                            ("Graphic Designer", "Django Developer")):
            with self.subTest(pair=(left, right)):
                self.assertTrue(role_written(left))
                self.assertTrue(role_written(right))
                self.assertEqual(role_written(left) & role_written(right), set())

    def test_the_bank_opens_with_a_role_specific_question(self):
        """Personal CV questions must not front-load every role identically."""
        for role in ("Flutter Developer", "Data Analyst", "Graphic Designer"):
            with self.subTest(role=role):
                self.assertEqual(self.bank(role)[0]["category"], TECHNICAL)

        openers = {self.bank(role)[0]["question"]
                   for role in ("Flutter Developer", "Data Analyst", "Graphic Designer")}
        self.assertEqual(len(openers), 3)

    def test_a_designer_is_never_asked_a_system_design_question(self):
        categories = {q["category"] for q in self.bank("Graphic Designer")}
        self.assertNotIn(SYSTEM_DESIGN, categories)

    def test_the_bank_spans_categories_and_difficulties(self):
        bank = self.bank("Flutter Developer")
        self.assertGreaterEqual(len({q["category"] for q in bank}), 4)
        self.assertGreaterEqual(len({q["difficulty"] for q in bank}), 2)

    def test_questions_are_personalised_from_the_users_own_cv(self):
        joined = " ".join(q["question"] for q in self.bank("Flutter Developer"))
        self.assertIn("Flutter", joined)   # a skill they have
        self.assertIn("Kotlin", joined)    # a gap they must address

    def test_the_requested_count_is_respected(self):
        self.assertEqual(len(self.bank("Flutter Developer", count=6)), 6)

    def test_restricting_difficulty_restricts_the_bank(self):
        profile = match_profile("Flutter Developer")
        bank = _compose_bank("Flutter Developer", profile, CONTEXT, "beginner",
                             available_categories(profile), 8)
        role_written = [q for q in bank if q["skill"] != "experience depth"]
        self.assertTrue(role_written)

    def test_regenerating_varies_the_questions(self):
        profile = match_profile("Flutter Developer")
        categories = available_categories(profile)
        first = _compose_bank("Flutter Developer", profile, CONTEXT, "mixed", categories, 8, offset=0)
        second = _compose_bank("Flutter Developer", profile, CONTEXT, "mixed", categories, 8, offset=1)
        self.assertNotEqual([q["question"] for q in first], [q["question"] for q in second])


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
class ReadinessTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)

    def test_no_cv_reports_no_score_rather_than_a_made_up_one(self):
        no_cv = make_seeker("nocv@example.com", resume="")
        readiness = InterviewReadiness.compute(no_cv)

        self.assertFalse(readiness["has_cv"])
        self.assertEqual(readiness["overall"], 0)
        self.assertIn("AI Job Match", readiness["note"])

    def test_readiness_is_computed_from_the_users_data(self):
        save_analysis(self.user, RICH_PAYLOAD)
        readiness = InterviewReadiness.compute(self.user)

        self.assertTrue(readiness["has_cv"])
        for key in ("overall", "technical", "behavioral", "communication", "confidence"):
            self.assertGreater(readiness[key], 0, key)
            self.assertLessEqual(readiness[key], 100, key)
        self.assertIn(readiness["band"], ("Early", "Building", "Solid", "Strong"))

    def test_every_component_is_reported_so_the_score_is_explainable(self):
        save_analysis(self.user, RICH_PAYLOAD)
        labels = {c["label"] for c in InterviewReadiness.compute(self.user)["components"]}

        self.assertEqual(labels, {
            "Skill coverage", "AI match score", "CV quality", "Experience",
            "Projects", "Certifications", "Quiz performance", "Open skill gaps",
        })

    def test_a_stronger_profile_scores_higher(self):
        save_analysis(self.user, RICH_PAYLOAD)
        strong = InterviewReadiness.compute(self.user)["overall"]

        weak_payload = dict(RICH_PAYLOAD, resume_score=20,
                            resume_quality={"score": 20},
                            cv_signals={"experience_years": 0.5, "project_count": 0,
                                        "certification_count": 0, "achievement_count": 0})
        other = make_seeker("weak@example.com")
        save_analysis(other, weak_payload)
        with patch("apps.skillgap.services.analyze_skill_gap",
                   return_value=dict(GAP_WITH_COVERAGE,
                                     coverage={"current_skill_coverage": 20})):
            weak = InterviewReadiness.compute(other)["overall"]

        self.assertGreater(strong, weak)

    def test_practice_scores_drive_the_confidence_component(self):
        save_analysis(self.user, RICH_PAYLOAD)
        unpractised = InterviewReadiness.compute(self.user)
        practised = InterviewReadiness.compute(self.user, practice_scores=[90, 88, 92])

        self.assertFalse(unpractised["practiced"])
        self.assertTrue(practised["practiced"])
        self.assertGreater(practised["confidence"], unpractised["confidence"])

    def test_bands_are_labelled(self):
        self.assertEqual(InterviewReadiness.band(85), "Strong")
        self.assertEqual(InterviewReadiness.band(65), "Solid")
        self.assertEqual(InterviewReadiness.band(45), "Building")
        self.assertEqual(InterviewReadiness.band(10), "Early")


# ---------------------------------------------------------------------------
# Answer evaluation
# ---------------------------------------------------------------------------
QUESTION = {
    "question": "Explain the Flutter widget lifecycle.",
    "category": TECHNICAL,
    "difficulty": "intermediate",
    "expected_points": ["initState is called once", "build runs on every rebuild",
                        "dispose releases resources"],
}


@override_settings(GEMINI_API_KEY="")
class HeuristicEvaluationTests(SimpleTestCase):
    def test_an_empty_answer_scores_zero_and_says_why(self):
        result = _heuristic_evaluation(QUESTION, "")
        self.assertEqual(result["score"], 0)
        self.assertTrue(result["weaknesses"])

    def test_a_one_word_answer_is_not_credited(self):
        self.assertLessEqual(_heuristic_evaluation(QUESTION, "Widgets.")["score"], 10)

    def test_covering_the_expected_points_scores_higher(self):
        weak = _heuristic_evaluation(QUESTION, "It is about widgets and how they work in the app. " * 4)
        strong = _heuristic_evaluation(QUESTION, (
            "The situation is that initState is called once when the element is mounted, "
            "so I put one-off setup there. The build method runs on every rebuild, which is "
            "why it must stay cheap. As a result I moved expensive work out and cut rebuild "
            "time by 40 percent. Finally dispose releases resources such as controllers and "
            "stream subscriptions, which prevented a memory leak we had."
        ))
        self.assertGreater(strong["score"], weak["score"])
        self.assertTrue(strong["strengths"])

    def test_missing_points_are_named_so_the_user_can_improve(self):
        result = _heuristic_evaluation(QUESTION, "The build method runs on every rebuild. " * 5)
        self.assertTrue(any("Did not address" in w for w in result["weaknesses"]))

    def test_a_short_answer_never_reaches_the_model(self):
        """An empty answer has one honest grade - no point paying for a call."""
        with patch("apps.chatbot.interview._call_model") as call:
            evaluation, ai = evaluate_answer(QUESTION, "no idea", "Flutter Developer")
        call.assert_not_called()
        self.assertFalse(ai)
        self.assertLessEqual(evaluation["score"], 10)


@override_settings(GEMINI_API_KEY="test-key")
class ModelEvaluationTests(SimpleTestCase):
    ANSWER = ("I use initState for one-off setup, keep build cheap because it runs on every "
              "rebuild, and release controllers in dispose to avoid leaks.")

    @patch("apps.chatbot.interview._call_model")
    def test_a_model_grade_is_used_when_available(self, call):
        call.return_value = ('{"score": 84, "strengths": ["Covered the full lifecycle"], '
                             '"weaknesses": ["No example"], "better_answer": "In my last app..."}')
        evaluation, ai = evaluate_answer(QUESTION, self.ANSWER, "Flutter Developer")

        self.assertTrue(ai)
        self.assertEqual(evaluation["score"], 84)
        self.assertEqual(evaluation["strengths"], ["Covered the full lifecycle"])
        self.assertEqual(evaluation["better_answer"], "In my last app...")

    @patch("apps.chatbot.interview._call_model", return_value=None)
    def test_an_outage_falls_back_to_the_heuristic_grade(self, _call):
        evaluation, ai = evaluate_answer(QUESTION, self.ANSWER, "Flutter Developer")
        self.assertFalse(ai)
        self.assertGreater(evaluation["score"], 0)

    @patch("apps.chatbot.interview._call_model", return_value="not json at all")
    def test_unparseable_output_falls_back_too(self, _call):
        _evaluation, ai = evaluate_answer(QUESTION, self.ANSWER, "Flutter Developer")
        self.assertFalse(ai)

    @patch("apps.chatbot.interview._call_model")
    def test_an_out_of_range_score_is_clamped(self, call):
        call.return_value = '{"score": 480, "strengths": [], "weaknesses": []}'
        evaluation, _ai = evaluate_answer(QUESTION, self.ANSWER, "Flutter Developer")
        self.assertEqual(evaluation["score"], 100)


class GeminiModelBuildTests(SimpleTestCase):
    """Guards the bug that silently disabled every AI path.

    `google-generativeai` is pinned at 0.3.2, whose `GenerativeModel` has no
    `system_instruction` parameter. Passing it raised TypeError inside a broad
    `except Exception`, so the assistant reported "model unavailable" and fell
    back to templated answers on every single request.
    """

    def setUp(self):
        import apps.chatbot.gemini as gemini_module
        gemini_module._SUPPORTS_SYSTEM_INSTRUCTION = None
        self.addCleanup(setattr, gemini_module, "_SUPPORTS_SYSTEM_INSTRUCTION", None)

    def test_the_pinned_library_really_lacks_system_instruction(self):
        """If this fails the pin moved - build_model will then pass it through."""
        import google.generativeai as genai

        self.assertNotIn("system_instruction",
                         inspect.signature(genai.GenerativeModel.__init__).parameters)

    def test_an_old_library_gets_the_instruction_prepended(self):
        class OldModel:
            def __init__(self, model_name=None, generation_config=None):
                self.model_name = model_name

        genai = SimpleNamespace(GenerativeModel=OldModel)
        model, prefix = build_model(genai, "gemini-2.5-flash", {}, system_instruction="BE GROUNDED")

        self.assertIsInstance(model, OldModel)
        self.assertEqual(prefix, "BE GROUNDED\n\n")

    def test_a_newer_library_receives_the_parameter(self):
        captured = {}

        class NewModel:
            def __init__(self, model_name=None, generation_config=None, system_instruction=None):
                captured["system_instruction"] = system_instruction

        genai = SimpleNamespace(GenerativeModel=NewModel)
        _model, prefix = build_model(genai, "gemini-2.5-flash", {}, system_instruction="BE GROUNDED")

        self.assertEqual(prefix, "")
        self.assertEqual(captured["system_instruction"], "BE GROUNDED")

    def test_no_system_instruction_means_no_prefix(self):
        class OldModel:
            def __init__(self, model_name=None, generation_config=None):
                pass

        _model, prefix = build_model(SimpleNamespace(GenerativeModel=OldModel), "m", {})
        self.assertEqual(prefix, "")


class JsonParsingTests(SimpleTestCase):
    def test_fenced_json_is_parsed(self):
        self.assertEqual(_parse_json('```json\n{"score": 5}\n```'), {"score": 5})

    def test_json_wrapped_in_prose_is_recovered(self):
        self.assertEqual(_parse_json('Sure! {"score": 5} Hope that helps.'), {"score": 5})

    def test_unparseable_input_returns_none(self):
        self.assertIsNone(_parse_json("no json here"))
        self.assertIsNone(_parse_json(None))


# ---------------------------------------------------------------------------
# Generation, sessions and the report
# ---------------------------------------------------------------------------
@override_settings(GEMINI_API_KEY="")
class GenerationTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)

    def test_without_a_key_a_role_specific_bank_is_still_produced(self):
        payload, ai = generate_bank(self.user, "Data Analyst")

        self.assertFalse(ai)
        self.assertTrue(payload["questions"])
        self.assertIn("SQL", " ".join(q["question"] for q in payload["questions"]))
        self.assertEqual(payload["profile_key"], "data_analyst")

    def test_tips_and_an_improvement_plan_come_with_the_bank(self):
        payload, _ai = generate_bank(self.user, "Flutter Developer")

        self.assertTrue(payload["tips"])
        self.assertIn("Kotlin", " ".join(payload["tips"]))
        plan = payload["improvement"]
        self.assertEqual(plan["skills_to_improve"], ["Kotlin", "CI/CD"])
        self.assertTrue(plan["recommended_projects"])
        self.assertTrue(plan["certifications"])

    def test_the_readiness_snapshot_is_stored_with_the_bank(self):
        payload, _ai = generate_bank(self.user, "Flutter Developer")
        self.assertTrue(payload["readiness"]["has_cv"])


@override_settings(GEMINI_API_KEY="test-key")
class ModelGenerationTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)

    MODEL_JSON = """{
      "questions": [
        {"question": "Explain Flutter's rendering pipeline.", "category": "technical",
         "difficulty": "advanced", "skill": "Flutter", "why_asked": "You list Flutter.",
         "expected_points": ["build", "layout", "paint"]},
        {"question": "Tell me about a conflict.", "category": "behavioral",
         "difficulty": "intermediate", "skill": "teamwork", "why_asked": "Standard round.",
         "expected_points": ["situation", "action"]}
      ],
      "tips": ["Practise Kotlin before interviewing."],
      "improvement": {"skills_to_improve": ["Kotlin"], "recommended_projects": ["Ship an app"],
                      "portfolio": ["Add GitHub"], "certifications": ["AAD"],
                      "learning_priorities": ["Kotlin"]}
    }"""

    @patch("apps.chatbot.interview._call_model")
    def test_the_model_bank_is_used_when_available(self, call):
        call.return_value = self.MODEL_JSON
        payload, ai = generate_bank(self.user, "Flutter Developer")

        self.assertTrue(ai)
        self.assertEqual(len(payload["questions"]), 2)
        self.assertEqual(payload["questions"][0]["question"], "Explain Flutter's rendering pipeline.")
        self.assertEqual(payload["tips"], ["Practise Kotlin before interviewing."])

    @patch("apps.chatbot.interview._call_model")
    def test_one_call_produces_questions_tips_and_plan(self, call):
        """The no-duplicate-AI-calls rule: a session costs one round trip."""
        call.return_value = self.MODEL_JSON
        generate_bank(self.user, "Flutter Developer")
        self.assertEqual(call.call_count, 1)

    @patch("apps.chatbot.interview._call_model")
    def test_an_invalid_category_from_the_model_is_corrected(self, call):
        call.return_value = ('{"questions": [{"question": "Q?", "category": "astrology", '
                             '"difficulty": "wizard", "expected_points": []}], "tips": []}')
        payload, _ai = generate_bank(self.user, "Flutter Developer")

        self.assertEqual(payload["questions"][0]["category"], TECHNICAL)
        self.assertEqual(payload["questions"][0]["difficulty"], "intermediate")

    @patch("apps.chatbot.interview._call_model")
    def test_a_system_design_question_is_dropped_for_roles_without_one(self, call):
        call.return_value = ('{"questions": [{"question": "Design a CDN.", '
                             '"category": "system_design", "difficulty": "advanced", '
                             '"expected_points": []}], "tips": []}')
        payload, _ai = generate_bank(self.user, "Graphic Designer")
        self.assertEqual(payload["questions"][0]["category"], TECHNICAL)

    @patch("apps.chatbot.interview._call_model", return_value="garbage")
    def test_unusable_model_output_falls_back_to_the_role_bank(self, _call):
        payload, ai = generate_bank(self.user, "Data Analyst")
        self.assertFalse(ai)
        self.assertIn("SQL", " ".join(q["question"] for q in payload["questions"]))


@override_settings(GEMINI_API_KEY="")
class SessionLifecycleTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)

    def test_a_session_is_created_and_then_reused(self):
        first, generated = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        self.assertTrue(generated)

        second, regenerated = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        self.assertFalse(regenerated)
        self.assertEqual(first.id, second.id)

    def test_changing_the_target_role_regenerates(self):
        first, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        second, regenerated = InterviewService.get_or_create_session(self.user, "Data Analyst")

        self.assertTrue(regenerated)
        self.assertNotEqual(first.id, second.id)
        self.assertEqual(second.target_role, "Data Analyst")

        # The new bank is about the new role, not the old one. Asserted on
        # topic vocabulary rather than one exact question, because a regenerate
        # deliberately rotates which questions are picked.
        text = " ".join(q["question"] for q in second.questions).lower()
        self.assertTrue(any(word in text for word in ("sql", "dataset", "dashboard", "data")))
        self.assertNotIn("widget", text)

    def test_a_new_cv_regenerates(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        self.user.profile.resume_text = "A completely different CV about data analysis."
        self.user.profile.save()

        _fresh, regenerated = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        self.assertTrue(regenerated)

    def test_force_new_regenerates_and_archives_the_old_session(self):
        first, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        second, regenerated = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", force_new=True,
        )

        self.assertTrue(regenerated)
        self.assertNotEqual(first.id, second.id)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertEqual(InterviewSession.objects.filter(user=self.user).count(), 2)

    def test_the_role_defaults_to_the_analysed_specialization(self):
        session, _ = InterviewService.get_or_create_session(self.user, "")
        self.assertEqual(session.target_role, "Flutter Developer")

    def test_answering_records_a_graded_turn_and_advances(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        turn = InterviewService.submit_answer(session, "The situation was a slow list. " * 12)

        session.refresh_from_db()
        self.assertIsNotNone(turn)
        self.assertEqual(session.current_index, 1)
        self.assertEqual(session.status, InterviewSession.STATUS_IN_PROGRESS)
        self.assertGreater(turn.score, 0)

    def test_answering_the_same_question_twice_replaces_the_turn(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        InterviewService.submit_answer(session, "First attempt. " * 10, question_index=0)
        InterviewService.submit_answer(session, "Second attempt, much better. " * 10, question_index=0)

        self.assertEqual(InterviewTurn.objects.filter(session=session).count(), 1)

    def test_answering_a_question_that_does_not_exist_is_rejected(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        self.assertIsNone(InterviewService.submit_answer(session, "hello", question_index=999))

    def test_completing_writes_a_report_and_closes_the_session(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        InterviewService.submit_answer(session, "The situation was a slow list. " * 12, question_index=0)
        InterviewService.submit_answer(session, "I disagreed with a teammate and we measured it. " * 8,
                                       question_index=1)

        report = InterviewService.complete(session)
        session.refresh_from_db()

        self.assertEqual(session.status, InterviewSession.STATUS_COMPLETED)
        self.assertIsNotNone(session.completed_at)
        self.assertGreater(report.overall_score, 0)
        self.assertTrue(report.improvement_plan)
        self.assertEqual(report.missing_skills, ["Kotlin", "CI/CD"])

    def test_resetting_clears_answers_but_keeps_the_questions(self):
        session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        questions = list(session.questions)
        InterviewService.submit_answer(session, "An answer. " * 12, question_index=0)
        InterviewService.complete(session)

        InterviewService.reset(session)
        session.refresh_from_db()

        self.assertEqual(session.questions, questions)
        self.assertEqual(session.current_index, 0)
        self.assertEqual(session.status, InterviewSession.STATUS_READY)
        self.assertEqual(session.turns.count(), 0)
        self.assertFalse(InterviewReport.objects.filter(session=session).exists())

    def test_history_is_kept_across_sessions(self):
        InterviewService.get_or_create_session(self.user, "Flutter Developer")
        InterviewService.get_or_create_session(self.user, "Data Analyst")

        history = list(InterviewService.history(self.user))
        self.assertEqual(len(history), 2)
        self.assertEqual({s.target_role for s in history}, {"Flutter Developer", "Data Analyst"})

    def test_sessions_are_isolated_per_user(self):
        InterviewService.get_or_create_session(self.user, "Flutter Developer")
        other = make_seeker("other@example.com")
        self.assertIsNone(InterviewService.active(other))


@override_settings(GEMINI_API_KEY="")
class ReportScoringTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)
        self.session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")

    def turn(self, category, score, index):
        return InterviewTurn.objects.create(
            session=self.session, question_index=index, question="Q?",
            category=category, difficulty="intermediate", answer="An answer.",
            score=score, strengths=["Clear"], weaknesses=["Vague"],
        )

    def test_scores_are_split_by_category(self):
        turns = [self.turn(TECHNICAL, 80, 0), self.turn(TECHNICAL, 60, 1),
                 self.turn(HR, 90, 2), self.turn(BEHAVIORAL, 50, 3)]
        fields, _ai = build_report(self.session, turns, {"skill_gap": GAP_WITH_COVERAGE})

        self.assertEqual(fields["technical_score"], 70)
        self.assertEqual(fields["hr_score"], 90)
        self.assertEqual(fields["communication_score"], 50)
        self.assertEqual(fields["overall_score"], 70)

    def test_unanswered_questions_do_not_drag_the_score_down(self):
        turns = [self.turn(TECHNICAL, 80, 0)]
        turns.append(InterviewTurn.objects.create(
            session=self.session, question_index=1, question="Q?", category=TECHNICAL,
            difficulty="intermediate", answer="", score=0,
        ))
        fields, _ai = build_report(self.session, turns, {})
        self.assertEqual(fields["overall_score"], 80)

    def test_consistent_answers_read_as_more_confident(self):
        even = [self.turn(TECHNICAL, 70, 0), self.turn(TECHNICAL, 72, 1), self.turn(HR, 71, 2)]
        even_fields, _ = build_report(self.session, even, {})

        self.session.turns.all().delete()
        swingy = [self.turn(TECHNICAL, 100, 0), self.turn(TECHNICAL, 20, 1), self.turn(HR, 95, 2)]
        swingy_fields, _ = build_report(self.session, swingy, {})

        self.assertGreater(even_fields["confidence_score"], swingy_fields["confidence_score"])

    def test_courses_are_reused_rather_than_regenerated(self):
        turns = [self.turn(TECHNICAL, 70, 0)]
        courses = [{"title": "Kotlin Bootcamp", "provider": "Udacity",
                    "closes_gap": "Kotlin", "url": "https://example.com"}]
        fields, _ai = build_report(self.session, turns, {}, courses=courses)

        self.assertEqual(fields["recommended_courses"][0]["title"], "Kotlin Bootcamp")

    def test_a_deterministic_debrief_names_the_best_and_worst_answers(self):
        turns = [self.turn(TECHNICAL, 90, 0), self.turn(HR, 30, 1)]
        fields, ai = build_report(self.session, turns, {"skill_gap": GAP_WITH_COVERAGE})

        self.assertFalse(ai)
        self.assertIn("Technical", fields["strengths"][0])
        self.assertIn("HR", fields["weaknesses"][0])
        self.assertTrue(fields["improvement_plan"])

    def test_a_session_with_no_answers_still_reports(self):
        fields, ai = build_report(self.session, [], {})
        self.assertEqual(fields["overall_score"], 0)
        self.assertFalse(ai)


@override_settings(GEMINI_API_KEY="test-key")
class ReportNarrativeTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)
        # A key is set for this class, so generation would otherwise make a real
        # network call. The bank itself is not what these tests are about.
        with patch("apps.chatbot.interview._call_model", return_value=None):
            self.session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")

    @patch("apps.chatbot.interview._call_model")
    def test_the_narrative_is_ai_written_but_the_scores_are_not(self, call):
        call.return_value = ('{"strengths": ["Strong lifecycle knowledge"], '
                             '"weaknesses": ["Rambling"], "improvement_plan": ["Practise STAR"], '
                             '"next_topics": ["Kotlin"]}')
        turn = InterviewTurn.objects.create(
            session=self.session, question_index=0, question="Q?", category=TECHNICAL,
            difficulty="intermediate", answer="An answer.", score=77,
        )
        fields, ai = build_report(self.session, [turn], {})

        self.assertTrue(ai)
        self.assertEqual(fields["strengths"], ["Strong lifecycle knowledge"])
        # The model was told the numbers; it did not get to invent them.
        self.assertEqual(fields["overall_score"], 77)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@override_settings(GEMINI_API_KEY="")
class InterviewAPITests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis(gap=GAP_WITH_COVERAGE)
        save_analysis(self.user, RICH_PAYLOAD)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def start(self, role="Flutter Developer", **extra):
        return self.client.post("/api/chatbot/interview/session/",
                                {"role": role, **extra}, format="json")

    def test_get_returns_readiness_and_options_before_any_session_exists(self):
        response = self.client.get("/api/chatbot/interview/session/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["has_session"])
        self.assertTrue(response.data["readiness"]["has_cv"])
        self.assertEqual(response.data["options"]["suggested_role"], "Flutter Developer")
        self.assertTrue(response.data["options"]["categories"])

    def test_generating_returns_the_full_session(self):
        response = self.start("Data Analyst")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["generated"])
        session = response.data["session"]
        self.assertEqual(session["target_role"], "Data Analyst")
        self.assertTrue(session["questions"])
        self.assertTrue(session["tips"])
        self.assertTrue(session["improvement_plan"])
        self.assertIsNotNone(session["current_question"])

    def test_restoring_costs_no_ai_call(self):
        self.start()
        with patch("apps.chatbot.interview._call_model") as call:
            response = self.client.get("/api/chatbot/interview/session/")
        call.assert_not_called()
        self.assertTrue(response.data["has_session"])

    def test_the_current_question_hides_the_grading_rubric(self):
        response = self.start()
        current = response.data["session"]["current_question"]

        self.assertIn("question", current)
        self.assertNotIn("expected_points", current)
        # The study view still gets them.
        self.assertIn("expected_points", response.data["session"]["questions"][0])

    def test_answering_returns_an_evaluation_and_the_next_question(self):
        self.start()
        response = self.client.post(
            "/api/chatbot/interview/answer/",
            {"answer": "The situation was a slow list, so I profiled it and cut jank by 40 percent. " * 4},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("score", response.data["evaluation"])
        self.assertEqual(response.data["current_index"], 1)
        self.assertIsNotNone(response.data["next_question"])
        self.assertFalse(response.data["is_finished"])

    def test_completing_returns_the_report(self):
        self.start()
        self.client.post("/api/chatbot/interview/answer/",
                         {"answer": "A real answer with detail. " * 10}, format="json")
        response = self.client.post("/api/chatbot/interview/complete/")

        self.assertEqual(response.status_code, 200)
        report = response.data["report"]
        for key in ("overall_score", "technical_score", "hr_score",
                    "communication_score", "confidence_score", "improvement_plan"):
            self.assertIn(key, report)
        self.assertEqual(response.data["session"]["status"], "completed")

    def test_reset_clears_answers_over_the_api(self):
        self.start()
        self.client.post("/api/chatbot/interview/answer/",
                         {"answer": "An answer. " * 12}, format="json")
        response = self.client.post("/api/chatbot/interview/reset/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["session"]["current_index"], 0)
        self.assertEqual(response.data["session"]["answered"], 0)

    def test_history_lists_past_interviews(self):
        self.start("Flutter Developer")
        self.start("Data Analyst")
        response = self.client.get("/api/chatbot/interview/sessions/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["sessions"]), 2)

    def test_a_past_session_can_be_reopened(self):
        session_id = self.start().data["session"]["id"]
        response = self.client.get(f"/api/chatbot/interview/sessions/{session_id}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["session"]["id"], session_id)

    def test_another_users_session_is_not_reachable(self):
        session_id = self.start().data["session"]["id"]
        intruder = APIClient()
        intruder.force_authenticate(make_seeker("intruder@example.com"))
        self.assertEqual(
            intruder.get(f"/api/chatbot/interview/sessions/{session_id}/").status_code, 404,
        )

    def test_readiness_has_its_own_endpoint(self):
        response = self.client.get("/api/chatbot/interview/readiness/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["readiness"]["has_cv"])

    def test_an_unsupported_difficulty_is_rejected(self):
        self.assertEqual(self.start(difficulty="wizard").status_code, 400)

    def test_categories_must_be_a_list(self):
        self.assertEqual(self.start(categories="technical").status_code, 400)

    def test_answering_without_a_session_is_a_404(self):
        self.assertEqual(
            self.client.post("/api/chatbot/interview/answer/", {"answer": "hi"}, format="json").status_code,
            404,
        )

    def test_the_legacy_flat_endpoint_is_unchanged(self):
        """Existing clients must keep working - the contract did not move."""
        response = self.client.post("/api/chatbot/interview/",
                                    {"role": "flutter developer"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.data["questions"], list)
        self.assertTrue(all(isinstance(q, str) for q in response.data["questions"]))

    def test_interview_practice_is_job_seeker_only(self):
        anonymous = APIClient()
        recruiter = APIClient()
        recruiter.force_authenticate(make_recruiter())

        for client, expected in ((anonymous, 401), (recruiter, 403)):
            self.assertEqual(client.get("/api/chatbot/interview/session/").status_code, expected)
            self.assertEqual(
                client.post("/api/chatbot/interview/session/", {}, format="json").status_code, expected,
            )


@override_settings(GEMINI_API_KEY="")
class InterviewPageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()

    def test_the_page_requires_login(self):
        response = self.client.get("/interview-practice/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_the_page_renders_for_a_signed_in_user(self):
        self.client.force_login(self.user)
        response = self.client.get("/interview-practice/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Interview Practice")
        self.assertContains(response, "/api/chatbot/interview/session/")

    def test_the_page_is_three_stages_not_a_dashboard(self):
        """Setup, interview and report each own the screen while they are used."""
        self.client.force_login(self.user)
        response = self.client.get("/interview-practice/")

        for stage in ("stage-setup", "stage-interview", "stage-report"):
            self.assertContains(response, stage)

    def test_the_old_address_still_takes_you_there(self):
        """The feature moved; links already shared must not break."""
        self.client.force_login(self.user)
        response = self.client.get("/interview/")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response.url, "/interview-practice/")

    def test_interview_practice_is_reachable_from_the_sidebar(self):
        """It is its own feature now, not a panel inside the chat page."""
        self.client.force_login(self.user)
        nav = self.client.get("/chat/")

        self.assertContains(nav, 'href="/interview-practice/"')
        # The launcher form and its tips panel left with it.
        self.assertNotContains(nav, "interviewForm")
        self.assertNotContains(nav, "Quick tips")


# ---------------------------------------------------------------------------
# Interview setup - the round, the length and the clock
# ---------------------------------------------------------------------------
class SetupChoiceTests(SimpleTestCase):
    def test_a_round_maps_to_the_categories_behind_it(self):
        technical = categories_for(InterviewSession.TYPE_TECHNICAL)
        behavioral = categories_for(InterviewSession.TYPE_BEHAVIORAL)

        self.assertIn(TECHNICAL, technical)
        self.assertNotIn(BEHAVIORAL, technical)
        self.assertIn(BEHAVIORAL, behavioral)
        self.assertIn(SCENARIO, behavioral)
        self.assertNotIn(TECHNICAL, behavioral)

    def test_explicit_categories_still_win(self):
        """The finer control predates interview types and still works."""
        self.assertEqual(categories_for(InterviewSession.TYPE_TECHNICAL, [HR]), [HR])

    def test_an_unknown_round_falls_back_to_mixed(self):
        self.assertEqual(sorted(categories_for("astrology")),
                         sorted(categories_for(InterviewSession.TYPE_MIXED)))

    def test_a_question_count_is_clamped_rather_than_rejected(self):
        self.assertEqual(clamp_question_count(1), MIN_QUESTIONS)
        self.assertEqual(clamp_question_count(500), MAX_QUESTIONS)
        self.assertEqual(clamp_question_count(10), 10)
        self.assertEqual(clamp_question_count("not a number"), 8)

    def test_an_unoffered_duration_reads_as_untimed(self):
        self.assertEqual(clamp_duration(30), 30)
        self.assertEqual(clamp_duration(7), 0)
        self.assertEqual(clamp_duration(None), 0)


@override_settings(GEMINI_API_KEY="")
class SetupAppliesToTheSessionTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    def test_the_chosen_length_is_the_interview_that_is_built(self):
        session, _ = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", question_count=5,
        )
        self.assertEqual(session.question_count, 5)
        self.assertLessEqual(session.total_questions, 5)

    def test_a_behavioral_round_asks_no_technical_questions(self):
        session, _ = InterviewService.get_or_create_session(
            self.user, "Flutter Developer",
            interview_type=InterviewSession.TYPE_BEHAVIORAL,
        )
        categories = {q["category"] for q in session.questions}
        self.assertTrue(categories)
        self.assertFalse(categories & {TECHNICAL, SYSTEM_DESIGN})

    def test_changing_the_round_rebuilds_the_questions(self):
        """Otherwise picking a new setup silently hands back the old bank."""
        first, _ = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", interview_type=InterviewSession.TYPE_TECHNICAL,
        )
        second, generated = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", interview_type=InterviewSession.TYPE_BEHAVIORAL,
        )
        self.assertTrue(generated)
        self.assertNotEqual(first.id, second.id)

    def test_the_same_setup_is_still_reused(self):
        first, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")
        second, generated = InterviewService.get_or_create_session(self.user, "Flutter Developer")

        self.assertFalse(generated)
        self.assertEqual(first.id, second.id)

    def test_the_clock_changes_without_paying_for_a_rebuild(self):
        """Duration does not affect the questions, so it must not cost an AI call."""
        first, _ = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", duration_minutes=0,
        )
        second, generated = InterviewService.get_or_create_session(
            self.user, "Flutter Developer", duration_minutes=30,
        )
        self.assertFalse(generated)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.duration_minutes, 30)


@override_settings(GEMINI_API_KEY="")
class InterviewTimingTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)
        self.session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")

    def test_the_clock_starts_when_the_candidate_does(self):
        """Not when the questions were generated - that would report days."""
        self.assertIsNone(self.session.started_at)
        self.assertIsNone(self.session.elapsed_seconds)

        InterviewService.submit_answer(self.session, "A real answer with detail. " * 10)
        self.session.refresh_from_db()

        self.assertIsNotNone(self.session.started_at)
        self.assertIsNotNone(self.session.elapsed_seconds)

    def test_the_start_time_is_not_reset_by_later_answers(self):
        InterviewService.submit_answer(self.session, "A real answer with detail. " * 10)
        self.session.refresh_from_db()
        started = self.session.started_at

        InterviewService.submit_answer(self.session, "Another real answer. " * 10)
        self.session.refresh_from_db()
        self.assertEqual(self.session.started_at, started)

    def test_practising_again_is_timed_from_scratch(self):
        InterviewService.submit_answer(self.session, "A real answer with detail. " * 10)
        InterviewService.reset(self.session)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.started_at)


# ---------------------------------------------------------------------------
# The AI coach - delivery cues for the answer that was actually given
# ---------------------------------------------------------------------------
class CoachingTests(SimpleTestCase):
    QUESTION = {"question": "Tell me about a performance problem you fixed.",
                "category": TECHNICAL, "difficulty": "intermediate",
                "expected_points": ["profiling", "the measured outcome"]}

    def coach(self, answer):
        return _heuristic_evaluation(self.QUESTION, answer)["coaching"]

    def test_an_unstructured_answer_is_told_to_use_star(self):
        cues = self.coach("I fixed the list view and it got better. " * 6)
        self.assertTrue(any("STAR" in c for c in cues))

    def test_an_answer_without_numbers_is_asked_for_one(self):
        cues = self.coach("The situation was a slow list, so my action was to rewrite it. " * 5)
        self.assertTrue(any("number" in c.lower() for c in cues))

    def test_a_strong_answer_is_not_given_filler_advice(self):
        cues = self.coach(
            "The situation was a janky list. My action was to profile it, and as a result "
            "I cut frame time by 40 percent across 12000 users. " * 4
        )
        self.assertFalse(any("STAR" in c for c in cues))
        self.assertFalse(any("number" in c.lower() for c in cues))

    def test_an_empty_answer_gets_coaching_rather_than_silence(self):
        self.assertTrue(_heuristic_evaluation(self.QUESTION, "")["coaching"])

    def test_coaching_stays_short_enough_to_act_on(self):
        cues = self.coach("We did a thing.")
        self.assertLessEqual(len(cues), 3)


@override_settings(GEMINI_API_KEY="")
class CoachingIsStoredTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)
        self.session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")

    def test_coaching_is_saved_with_the_turn_it_belongs_to(self):
        turn = InterviewService.submit_answer(self.session, "We built the thing. " * 12)
        self.assertTrue(turn.coaching)

    def test_coaching_reaches_the_api(self):
        InterviewService.submit_answer(self.session, "We built the thing. " * 12)
        client = APIClient()
        client.force_authenticate(self.user)
        response = client.get("/api/chatbot/interview/session/")
        self.assertTrue(response.data["session"]["turns"][0]["coaching"])


@override_settings(GEMINI_API_KEY="")
class BehavioralScoreTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)
        self.session, _ = InterviewService.get_or_create_session(self.user, "Flutter Developer")

    def turn(self, category, score, index):
        return InterviewTurn.objects.create(
            session=self.session, question_index=index, question="Q?",
            category=category, difficulty="intermediate", answer="An answer.", score=score,
        )

    def test_the_behavioral_score_covers_every_non_technical_question(self):
        """Including HR - a candidate asking how the human side went means all of it."""
        turns = [self.turn(TECHNICAL, 90, 0), self.turn(HR, 40, 1), self.turn(BEHAVIORAL, 60, 2)]
        fields, _ai = build_report(self.session, turns, {})

        self.assertEqual(fields["technical_score"], 90)
        self.assertEqual(fields["behavioral_score"], 50)   # HR 40 and behavioral 60
        self.assertEqual(fields["communication_score"], 60)  # the story-telling round only

    def test_a_purely_technical_round_scores_no_behavioral(self):
        fields, _ai = build_report(self.session, [self.turn(TECHNICAL, 80, 0)], {})
        self.assertEqual(fields["behavioral_score"], 0)

    def test_the_score_reaches_the_report_api(self):
        self.turn(BEHAVIORAL, 70, 0)
        InterviewService.complete(self.session)

        client = APIClient()
        client.force_authenticate(self.user)
        response = client.post("/api/chatbot/interview/complete/")
        self.assertIn("behavioral_score", response.data["report"])


@override_settings(GEMINI_API_KEY="")
class ReadinessSummaryTests(AnalysisPatchMixin, TestCase):
    """Step 1 shows two lists a candidate can act on, not twelve progress bars."""

    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    def test_readiness_names_the_role_and_both_lists(self):
        readiness = InterviewService.readiness(self.user)

        self.assertEqual(readiness["target_role"], "Flutter Developer")
        self.assertIn("Flutter", readiness["strengths"])
        self.assertIn("Kotlin", readiness["focus"])

    def test_the_lists_stay_short_enough_to_read(self):
        readiness = InterviewService.readiness(self.user)
        self.assertLessEqual(len(readiness["strengths"]), 5)
        self.assertLessEqual(len(readiness["focus"]), 5)

    def test_a_user_without_a_cv_gets_empty_lists_not_invented_ones(self):
        blank = make_seeker("nocv@example.com", resume="")
        readiness = InterviewService.readiness(blank)

        self.assertFalse(readiness["has_cv"])
        self.assertEqual(readiness["strengths"], [])
        self.assertEqual(readiness["focus"], [])


@override_settings(GEMINI_API_KEY="")
class SetupAPITests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_the_setup_step_is_told_what_it_may_offer(self):
        options = self.client.get("/api/chatbot/interview/session/").data["options"]

        self.assertTrue(options["interview_types"])
        self.assertTrue(options["durations"])
        self.assertEqual(options["question_counts"]["min"], MIN_QUESTIONS)
        for entry in options["interview_types"]:
            self.assertIn(entry["value"], dict(InterviewSession.TYPE_CHOICES))

    def test_the_chosen_setup_is_stored_and_returned(self):
        response = self.client.post(
            "/api/chatbot/interview/session/",
            {"role": "Flutter Developer", "interview_type": "behavioral",
             "difficulty": "advanced", "question_count": 5, "duration_minutes": 30},
            format="json",
        )
        session = response.data["session"]

        self.assertEqual(session["interview_type"], "behavioral")
        self.assertEqual(session["difficulty"], "advanced")
        self.assertEqual(session["question_count"], 5)
        self.assertEqual(session["duration_minutes"], 30)

    def test_an_unsupported_round_is_refused(self):
        response = self.client.post(
            "/api/chatbot/interview/session/",
            {"role": "Flutter Developer", "interview_type": "astrology"}, format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_an_out_of_range_length_lands_on_the_nearest_legal_one(self):
        """A slider that 400s is worse than one that snaps."""
        response = self.client.post(
            "/api/chatbot/interview/session/",
            {"role": "Flutter Developer", "question_count": 999, "duration_minutes": 7},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["session"]["question_count"], MAX_QUESTIONS)
        self.assertEqual(response.data["session"]["duration_minutes"], 0)

    def test_history_carries_what_the_list_has_to_show(self):
        self.client.post("/api/chatbot/interview/session/",
                         {"role": "Flutter Developer", "duration_minutes": 15}, format="json")
        row = self.client.get("/api/chatbot/interview/sessions/").data["sessions"][0]

        for field in ("target_role", "difficulty", "interview_type", "total_questions",
                      "answered", "overall_score", "duration_minutes", "elapsed_seconds",
                      "updated_at"):
            self.assertIn(field, row)

# file path: apps/chatbot/tests.py
"""Tests for the AI Career Assistant.

The assistant makes three promises, and each one is covered here:

* **Grounded** - every figure in an answer comes from the user's own record, and
  data the user does not have is reported as missing rather than invented.
* **Available** - a Gemini outage costs the phrasing, not the facts; the
  deterministic composer answers from the same context.
* **Cheap** - a question only pays for the sections it needs, so asking about
  applications never triggers a roadmap generation.

The expensive analysis services are patched throughout: this suite tests the
assistant's own logic, not the pipelines it reads from.
"""

from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile
from apps.chatbot.context import CareerContextBuilder
from apps.chatbot.formatter import polish
from apps.chatbot.intents import (
    CHAT_FALLBACK_INTENT,
    DEFAULT_INTENT,
    INTENTS,
    MODE_CAREER,
    MODE_CONVERSATION,
    candidate_terms,
    is_follow_up,
    looks_conversational,
    route,
    sections_for,
)
from apps.chatbot.memory import ConversationMemory
from apps.chatbot.models import ChatMessage, Conversation
from apps.chatbot.prompts import PromptBuilder
from apps.chatbot.services import (
    MAX_CONTEXT_CHARS,
    CareerAssistant,
    _serialize_context,
    active_conversation,
    ask,
    compose_conversational_answer,
    compose_grounded_answer,
    interview_questions,
    start_new_conversation,
    starter_suggestions,
)
from apps.jobs.models import Application, JobPosting, SavedJob
from apps.shared.fingerprint import profile_resume_fingerprint
from apps.state.services import AnalysisSessionService, QuizSessionService

User = get_user_model()

RESUME = "Flutter developer with 4 years building cross-platform apps. " * 5


def intent_named(name):
    return next(intent for intent in INTENTS if intent.name == name)


ANALYSIS_PAYLOAD = {
    "profession": "Mobile Developer",
    "specialization": "Flutter Developer",
    "career_level": "mid",
    "resume_score": 78,
    "skills_extracted": ["Flutter", "Dart", "Firebase"],
    "resume_summary": "Mobile engineer focused on Flutter.",
    "score_breakdown": {
        "profession_match": 90,
        "skills_match": 64,
        "experience_match": 70,
    },
    "matched_jobs": [
        {
            "job": {
                "id": 1,
                "title": "Senior Flutter Developer",
                "company": "Acme",
                "location": "Kathmandu",
            },
            "match_percentage": 89,
            "matched_skills": ["Flutter", "Dart"],
            "missing_skills": ["Kotlin"],
        },
        {
            "job": {"id": 2, "title": "Mobile Engineer", "company": "Globex"},
            "match_percentage": 71,
            "matched_skills": ["Firebase"],
        },
    ],
}

SKILL_GAP = {
    "has_resume": True,
    "user_skills": ["Flutter", "Dart", "Firebase"],
    "missing_skills": ["Kotlin", "CI/CD"],
    "missing_skill_details": [
        {"skill": "Kotlin", "priority": "high", "importance": 0.9,
         "job_count": 3, "gap_category": "critical"},
        {"skill": "CI/CD", "priority": "medium", "importance": 0.5,
         "job_count": 1, "gap_category": "important"},
    ],
    "gap_categories": {"critical": ["Kotlin"], "important": ["CI/CD"]},
    "career_level": "mid",
    "career_level_label": "Mid-level",
    "experience_years": 4,
    "profession": "Mobile Developer",
    "specialization": "Flutter Developer",
    "match_score": 78,
}

#: The same gaps after `CareerContextBuilder` has mapped them - `job_count`
#: becomes `required_by_jobs`. Answers read this shape, not the raw service one.
MAPPED_GAP_DETAILS = [
    {"skill": "Kotlin", "priority": "high", "importance": 0.9,
     "required_by_jobs": 3, "category": "critical"},
    {"skill": "CI/CD", "priority": "medium", "importance": 0.5,
     "required_by_jobs": 1, "category": "important"},
]


def make_seeker(email="seeker@example.com", resume=RESUME):
    user = User.objects.create_user(
        username=email, email=email, password="pw-12345", role="job_seeker",
    )
    UserProfile.objects.create(user=user, resume_text=resume, skills=["Flutter", "Dart"])
    user.refresh_from_db()
    return user


def make_recruiter(email="recruiter@example.com"):
    return User.objects.create_user(
        username=email, email=email, password="pw-12345", role="recruiter",
    )


def save_analysis(user, payload=None):
    return AnalysisSessionService.save(
        user,
        payload if payload is not None else ANALYSIS_PAYLOAD,
        resume_fingerprint=profile_resume_fingerprint(user),
        cv_filename="flutter_cv.pdf",
    )


class AnalysisPatchMixin:
    """Stubs the analysis pipelines so tests exercise the assistant, not them."""

    def patch_analysis(self, gap=None, courses=None, roadmap=None):
        patchers = [
            patch("apps.skillgap.services.analyze_skill_gap",
                  return_value=gap if gap is not None else SKILL_GAP),
            patch("apps.skillgap.course_service.CourseRecommendationService.get_or_generate",
                  return_value=courses if courses is not None else {"has_resume": True, "courses": []}),
            patch("apps.skillgap.roadmap_service.LearningRoadmapService.get_or_generate",
                  return_value=roadmap if roadmap is not None else {"progress": {}, "roadmap": {}}),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# Routing - deterministic, no database, no model call
# ---------------------------------------------------------------------------
class IntentRoutingTests(SimpleTestCase):
    def test_questions_route_to_their_topic(self):
        cases = {
            "Which jobs fit my profile?": "job_fit",
            "Why is my match score only 62%?": "score_explain",
            "What should I learn first?": "skills_next",
            "Which course should I start with?": "courses",
            "How is my roadmap progressing?": "roadmap",
            "Which jobs have I applied to?": "applications",
            "Show my saved jobs": "saved_jobs",
            "Give me interview practice questions": "interview",
            "Compare my CV with the Flutter role": "compare",
            "Which companies are hiring in my industry?": "market",
            "What was my quiz score?": "quiz",
            "What side project should I build?": "portfolio",
            "How do I use SkillSync?": "platform",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(route(question).name, expected)

    def test_unrecognised_and_empty_questions_fall_back(self):
        """Routing never blocks an answer - the worst case is a broader context."""
        self.assertEqual(route("").name, DEFAULT_INTENT.name)
        self.assertEqual(route("   ").name, DEFAULT_INTENT.name)
        self.assertEqual(route("tell me a joke about penguins").name, DEFAULT_INTENT.name)

    def test_sections_are_deduplicated_with_base_first(self):
        sections = sections_for(intent_named("courses"))
        self.assertEqual(sections[:2], ("profile", "cv"))
        self.assertEqual(len(sections), len(set(sections)))
        self.assertIn("courses", sections)

    def test_a_question_only_asks_for_the_sections_it_needs(self):
        """The cost guarantee: an applications question must not pull a roadmap."""
        sections = sections_for(route("Which jobs have I applied to?"))
        self.assertIn("applications", sections)
        self.assertNotIn("roadmap", sections)
        self.assertNotIn("courses", sections)

    def test_candidate_terms_drop_filler_words(self):
        terms = candidate_terms("Compare my CV with the Flutter role at Acme")
        self.assertIn("Flutter", terms)
        self.assertIn("Acme", terms)
        for stopword in ("Compare", "role", "with"):
            self.assertNotIn(stopword, terms)

    def test_candidate_terms_are_bounded(self):
        self.assertLessEqual(len(candidate_terms(" ".join(f"term{i}" for i in range(40)))), 8)


# ---------------------------------------------------------------------------
# The availability floor - answers composed with no model involved
# ---------------------------------------------------------------------------
class GroundedAnswerTests(SimpleTestCase):
    def context(self, **overrides):
        base = {
            "cv": {"uploaded": True, "profession": "Mobile Developer",
                   "specialization": "Flutter Developer", "skills": ["Flutter", "Dart"]},
            "skill_gap": dict(SKILL_GAP, total_gaps=2, skills=SKILL_GAP["user_skills"],
                              missing_details=MAPPED_GAP_DETAILS),
            "match": {"best_score": 78,
                      "score_breakdown": ANALYSIS_PAYLOAD["score_breakdown"],
                      "recommended_jobs": [
                          {"title": "Senior Flutter Developer", "company": "Acme",
                           "match_percentage": 89, "matched_skills": ["Flutter", "Dart"]},
                      ]},
        }
        base.update(overrides)
        return base

    def test_no_cv_is_reported_as_missing_and_never_guessed(self):
        answer = compose_grounded_answer(
            intent_named("job_fit"), {"cv": {"uploaded": False}}, "What jobs fit me?",
        )
        self.assertIn("AI Job Match", answer)
        # Nothing about a profile it does not have.
        self.assertNotIn("%", answer)

    def test_job_fit_names_real_postings_with_their_percentages(self):
        answer = compose_grounded_answer(intent_named("job_fit"), self.context(), "")
        self.assertIn("Senior Flutter Developer", answer)
        self.assertIn("Acme", answer)
        self.assertIn("89%", answer)

    def test_job_fit_with_no_matches_says_so_instead_of_inventing_one(self):
        answer = compose_grounded_answer(
            intent_named("job_fit"),
            self.context(match={"best_score": 78, "recommended_jobs": []}),
            "",
        )
        self.assertIn("no matching postings", answer.lower())

    def test_score_explanation_uses_the_stored_breakdown(self):
        answer = compose_grounded_answer(intent_named("score_explain"), self.context(), "")
        self.assertIn("78%", answer)
        self.assertIn("Profession: 90%", answer)
        self.assertIn("Skills: 64%", answer)
        self.assertIn("Kotlin", answer)

    def test_skills_next_ranks_gaps_by_impact(self):
        answer = compose_grounded_answer(intent_named("skills_next"), self.context(), "")
        self.assertIn("1. Kotlin", answer)
        self.assertIn("required by 3 postings", answer)
        self.assertLess(answer.index("Kotlin"), answer.index("CI/CD"))

    def test_courses_without_recommendations_points_at_the_feature(self):
        answer = compose_grounded_answer(
            intent_named("courses"), self.context(courses={"courses": []}), "",
        )
        self.assertIn("Skill Gap Analysis", answer)

    def test_courses_are_listed_in_priority_order(self):
        answer = compose_grounded_answer(
            intent_named("courses"),
            self.context(courses={"courses": [
                {"title": "Kotlin Bootcamp", "provider": "Udacity", "closes_gap": "Kotlin",
                 "hours": 20, "expected_score_gain": 6},
            ]}),
            "",
        )
        self.assertIn("1. Kotlin Bootcamp (Udacity)", answer)
        self.assertIn("+6% match", answer)

    def test_roadmap_reports_progress_and_projection(self):
        answer = compose_grounded_answer(
            intent_named("roadmap"),
            self.context(roadmap={"has_roadmap": True, "completed": 2, "total_steps": 6,
                                  "percentage": 33, "in_progress": 1, "remaining_hours": 40,
                                  "weekly_hours": 8, "estimated_completion_date": "2026-09-30"}),
            "",
        )
        self.assertIn("2 of 6 steps", answer)
        self.assertIn("33%", answer)
        self.assertIn("2026-09-30", answer)

    def test_applications_use_exact_counts(self):
        answer = compose_grounded_answer(
            intent_named("applications"),
            self.context(applications={
                "total": 2, "by_status": {"submitted": 1, "reviewing": 1},
                "recent": [{"title": "Senior Flutter Developer", "company": "Acme",
                            "status_label": "Reviewing", "applied_on": "2026-07-01"}],
            }),
            "",
        )
        self.assertIn("applied to 2 jobs", answer)
        self.assertIn("Reviewing", answer)

    def test_no_applications_is_stated_plainly(self):
        answer = compose_grounded_answer(
            intent_named("applications"), self.context(applications={"total": 0}), "",
        )
        self.assertIn("haven't applied", answer)

    def test_untaken_quiz_is_not_given_a_score(self):
        answer = compose_grounded_answer(
            intent_named("quiz"), self.context(quiz={"taken": False}), "",
        )
        self.assertIn("haven't taken", answer)
        self.assertNotIn("%", answer)

    def test_seniority_verdict_leads_with_the_level(self):
        answer = compose_grounded_answer(intent_named("seniority"), self.context(), "")
        self.assertIn("Mid-level", answer)
        self.assertIn("4 years", answer)
        self.assertIn("Kotlin", answer)

    def test_unknown_intent_still_returns_a_factual_snapshot(self):
        answer = compose_grounded_answer(DEFAULT_INTENT, self.context(), "anything")
        self.assertIn("Flutter Developer", answer)
        self.assertIn("78%", answer)

    def test_singular_and_plural_agree(self):
        answer = compose_grounded_answer(
            intent_named("applications"),
            self.context(applications={"total": 1, "by_status": {"submitted": 1}, "recent": []}),
            "",
        )
        self.assertIn("applied to 1 job ", answer + " ")
        self.assertNotIn("1 jobs", answer)


class ContextSerializationTests(SimpleTestCase):
    def test_oversized_context_sheds_the_least_relevant_sections(self):
        context = {
            "cv": {"profession": "Mobile Developer"},
            "match": {"blob": "x" * (MAX_CONTEXT_CHARS // 2)},
            "market": {"blob": "y" * MAX_CONTEXT_CHARS},
        }
        blob = _serialize_context(context)
        self.assertLessEqual(len(blob), MAX_CONTEXT_CHARS)
        # Trimming happens from the end, so the earliest section survives.
        self.assertIn("Mobile Developer", blob)
        self.assertNotIn("market", blob)

    def test_context_within_the_budget_is_untouched(self):
        blob = _serialize_context({"cv": {"profession": "Mobile Developer"}})
        self.assertIn("Mobile Developer", blob)


# ---------------------------------------------------------------------------
# Context building - reads existing services, never recomputes
# ---------------------------------------------------------------------------
class CareerContextTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()

    def test_cv_and_match_come_from_the_stored_analysis(self):
        save_analysis(self.user)
        context = CareerContextBuilder(self.user).build(("cv", "match"))

        self.assertTrue(context["cv"]["uploaded"])
        self.assertEqual(context["cv"]["filename"], "flutter_cv.pdf")
        self.assertEqual(context["cv"]["specialization"], "Flutter Developer")
        self.assertEqual(context["match"]["best_score"], 78)
        self.assertEqual(context["match"]["recommended_jobs"][0]["title"],
                         "Senior Flutter Developer")
        self.assertEqual(context["match"]["recommended_jobs"][0]["match_percentage"], 89)

    def test_without_an_analysis_the_cv_section_says_so(self):
        cv = CareerContextBuilder(self.user).build(("cv",))["cv"]
        self.assertIn("No AI Match analysis on record", cv["note"])

    def test_unknown_section_names_are_ignored(self):
        self.assertEqual(CareerContextBuilder(self.user).build(("not_a_section",)), {})

    def test_a_section_is_computed_at_most_once_per_request(self):
        save_analysis(self.user)
        builder = CareerContextBuilder(self.user)
        with patch.object(builder, "_build_match", wraps=builder._build_match) as build:
            builder.build(("match",))
            builder.build(("match",))
            self.assertEqual(build.call_count, 1)

    def test_one_broken_source_degrades_only_its_section(self):
        """`_safe` is the reason a single outage cannot take the answer down."""
        save_analysis(self.user)
        with patch("apps.skillgap.services.analyze_skill_gap", side_effect=RuntimeError("down")):
            context = CareerContextBuilder(self.user).build(("cv", "skill_gap"))
        self.assertIn("cv", context)
        self.assertNotIn("skill_gap", context)

    def test_snapshot_summarises_who_is_asking(self):
        save_analysis(self.user)
        snapshot = CareerContextBuilder(self.user).snapshot()
        self.assertTrue(snapshot["has_cv"])
        self.assertEqual(snapshot["specialization"], "Flutter Developer")
        self.assertEqual(snapshot["match_score"], 78)
        self.assertEqual(snapshot["career_level"], "Mid-level")
        self.assertEqual(snapshot["gap_count"], 2)

    def test_applications_section_counts_by_status(self):
        recruiter = make_recruiter()
        job = JobPosting.objects.create(
            recruiter=recruiter, title="Senior Flutter Developer", company="Acme",
            description="Build apps", required_skills=["Flutter", "Kotlin"],
        )
        Application.objects.create(job=job, applicant=self.user, status="reviewing")

        applications = CareerContextBuilder(self.user).build(("applications",))["applications"]
        self.assertEqual(applications["total"], 1)
        self.assertEqual(applications["by_status"], {"reviewing": 1})
        self.assertEqual(applications["recent"][0]["company"], "Acme")

    def test_saved_jobs_section_lists_the_users_shortlist(self):
        recruiter = make_recruiter()
        job = JobPosting.objects.create(
            recruiter=recruiter, title="Mobile Engineer", company="Globex",
            description="Ship features", required_skills=["Dart"],
        )
        SavedJob.objects.create(user=self.user, job=job)

        saved = CareerContextBuilder(self.user).build(("saved_jobs",))["saved_jobs"]
        self.assertEqual(saved["total"], 1)
        self.assertEqual(saved["jobs"][0]["title"], "Mobile Engineer")

    def test_quiz_section_reports_the_stored_result(self):
        QuizSessionService.start(
            self.user, [{"id": 1, "question": "Q", "options": ["a"], "answer": "a"}], "fp",
        )
        QuizSessionService.complete(
            self.user, {"1": "b"}, score=0, total=1, percentage=0.0,
            results=[{"question": "Q", "correct": False}],
        )

        quiz = CareerContextBuilder(self.user).build(("quiz",))["quiz"]
        self.assertTrue(quiz["taken"])
        self.assertEqual(quiz["status"], "completed")
        self.assertEqual(quiz["weak_areas"], ["Q"])

    def test_market_section_aggregates_without_leaking_recruiters(self):
        recruiter = make_recruiter()
        for index in range(2):
            JobPosting.objects.create(
                recruiter=recruiter, title=f"Flutter Dev {index}", company="Acme",
                description="Build apps", required_skills=["Flutter", "Kotlin"],
                job_category="Mobile Developer",
            )
        save_analysis(self.user)

        market = CareerContextBuilder(self.user).build(("market",))["market"]
        self.assertEqual(market["total_active_jobs"], 2)
        self.assertEqual(market["jobs_in_user_field"], 2)
        self.assertEqual(market["most_demanded_skills_in_field"][0]["postings"], 2)
        self.assertNotIn("recruiter", str(market))

    def test_find_jobs_resolves_a_posting_named_in_the_question(self):
        recruiter = make_recruiter()
        JobPosting.objects.create(
            recruiter=recruiter, title="Senior Flutter Developer", company="Acme",
            description="Build apps", required_skills=["Flutter", "Kotlin"],
        )
        found = CareerContextBuilder(self.user).find_jobs(
            candidate_terms("Compare my CV with the Flutter role at Acme"),
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["skills_user_has"], ["Flutter"])
        self.assertEqual(found[0]["skills_user_lacks"], ["Kotlin"])

    def test_find_jobs_ignores_short_and_empty_terms(self):
        self.assertEqual(CareerContextBuilder(self.user).find_jobs([]), [])
        self.assertEqual(CareerContextBuilder(self.user).find_jobs(["ab"]), [])


# ---------------------------------------------------------------------------
# Answering and conversation persistence
# ---------------------------------------------------------------------------
@override_settings(GEMINI_API_KEY="")
class AssistantAnswerTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()

    def test_an_empty_question_prompts_instead_of_answering(self):
        result = CareerAssistant.answer(self.user, "   ")
        self.assertFalse(result["is_ai_generated"])
        self.assertEqual(result["context_used"], [])
        self.assertTrue(result["suggestions"])

    def test_without_a_key_the_answer_is_composed_from_the_users_data(self):
        save_analysis(self.user)
        result = CareerAssistant.answer(self.user, "Which jobs fit my profile?")

        self.assertFalse(result["is_ai_generated"])
        self.assertEqual(result["intent"], "job_fit")
        self.assertIn("Senior Flutter Developer", result["reply"])
        self.assertIn("match", result["context_used"])

    def test_context_used_records_what_grounded_the_answer(self):
        save_analysis(self.user)
        result = CareerAssistant.answer(self.user, "Which jobs have I applied to?")
        self.assertEqual(result["context_used"], sorted(result["context_used"]))
        self.assertIn("cv", result["context_used"])
        self.assertNotIn("roadmap", result["context_used"])

    def test_suggestions_are_narrowed_to_what_the_user_has(self):
        save_analysis(self.user)
        suggestions = CareerAssistant.answer(self.user, "Why is my match score 78%?")["suggestions"]
        self.assertLessEqual(len(suggestions), 4)
        self.assertEqual(len(suggestions), len(set(suggestions)))
        self.assertTrue(any("Senior Flutter Developer" in s for s in suggestions))

    def test_a_user_without_a_cv_gets_onboarding_suggestions(self):
        no_cv = make_seeker("nocv@example.com", resume="")
        suggestions = CareerAssistant.answer(no_cv, "What jobs fit me?")["suggestions"]
        self.assertIn("How do I get started?", suggestions)

    def test_a_user_without_a_cv_is_told_so_rather_than_given_a_profile(self):
        """The grounding guarantee at its sharpest: no data, no invented answer."""
        no_cv = make_seeker("nocv2@example.com", resume="")
        reply = CareerAssistant.answer(no_cv, "What jobs fit me?")["reply"]
        self.assertIn("AI Job Match", reply)
        self.assertNotIn("%", reply)

    def test_a_named_job_is_resolved_for_comparisons(self):
        recruiter = make_recruiter()
        JobPosting.objects.create(
            recruiter=recruiter, title="Senior Flutter Developer", company="Acme",
            description="Build apps", required_skills=["Flutter", "Kotlin"],
        )
        save_analysis(self.user)
        result = CareerAssistant.answer(self.user, "Compare my CV with the Flutter role at Acme")
        self.assertIn("jobs_in_question", result["context_used"])


@override_settings(GEMINI_API_KEY="test-key")
class ModelFallbackTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_a_model_answer_is_used_when_available(self, model_cls, _configure):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(
            text="You match Senior Flutter Developer at Acme at 89%.",
        )
        result = CareerAssistant.answer(self.user, "Which jobs fit my profile?")

        self.assertTrue(result["is_ai_generated"])
        self.assertIn("89%", result["reply"])

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_an_outage_costs_the_phrasing_not_the_facts(self, model_cls, _configure):
        model_cls.side_effect = RuntimeError("upstream unavailable")
        result = CareerAssistant.answer(self.user, "Which jobs fit my profile?")

        self.assertFalse(result["is_ai_generated"])
        self.assertIn("Senior Flutter Developer", result["reply"])
        self.assertIn("89%", result["reply"])

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_an_empty_model_response_falls_back_too(self, model_cls, _configure):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(text="   ")
        result = CareerAssistant.answer(self.user, "Which jobs fit my profile?")

        self.assertFalse(result["is_ai_generated"])
        self.assertIn("Senior Flutter Developer", result["reply"])

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_the_prompt_carries_the_users_data_and_the_intent_guidance(self, model_cls, _configure):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(text="ok")
        CareerAssistant.answer(self.user, "Which jobs fit my profile?")

        prompt = model_cls.return_value.generate_content.call_args[0][0]
        self.assertIn("USER DATA:", prompt)
        self.assertIn("Senior Flutter Developer", prompt)
        self.assertIn(intent_named("job_fit").guidance, prompt)
        self.assertIn("QUESTION: Which jobs fit my profile?", prompt)


@override_settings(GEMINI_API_KEY="")
class ConversationTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()

    def test_asking_records_both_sides_of_the_exchange(self):
        result = ask(self.user, "Which jobs fit my profile?")
        conversation = Conversation.objects.get(user=self.user)
        messages = list(conversation.messages.all())

        self.assertEqual(result["conversation_id"], conversation.id)
        self.assertEqual([m.role for m in messages], ["user", "assistant"])
        self.assertEqual(messages[1].content, result["reply"])
        self.assertFalse(messages[1].is_ai_generated)

    def test_the_thread_is_titled_from_the_first_question_only(self):
        ask(self.user, "Which jobs fit my profile?")
        ask(self.user, "And which skill should I learn first?")

        conversation = Conversation.objects.get(user=self.user)
        self.assertEqual(conversation.title, "Which jobs fit my profile?")
        self.assertEqual(conversation.messages.count(), 4)

    def test_one_live_thread_is_reused_across_questions(self):
        ask(self.user, "First question")
        ask(self.user, "Second question")
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 1)

    def test_starting_a_new_thread_archives_rather_than_deletes(self):
        ask(self.user, "Which jobs fit my profile?")
        fresh = start_new_conversation(self.user)

        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 2)
        self.assertEqual(Conversation.objects.filter(user=self.user, is_active=True).count(), 1)
        self.assertEqual(active_conversation(self.user).id, fresh.id)
        # The archived thread keeps its messages.
        archived = Conversation.objects.filter(user=self.user, is_active=False).first()
        self.assertEqual(archived.messages.count(), 2)

    def test_active_conversation_can_be_read_without_creating_one(self):
        self.assertIsNone(active_conversation(self.user, create=False))
        self.assertFalse(Conversation.objects.filter(user=self.user).exists())

    def test_history_is_replayed_to_the_model_oldest_first(self):
        ask(self.user, "Which jobs fit my profile?")
        conversation = active_conversation(self.user)
        history = CareerAssistant._history(conversation)

        self.assertTrue(history.startswith("User: Which jobs fit my profile?"))
        self.assertIn("Assistant:", history)

    def test_conversations_are_isolated_per_user(self):
        other = make_seeker("other@example.com")
        ask(self.user, "Which jobs fit my profile?")
        self.assertIsNone(active_conversation(other, create=False))

    def test_an_overlong_question_is_stored_truncated(self):
        ask(self.user, "x" * 6000)
        stored = ChatMessage.objects.filter(role="user").first()
        self.assertEqual(len(stored.content), 4000)


@override_settings(GEMINI_API_KEY="")
class StarterSuggestionTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()

    def test_a_user_without_a_cv_is_pointed_at_onboarding(self):
        self.patch_analysis(gap={"has_resume": False})
        prompts = starter_suggestions(self.user)
        self.assertIn("How do I get my CV analysed?", prompts)

    def test_an_analysed_user_gets_their_own_numbers_back(self):
        self.patch_analysis()
        save_analysis(self.user)
        prompts = starter_suggestions(self.user)

        self.assertEqual(len(prompts), 4)
        self.assertIn("Why is my match score 78%?", prompts)
        self.assertIn("Which skill should I learn first?", prompts)


@override_settings(GEMINI_API_KEY="")
class InterviewQuestionTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()

    def test_questions_are_generic_without_a_user(self):
        questions = interview_questions("data analyst")
        self.assertEqual(len(questions), 5)
        self.assertIn("data analyst", questions[0])

    def test_questions_are_generic_when_the_user_has_no_cv(self):
        no_cv = make_seeker("nocv@example.com", resume="")
        self.assertEqual(
            interview_questions("flutter developer", user=no_cv),
            interview_questions("flutter developer"),
        )

    def test_questions_are_drawn_from_the_users_own_profile(self):
        save_analysis(self.user)
        questions = interview_questions("flutter developer", user=self.user)

        self.assertLessEqual(len(questions), 6)
        joined = " ".join(questions)
        self.assertIn("Flutter", joined)          # a skill they have
        self.assertIn("Kotlin", joined)           # a gap they must address
        self.assertIn("Senior Flutter Developer", joined)  # their top match

    def test_a_blank_role_still_produces_questions(self):
        self.assertTrue(interview_questions(""))


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------
@override_settings(GEMINI_API_KEY="")
class ChatbotAPITests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_ask_returns_the_reply_contract(self):
        save_analysis(self.user)
        response = self.client.post(
            "/api/chatbot/", {"message": "Which jobs fit my profile?"}, format="json",
        )

        self.assertEqual(response.status_code, 200)
        for field in ("reply", "suggestions", "conversation_id", "message_id",
                      "created_at", "context_used", "is_ai_generated"):
            self.assertIn(field, response.data)
        self.assertIn("Senior Flutter Developer", response.data["reply"])

    def test_history_is_empty_before_the_first_question(self):
        response = self.client.get("/api/chatbot/history/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data["conversation_id"])
        self.assertEqual(response.data["messages"], [])
        self.assertTrue(response.data["suggestions"])

    def test_history_restores_the_thread_in_order(self):
        self.client.post("/api/chatbot/", {"message": "First question"}, format="json")
        self.client.post("/api/chatbot/", {"message": "Second question"}, format="json")

        response = self.client.get("/api/chatbot/history/")
        roles = [m["role"] for m in response.data["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])
        self.assertEqual(response.data["messages"][0]["content"], "First question")
        self.assertEqual(response.data["title"], "First question")

    def test_history_offers_the_last_replys_follow_ups(self):
        self.client.post("/api/chatbot/", {"message": "Which jobs fit my profile?"}, format="json")
        response = self.client.get("/api/chatbot/history/")
        last = response.data["messages"][-1]
        self.assertEqual(response.data["suggestions"], last["suggestions"])

    def test_new_conversation_returns_an_empty_thread(self):
        self.client.post("/api/chatbot/", {"message": "First question"}, format="json")
        response = self.client.post("/api/chatbot/new/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["messages"], [])
        self.assertEqual(self.client.get("/api/chatbot/history/").data["messages"], [])

    def test_suggestions_endpoint_returns_personalised_prompts(self):
        save_analysis(self.user)
        response = self.client.get("/api/chatbot/suggestions/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Why is my match score 78%?", response.data["suggestions"])

    def test_interview_endpoint_is_cv_aware(self):
        save_analysis(self.user)
        response = self.client.post(
            "/api/chatbot/interview/", {"role": "flutter developer"}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Flutter", " ".join(response.data["questions"]))

    def test_an_empty_message_is_answered_not_rejected(self):
        response = self.client.post("/api/chatbot/", {"message": ""}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_ai_generated"])

    def test_the_assistant_is_job_seeker_only(self):
        for client, expected in (
            (APIClient(), 401),                       # anonymous
            (self._as(make_recruiter()), 403),        # wrong role
        ):
            for url in ("/api/chatbot/", "/api/chatbot/new/"):
                self.assertEqual(client.post(url, {}, format="json").status_code, expected)
            for url in ("/api/chatbot/history/", "/api/chatbot/suggestions/"):
                self.assertEqual(client.get(url).status_code, expected)

    def test_one_users_thread_is_never_served_to_another(self):
        self.client.post("/api/chatbot/", {"message": "My private question"}, format="json")
        other = self._as(make_seeker("other@example.com"))
        self.assertEqual(other.get("/api/chatbot/history/").data["messages"], [])

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client


# ---------------------------------------------------------------------------
# Conversation mode - the assistant as something you can actually talk to
# ---------------------------------------------------------------------------
class ConversationRoutingTests(SimpleTestCase):
    def test_social_messages_are_conversation_not_data_questions(self):
        cases = {
            "Hi": "greeting",
            "hello!": "greeting",
            "Good morning": "greeting",
            "How are you?": "greeting",
            "Thanks": "gratitude",
            "thank you so much": "gratitude",
            "That helps, thanks": "gratitude",
            "ok": "small_talk",
            "Cool": "small_talk",
            "wow": "small_talk",
            "sounds good": "small_talk",
            "Goodbye": "farewell",
            "see you later": "farewell",
            "Who are you?": "identity",
            "What can you do?": "identity",
            "Can you help me?": "identity",
            "Tell me about yourself": "identity",
            "I'm nervous about interviews": "encouragement",
            "I feel stuck": "encouragement",
            "I keep getting rejected": "encouragement",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                intent = route(message)
                self.assertEqual(intent.name, expected)
                self.assertEqual(intent.mode, MODE_CONVERSATION)

    def test_a_greeting_wrapped_around_a_real_question_stays_a_question(self):
        """Social patterns are anchored, so "Hi, why is my score low?" is not a hello."""
        for message in ("Hi, why is my match score low?",
                        "Hello! Which jobs fit my profile?",
                        "Thanks - now compare my CV with the Flutter role"):
            with self.subTest(message=message):
                self.assertEqual(route(message).mode, MODE_CAREER)

    def test_asking_for_help_with_something_is_still_that_something(self):
        """"Can you help me?" is chat. "Can you help me rewrite my CV?" is work."""
        self.assertEqual(route("Can you help me?").name, "identity")
        self.assertEqual(route("Can you help me improve my CV?").name, "cv_review")

    def test_conversation_costs_no_sections(self):
        """The cost guarantee for chat: saying hello queries nothing."""
        for name in ("greeting", "gratitude", "small_talk", "farewell", "identity"):
            with self.subTest(intent=name):
                self.assertEqual(sections_for(intent_named(name)), ())

    def test_an_upset_user_gets_identity_context_and_nothing_analytical(self):
        """Enough to use their name, not enough to quote statistics back at them."""
        self.assertEqual(sections_for(intent_named("encouragement")), ("profile", "cv"))

    def test_bare_follow_ups_inherit_the_previous_topic(self):
        previous = intent_named("score_explain")
        for message in ("Why?", "Explain more", "Tell me more", "and then?", "How so"):
            with self.subTest(message=message):
                self.assertTrue(is_follow_up(message))
                self.assertEqual(route(message, previous_intent=previous).name, "score_explain")

    def test_a_follow_up_with_no_conversation_still_routes_safely(self):
        self.assertEqual(route("Why?").name, DEFAULT_INTENT.name)

    def test_a_follow_up_that_names_its_own_action_keeps_that_action(self):
        """"Compare it" is a comparison; memory supplies what "it" is."""
        intent = route("Compare it", previous_intent=intent_named("job_fit"))
        self.assertEqual(intent.name, "compare")
        self.assertTrue(intent.resolve_jobs)

    def test_short_unplaceable_remarks_are_chat_and_real_questions_are_not(self):
        self.assertTrue(looks_conversational("sounds nice"))
        self.assertTrue(looks_conversational("hmm interesting"))
        self.assertFalse(looks_conversational("tell me a joke about penguins"))
        self.assertFalse(looks_conversational("my cv"))

    def test_cover_letters_are_routed_to_their_own_intent(self):
        intent = route("Generate a cover letter for that job")
        self.assertEqual(intent.name, "cover_letter")
        self.assertTrue(intent.resolve_jobs)

    def test_requests_whose_object_lives_in_memory_still_route_by_action(self):
        """"Rewrite it" is CV work and "should I apply?" is a job decision.

        Neither names its object, so both would otherwise fall through to a
        generic answer - or, being short, be mistaken for small talk.
        """
        self.assertEqual(route("Rewrite it").name, "cv_review")
        self.assertEqual(route("Should I apply?").name, "compare")
        self.assertTrue(route("Should I apply?").resolve_jobs)


class ConversationalReplyTests(SimpleTestCase):
    """The offline floor for chat: still human, still claiming nothing."""

    def memory(self, turns=0):
        return ConversationMemory(None, {"turns": turns})

    def test_a_greeting_never_recites_the_users_record(self):
        for turn in range(4):
            with self.subTest(turn=turn):
                reply = compose_conversational_answer(
                    intent_named("greeting"), self.memory(turn),
                )
                self.assertNotIn("%", reply)
                self.assertNotIn("analysed as", reply)
                self.assertGreater(len(reply.split()), 12)

    def test_the_first_greeting_introduces_the_assistant(self):
        reply = compose_conversational_answer(intent_named("greeting"), self.memory(0))
        self.assertIn("SkillSync AI", reply)

    def test_the_same_message_is_not_answered_identically_every_time(self):
        """Repetition was the robotic tell; an outage is no excuse for it."""
        intent = intent_named("gratitude")
        replies = {compose_conversational_answer(intent, self.memory(turn)) for turn in range(3)}
        self.assertEqual(len(replies), 3)

    def test_a_name_already_retrieved_is_used_and_nothing_else_is(self):
        """`encouragement` is the one chat intent allowed to know who it is talking to."""
        reply = compose_conversational_answer(
            intent_named("encouragement"), self.memory(1), {"profile": {"name": "Sabina Pal"}},
        )
        self.assertIn("Sabina", reply)
        self.assertNotIn("Pal", reply)

    def test_distress_is_acknowledged_before_anything_is_offered(self):
        reply = compose_conversational_answer(intent_named("encouragement"), self.memory(0))
        self.assertNotIn("%", reply)
        self.assertTrue(len(reply.split()) > 20)


@override_settings(GEMINI_API_KEY="")
class ConversationModeCostTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    def test_a_greeting_reads_nothing_from_the_users_record(self):
        with patch.object(CareerContextBuilder, "build") as build:
            result = CareerAssistant.answer(self.user, "Hi")

        build.assert_not_called()
        self.assertEqual(result["context_used"], [])
        self.assertEqual(result["mode"], MODE_CONVERSATION)
        self.assertNotIn("%", result["reply"])

    def test_a_career_question_still_pays_for_its_data(self):
        result = CareerAssistant.answer(self.user, "Which jobs fit my profile?")
        self.assertEqual(result["mode"], MODE_CAREER)
        self.assertIn("match", result["context_used"])

    def test_an_unplaceable_remark_is_answered_without_a_lookup(self):
        with patch.object(CareerContextBuilder, "build") as build:
            result = CareerAssistant.answer(self.user, "sounds good then")

        build.assert_not_called()
        self.assertEqual(result["intent"], CHAT_FALLBACK_INTENT.name)


@override_settings(GEMINI_API_KEY="test-key")
class ConversationGenerationTests(AnalysisPatchMixin, TestCase):
    """A greeting is written by the model, not selected from a template."""

    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_a_greeting_is_generated_with_the_conversational_persona(self, model_cls, _cfg):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(
            text="Hi! 👋 Welcome back - what would you like to work on today?",
        )
        result = CareerAssistant.answer(self.user, "Hi")

        self.assertTrue(result["is_ai_generated"])
        self.assertIn("Welcome back", result["reply"])

        prompt = model_cls.return_value.generate_content.call_args[0][0]
        self.assertIn("THE USER JUST SAID: Hi", prompt)
        # The whole point of the mode: no record was read, so none is offered.
        self.assertNotIn("USER DATA:", prompt)
        self.assertNotIn("Senior Flutter Developer", prompt)

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_chat_and_career_reach_the_model_with_different_settings(self, model_cls, _cfg):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(text="ok")

        CareerAssistant.answer(self.user, "Thanks!")
        chat_config = model_cls.call_args.kwargs["generation_config"]
        CareerAssistant.answer(self.user, "Which jobs fit my profile?")
        career_config = model_cls.call_args.kwargs["generation_config"]

        self.assertGreater(chat_config["temperature"], career_config["temperature"])

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_the_model_is_shown_its_last_reply_so_it_does_not_repeat_it(self, model_cls, _cfg):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(
            text="Happy to help - want to look at your matches?",
        )
        ask(self.user, "Thanks")
        ask(self.user, "Thanks again")

        prompt = model_cls.return_value.generate_content.call_args[0][0]
        self.assertIn("do not repeat", prompt)
        self.assertIn("Happy to help", prompt)

    @patch("google.generativeai.configure")
    @patch("google.generativeai.GenerativeModel")
    def test_a_model_reply_is_cleaned_before_the_user_sees_it(self, model_cls, _cfg):
        model_cls.return_value.generate_content.return_value = SimpleNamespace(
            text='"As an AI language model, I can help with that."',
        )
        reply = CareerAssistant.answer(self.user, "Hi")["reply"]
        self.assertEqual(reply, "I can help with that.")


@override_settings(GEMINI_API_KEY="")
class ConversationMemoryTests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)

    def memory(self):
        return ConversationMemory.load(active_conversation(self.user))

    def test_the_job_under_discussion_is_remembered_for_the_next_turn(self):
        ask(self.user, "Which jobs fit my profile?")
        memory = self.memory()

        self.assertEqual(memory.focus_job["title"], "Senior Flutter Developer")
        self.assertEqual(memory.focus_job["company"], "Acme")
        self.assertIn("Senior Flutter Developer", memory.as_prompt_block())

    def test_memory_tells_the_model_what_it_refers_to(self):
        ask(self.user, "Which jobs fit my profile?")
        block = self.memory().as_prompt_block()
        self.assertIn('"it"', block)

    def test_what_was_established_survives_a_turn_of_small_talk(self):
        """"Thanks" must not wipe the job the next question depends on."""
        ask(self.user, "Which jobs fit my profile?")
        ask(self.user, "Thanks!")

        memory = self.memory()
        self.assertEqual(memory.focus_job["title"], "Senior Flutter Developer")
        self.assertEqual(memory.profile["specialization"], "Flutter Developer")

    def test_the_profile_is_learned_from_a_real_retrieval_only(self):
        ask(self.user, "Hi")
        self.assertEqual(self.memory().profile, {})

        ask(self.user, "Why is my match score 78%?")
        self.assertEqual(self.memory().profile["profession"], "Mobile Developer")

    def test_the_running_summary_names_the_topics_covered(self):
        ask(self.user, "Which jobs fit my profile?")
        ask(self.user, "Which skill should I learn first?")

        summary = self.memory().summary()
        self.assertIn("their job matches", summary)
        self.assertIn("which skills to learn next", summary)

    def test_a_bare_why_is_answered_about_the_previous_topic(self):
        ask(self.user, "Why is my match score 78%?")
        result = ask(self.user, "Why?")
        self.assertEqual(result["intent"], "score_explain")

    def test_a_follow_up_resolves_the_job_from_memory_not_from_the_words(self):
        recruiter = make_recruiter()
        JobPosting.objects.create(
            recruiter=recruiter, title="Senior Flutter Developer", company="Acme",
            description="Build apps", required_skills=["Flutter", "Kotlin"],
        )
        ask(self.user, "Which jobs fit my profile?")
        result = ask(self.user, "Compare it with my CV")
        self.assertIn("jobs_in_question", result["context_used"])

    def test_memory_is_persisted_with_the_transcript(self):
        ask(self.user, "Which jobs fit my profile?")
        stored = Conversation.objects.get(user=self.user).memory
        self.assertEqual(stored["last_intent"], "job_fit")
        self.assertEqual(stored["turns"], 1)

    def test_a_new_thread_starts_with_no_memory_of_the_old_one(self):
        """A closed conversation must not leak into "compare it" in the next."""
        ask(self.user, "Which jobs fit my profile?")
        start_new_conversation(self.user)
        self.assertIsNone(self.memory().focus_job)

    def test_the_routing_decision_is_recorded_on_the_message(self):
        ask(self.user, "Hi")
        ask(self.user, "Which jobs fit my profile?")
        intents = list(
            ChatMessage.objects
            .filter(role=ChatMessage.ROLE_ASSISTANT)
            .order_by("created_at", "id")
            .values_list("intent", flat=True)
        )
        self.assertEqual(intents, ["greeting", "job_fit"])


class PromptBuilderTests(SimpleTestCase):
    def memory(self, **data):
        return ConversationMemory(None, data)

    def test_a_career_prompt_carries_the_data_and_the_question(self):
        prompt = PromptBuilder(
            "Which jobs fit my profile?",
            intent_named("job_fit"),
            memory=self.memory(),
            data_block='{"match":{"best_score":78}}',
        ).build()

        self.assertIn("USER DATA:", prompt)
        self.assertIn('"best_score":78', prompt)
        self.assertIn(intent_named("job_fit").guidance, prompt)
        self.assertIn("QUESTION: Which jobs fit my profile?", prompt)

    def test_a_conversation_prompt_never_pretends_to_have_data(self):
        prompt = PromptBuilder("Hi", intent_named("greeting"), memory=self.memory()).build()

        self.assertNotIn("USER DATA:", prompt)
        self.assertIn("THE USER JUST SAID: Hi", prompt)

    def test_the_previous_reply_is_shown_so_it_is_not_repeated(self):
        prompt = PromptBuilder(
            "Thanks", intent_named("gratitude"),
            memory=self.memory(last_assistant_message="You match 3 roles."),
        ).build()
        self.assertIn("do not repeat", prompt)
        self.assertIn("You match 3 roles.", prompt)

    def test_memory_reaches_the_model_so_a_follow_up_can_resolve(self):
        memory = self.memory(focus_job={"title": "Senior Flutter Developer", "company": "Acme"})
        prompt = PromptBuilder(
            "Why?", intent_named("compare"), memory=memory, data_block="{}",
        ).build()
        self.assertIn("Senior Flutter Developer", prompt)

    def test_chat_is_allowed_to_be_creative_and_career_answers_are_not(self):
        chat = PromptBuilder("Hi", intent_named("greeting")).generation_config
        career = PromptBuilder("Why?", intent_named("job_fit")).generation_config
        self.assertGreater(chat["temperature"], career["temperature"])

    def test_each_mode_gets_its_own_system_prompt(self):
        chat = PromptBuilder("Hi", intent_named("greeting")).system_prompt
        career = PromptBuilder("Why?", intent_named("job_fit")).system_prompt
        self.assertNotEqual(chat, career)
        self.assertIn("USER DATA", career)
        self.assertNotIn("USER DATA", chat)


class ResponseFormatterTests(SimpleTestCase):
    def test_a_reply_fenced_as_code_is_unwrapped(self):
        self.assertEqual(polish("```\nHere is your summary.\n```"), "Here is your summary.")

    def test_a_reply_quoted_in_its_entirety_is_unwrapped(self):
        self.assertEqual(polish('"Nice to see you again!"'), "Nice to see you again!")

    def test_a_quotation_inside_a_reply_is_left_alone(self):
        text = 'Say "I led the migration" and stop there.'
        self.assertEqual(polish(text), text)

    def test_model_self_references_are_removed(self):
        self.assertEqual(
            polish("As an AI language model, I can help with your CV."),
            "I can help with your CV.",
        )

    def test_a_repeated_opening_sentence_is_dropped(self):
        previous = "Great question! Your best match is 78%."
        polished = polish("Great question! Here's the breakdown.", previous)
        self.assertEqual(polished, "Here's the breakdown.")

    def test_a_repeated_opening_is_kept_when_it_is_the_whole_answer(self):
        """Never delete the reply itself in the name of variety."""
        self.assertEqual(polish("Yes.", "Yes."), "Yes.")

    def test_polishing_never_loses_an_answer(self):
        self.assertEqual(polish(""), "")
        self.assertIsNone(polish(None))


@override_settings(GEMINI_API_KEY="")
class ConversationAPITests(AnalysisPatchMixin, TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_seeker()
        self.patch_analysis()
        save_analysis(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_a_greeting_is_answered_as_conversation_over_the_api(self):
        response = self.client.post("/api/chatbot/", {"message": "Hi"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], MODE_CONVERSATION)
        self.assertEqual(response.data["intent"], "greeting")
        self.assertEqual(response.data["context_used"], [])
        self.assertTrue(response.data["reply"])
        self.assertTrue(response.data["suggestions"])

    def test_the_existing_reply_contract_is_unchanged(self):
        response = self.client.post(
            "/api/chatbot/", {"message": "Which jobs fit my profile?"}, format="json",
        )
        for field in ("reply", "suggestions", "conversation_id", "message_id",
                      "created_at", "context_used", "is_ai_generated"):
            self.assertIn(field, response.data)
        self.assertEqual(response.data["mode"], MODE_CAREER)

    def test_history_replays_how_each_message_was_routed(self):
        self.client.post("/api/chatbot/", {"message": "Hello"}, format="json")
        response = self.client.get("/api/chatbot/history/")
        self.assertEqual(response.data["messages"][-1]["intent"], "greeting")

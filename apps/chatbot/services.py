# file path: apps/chatbot/services.py
"""AI Career Assistant.

A career coach that can hold a conversation and answer from the user's own
SkillSync record. Which of those two things a message needs is decided per turn,
because they pull in opposite directions:

* **Conversation** - "hi", "thanks", "I'm nervous about interviews". No data is
  fetched and none is claimed. The model is given the persona, the state of the
  exchange and the message, and writes something new. Saying hello must never
  cost a skill gap analysis, and must never turn into a recital of the user's
  numbers.
* **Career work** - "which jobs fit me?", "why was that recommended?". The
  retrieval layer gathers exactly the sections the question needs from what the
  existing services already produced, and the model is told to use nothing else.

Both paths run through the same pipeline - route, remember, retrieve, prompt,
generate, format - so there is one place to reason about behaviour:

    intents.route          which mode, which sections
    memory                 what "it", "that job" and "why?" refer to
    context                the retrieval layer (never re-runs an analysis)
    prompts.PromptBuilder  what the model actually sees
    formatter.polish       what the user actually reads

Three properties hold throughout:

* **Grounded.** In career mode the model is given the user's data and told to
  use nothing else. Missing data is reported as missing rather than filled in
  with plausible text.
* **Available.** If the model call fails, a reply is composed from the same
  context - real numbers in career mode, a natural sentence in conversation -
  so the assistant never answers with an error.
* **Cheap.** Only the sections a question needs are gathered and sent, and small
  talk gathers nothing.
"""

import json
import logging

from django.conf import settings
from django.db import transaction

from .context import CareerContextBuilder
from .formatter import polish
from .gemini import build_model
from .intents import (
    CHAT_FALLBACK_INTENT,
    DEFAULT_INTENT,
    candidate_terms,
    looks_conversational,
    route,
    sections_for,
)
from .memory import ConversationMemory
from .models import ChatMessage, Conversation
from .persona import ASSISTANT_NAME, CAREER_SYSTEM_PROMPT
from .prompts import PromptBuilder

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"

#: Turns of history replayed to the model. Enough for "and the second one?"
#: to resolve, small enough to stay fast.
HISTORY_TURNS = 8

#: Upper bound on the serialized context. Sections are dropped from the least
#: relevant end if a user's record is unusually large.
MAX_CONTEXT_CHARS = 14000

#: The career-mode system prompt. Kept under its original name because callers
#: outside this module import it; the text now lives with the rest of the
#: assistant's personality in `persona`.
SYSTEM_PROMPT = CAREER_SYSTEM_PROMPT


class CareerAssistant:
    """Answers one message, conversationally or from the user's SkillSync record."""

    @classmethod
    def answer(cls, user, message, conversation=None, memory=None):
        """Produce a reply.

        `memory` is accepted so a caller that also persists the exchange can
        write the updated state in the same transaction as the messages. When
        it is omitted the memory is loaded here and updated in place, which is
        what a direct caller wants.
        """
        question = (message or "").strip()
        if not question:
            return {
                "reply": "Ask me anything about your CV, matches, skills, courses or applications.",
                "suggestions": list(starter_suggestions(user)),
                "context_used": [],
                "is_ai_generated": False,
            }

        if memory is None:
            memory = ConversationMemory.load(conversation)

        intent = cls._route(question, memory)
        context = cls._retrieve(user, question, intent, memory)
        history = cls._history(conversation)

        reply, generated = cls._generate(question, intent, context, history, memory)
        suggestions = cls._suggestions(intent, context, memory)

        memory.record(intent=intent, question=question, reply=reply, context=context)

        return {
            "reply": reply,
            "suggestions": suggestions,
            "context_used": sorted(context.keys()),
            "is_ai_generated": generated,
            "intent": intent.name,
            "mode": intent.mode,
        }

    # -- routing ------------------------------------------------------------
    @staticmethod
    def _route(question, memory):
        """Decide what kind of message this is.

        The router resolves a bare follow-up ("why?", "explain") against the
        previous turn. What it cannot do is tell a short unmatched remark from a
        question about the user's record, so anything it could not place is
        checked once more: chat gets answered as chat instead of triggering a
        full retrieval to reply to "sounds good".
        """
        intent = route(question, previous_intent=memory.previous_intent)
        if intent.name == DEFAULT_INTENT.name and looks_conversational(question):
            return CHAT_FALLBACK_INTENT
        return intent

    # -- retrieval ----------------------------------------------------------
    @staticmethod
    def _retrieve(user, question, intent, memory):
        """Gather the sections this intent declared, and nothing else."""
        sections = sections_for(intent)
        if not sections:
            return {}

        builder = CareerContextBuilder(user)
        context = builder.build(sections)

        if intent.resolve_jobs:
            jobs = builder.find_jobs(candidate_terms(question))
            if not jobs:
                # "Compare it", "write a cover letter for that role" - the job
                # is not in the message, it is in what was said before.
                jobs = builder.find_jobs(_focus_job_terms(memory))
            if jobs:
                context["jobs_in_question"] = jobs
        return context

    # -- generation ---------------------------------------------------------
    @classmethod
    def _generate(cls, question, intent, context, history, memory):
        """Returns ``(reply, is_ai_generated)``."""
        if not getattr(settings, "GEMINI_API_KEY", ""):
            return cls._compose(intent, context, question, memory), False

        # Built after the key check: serializing the context is real work, and
        # there is no point paying for it to then answer offline.
        prompt = PromptBuilder(
            question,
            intent,
            memory=memory,
            context=context,
            data_block=("" if intent.is_conversational else _serialize_context(context)),
            history=history,
        )

        try:
            import google.generativeai as genai

            genai.configure(api_key=settings.GEMINI_API_KEY)
            # `system_instruction` is not accepted by the pinned library version;
            # `build_model` prepends it to the prompt instead. See chatbot.gemini.
            model, prefix = build_model(
                genai,
                MODEL_NAME,
                prompt.generation_config,
                system_instruction=prompt.system_prompt,
            )
            result = model.generate_content(prefix + prompt.build())
            reply = polish(getattr(result, "text", "") or "", memory.last_assistant_message)
            if reply:
                return reply, True
            logger.warning("assistant: empty model response for intent %s", intent.name)
        except Exception:
            logger.warning("assistant: model unavailable, answering from data", exc_info=True)

        return cls._compose(intent, context, question, memory), False

    @staticmethod
    def _compose(intent, context, question, memory):
        """The reply when the model is unavailable, in the right register."""
        if intent.is_conversational:
            return compose_conversational_answer(intent, memory, context)
        return compose_grounded_answer(intent, context, question)

    @staticmethod
    def _history(conversation):
        if conversation is None:
            return ""
        rows = list(
            conversation.messages.order_by("-created_at", "-id")[:HISTORY_TURNS]
        )[::-1]
        return "\n".join(
            f"{'User' if row.role == ChatMessage.ROLE_USER else 'Assistant'}: {row.content[:600]}"
            for row in rows
        )

    # -- follow-ups ---------------------------------------------------------
    @staticmethod
    def _suggestions(intent, context, memory=None):
        """Follow-ups worth asking, narrowed to what this user actually has."""
        if intent.is_conversational:
            return _conversational_suggestions(intent, memory)

        cv = context.get("cv") or {}
        if not cv.get("uploaded"):
            return [
                "How do I get started?",
                "What does the AI Match score measure?",
                "What can you help me with?",
            ]

        gap = context.get("skill_gap") or {}
        match = context.get("match") or {}
        suggestions = list(intent.follow_ups)

        top_job = (match.get("recommended_jobs") or [{}])[0]
        if top_job.get("title") and intent.name != "compare":
            suggestions.append(f"Compare my CV with the {top_job['title']} role.")

        first_gap = (gap.get("missing_skills") or [None])[0]
        if first_gap and intent.name not in ("skills_next", "courses"):
            suggestions.append(f"How do I learn {first_gap}?")

        return _unique(suggestions)[:4]


def _focus_job_terms(memory):
    """Search terms for the job the conversation is already about."""
    job = memory.focus_job if memory else None
    if not job:
        return []
    return [part for part in (job.get("title"), job.get("company")) if part]


def _unique(items):
    seen, unique = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            unique.append(item)
    return unique


def _conversational_suggestions(intent, memory):
    """Openers for a chat turn - no database, so they come from memory."""
    suggestions = list(intent.follow_ups)
    if memory is not None:
        job = memory.focus_job
        if job and job.get("title"):
            suggestions.insert(0, f"Why was {job['title']} recommended to me?")
        for skill in memory.missing_skills[:1]:
            suggestions.append(f"How do I learn {skill}?")
    return _unique(suggestions)[:4]


# ---------------------------------------------------------------------------
# Deterministic answers - used when the model is unavailable
# ---------------------------------------------------------------------------
def _pct(value):
    return f"{int(value)}%" if isinstance(value, (int, float)) else "n/a"


def _listing(items, limit=4):
    items = [str(i) for i in (items or []) if i][:limit]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


#: Offline conversation. Several phrasings per intent, rotated by turn number:
#: a fixed sentence repeated every time is the robotic feel this assistant is
#: built to avoid, and an outage is no excuse for it. These are deliberately
#: free of any claim about the user, because nothing was fetched.
_CONVERSATION_REPLIES = {
    "greeting": (
        "Hi{name}! 👋 I'm {assistant}, your career assistant. I can find jobs that fit your CV, "
        "explain your match scores, show you which skills to close, and get you ready for "
        "interviews. What would you like to work on?",
        "Hello{name}! Good to see you. We could look at your job matches, sharpen your CV, work "
        "through your skill gaps, or run some interview practice - where would you like to start?",
        "Hey{name}! I'm here whenever you're ready. Tell me what's on your mind - your matches, "
        "your CV, your next skill, or interview prep.",
    ),
    "gratitude": (
        "You're welcome! If you'd like to keep going, we can look at your job matches, tighten "
        "your CV, or run through some interview questions.",
        "Anytime - glad that was useful. Want to pick up your skill gaps next, or look at what "
        "to apply for?",
        "Happy to help. Say the word whenever you want to dig into a role or rework part of "
        "your CV.",
    ),
    "small_talk": (
        "Got it. What would you like to look at next - your matches, your CV, or your skill plan?",
        "Sounds good. I'm here whenever you want to dig into a role or tune your CV.",
        "Understood. Anything you'd like me to pull up from your profile?",
    ),
    "farewell": (
        "Take care{name}! Everything's saved, so we can pick up exactly where we left off. "
        "Good luck out there. 👋",
        "Goodbye for now - keep at it. Come back whenever you want another round of interview "
        "practice or a fresh look at your matches.",
        "See you soon{name}. You're making progress, even on the quiet days.",
    ),
    "identity": (
        "I'm {assistant}, your career assistant here on SkillSync. I can match you to jobs and "
        "explain why each one fits, review or rewrite your CV, show you which skills are holding "
        "you back and how to close them, build a learning roadmap, run interview practice with "
        "feedback, and draft cover letters. Where would you like to start?",
        "I'm {assistant} - think of me as a recruiter and mentor in one. Job matching, CV work, "
        "skill gaps, learning plans, interview practice, cover letters: ask for any of it and "
        "I'll work from your own profile. What do you need first?",
    ),
    "encouragement": (
        "That's a completely normal way to feel, and it usually says more about how much you "
        "care than about your ability. The fastest way through it is rehearsal - I can run "
        "practice questions for your target role and tell you exactly what to tighten. "
        "Want to try a few?",
        "I hear you{name}, and you're far from alone in that. Let's make it concrete instead of "
        "heavy: I can show you what you're already strong at, or we can pick the one gap that "
        "would move you furthest. Which would help more right now?",
        "Job hunting wears people down - that feeling isn't a verdict on you. Let's take one "
        "small step: your CV, one skill, or a practice interview. Your call.",
    ),
    "chit_chat": (
        "I'm at my best with career questions - job matches, CV feedback, skill gaps and "
        "interview prep. What can I help you with?",
        "That's a bit outside my lane, but I'm glad to talk careers: your matches, your CV, or "
        "what to learn next. Which one?",
    ),
}


def compose_conversational_answer(intent, memory=None, context=None):
    """A natural reply when the model is unavailable.

    Deliberately claims nothing about the user - a conversational turn fetched
    no data, and an outage is not a reason to start guessing.
    """
    options = _CONVERSATION_REPLIES.get(intent.name) or _CONVERSATION_REPLIES["chit_chat"]
    turn = memory.turns if memory is not None else 0
    template = options[turn % len(options)]

    first_name = ""
    profile = (context or {}).get("profile") or {}
    if profile.get("name"):
        first_name = str(profile["name"]).split()[0]

    return template.format(
        assistant=ASSISTANT_NAME,
        name=f" {first_name}" if first_name else "",
    )


def compose_grounded_answer(intent, context, question=""):
    """Answer straight from the user's data, with no model involved.

    This is the availability floor: a Gemini outage costs the phrasing, not the
    facts. Every branch below reads the same context the model would have.
    """
    cv = context.get("cv") or {}
    if not cv.get("uploaded"):
        return (
            "I don't have a CV analysis for you yet, so I can't speak about your profile "
            "specifically. Upload your CV in AI Job Match and I'll be able to explain your "
            "match score, your skill gaps and the roles that fit you."
        )

    gap = context.get("skill_gap") or {}
    match = context.get("match") or {}
    roadmap = context.get("roadmap") or {}
    courses = context.get("courses") or {}
    applications = context.get("applications") or {}
    role = cv.get("specialization") or cv.get("profession") or "your target role"

    if intent.name == "job_fit":
        jobs = match.get("recommended_jobs") or []
        if not jobs:
            return (
                f"You're analysed as a {role}, but there are no matching postings on the platform "
                "right now. Check the Jobs page later, or widen your profile by adding skills."
            )
        lines = [f"You're a {role} with a best match of {_pct(match.get('best_score'))}. Your strongest openings:"]
        for job in jobs[:5]:
            lines.append(
                f"- {job.get('title')} at {job.get('company')} — {_pct(job.get('match_percentage'))}"
                + (f" (matches {_listing(job.get('matched_skills'), 3)})" if job.get("matched_skills") else "")
            )
        return "\n".join(lines)

    if intent.name == "score_explain":
        breakdown = match.get("score_breakdown") or gap.get("match_explanation") or {}
        labels = {
            "profession_match": "Profession", "skills_match": "Skills",
            "experience_match": "Experience", "education_match": "Education",
            "project_match": "Projects", "certification_match": "Certifications",
            "semantic_similarity": "Semantic fit",
        }
        rows = [f"{label}: {_pct(breakdown[key])}" for key, label in labels.items() if key in breakdown]
        missing = _listing(gap.get("missing_skills"), 4)
        answer = [f"Your best match is {_pct(match.get('best_score') or gap.get('match_score'))}."]
        if rows:
            answer.append("It breaks down as " + "; ".join(rows) + ".")
        if missing:
            answer.append(f"The gap is mostly {missing} — those are what the matched roles ask for and your CV doesn't show.")
        return " ".join(answer)

    if intent.name in ("skills_next", "portfolio"):
        details = gap.get("missing_details") or []
        if not details:
            return (
                f"No critical gaps are open for {role} right now — your skills line up with the "
                "postings we can see. Keep the roadmap moving and check back after new roles appear."
            )
        lines = ["Close these in this order — highest impact first:"]
        for index, info in enumerate(details[:5], start=1):
            demand = info.get("required_by_jobs") or 0
            lines.append(
                f"{index}. {info.get('skill')} ({info.get('priority')} priority"
                + (f", required by {demand} posting{'s' if demand != 1 else ''}" if demand else "")
                + ")"
            )
        return "\n".join(lines)

    if intent.name == "courses":
        rows = courses.get("courses") or []
        if not rows:
            return "No course recommendations are on file yet. Run Skill Gap Analysis and they'll be generated from your gaps."
        lines = ["Start here, in order:"]
        for index, course in enumerate(rows[:4], start=1):
            lines.append(
                f"{index}. {course.get('title')} ({course.get('provider')}) — closes {course.get('closes_gap')}, "
                f"about {course.get('hours')} hours"
                + (f", +{course.get('expected_score_gain')}% match" if course.get("expected_score_gain") else "")
            )
        return "\n".join(lines)

    if intent.name == "roadmap":
        if not roadmap.get("has_roadmap"):
            return "You don't have a learning roadmap yet. Open Skill Gap Analysis and one will be built from your CV."
        return (
            f"You've completed {roadmap.get('completed')} of {roadmap.get('total_steps')} steps "
            f"({_pct(roadmap.get('percentage'))}), with {roadmap.get('in_progress')} in progress. "
            f"About {roadmap.get('remaining_hours')} hours remain — on {roadmap.get('weekly_hours')} hours a week "
            f"that lands around {roadmap.get('estimated_completion_date')}."
        )

    if intent.name == "applications":
        total = applications.get("total", 0)
        if not total:
            return "You haven't applied to any jobs through SkillSync yet. Your recommended roles are the place to start."
        by_status = ", ".join(f"{count} {status}" for status, count in (applications.get("by_status") or {}).items())
        recent = applications.get("recent") or []
        lines = [f"You've applied to {total} job{'s' if total != 1 else ''}" + (f" — {by_status}." if by_status else ".")]
        for row in recent[:5]:
            lines.append(f"- {row.get('title')} at {row.get('company')}: {row.get('status_label')} (applied {row.get('applied_on')})")
        return "\n".join(lines)

    if intent.name == "seniority":
        level = gap.get("career_level_label") or "your current level"
        critical = len((gap.get("gap_categories") or {}).get("critical") or [])
        return (
            f"Your CV reads as {level} with {gap.get('experience_years', 0)} years of experience and a best match of "
            f"{_pct(match.get('best_score') or gap.get('match_score'))}. "
            + (f"{critical} critical gap{'s' if critical != 1 else ''} stand between you and the roles you're targeting: "
               f"{_listing((gap.get('gap_categories') or {}).get('critical'), 4)}."
               if critical else "No critical gaps are open, so you're competitive for the roles we can see.")
        )

    if intent.name == "quiz":
        quiz = context.get("quiz") or {}
        if not quiz.get("taken"):
            return "You haven't taken the skills quiz yet. It's generated from your CV — open Quiz to try it."
        return (
            f"Your last quiz: {quiz.get('score')}/{quiz.get('total')} ({_pct(quiz.get('percentage'))}), "
            f"status {quiz.get('status')}."
        )

    if intent.name == "cover_letter":
        jobs = (context.get("jobs_in_question") or []) or (match.get("recommended_jobs") or [])
        target = jobs[0] if jobs else {}
        if not target.get("title"):
            return (
                "Tell me which role the letter is for and I'll draft it from your CV. If you'd "
                "like, name one of your recommended jobs and I'll use its requirements."
            )
        strengths = _listing(target.get("matched_skills") or target.get("skills_user_has"), 3)
        return (
            f"I can draft a letter for {target.get('title')}"
            + (f" at {target.get('company')}" if target.get("company") else "")
            + (f", leading on your {strengths}." if strengths else ".")
            + " Ask me again in a moment — the writing step needs the AI service, which is "
            "unavailable right now."
        )

    # Anything else: a factual snapshot beats a generic paragraph.
    return (
        f"Here's where you stand: analysed as {role} with a best match of "
        f"{_pct(match.get('best_score') or gap.get('match_score'))}, "
        f"{len(gap.get('skills') or cv.get('skills') or [])} skills on file and "
        f"{gap.get('total_gaps', 0)} open gap(s)"
        + (f", the most important being {_listing(gap.get('missing_skills'), 3)}." if gap.get("missing_skills") else ".")
        + " Ask me about your matches, your score, your skills or your applications."
    )


def _serialize_context(context):
    """Compact JSON, trimmed from the least relevant end if oversized."""
    # Later sections are the most situational, so they are shed first.
    ordered = list(context.items())
    while ordered:
        blob = json.dumps(dict(ordered), ensure_ascii=False, separators=(",", ":"), default=str)
        if len(blob) <= MAX_CONTEXT_CHARS:
            return blob
        ordered.pop()
    return "{}"


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
def active_conversation(user, create=True):
    """The user's live thread, so the discussion survives navigation and logout."""
    conversation = Conversation.objects.filter(user=user, is_active=True).order_by("-updated_at").first()
    if conversation is None and create:
        conversation = Conversation.objects.create(user=user)
    return conversation


def start_new_conversation(user):
    """Archive the current thread and open a fresh one.

    The new thread starts with empty memory on purpose: "compare it" must not
    resolve to a job from a conversation the user deliberately closed.
    """
    Conversation.objects.filter(user=user, is_active=True).update(is_active=False)
    return Conversation.objects.create(user=user)


def ask(user, message, conversation=None):
    """Answer a question and record both sides of the exchange."""
    conversation = conversation or active_conversation(user)
    memory = ConversationMemory.load(conversation)
    result = CareerAssistant.answer(user, message, conversation, memory=memory)

    with transaction.atomic():
        ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_USER,
            content=(message or "").strip()[:4000],
        )
        assistant_message = ChatMessage.objects.create(
            conversation=conversation,
            role=ChatMessage.ROLE_ASSISTANT,
            content=result["reply"],
            context_used=result["context_used"],
            suggestions=result["suggestions"],
            is_ai_generated=result["is_ai_generated"],
            intent=result.get("intent", ""),
        )
        if not conversation.title:
            conversation.title = (message or "").strip()[:120]
        # Memory and transcript are written together, so they can never disagree.
        conversation.memory = memory.data
        conversation.save(update_fields=["title", "memory", "updated_at"])

    result["conversation_id"] = conversation.id
    result["message_id"] = assistant_message.id
    result["created_at"] = assistant_message.created_at.isoformat()
    return result


def starter_suggestions(user):
    """Opening prompts chosen from what this user actually has on record."""
    builder = CareerContextBuilder(user)
    snapshot = builder.snapshot()

    if not snapshot["has_cv"]:
        return (
            "What can you help me with?",
            "How do I get my CV analysed?",
            "What does the match score measure?",
            "Which jobs are on the platform?",
        )

    prompts = ["What jobs fit my profile?"]
    if snapshot["match_score"]:
        prompts.append(f"Why is my match score {snapshot['match_score']}%?")
    else:
        prompts.append("Why is my match score low?")
    if snapshot["gap_count"]:
        prompts.append("Which skill should I learn first?")
    else:
        prompts.append("Am I ready for senior roles?")
    prompts.append("How can I improve my CV?")
    return tuple(prompts[:4])


# ---------------------------------------------------------------------------
# Backward-compatible entry points
# ---------------------------------------------------------------------------
def career_chat(message, user=None):
    """Legacy signature. Personalised when a user is supplied."""
    if user is not None:
        return ask(user, message)["reply"]

    text = (message or "").strip()
    if not text:
        return "Please share your question or the area where you want career guidance."
    return compose_grounded_answer(DEFAULT_INTENT, {}, text)


def interview_questions(role, user=None):
    """Interview questions, drawn from the user's own profile when available."""
    role = role or "software engineer"
    if user is None:
        return _generic_interview_questions(role)

    builder = CareerContextBuilder(user)
    context = builder.build(("cv", "skill_gap", "match"))
    cv = context.get("cv") or {}
    if not cv.get("uploaded"):
        return _generic_interview_questions(role)

    gap = context.get("skill_gap") or {}
    skills = cv.get("skills") or gap.get("skills") or []
    missing = gap.get("missing_skills") or []

    questions = [
        f"Walk me through a project where you used {skills[0]}." if skills
        else f"Walk me through your most relevant {role} project.",
        f"How would you approach a {role} task that required {missing[0]}?" if missing
        else f"What makes you a strong {role} candidate?",
    ]
    if len(skills) > 1:
        questions.append(f"How do you decide between {skills[0]} and {skills[1]} on a real project?")
    top = (context.get("match") or {}).get("recommended_jobs") or []
    if top:
        questions.append(
            f"The {top[0].get('title')} role at {top[0].get('company')} needs "
            f"{_listing(top[0].get('required_skills') or top[0].get('matched_skills'), 2)}. "
            "How does your experience line up?"
        )
    questions.extend([
        "Describe a time you resolved ambiguity with data.",
        f"What are you actively improving as a {role}, and how are you measuring it?",
    ])
    return questions[:6]


def _generic_interview_questions(role):
    return [
        f"Tell me about a project that proves you are ready for a {role} role.",
        "Describe a time you resolved ambiguity with data.",
        "How do you prioritize when deadlines conflict?",
        "What technical skill are you actively improving, and how are you measuring progress?",
        "Why is this opportunity a strong fit for your career direction?",
    ]

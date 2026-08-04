# file path: apps/chatbot/interview.py
"""Interview practice: a personal interview coach built on the user's own record.

The feature used to return the same five questions to every user for every role.
It now produces a question bank, coaching tips, an improvement plan, a readiness
score, per-answer evaluation and a closing report - all personalised from data
SkillSync has already computed:

    CV + analysis     -> apps.state.services.AnalysisSessionService
    skill gap         -> apps.skillgap.services.analyze_skill_gap
    courses           -> apps.skillgap.course_service
    quiz              -> apps.state.services.QuizSessionService

All of it is read through `chatbot.context.CareerContextBuilder`, so nothing here
re-scores a CV or re-ranks a job, and every number agrees with the page it came
from.

Three properties carried over from the assistant, deliberately:

* **Grounded.** Questions, tips and evaluations reference the user's real skills,
  gaps and match score. Missing data is reported as missing.
* **Available.** Every AI call has a deterministic fallback. Without Gemini the
  user still gets a *role-specific* bank (see `role_profiles`), a real readiness
  score and a real evaluation - the phrasing degrades, the feature does not.
* **Cheap.** One AI call builds the whole session (questions + tips + plan), and
  a session is only regenerated when the target role changes, the CV changes, or
  the user explicitly asks for a new interview.
"""

import json
import logging
import re
import statistics

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.shared.fingerprint import profile_resume_fingerprint

from .context import CareerContextBuilder
from .gemini import build_model
from .models import InterviewReport, InterviewSession, InterviewTurn
from .role_profiles import (
    ADVANCED,
    BEGINNER,
    BEHAVIORAL,
    BEHAVIORAL_QUESTIONS,
    CATEGORY_LABELS,
    HR,
    HR_QUESTIONS,
    INTERMEDIATE,
    LEVELS,
    LEVEL_LABELS,
    PROBLEM_SOLVING,
    SCENARIO,
    SYSTEM_DESIGN,
    TECHNICAL,
    available_categories,
    match_profile,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "gemini-2.5-flash"

#: Questions per generated session when the candidate does not choose. Enough
#: for a realistic round without making the mock interview a chore.
QUESTION_TARGET = 8

#: What a candidate may ask for. A five-question round is a warm-up; beyond
#: fifteen nobody finishes, and the AI call gets slow enough to feel broken.
MIN_QUESTIONS = 5
MAX_QUESTIONS = 15

#: Interview lengths offered, in minutes. 0 is untimed - the clock is a pacing
#: aid, and some people practise better without one.
DURATION_CHOICES = (0, 15, 30, 45, 60)

#: Which question categories each round is made of. Selecting a round is one
#: decision; the categories behind it stay available to callers that want them.
CATEGORIES_FOR_TYPE = {
    InterviewSession.TYPE_TECHNICAL: (TECHNICAL, PROBLEM_SOLVING, SYSTEM_DESIGN),
    InterviewSession.TYPE_BEHAVIORAL: (BEHAVIORAL, SCENARIO),
    InterviewSession.TYPE_HR: (HR, BEHAVIORAL),
    InterviewSession.TYPE_MIXED: (TECHNICAL, BEHAVIORAL, HR, SCENARIO,
                                  PROBLEM_SOLVING, SYSTEM_DESIGN),
}

#: Answers shorter than this cannot demonstrate anything, and are scored as such.
MIN_USEFUL_ANSWER_CHARS = 40


def clamp_question_count(value):
    """Keep a requested question count inside what the feature can deliver."""
    try:
        return max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(value)))
    except (TypeError, ValueError):
        return QUESTION_TARGET


def clamp_duration(value):
    """Snap a requested duration to an offered one; anything odd means untimed."""
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        return 0
    return minutes if minutes in DURATION_CHOICES else 0


def categories_for(interview_type, explicit=None):
    """Categories to generate from.

    Explicit categories win - they are the more specific instruction, and the
    API accepted them before interview types existed.
    """
    if explicit:
        return list(explicit)
    return list(CATEGORIES_FOR_TYPE.get(interview_type)
                or CATEGORIES_FOR_TYPE[InterviewSession.TYPE_MIXED])


# ---------------------------------------------------------------------------
# Gemini plumbing - lazy, and never fatal
# ---------------------------------------------------------------------------
def _model_available():
    return bool(getattr(settings, "GEMINI_API_KEY", ""))


def _call_model(prompt, *, temperature=0.6, max_tokens=4096, system_instruction=None):
    """Return the model's text, or None if it is unavailable or unusable.

    Mirrors `CareerAssistant._generate`: the caller always has a deterministic
    path to fall back to, so a Gemini outage never surfaces as an error.
    """
    if not _model_available():
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model, prefix = build_model(
            genai,
            MODEL_NAME,
            {"temperature": temperature, "top_p": 0.9, "max_output_tokens": max_tokens},
            system_instruction=system_instruction,
        )
        text = (getattr(model.generate_content(prefix + prompt), "text", "") or "").strip()
        return text or None
    except Exception:
        logger.warning("interview: model unavailable, composing from data", exc_info=True)
        return None


def _parse_json(text):
    """Parse a model response that should be JSON, tolerating fences and prose."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.IGNORECASE | re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except (ValueError, TypeError):
        pass
    # Models occasionally wrap JSON in a sentence; take the outermost object.
    match = re.search(r"[\[{].*[\]}]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (ValueError, TypeError):
            pass
    logger.warning("interview: could not parse model JSON")
    return None


def _clamp(value, low=0, high=100):
    try:
        return max(low, min(high, int(round(float(value)))))
    except (TypeError, ValueError):
        return low


def _rotate(items, offset):
    """Rotate a sequence so 'Generate new interview' varies the fallback bank."""
    items = list(items or [])
    if not items:
        return []
    offset = offset % len(items)
    return items[offset:] + items[:offset]


# ---------------------------------------------------------------------------
# Readiness - deterministic, no AI call
# ---------------------------------------------------------------------------
class InterviewReadiness:
    """How ready this user is for an interview, from data already computed.

    Deliberately arithmetic rather than AI-written: a readiness percentage that
    moves when the model feels differently would be worthless for tracking
    progress. Every component below is sourced, weighted and explained, so the
    UI can show *why* a score is what it is.
    """

    #: Contribution of each component to the sub-scores. Kept here so the
    #: weighting is inspectable rather than buried in the arithmetic.
    TECHNICAL_WEIGHTS = {"skill_coverage": 0.35, "match": 0.30, "experience": 0.20, "quiz": 0.15}
    BEHAVIORAL_WEIGHTS = {"experience": 0.40, "projects": 0.35, "evidence": 0.25}
    COMMUNICATION_WEIGHTS = {"cv_quality": 0.60, "achievements": 0.40}
    OVERALL_WEIGHTS = {"technical": 0.40, "behavioral": 0.25, "communication": 0.20, "confidence": 0.15}

    @classmethod
    def compute(cls, user, builder=None, practice_scores=None):
        builder = builder or CareerContextBuilder(user)
        context = builder.build(("cv", "skill_gap", "match", "quiz"))
        cv = context.get("cv") or {}
        gap = context.get("skill_gap") or {}
        match = context.get("match") or {}
        quiz = context.get("quiz") or {}

        if not cv.get("uploaded"):
            return {
                "has_cv": False,
                "overall": 0, "technical": 0, "behavioral": 0, "communication": 0,
                "confidence": 0, "confidence_label": "Not assessed",
                "band": "Not assessed",
                "components": [], "strengths": [], "focus": [], "target_role": "",
                "note": ("No CV analysis on record. Upload your CV in AI Job Match to get a "
                         "readiness score."),
            }

        signals = cv.get("signals") or {}
        coverage = gap.get("coverage") or {}
        quality = (cv.get("quality") or {}).get("score")

        # --- raw components, each 0-100 -----------------------------------
        skill_coverage = _clamp(coverage.get("current_skill_coverage", 0))
        match_score = _clamp(match.get("best_score") or gap.get("match_score") or cv.get("match_score") or 0)
        cv_quality = _clamp(quality if quality is not None else 0)
        quiz_score = _clamp(quiz.get("percentage", 0)) if quiz.get("taken") else 0

        years = float(gap.get("experience_years") or signals.get("experience_years") or 0)
        experience = _clamp(min(years / 8.0, 1.0) * 100)          # 8+ years reads as fully ready
        projects = _clamp(min((signals.get("project_count") or 0) / 5.0, 1.0) * 100)
        certifications = _clamp(min((signals.get("certification_count") or 0) / 3.0, 1.0) * 100)
        achievements = _clamp(min((signals.get("achievement_count") or 0) / 8.0, 1.0) * 100)

        # Leadership, internships, open source and awards all evidence the kind
        # of story a behavioral round asks for.
        evidence_flags = ("has_leadership", "has_internship", "has_open_source",
                          "has_awards", "has_research", "has_publications")
        evidence = _clamp(
            sum(1 for flag in evidence_flags if signals.get(flag)) / len(evidence_flags) * 100
        )

        total_gaps = int(gap.get("total_gaps") or 0)
        gap_penalty = min(20, total_gaps * 2)      # each open gap costs, capped

        # --- sub-scores ----------------------------------------------------
        technical = _clamp(
            cls.TECHNICAL_WEIGHTS["skill_coverage"] * skill_coverage
            + cls.TECHNICAL_WEIGHTS["match"] * match_score
            + cls.TECHNICAL_WEIGHTS["experience"] * experience
            + cls.TECHNICAL_WEIGHTS["quiz"] * quiz_score
            - gap_penalty
        )
        behavioral = _clamp(
            cls.BEHAVIORAL_WEIGHTS["experience"] * experience
            + cls.BEHAVIORAL_WEIGHTS["projects"] * projects
            + cls.BEHAVIORAL_WEIGHTS["evidence"] * evidence
        )
        # CV quality is the only written-communication evidence available before
        # the user answers anything: structure, action verbs, quantified claims.
        communication = _clamp(
            cls.COMMUNICATION_WEIGHTS["cv_quality"] * cv_quality
            + cls.COMMUNICATION_WEIGHTS["achievements"] * achievements
        )

        # Confidence reflects demonstrated practice where it exists, and falls
        # back to how much of the target role the user already covers.
        practice_scores = [s for s in (practice_scores or []) if s]
        if practice_scores:
            confidence = _clamp(statistics.fmean(practice_scores))
        else:
            confidence = _clamp((skill_coverage + match_score) / 2 - gap_penalty)

        overall = _clamp(
            cls.OVERALL_WEIGHTS["technical"] * technical
            + cls.OVERALL_WEIGHTS["behavioral"] * behavioral
            + cls.OVERALL_WEIGHTS["communication"] * communication
            + cls.OVERALL_WEIGHTS["confidence"] * confidence
        )

        return {
            "has_cv": True,
            "overall": overall,
            "technical": technical,
            "behavioral": behavioral,
            "communication": communication,
            "confidence": confidence,
            "confidence_label": cls.band(confidence),
            "band": cls.band(overall),
            "practiced": bool(practice_scores),
            # The two lists a candidate actually acts on: what they can be asked
            # about and answer well, and what will catch them out. Sourced from
            # the same skill gap the Skill Gap page shows, so they agree.
            "target_role": cv.get("specialization") or cv.get("profession") or "",
            "strengths": [str(s) for s in (gap.get("skills") or cv.get("skills") or [])][:5],
            "focus": [str(s) for s in (gap.get("missing_skills") or [])][:5],
            "components": [
                {"label": "Skill coverage", "value": skill_coverage,
                 "detail": f"{skill_coverage}% of what your matched roles ask for"},
                {"label": "AI match score", "value": match_score,
                 "detail": "Best match across your recommended jobs"},
                {"label": "CV quality", "value": cv_quality,
                 "detail": "Structure, keywords and quantified achievements"},
                {"label": "Experience", "value": experience,
                 "detail": f"{years:g} year{'s' if years != 1 else ''} on record"},
                {"label": "Projects", "value": projects,
                 "detail": f"{signals.get('project_count') or 0} project(s) detected in your CV"},
                {"label": "Certifications", "value": certifications,
                 "detail": f"{signals.get('certification_count') or 0} certification(s) detected"},
                {"label": "Quiz performance", "value": quiz_score,
                 "detail": "Your last SkillSync quiz" if quiz.get("taken") else "No quiz taken yet"},
                {"label": "Open skill gaps", "value": _clamp(100 - gap_penalty * 5),
                 "detail": f"{total_gaps} gap(s) still open"},
            ],
        }

    @staticmethod
    def band(score):
        if score >= 80:
            return "Strong"
        if score >= 60:
            return "Solid"
        if score >= 40:
            return "Building"
        return "Early"


# ---------------------------------------------------------------------------
# Question bank generation
# ---------------------------------------------------------------------------
GENERATION_SYSTEM_PROMPT = """You are an expert technical interviewer and career coach preparing a candidate for a real interview.

You are given USER DATA (the candidate's analysed CV, skills, gaps and job matches) and a TARGET ROLE.

Rules:
1. Every question must be specific to the TARGET ROLE. A Flutter role gets Flutter questions; a Django role gets Django questions; a data analyst gets SQL and dashboard questions; a designer gets design-process and typography questions. Never produce generic filler that would suit any role.
2. Ground the personal questions in USER DATA - their real skills, projects, experience and missing skills. Do not invent employers, projects or credentials.
3. Spread questions across the requested categories and difficulty levels.
4. `expected_points` must list what a strong answer actually covers - it is used to grade the candidate later.
5. Tips must reference the candidate's real strengths and real gaps, not generic advice.
6. Return ONLY valid JSON matching the requested schema. No markdown, no commentary."""

GENERATION_SCHEMA = """{
  "questions": [
    {
      "question": "string - the interview question",
      "category": "one of: technical | behavioral | hr | scenario | problem_solving | system_design",
      "difficulty": "one of: beginner | intermediate | advanced",
      "skill": "the skill or topic being tested",
      "why_asked": "one sentence on why this candidate is being asked this",
      "expected_points": ["what a strong answer covers", "..."]
    }
  ],
  "tips": ["personalised preparation tip referencing their real strengths and gaps"],
  "improvement": {
    "skills_to_improve": ["skill"],
    "recommended_projects": ["a project that would prove a missing skill"],
    "portfolio": ["a concrete portfolio or CV improvement"],
    "certifications": ["a certification worth holding for this role"],
    "learning_priorities": ["what to study first, in order"]
  }
}"""


def _generation_prompt(role, profile, context, difficulty, categories, count):
    wanted = ", ".join(CATEGORY_LABELS[c] for c in categories)
    levels = (", ".join(LEVEL_LABELS[l] for l in LEVELS)
              if difficulty == InterviewSession.LEVEL_MIXED else LEVEL_LABELS.get(difficulty, difficulty))
    payload = json.dumps(context, ensure_ascii=False, separators=(",", ":"), default=str)[:12000]

    return f"""USER DATA:
{payload}

TARGET ROLE: {role}
ROLE FAMILY: {profile.label}
CORE TOPICS FOR THIS ROLE: {", ".join(profile.topics)}
SYSTEM DESIGN APPLICABLE: {"yes" if profile.system_design_applicable else "no - do not produce system design questions"}

Produce exactly {count} interview questions for this candidate.
CATEGORIES TO COVER: {wanted}
DIFFICULTY LEVELS TO COVER: {levels}

Return JSON in exactly this shape:
{GENERATION_SCHEMA}"""


def _personal_questions(context, role, offset=0):
    """Questions written from the candidate's own CV, used in the fallback bank."""
    cv = context.get("cv") or {}
    gap = context.get("skill_gap") or {}
    match = context.get("match") or {}

    skills = list(cv.get("skills") or gap.get("skills") or [])
    missing = list(gap.get("missing_skills") or [])
    jobs = match.get("recommended_jobs") or []
    questions = []

    for skill in _rotate(skills, offset)[:2]:
        questions.append({
            "question": f"Walk me through a project where you used {skill}. What was your specific contribution?",
            "category": TECHNICAL,
            "difficulty": INTERMEDIATE,
            "skill": skill,
            "why_asked": f"{skill} is on your CV, so an interviewer will probe it.",
            "expected_points": ["the problem being solved", f"how {skill} was applied",
                                "your individual contribution", "the measurable outcome"],
        })

    for skill in _rotate(missing, offset)[:2]:
        questions.append({
            "question": (f"This role expects {skill}, which isn't evidenced on your CV. "
                         f"How would you approach a task that required it?"),
            "category": SCENARIO,
            "difficulty": ADVANCED,
            "skill": skill,
            "why_asked": f"{skill} is an open gap for your target roles - expect to be asked.",
            "expected_points": ["honesty about the gap", "transferable experience",
                                "a concrete plan to close it", "evidence you learn quickly"],
        })

    if jobs:
        top = jobs[0]
        needed = [s for s in (top.get("missing_skills") or top.get("matched_skills") or [])][:2]
        questions.append({
            "question": (f"Your strongest match is {top.get('title')} at {top.get('company')} "
                         f"({top.get('match_percentage')}%). Why are you the right person for it?"),
            "category": HR,
            "difficulty": INTERMEDIATE,
            "skill": top.get("title") or role,
            "why_asked": "This is the role you are closest to landing.",
            "expected_points": ["specific overlap with the role's requirements",
                                "evidence from your own work"] + ([f"how you'd handle {needed[0]}"] if needed else []),
        })

    years = gap.get("experience_years")
    if years:
        questions.append({
            "question": (f"Your CV shows {years:g} years of experience. What is the most complex "
                         "thing you have shipped, and what made it hard?"),
            "category": BEHAVIORAL,
            "difficulty": ADVANCED,
            "skill": "experience depth",
            "why_asked": "Seniority is judged on the hardest problem you can describe well.",
            "expected_points": ["scope and constraints", "the decisions you owned",
                                "trade-offs made", "the result"],
        })
    return questions


def _compose_bank(role, profile, context, difficulty, categories, count, offset=0):
    """Build a role-specific bank with no model involved.

    This is the availability floor for question generation. It is *not* the old
    static list: the technical, scenario and system-design questions come from
    the matched role profile, and personal questions come from the candidate's
    own skills and gaps.
    """
    levels = list(LEVELS) if difficulty == InterviewSession.LEVEL_MIXED else [difficulty]
    role_label = role or profile.label

    def role_question(text, category, level):
        return {
            "question": text.replace("{role}", role_label),
            "category": category,
            "difficulty": level,
            "skill": profile.label if category == TECHNICAL else CATEGORY_LABELS[category],
            "why_asked": f"A standard {CATEGORY_LABELS[category].lower()} question for a {role_label}.",
            "expected_points": ["a specific, concrete example",
                                "your reasoning, not just the outcome",
                                "what you would do differently now"],
        }

    pools = {
        TECHNICAL: [role_question(q, TECHNICAL, lvl)
                    for lvl in levels for q in _rotate(profile.technical.get(lvl, ()), offset)],
        BEHAVIORAL: [role_question(q, BEHAVIORAL, lvl)
                     for lvl in levels for q in _rotate(BEHAVIORAL_QUESTIONS.get(lvl, ()), offset)],
        HR: [role_question(q, HR, lvl)
             for lvl in levels for q in _rotate(HR_QUESTIONS.get(lvl, ()), offset)],
        SCENARIO: [role_question(q, SCENARIO, INTERMEDIATE) for q in _rotate(profile.scenario, offset)],
        PROBLEM_SOLVING: [role_question(q, PROBLEM_SOLVING, ADVANCED)
                          for q in _rotate(profile.problem_solving, offset)],
        SYSTEM_DESIGN: [role_question(q, SYSTEM_DESIGN, ADVANCED) for q in _rotate(profile.system_design, offset)],
    }

    # Personal questions are woven into their own category's pool rather than
    # prepended. Front-loading them made every role open with the same four
    # CV questions, which is exactly the "same questions for every role"
    # problem this feature exists to fix. Inserting at index 1 keeps the bank
    # role-specific from the first question while still personalising early.
    for personal in _personal_questions(context, role_label, offset):
        pool = pools.setdefault(personal["category"], [])
        pool.insert(min(1, len(pool)), personal)

    # Round-robin across the requested categories so the bank is balanced
    # rather than dominated by whichever category has the deepest pool.
    questions = []
    wanted = [c for c in categories if pools.get(c)]
    cursors = {c: 0 for c in wanted}
    while len(questions) < count and wanted:
        for category in list(wanted):
            if len(questions) >= count:
                break
            pool, index = pools[category], cursors[category]
            if index >= len(pool):
                wanted.remove(category)
                continue
            cursors[category] += 1
            questions.append(pool[index])

    return questions[:count]


def _compose_tips(role, profile, context, readiness):
    """Coaching tips grounded in this candidate's strengths and gaps."""
    cv = context.get("cv") or {}
    gap = context.get("skill_gap") or {}
    skills = list(cv.get("skills") or gap.get("skills") or [])
    missing = list(gap.get("missing_skills") or [])
    tips = []

    if skills and missing:
        tips.append(
            f"You have strong {', '.join(skills[:2])} fundamentals but limited evidence of "
            f"{missing[0]}. Practise {missing[0]} before interviewing for {role} roles."
        )
    elif skills:
        tips.append(
            f"Lead with {skills[0]} - it is your strongest evidenced skill. Have one story "
            "ready that shows depth rather than breadth."
        )

    if missing:
        tips.append(
            f"Expect a question about {missing[0]}. Prepare an honest answer: what you know, "
            "what you have not done yet, and how you would close it."
        )

    if readiness.get("communication", 0) < 60:
        tips.append(
            "Your CV is light on quantified achievements, which usually means answers are too. "
            "Attach a number to every story you tell - users, latency, revenue, time saved."
        )
    if readiness.get("behavioral", 0) < 60:
        tips.append(
            "Prepare three STAR stories you can adapt: a conflict, a failure and a delivery "
            "under pressure. Most behavioral questions are variations of those."
        )
    if profile.system_design_applicable and readiness.get("technical", 0) >= 60:
        tips.append(
            f"At your level, expect a system design round. Practise talking through a "
            f"{profile.topics[0]} design out loud, drawing as you go."
        )
    tips.append("Answer out loud and time yourself - keep answers under two minutes.")
    return tips[:6]


def _compose_improvement(profile, context):
    """Skills, projects, portfolio, certifications and study order."""
    gap = context.get("skill_gap") or {}
    cv = context.get("cv") or {}
    signals = cv.get("signals") or {}
    missing = list(gap.get("missing_skills") or [])
    details = gap.get("missing_details") or []

    portfolio = []
    if not signals.get("github_links"):
        portfolio.append("Add a GitHub link - interviewers look for one and yours is missing.")
    if not signals.get("portfolio_links"):
        portfolio.append("Publish a portfolio or personal site showcasing two or three pieces of work.")
    if not signals.get("achievement_count"):
        portfolio.append("Rewrite your CV bullets to quantify outcomes rather than list duties.")
    portfolio.extend((cv.get("improvements") or [])[:2])

    return {
        "skills_to_improve": missing[:5],
        "recommended_projects": [
            f"Build and publish a small project that demonstrably uses {skill}."
            for skill in missing[:3]
        ] or [f"Ship a portfolio piece that shows {profile.topics[0]} end to end."],
        "portfolio": portfolio[:4],
        "certifications": list(profile.certifications)[:3],
        "learning_priorities": [
            info.get("skill") for info in details[:5] if info.get("skill")
        ] or missing[:5],
    }


def _normalise_questions(raw, profile, count):
    """Validate and clean model output into the stored question shape."""
    allowed_categories = set(available_categories(profile))
    cleaned = []
    for index, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        text = (item.get("question") or "").strip()
        if not text:
            continue
        category = (item.get("category") or TECHNICAL).strip().lower()
        if category not in allowed_categories:
            category = TECHNICAL
        difficulty = (item.get("difficulty") or INTERMEDIATE).strip().lower()
        if difficulty not in LEVELS:
            difficulty = INTERMEDIATE
        points = item.get("expected_points")
        cleaned.append({
            "id": len(cleaned),
            "question": text[:600],
            "category": category,
            "difficulty": difficulty,
            "skill": (item.get("skill") or "")[:120],
            "why_asked": (item.get("why_asked") or "")[:300],
            "expected_points": [str(p)[:200] for p in points][:6] if isinstance(points, list) else [],
        })
        if len(cleaned) >= count:
            break
    return cleaned


def generate_bank(user, role, *, difficulty=InterviewSession.LEVEL_MIXED,
                  categories=None, count=QUESTION_TARGET, offset=0, builder=None):
    """Build questions, tips and an improvement plan in a single AI call.

    Returns ``(payload, is_ai_generated)``. One call covers all three so a
    session costs one round trip rather than three (requirement: no duplicate
    AI calls).
    """
    builder = builder or CareerContextBuilder(user)
    context = builder.build(("cv", "skill_gap", "match", "courses"))
    cv = context.get("cv") or {}
    profile = match_profile(role, cv.get("specialization"), cv.get("profession"))
    categories = [c for c in (categories or available_categories(profile))
                  if c in available_categories(profile)] or list(available_categories(profile))
    readiness = InterviewReadiness.compute(user, builder=builder)

    raw = _parse_json(_call_model(
        _generation_prompt(role, profile, context, difficulty, categories, count),
        temperature=0.7,
        system_instruction=GENERATION_SYSTEM_PROMPT,
    ))

    if isinstance(raw, dict):
        questions = _normalise_questions(raw.get("questions"), profile, count)
        if questions:
            improvement = raw.get("improvement") if isinstance(raw.get("improvement"), dict) else {}
            tips = [str(t)[:400] for t in (raw.get("tips") or []) if t][:6]
            return {
                "questions": questions,
                "tips": tips or _compose_tips(role, profile, context, readiness),
                "improvement": {
                    key: [str(v)[:300] for v in (improvement.get(key) or [])][:5]
                    for key in ("skills_to_improve", "recommended_projects", "portfolio",
                                "certifications", "learning_priorities")
                } if improvement else _compose_improvement(profile, context),
                "readiness": readiness,
                "profile_key": profile.key,
                "role_label": profile.label,
            }, True

    questions = _compose_bank(role, profile, context, difficulty, categories, count, offset)
    for index, question in enumerate(questions):
        question["id"] = index
    return {
        "questions": questions,
        "tips": _compose_tips(role, profile, context, readiness),
        "improvement": _compose_improvement(profile, context),
        "readiness": readiness,
        "profile_key": profile.key,
        "role_label": profile.label,
    }, False


# ---------------------------------------------------------------------------
# Answer evaluation
# ---------------------------------------------------------------------------
EVALUATION_SYSTEM_PROMPT = """You are an experienced interviewer grading a candidate's answer.

Rules:
1. Grade only what the candidate actually said. Do not credit them for things they did not mention.
2. Be fair but honest - a vague or empty answer scores low, however confident it sounds.
3. `better_answer` must be a model answer the candidate can learn from, written in first person, under 150 words.
4. Strengths and weaknesses must be specific to this answer, not generic interview advice.
5. `coaching` is how they should deliver it next time - short imperative cues of at most 12 words,
   such as "Lead with the result, then the method" or "Name the metric you moved". At most three,
   and only ones this answer actually needs.
6. Return ONLY valid JSON. No markdown, no commentary."""

EVALUATION_SCHEMA = """{
  "score": 0-100,
  "strengths": ["what this answer genuinely did well"],
  "weaknesses": ["what was missing or weak, specifically"],
  "coaching": ["short delivery cue for the next answer"],
  "better_answer": "a stronger model answer in first person"
}"""

#: Cheap proxies for a well-structured spoken answer.
_STAR_MARKERS = re.compile(
    r"\b(situation|task|action|result|challenge|approach|outcome|impact|because|"
    r"so that|which led to|as a result)\b", re.I,
)
_METRIC_MARKER = re.compile(r"\b\d+(?:\.\d+)?\s*(%|percent|x|ms|seconds?|minutes?|hours?|days?|"
                            r"weeks?|months?|years?|users?|k|m|requests?)\b", re.I)


def _heuristic_evaluation(question, answer):
    """Grade an answer without a model.

    Rewards the things an interviewer actually rewards - covering the expected
    points, structure, and concrete numbers - so the score still means something
    when Gemini is unreachable.
    """
    text = (answer or "").strip()
    if len(text) < MIN_USEFUL_ANSWER_CHARS:
        return {
            "score": 10 if text else 0,
            "strengths": [],
            "weaknesses": ["The answer is too short to demonstrate anything. "
                           "Aim for a structured answer of 60-120 seconds."],
            "coaching": ["Answer out loud first, then write what you said.",
                         "Give one concrete example with a result."],
            "better_answer": "",
        }

    lowered = text.lower()
    expected = [p for p in (question.get("expected_points") or []) if p]
    covered = [
        point for point in expected
        # A point counts as covered when its distinctive words appear.
        if any(word in lowered for word in re.findall(r"[a-z]{5,}", point.lower())[:4])
    ]

    words = len(text.split())
    coverage_score = (len(covered) / len(expected) * 55) if expected else 30
    length_score = 25 if 60 <= words <= 300 else (15 if words > 30 else 5)
    structure_score = 10 if _STAR_MARKERS.search(text) else 0
    metric_score = 10 if _METRIC_MARKER.search(text) else 0

    strengths, weaknesses = [], []
    if covered:
        strengths.append(f"Covered {len(covered)} of {len(expected)} key points, including "
                         f"{covered[0][:80]}.")
    if structure_score:
        strengths.append("The answer has a recognisable structure an interviewer can follow.")
    if metric_score:
        strengths.append("You quantified the outcome, which makes the claim credible.")

    missed = [p for p in expected if p not in covered]
    if missed:
        weaknesses.append(f"Did not address: {'; '.join(m[:70] for m in missed[:3])}.")
    if not structure_score:
        weaknesses.append("Structure the answer explicitly - situation, action, result.")
    if not metric_score:
        weaknesses.append("Add a concrete number so the impact is measurable.")
    if words < 60:
        weaknesses.append("Too brief - expand with a specific example.")

    return {
        "score": _clamp(coverage_score + length_score + structure_score + metric_score),
        "strengths": strengths,
        "weaknesses": weaknesses,
        "coaching": _heuristic_coaching(text, words, structure_score, metric_score, missed),
        "better_answer": "",
    }


def _heuristic_coaching(text, words, structure_score, metric_score, missed):
    """Delivery cues from what the answer is missing, when the model is away.

    The same three things an interviewer notices first - structure, evidence,
    length - so the coaching is still about *this* answer rather than a rotation
    of generic advice.
    """
    cues = []
    if not structure_score:
        cues.append("Use the STAR structure: situation, task, action, result.")
    if not metric_score:
        cues.append("Name the number you moved - percent, hours, users.")
    if missed:
        cues.append(f"Work in the part you skipped: {missed[0][:60]}.")
    if words > 320:
        cues.append("Tighten it - aim for 90 seconds spoken.")
    elif words < 60:
        cues.append("Go one level deeper on what you personally did.")
    if not re.search(r"\bi\b", text, re.I):
        cues.append('Say "I", not "we" - they are hiring you.')
    return cues[:3]


def evaluate_answer(question, answer, role, context=None):
    """Grade one answer. Returns ``(evaluation, is_ai_generated)``."""
    text = (answer or "").strip()
    if len(text) < MIN_USEFUL_ANSWER_CHARS:
        # Not worth an AI call - an empty answer has one honest grade.
        return _heuristic_evaluation(question, text), False

    cv = (context or {}).get("cv") or {}
    prompt = f"""TARGET ROLE: {role}
CANDIDATE BACKGROUND: {cv.get("specialization") or cv.get("profession") or "not analysed"}, \
skills: {", ".join((cv.get("skills") or [])[:12]) or "none on record"}

QUESTION ({CATEGORY_LABELS.get(question.get("category"), "Technical")}, \
{question.get("difficulty", "intermediate")}): {question.get("question")}

A STRONG ANSWER COVERS:
{chr(10).join(f"- {p}" for p in (question.get("expected_points") or ["a specific, concrete example"]))}

CANDIDATE'S ANSWER:
{text[:4000]}

Return JSON in exactly this shape:
{EVALUATION_SCHEMA}"""

    parsed = _parse_json(_call_model(prompt, temperature=0.3, max_tokens=1200,
                                    system_instruction=EVALUATION_SYSTEM_PROMPT))
    if isinstance(parsed, dict) and parsed.get("score") is not None:
        coaching = [str(c)[:160] for c in (parsed.get("coaching") or []) if c][:3]
        return {
            "score": _clamp(parsed.get("score")),
            "strengths": [str(s)[:300] for s in (parsed.get("strengths") or [])][:5],
            "weaknesses": [str(w)[:300] for w in (parsed.get("weaknesses") or [])][:5],
            # An older model response without coaching still gets the cues the
            # heuristic can see, so the coach panel is never empty.
            "coaching": coaching or _heuristic_evaluation(question, text)["coaching"],
            "better_answer": str(parsed.get("better_answer") or "")[:2000],
        }, True

    return _heuristic_evaluation(question, text), False


# ---------------------------------------------------------------------------
# Closing report
# ---------------------------------------------------------------------------
REPORT_SYSTEM_PROMPT = """You are writing the debrief a candidate receives after a mock interview.

Rules:
1. Base every statement on the answers actually given and the scores already computed. Do not invent performance the transcript does not show.
2. Be specific and actionable. "Improve communication" is useless; "lead with the result, then the method" is not.
3. Never contradict the numeric scores you are given.
4. Return ONLY valid JSON. No markdown, no commentary."""

REPORT_SCHEMA = """{
  "strengths": ["specific strength demonstrated in the transcript"],
  "weaknesses": ["specific weakness demonstrated in the transcript"],
  "improvement_plan": ["a concrete, ordered next step"],
  "next_topics": ["topic to practise next"]
}"""

#: Which answer categories feed which headline score.
_TECHNICAL_CATEGORIES = (TECHNICAL, SYSTEM_DESIGN, PROBLEM_SOLVING)
#: How the story was told - structure, evidence, clarity - which is what the
#: behavioral and scenario rounds actually grade.
_COMMUNICATION_CATEGORIES = (BEHAVIORAL, SCENARIO)
#: Everything that is not a technical question. Broader than the line above by
#: design: a candidate asking "how did I do on the behavioral side?" means the
#: HR questions too.
_BEHAVIORAL_CATEGORIES = (BEHAVIORAL, SCENARIO, HR)


def _category_mean(turns, categories):
    scores = [t.score for t in turns if t.category in categories]
    return _clamp(statistics.fmean(scores)) if scores else 0


def build_report(session, turns, context, courses=None):
    """Score the session, then write the narrative. Returns ``(fields, ai)``.

    Scores are arithmetic over the answers actually given; only the prose is
    AI-written, and it is told the numbers rather than asked to invent them.
    """
    answered = [t for t in turns if t.answer]
    scores = [t.score for t in answered]
    overall = _clamp(statistics.fmean(scores)) if scores else 0

    technical = _category_mean(answered, _TECHNICAL_CATEGORIES)
    hr = _category_mean(answered, (HR,))
    behavioral = _category_mean(answered, _BEHAVIORAL_CATEGORIES)
    communication = _category_mean(answered, _COMMUNICATION_CATEGORIES)

    # Confidence rewards consistency: a candidate who scores evenly reads as
    # more prepared than one who alternates between excellent and blank.
    if len(scores) > 1:
        spread = statistics.pstdev(scores)
        consistency = _clamp(100 - spread * 2)
        completion = len(answered) / max(len(turns), 1) * 100
        confidence = _clamp(0.5 * overall + 0.3 * consistency + 0.2 * completion)
    else:
        confidence = overall

    gap = context.get("skill_gap") or {}
    missing_skills = list(gap.get("missing_skills") or [])[:6]
    recommended_courses = [
        {"title": c.get("title"), "provider": c.get("provider"),
         "closes_gap": c.get("closes_gap"), "url": c.get("url")}
        for c in (courses or [])[:4]
    ]

    fields = {
        "overall_score": overall,
        "technical_score": technical,
        "hr_score": hr,
        "behavioral_score": behavioral,
        "communication_score": communication,
        "confidence_score": confidence,
        "missing_skills": missing_skills,
        "recommended_courses": recommended_courses,
    }

    transcript = "\n\n".join(
        f"Q ({CATEGORY_LABELS.get(t.category, t.category)}, {t.difficulty}): {t.question}\n"
        f"A: {t.answer[:800]}\nScored: {t.score}/100"
        for t in answered
    )
    parsed = None
    if transcript:
        parsed = _parse_json(_call_model(
            f"""TARGET ROLE: {session.target_role}
COMPUTED SCORES - overall {overall}, technical {technical}, behavioral {behavioral}, \
HR {hr}, communication {communication}, confidence {confidence}.
KNOWN SKILL GAPS: {", ".join(missing_skills) or "none on record"}

TRANSCRIPT:
{transcript[:10000]}

Return JSON in exactly this shape:
{REPORT_SCHEMA}""",
            temperature=0.4,
            system_instruction=REPORT_SYSTEM_PROMPT,
        ))

    if isinstance(parsed, dict) and (parsed.get("strengths") or parsed.get("weaknesses")):
        fields.update({
            "strengths": [str(s)[:300] for s in (parsed.get("strengths") or [])][:6],
            "weaknesses": [str(w)[:300] for w in (parsed.get("weaknesses") or [])][:6],
            "improvement_plan": [str(p)[:300] for p in (parsed.get("improvement_plan") or [])][:6],
            "next_topics": [str(t)[:200] for t in (parsed.get("next_topics") or [])][:6],
        })
        return fields, True

    # Deterministic debrief, composed from the same turns the model would read.
    strengths = [s for turn in answered for s in (turn.strengths or [])][:5]
    weaknesses = [w for turn in answered for w in (turn.weaknesses or [])][:5]
    best = max(answered, key=lambda t: t.score, default=None)
    worst = min(answered, key=lambda t: t.score, default=None)
    if best is not None and best.score:
        strengths.insert(0, f"Strongest answer was the {CATEGORY_LABELS.get(best.category, best.category)} "
                            f"question, scoring {best.score}/100.")
    if worst is not None and worst is not best:
        weaknesses.insert(0, f"Weakest answer was the {CATEGORY_LABELS.get(worst.category, worst.category)} "
                             f"question, scoring {worst.score}/100.")

    fields.update({
        "strengths": strengths[:6],
        "weaknesses": weaknesses[:6],
        "improvement_plan": (
            [f"Close the {skill} gap - it came up in your target roles." for skill in missing_skills[:3]]
            + ["Re-run this interview and aim to beat your overall score.",
               "Rehearse your weakest category out loud until the structure is automatic."]
        )[:6],
        "next_topics": (missing_skills[:3] + [
            CATEGORY_LABELS.get(worst.category, "Technical") if worst is not None else "Technical",
        ])[:6],
    })
    return fields, False


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
class InterviewService:
    """Session lifecycle: generate once, answer many, report at the end."""

    @staticmethod
    def active(user):
        return (
            InterviewSession.objects
            .filter(user=user, is_active=True)
            .order_by("-updated_at")
            .first()
        )

    @staticmethod
    def history(user, limit=10):
        return (
            InterviewSession.objects
            .filter(user=user)
            .select_related("report")
            .order_by("-updated_at")[:limit]
        )

    @classmethod
    def practice_scores(cls, user):
        """Scores from every graded answer, used by the confidence component."""
        return list(
            InterviewTurn.objects
            .filter(session__user=user)
            .exclude(answer="")
            .values_list("score", flat=True)
        )

    @classmethod
    def readiness(cls, user, builder=None):
        return InterviewReadiness.compute(
            user, builder=builder, practice_scores=cls.practice_scores(user),
        )

    @classmethod
    def needs_regeneration(cls, session, target_role, fingerprint, *, setup=None):
        """A stored bank is reused unless what it was built for has changed.

        `setup` covers the choices that decide the questions themselves - the
        round, the difficulty, how many. Without this check, choosing a
        five-question behavioral round would hand back the twelve-question mixed
        bank from last time and look like the setting was ignored.
        """
        if session is None:
            return True
        if not session.matches(target_role, fingerprint):
            return True
        for field in ("difficulty", "interview_type", "question_count"):
            requested = (setup or {}).get(field)
            if requested is not None and getattr(session, field) != requested:
                return True
        return False

    @classmethod
    def get_or_create_session(cls, user, target_role, *, difficulty=InterviewSession.LEVEL_MIXED,
                              categories=None, force_new=False,
                              interview_type=InterviewSession.TYPE_MIXED,
                              question_count=QUESTION_TARGET, duration_minutes=0):
        """The single entry point the page uses to obtain a session.

        Reuses the stored bank unless the target role changed, the CV changed,
        the setup changed, or the user explicitly asked for a new interview -
        which is the whole of the "no duplicate AI calls" rule.
        """
        builder = CareerContextBuilder(user)
        fingerprint = profile_resume_fingerprint(user)
        session = cls.active(user)
        target_role = (target_role or "").strip()
        question_count = clamp_question_count(question_count)
        duration_minutes = clamp_duration(duration_minutes)

        if not target_role and session is not None:
            target_role = session.target_role
        if not target_role:
            cv = builder.build(("cv",)).get("cv") or {}
            target_role = cv.get("specialization") or cv.get("profession") or "your target role"

        setup = {"difficulty": difficulty, "interview_type": interview_type,
                 "question_count": question_count}
        if not force_new and not cls.needs_regeneration(session, target_role, fingerprint, setup=setup):
            # The clock does not affect the questions, so a changed duration is
            # applied to the existing session rather than costing a rebuild.
            if session.duration_minutes != duration_minutes:
                session.duration_minutes = duration_minutes
                session.save(update_fields=["duration_minutes", "updated_at"])
            return session, False

        payload, ai_generated = generate_bank(
            user, target_role, difficulty=difficulty,
            categories=categories_for(interview_type, categories),
            count=question_count,
            builder=builder,
            # A regenerate should not hand back the same fallback questions.
            offset=InterviewSession.objects.filter(user=user).count(),
        )

        with transaction.atomic():
            InterviewSession.objects.filter(user=user, is_active=True).update(is_active=False)
            session = InterviewSession.objects.create(
                user=user,
                target_role=target_role[:180],
                resume_fingerprint=fingerprint or "",
                difficulty=difficulty,
                interview_type=interview_type,
                question_count=question_count,
                duration_minutes=duration_minutes,
                questions=payload["questions"],
                tips=payload["tips"],
                improvement_plan=payload["improvement"],
                readiness=payload["readiness"],
                is_ai_generated=ai_generated,
            )
        return session, True

    @classmethod
    def submit_answer(cls, session, answer, question_index=None):
        """Grade one answer, store the turn and advance the interview."""
        index = session.current_index if question_index is None else int(question_index)
        question = session.question_at(index)
        if question is None:
            return None

        builder = CareerContextBuilder(session.user)
        context = builder.build(("cv",))
        evaluation, ai_generated = evaluate_answer(
            question, answer, session.target_role, context,
        )

        with transaction.atomic():
            turn, _ = InterviewTurn.objects.update_or_create(
                session=session,
                question_index=index,
                defaults={
                    "question": question.get("question", "")[:2000],
                    "category": question.get("category", "")[:40],
                    "difficulty": question.get("difficulty", "")[:20],
                    "answer": (answer or "")[:8000],
                    "score": evaluation["score"],
                    "strengths": evaluation["strengths"],
                    "weaknesses": evaluation["weaknesses"],
                    "coaching": evaluation.get("coaching") or [],
                    "better_answer": evaluation["better_answer"],
                    "is_ai_generated": ai_generated,
                },
            )
            fields = ["current_index", "status", "updated_at"]
            session.current_index = max(session.current_index, index + 1)
            if session.status == InterviewSession.STATUS_READY:
                session.status = InterviewSession.STATUS_IN_PROGRESS
            if session.started_at is None:
                # The interview starts when the candidate does, not when the
                # questions were generated.
                session.started_at = timezone.now()
                fields.append("started_at")
            session.save(update_fields=fields)
        return turn

    @classmethod
    def complete(cls, session):
        """Close the session and write its report."""
        turns = list(session.turns.all())
        builder = CareerContextBuilder(session.user)
        context = builder.build(("cv", "skill_gap"))
        courses = (builder.build(("courses",)).get("courses") or {}).get("courses") or []

        fields, ai_generated = build_report(session, turns, context, courses)

        with transaction.atomic():
            InterviewReport.objects.update_or_create(
                session=session,
                defaults={**fields, "is_ai_generated": ai_generated},
            )
            session.status = InterviewSession.STATUS_COMPLETED
            session.completed_at = timezone.now()
            session.save(update_fields=["status", "completed_at", "updated_at"])
        session.refresh_from_db()
        return session.report

    @classmethod
    def reset(cls, session):
        """Discard answers so the same bank can be practised again."""
        session.turns.all().delete()
        InterviewReport.objects.filter(session=session).delete()
        session.current_index = 0
        session.status = InterviewSession.STATUS_READY
        session.completed_at = None
        # A re-run is timed from scratch, not from the first attempt.
        session.started_at = None
        session.save(update_fields=["current_index", "status", "completed_at",
                                    "started_at", "updated_at"])
        return session

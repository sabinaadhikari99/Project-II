import json
import logging
import re
from collections import Counter

from django.conf import settings
from django.db import transaction

from apps.notifications.services import send_application_email
from apps.notifications.services import notify_job_match
from apps.shared.constants import JOB_VECTOR_PREFIX, PROFILE_VECTOR_PREFIX
from apps.shared.cv_signals import (
    EDUCATION_RANK,
    education_rank,
    extract_cv_signals,
    extract_skills_section,
)
from apps.shared.deductions import (
    SEVERITY_POINTS,
    build_strengths,
    classify_requirement,
    evaluate_deductions,
)
from apps.shared.embedding_client import get_embedding
from apps.shared.pdf_utils import extract_pdf_text
from apps.shared.resume_quality import analyze_resume_quality
from apps.shared.profession_classifier import (
    classify_job,
    classify_profession_from_skills,
    classify_profession_with_resume,
    extract_resume_sections,
    get_related_profession_titles,
    normalize_skill,
    SKILL_SYNONYMS,
    PROFESSION_CONFIGS,
    RELATED_PROFESSIONS,
)
from apps.shared.skill_normalizer import normalize_skill as norm_skill, normalize_skill_set
from apps.shared.specializations import (
    SPECIALIZATIONS,
    detect_specialization,
    get_adjacent_parents,
)
from apps.shared.vector_db import get_vector_manager

from .models import Application, JobPosting

logger = logging.getLogger(__name__)

COMMON_SKILLS = [
    "Python", "Django", "Django REST Framework", "DRF", "FastAPI", "JavaScript",
    "React", "Bootstrap", "HTML", "CSS", "SQL", "SQLite", "PostgreSQL", "MySQL",
    "Pandas", "NumPy", "Machine Learning", "NLP", "FAISS", "APIs", "Git",
    "Docker", "AWS", "Excel", "Power BI", "Communication", "Leadership",
]

SCORE_WEIGHTS = {
    "profession": float(getattr(settings, "AI_WEIGHT_PROFESSION", 40)),
    "skills": float(getattr(settings, "AI_WEIGHT_SKILLS", 30)),
    "experience": float(getattr(settings, "AI_WEIGHT_EXPERIENCE", 15)),
    "education": float(getattr(settings, "AI_WEIGHT_EDUCATION", 10)),
    "semantic": float(getattr(settings, "AI_WEIGHT_SEMANTIC", 5)),
    # Evidence components read straight off the CV. Without these the score had
    # no way to distinguish a portfolio-rich certified candidate from a bare
    # skills list, so most candidates collapsed onto the same few values.
    "projects": float(getattr(settings, "AI_WEIGHT_PROJECTS", 6)),
    "certifications": float(getattr(settings, "AI_WEIGHT_CERTIFICATIONS", 4)),
}

#: How much a matched skill is worth, by where in the CV it was found.
#:
#: A skill listed in the SKILLS section is a claim the candidate is making; a
#: skill that only turns up inside a sentence is weaker evidence of the same
#: thing. Scoring them identically is why deleting "Jenkins" from a skills list
#: changed nothing while "set up Jenkins automation servers" remained in the
#: experience bullets - the extractor scans the whole document and could not
#: tell the two apart.
#: The spread is deliberately modest. A skill demonstrated in an experience
#: bullet is genuinely good evidence - arguably better than a bare list entry -
#: so prose is discounted, not discredited. Tune via settings if a harsher or
#: flatter curve suits your market.
SKILL_SOURCE_WEIGHTS = {
    "skills_section": float(getattr(settings, "AI_SKILL_WEIGHT_DECLARED", 1.0)),
    "experience": float(getattr(settings, "AI_SKILL_WEIGHT_EXPERIENCE", 0.85)),
    "projects": float(getattr(settings, "AI_SKILL_WEIGHT_PROJECTS", 0.85)),
    "summary": float(getattr(settings, "AI_SKILL_WEIGHT_SUMMARY", 0.7)),
    "elsewhere": float(getattr(settings, "AI_SKILL_WEIGHT_ELSEWHERE", 0.7)),
}

#: normalised skill key -> every spelling that normalises to it.
#:
#: `extract_resume_skills` returns NORMALISED keys ("restapis", "cicd"), which
#: never appear in a CV verbatim. Locating a skill in the document therefore has
#: to search the words a human would write, so this reverse index is built from
#: the vocabularies the extractor itself draws on.
_SPELLINGS_BY_NORM = {}


def _register_spelling(name):
    key = norm_skill(str(name))
    if key:
        _SPELLINGS_BY_NORM.setdefault(key, set()).add(str(name).strip())


for _raw, _canon in SKILL_SYNONYMS.items():
    _register_spelling(_raw)
    _register_spelling(_canon)
for _config in PROFESSION_CONFIGS.values():
    for _name in _config.get("skills", {}):
        _register_spelling(_name)
for _config in SPECIALIZATIONS.values():
    for _name in _config.get("signals", {}):
        _register_spelling(_name)
    for _name in _config.get("core_skills", []):
        _register_spelling(_name)
for _name in COMMON_SKILLS:
    _register_spelling(_name)

AI_MATCH_THRESHOLD = int(getattr(settings, "AI_MATCH_THRESHOLD", 70))
AI_MATCH_NOTIFICATION_THRESHOLD = int(getattr(settings, "AI_MATCH_NOTIFICATION_THRESHOLD", 80))

#: Profession sub-score used when the classifier could not identify the CV at
#: all. Neutral on purpose: claiming a perfect profession match would be a lie,
#: and claiming zero would punish the candidate for our classifier failing.
UNKNOWN_PROFESSION_MATCH = 0.5


def create_job_with_embedding(recruiter, data) -> JobPosting:
    with transaction.atomic():
        data = dict(data)
        data["job_category"] = classify_job(
            data.get("title", ""),
            data.get("required_skills", []),
        )
        job = JobPosting.objects.create(recruiter=recruiter, **data)
        get_vector_manager().update_embedding(
            f"{JOB_VECTOR_PREFIX}:{job.id}",
            get_embedding(job.embedding_text),
        )
    return job


def update_job_embedding(job: JobPosting):
    if not job.job_category:
        job.job_category = classify_job(job.title, job.required_skills)
        job.save(update_fields=["job_category"])
    get_vector_manager().update_embedding(
        f"{JOB_VECTOR_PREFIX}:{job.id}",
        get_embedding(job.embedding_text),
    )


def recommend_jobs_for_user(user, limit=10, request=None, resume_text=None,
                            user_skills=None, skill_confidence=None):
    """Ranked job recommendations for a user.

    `user_skills` defaults to the stored `UserProfile.skills`, which is what the
    profile-driven recommendations page wants. An AI Match analysis passes the
    skills it just extracted from the uploaded CV instead: the stored list is a
    running union across every upload, so scoring from it meant a skill removed
    from a CV was still scored and the number could only ever move upward.
    """
    profile = getattr(user, "profile", None)
    if not profile:
        return []

    user_skills = list(user_skills) if user_skills is not None else (profile.skills or [])
    is_debug = getattr(settings, "AI_MATCH_DEBUG", False)
    if resume_text:
        user_profession, profession_conf = classify_profession_with_resume(
            resume_text, extracted_skills=user_skills,
        )
        if is_debug:
            logger.info(
                "Hybrid classify: profession=%s confidence=%d skills=%s",
                user_profession, profession_conf, user_skills,
            )
    else:
        user_profession = classify_profession_from_skills(user_skills)

    # A CV that cannot be classified used to return an empty list outright -
    # that is the "Data Analyst CV shows empty results" symptom. Fall back to
    # semantic similarity instead so the user always gets something relevant.
    if not user_profession:
        if is_debug:
            logger.info("No profession detected; using semantic-only fallback")
        return _semantic_fallback_recommendations(
            user, profile, resume_text, limit, request,
            user_profession=None,
            user_skills=user_skills, skill_confidence=skill_confidence,
        )

    specialization, _ = detect_specialization(
        resume_text or "", user_skills, user_profession,
    )
    profession_titles = get_related_profession_titles(user_profession)

    if is_debug:
        logger.info(
            "Job filter: profession=%s specialization=%s related=%s",
            user_profession, specialization, profession_titles,
        )

    candidate_jobs = JobPosting.objects.filter(
        is_active=True,
        job_category__in=profession_titles,
    )
    if not candidate_jobs.exists():
        # Widen to the specialisation's declared adjacent categories only.
        # Never to the whole table: that is what put Frontend roles in front of
        # Flutter and Graphic Design candidates.
        adjacent = set(get_adjacent_parents(specialization)) | set(profession_titles)
        candidate_jobs = JobPosting.objects.filter(
            is_active=True, job_category__in=adjacent,
        )
        if is_debug:
            logger.info("Widened to adjacent categories: %s -> %d jobs",
                        adjacent, candidate_jobs.count())
    if not candidate_jobs.exists():
        if is_debug:
            logger.info("No candidate jobs for %s; semantic fallback", profession_titles)
        return _semantic_fallback_recommendations(
            user, profile, resume_text, limit, request,
            user_profession=user_profession, specialization=specialization,
            user_skills=user_skills, skill_confidence=skill_confidence,
        )

    if is_debug:
        logger.info("Candidate jobs found: %d", candidate_jobs.count())
        for j in candidate_jobs:
            logger.info("  job=%s category=%s", j.title, j.job_category)

    ranked = _hybrid_rank_jobs(
        user=user,
        profile=profile,
        user_skills=user_skills,
        user_profession=user_profession,
        candidate_jobs=candidate_jobs,
        limit=limit,
        request=request,
        resume_text=resume_text,
        specialization=specialization,
        skill_confidence=skill_confidence,
    )

    recommendations = []
    for item in ranked:
        recommendation = _build_recommendation(
            user=user,
            profile=profile,
            job=item["job"],
            vector_score=item.get("score", 0),
            match_explanation=item.get("match_explanation", {}),
            request=request,
            deductions=item.get("deductions"),
            strengths=item.get("strengths"),
            user_skills=user_skills,
        )
        if recommendation is None:
            continue
        recommendations.append(recommendation)
        if recommendation["match_percentage"] >= AI_MATCH_NOTIFICATION_THRESHOLD:
            notify_job_match(
                user,
                item["job"],
                recommendation["match_percentage"],
                recommendation["required_skills"],
                _application_link(item["job"], request),
            )

    return sorted(recommendations, key=lambda r: r["match_percentage"], reverse=True)[:limit]


def _semantic_fallback_recommendations(user, profile, resume_text, limit, request,
                                       user_profession=None, specialization=None,
                                       user_skills=None, skill_confidence=None):
    """Last-resort recommendations driven purely by embedding similarity.

    Used only when the profession is undetectable or its categories hold no
    postings. Returning an empty list here was the "CV shows empty results"
    bug: the user got a blank page with no explanation. Results are flagged
    is_related_role so the UI can label them as broader suggestions.

    `user_profession` is the profession actually detected for the CV (None when
    the classifier could not decide). It MUST be passed through rather than
    substituted with the job's own category: doing the latter made the
    comparison inside compute_match_score self-referential, awarding a perfect
    profession sub-score - the single largest weighted component - to precisely
    the results we are least confident about.
    """
    from apps.src.job_recommendation import build_recommendation_text

    text = resume_text or build_recommendation_text(profile)
    if not text:
        return []

    try:
        matches = get_vector_manager().search_similar(
            get_embedding(text), top_k=max(limit * 3, 20),
            prefix=f"{JOB_VECTOR_PREFIX}:",
        )
    except Exception:
        logger.warning("Semantic fallback unavailable", exc_info=True)
        return []

    scores = {}
    for object_id, score in matches:
        try:
            scores[int(str(object_id).split(":")[1])] = score
        except (IndexError, ValueError):
            continue
    if not scores:
        return []

    jobs = JobPosting.objects.filter(is_active=True, id__in=list(scores))
    # Same CV signals the primary path uses, so a job reached through the
    # fallback is scored on the same evidence as one reached through filtering.
    cv_signals = extract_cv_signals(resume_text or profile.resume_text or "")
    effective_skills = list(user_skills) if user_skills is not None else (profile.skills or [])
    recommendations = []
    for job in sorted(jobs, key=lambda j: -scores.get(j.id, 0.0))[:limit]:
        result = compute_match_score(
            user_skills=effective_skills,
            user_profession=user_profession,
            profile=profile,
            job=job,
            vector_score=scores.get(job.id, 0.0),
            cv_signals=cv_signals,
            specialization=specialization,
            skill_confidence=skill_confidence,
        )
        recommendation = _build_recommendation(
            user=user, profile=profile, job=job,
            vector_score=result["score"],
            match_explanation=result["match_explanation"],
            request=request,
            deductions=result.get("deductions"),
            strengths=result.get("strengths"),
            user_skills=effective_skills,
        )
        if recommendation is None:
            continue
        recommendation["is_related_role"] = True
        recommendations.append(recommendation)
    return recommendations


def _hybrid_rank_jobs(user, profile, user_skills, user_profession, candidate_jobs, limit,
                      request=None, resume_text=None, specialization=None,
                      skill_confidence=None):
    job_ids_for_vector = list(candidate_jobs.values_list("id", flat=True))

    from apps.src.job_recommendation import build_recommendation_text

    rec_text = resume_text or build_recommendation_text(profile)
    embedding = get_embedding(rec_text)
    vector_matches = get_vector_manager().search_similar(
        embedding,
        top_k=min(len(job_ids_for_vector) * 2, 40),
        prefix=f"{JOB_VECTOR_PREFIX}:",
    )
    vector_scores = {}
    for object_id, score in vector_matches:
        try:
            job_id = int(object_id.split(":")[1])
        except (IndexError, ValueError):
            continue
        vector_scores[job_id] = score

    # Parse the CV itself, never `rec_text` - build_recommendation_text() wraps
    # the document in "Skills: ... Headline: ..." scaffolding that skews the
    # section and project counts. Falling back to the stored resume_text is what
    # makes /api/jobs/recommended/ score a CV the same way AI Match does; that
    # path used to pass "" and silently lose the project, certification,
    # experience and education evidence entirely.
    cv_signals = extract_cv_signals(resume_text or profile.resume_text or "")

    scored_jobs = []
    for job in candidate_jobs:
        vector_score = vector_scores.get(job.id, 0.0)
        result = _compute_weighted_score(
            user_skills=user_skills,
            user_profession=user_profession,
            profile=profile,
            job=job,
            vector_score=vector_score,
            cv_signals=cv_signals,
            specialization=specialization,
            skill_confidence=skill_confidence,
        )
        scored_jobs.append(result)

    scored_jobs.sort(key=lambda x: x["final_score"], reverse=True)
    return scored_jobs[:limit]


def locate_resume_skills(resume_text, skills):
    """Where each extracted skill appears in the CV, and what that is worth.

    Returns ``{normalised skill: {"skill", "sources", "confidence"}}`` where
    confidence is the best SKILL_SOURCE_WEIGHTS value across the sections the
    skill was found in. Feed the confidences to `compute_match_score` and a
    declared skill counts fully while a passing mention counts partially, so
    editing the SKILLS section moves the score in both directions.

    Reuses the existing section extractors and synonym table rather than
    re-parsing: `extract_resume_sections` for the prose blocks,
    `extract_skills_section` for the skills list, `SKILL_SYNONYMS` for spelling.
    """
    text = resume_text or ""
    if not text.strip() or not skills:
        return {}

    sections = extract_resume_sections(text)
    bodies = {
        "skills_section": extract_skills_section(text),
        "experience": sections.get("experience") or "",
        "projects": sections.get("projects") or "",
        "summary": sections.get("summary") or "",
    }

    located = {}
    for skill in skills:
        raw = str(skill).strip()
        if not raw:
            continue
        # Search every spelling that normalises to this skill, plus the value
        # itself for anything the reverse index does not know (a job posting's
        # own bespoke requirement, say).
        spellings = {raw} | _SPELLINGS_BY_NORM.get(norm_skill(raw), set())
        patterns = [
            re.compile(r"(?<![a-z0-9+#.])" + re.escape(s.lower()) + r"(?![a-z0-9+#.])",
                       re.IGNORECASE)
            for s in spellings
        ]
        found = [name for name, body in bodies.items()
                 if body and any(p.search(body) for p in patterns)]
        if not found:
            # Present in the document (the extractor found it) but outside any
            # section this function can name - a header, a footer, a stray line.
            found = ["elsewhere"]
        located[norm_skill(raw)] = {
            "skill": raw,
            "sources": found,
            "confidence": max(SKILL_SOURCE_WEIGHTS[name] for name in found),
        }
    return located


def skill_confidence_map(located):
    """Flatten `locate_resume_skills` output to {normalised skill: confidence}."""
    return {key: entry["confidence"] for key, entry in (located or {}).items()}


def split_required_skills(required_skills, user_skills):
    """Split a posting's requirements into (matched, missing), original spelling.

    Single source of truth for "does this candidate have this requirement",
    shared by the scorer, the deduction layer and the recommendation builder so
    the three can never disagree about what is missing.
    """
    user_norm = normalize_skill_set(user_skills)
    required_raw = list(required_skills or [])
    matched = [s for s in required_raw if norm_skill(s) in user_norm]
    missing = [s for s in required_raw if norm_skill(s) not in user_norm]
    return matched, missing


def compute_match_score(user_skills, user_profession, profile, job, vector_score,
                        cv_signals=None, specialization=None, skill_confidence=None):
    """Weighted match score, then explainable job-specific deductions.

    Stage 1 is the existing seven-component weighted average - unchanged, and
    still the foundation of the number.

    Stage 2 subtracts named penalties for requirements THIS posting lists and
    THIS CV does not evidence (see apps.shared.deductions). Deductions are
    capped, always job-specific and always carry their justification, so the
    final score is both better separated and fully explainable.

    `cv_signals` (from apps.shared.cv_signals.extract_cv_signals) is optional and
    backwards compatible: when supplied, experience / education / projects /
    certifications are read from the UPLOADED CV rather than from static
    UserProfile columns, so the score actually moves between different CVs.

    `specialization` is the fine-grained role from apps.shared.specializations.
    It only sharpens how severely a missing requirement is judged; it never
    changes which jobs are considered.

    `skill_confidence` maps a normalised skill to how strongly the CV evidences
    it (see locate_resume_skills). Omit it and every matched skill counts as a
    full 1.0, which is exactly the behaviour every existing caller had.
    """
    user_profession_lower = user_profession.lower() if user_profession else ""

    job_profession = (job.job_category or "").lower()
    related_professions = {p.lower() for p in get_related_profession_titles(user_profession or "")}
    if not user_profession_lower:
        # Unknown profession. Guarded explicitly because two empty strings
        # compare equal, which used to hand an unclassifiable CV a perfect
        # profession match against an uncategorised posting.
        profession_match = UNKNOWN_PROFESSION_MATCH
    elif user_profession_lower == job_profession:
        profession_match = 1.0
    elif job_profession in related_professions:
        profession_match = 0.6
    else:
        profession_match = 0.0
    profession_score = round(profession_match * 100)

    matched_raw, missing_raw = split_required_skills(job.required_skills or [], user_skills)
    required = normalize_skill_set(job.required_skills or [])
    user_skills_norm = normalize_skill_set(user_skills)
    if required:
        matched_skills = user_skills_norm & required
        # A matched skill contributes its confidence, not a flat 1.0, when the
        # caller supplied provenance (see locate_resume_skills). Without it the
        # sum is just the count, so every existing caller - Skill Gap Analysis
        # included - keeps the exact behaviour it had.
        if skill_confidence:
            covered = sum(
                min(1.0, max(0.0, float(skill_confidence.get(skill, 1.0))))
                for skill in matched_skills
            )
        else:
            covered = len(matched_skills)
        skills_pct = covered / len(required)
        matched_count = len(matched_skills)
    else:
        matched_skills = set()
        skills_pct = 0.5
        matched_count = 0
    skills_score = round(skills_pct * 100)

    signals = cv_signals or {}

    # CV-parsed experience wins over the static profile column when available.
    user_exp = float(signals.get("experience_years") or 0) or float(
        getattr(profile, "experience_years", 0) or 0
    )
    job_exp = float(job.experience_required or 0)
    if job_exp == 0:
        # Graded rather than a flat 1.0: an open-ended posting still rewards a
        # candidate who actually has experience, so the sub-score varies by CV.
        exp_pct = min(1.0, 0.6 + user_exp / 10.0)
    else:
        exp_pct = min(1.0, 0.5 + user_exp / (job_exp * 2)) if user_exp >= job_exp \
            else max(0.1, user_exp / job_exp)
    experience_score = round(exp_pct * 100)

    # Education is compared on the EDUCATION_RANK ordinal scale, never by
    # substring. The old string test asked whether one qualification contained
    # the other, so a master's or a PhD failed a "Bachelor's degree"
    # requirement - neither string contains the other - and scored 0.3 while a
    # bachelor's scored 1.0. Over-qualification was penalised. Ranks make the
    # comparison directional: meeting or exceeding the requirement is always
    # full marks.
    user_level = signals.get("education_level") or ""
    if user_level and user_level != "unknown":
        user_rank = EDUCATION_RANK.get(user_level, 0)
    else:
        # No parsed CV (e.g. the profile-only recommendation path): read the
        # free-text profile column through the same parser.
        user_rank = education_rank(getattr(profile, "education", "") or "")
    job_rank = education_rank(getattr(job, "education_required", "") or "")

    if job_rank == 0:
        # The posting states no requirement: scale with the candidate's level.
        education_pct = 0.55 + 0.1 * user_rank
    elif user_rank >= job_rank:
        education_pct = 1.0
    elif user_rank == 0:
        # Nothing recognisable in the CV to compare against a stated requirement.
        education_pct = 0.3
    else:
        # Below the requirement, graded by how far below rather than a flat floor.
        education_pct = max(0.3, 1.0 - 0.25 * (job_rank - user_rank))
    education_pct = max(0.0, min(education_pct, 1.0))
    education_score = round(education_pct * 100)

    semantic_pct = max(0.0, min(float(vector_score), 1.0))
    semantic_score = round(semantic_pct * 100)

    # Demonstrated delivery: projects + supporting evidence in the document.
    project_pct = min(1.0, 0.25 * min(int(signals.get("project_count") or 0), 3))
    if signals.get("has_portfolio"):
        project_pct = min(1.0, project_pct + 0.15)
    if signals.get("has_metrics"):
        project_pct = min(1.0, project_pct + 0.15)
    if signals.get("has_leadership"):
        project_pct = min(1.0, project_pct + 0.1)
    project_score = round(project_pct * 100)

    certification_score = round(
        min(1.0, 0.4 * min(int(signals.get("certification_count") or 0), 3)) * 100
    )

    w = SCORE_WEIGHTS
    components = (
        (profession_score, w["profession"]),
        (skills_score, w["skills"]),
        (experience_score, w["experience"]),
        (education_score, w["education"]),
        (semantic_score, w["semantic"]),
        (project_score, w["projects"]),
        (certification_score, w["certifications"]),
    )
    total_weight = sum(weight for _, weight in components) or 1
    base_score = round(
        sum(score * weight for score, weight in components) / total_weight
    )
    base_score = max(1, min(base_score, 100))

    # --- stage 2: explainable, job-specific deductions ---------------------
    deduction_report = evaluate_deductions(
        job=job,
        missing_skills=missing_raw,
        signals=signals,
        profession=user_profession,
        specialization=specialization,
    )
    strengths = build_strengths(
        job=job,
        matched_skills=matched_raw,
        signals=signals,
        profession=user_profession,
        specialization=specialization,
    )
    final_score = max(1, min(base_score - deduction_report["total"], 100))

    match_explanation = {
        "profession_match": profession_score,
        "skills_match": skills_score,
        "experience_match": experience_score,
        "education_match": education_score,
        "semantic_similarity": semantic_score,
        "project_match": project_score,
        "certification_match": certification_score,
        # The weighted score before deductions, kept alongside the final one so
        # the UI can show the arithmetic rather than just the answer. Both are
        # plain ints, which keeps the existing DictField(IntegerField) contract.
        "base_score": base_score,
        "total_deduction": deduction_report["total"],
        "final_score": final_score,
    }

    return {
        "job": job,
        "score": final_score / 100,
        "final_score": final_score,
        "base_score": base_score,
        "profession_match": profession_score,
        "skills_score": skills_score,
        "experience_score": experience_score,
        "education_score": education_score,
        "semantic_score": semantic_score,
        "project_score": project_score,
        "certification_score": certification_score,
        "missing_count": len(required) - matched_count,
        "match_explanation": match_explanation,
        "deductions": deduction_report["deductions"],
        "total_deduction": deduction_report["total"],
        "deduction_capped": deduction_report["capped"],
        "additional_gaps": deduction_report["additional_gaps"],
        "strengths": strengths,
    }


_compute_weighted_score = compute_match_score


def estimate_score_gain(required_skill_count, skills_learned=1, deduction_recovered=0):
    """Points the overall match score would gain by learning N missing skills.

    Derived from the real weighting rather than guessed: the skills component is
    matched/required, so each newly acquired required skill lifts that component
    by 1/required, which contributes (w_skills / total_weight) of that lift to
    the final score.

    `deduction_recovered` is the stage-2 penalty that acquiring the skill also
    removes (see apps.shared.deductions). Learning a critical requirement is now
    worth its weighted contribution PLUS the 5 points it stops costing, which is
    why the two terms are added here. The result stays a lower bound: with
    several gaps closed at once the deduction cap may already have been binding.
    """
    if not required_skill_count:
        return int(round(max(0, deduction_recovered)))
    total_weight = sum(SCORE_WEIGHTS.values()) or 1
    per_skill = (100.0 / required_skill_count) * SCORE_WEIGHTS["skills"] / total_weight
    learned = max(0, skills_learned)
    return int(round(per_skill * learned + max(0, deduction_recovered)))


def match_candidates_for_job(job: JobPosting, limit=10):
    matches = get_vector_manager().search_similar(
        get_embedding(job.embedding_text),
        top_k=limit,
        prefix=f"{PROFILE_VECTOR_PREFIX}:",
    )
    user_ids = [int(object_id.split(":")[1]) for object_id, _ in matches]
    from apps.accounts.models import User

    users = {user.id: user for user in User.objects.filter(id__in=user_ids).select_related("profile")}
    return [{"candidate": users[user_id], "score": score}
            for object_id, score in matches
            for user_id in [int(object_id.split(":")[1])]
            if user_id in users]


def apply_to_job(user, job, cover_letter=""):
    application, created = Application.objects.get_or_create(
        job=job, applicant=user, defaults={"cover_letter": cover_letter},
    )
    if created:
        send_application_email(application)
    return application


def analyze_resume_match(user, resume_file, request=None):
    from apps.accounts.models import UserProfile

    try:
        resume_text = extract_pdf_text(resume_file)
        if len(resume_text.strip()) < 80:
            raise ValueError("The uploaded PDF text looks empty or unclear.")

        extracted_skills = extract_resume_skills(resume_text)
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.resume_text = resume_text
        prior_profile_skills = list(profile.skills or [])
        # The profile keeps the cumulative list so manually added skills and
        # earlier CVs are not destroyed. Scoring no longer reads it - see below.
        merged_skills = sorted(set(profile.skills or []) | set(extracted_skills))
        profile.skills = merged_skills
        profile.save()
        # get_or_create() returned a NEW UserProfile instance; prime Django's
        # cached reverse relation so downstream reads see the saved row.
        user.profile = profile

        # An AI Match score describes THE UPLOADED DOCUMENT, so it is computed
        # from that document's own skills. `merged_skills` stays the profile's
        # cumulative list - it is what the profile page and manual edits rely on
        # - but scoring from it made the number monotonically non-decreasing:
        # a skill deleted from a CV was still scored, so removing one could
        # never lower the score and any incidental addition could only raise it.
        skill_sources = locate_resume_skills(resume_text, extracted_skills)
        skill_confidence = skill_confidence_map(skill_sources)

        user_profession, profession_conf = classify_profession_with_resume(
            resume_text, extracted_skills=extracted_skills,
        )
        is_debug = getattr(settings, "AI_MATCH_DEBUG", False)
        if is_debug:
            logger.info(
                "Resume analysis: profession=%s confidence=%d cv_skills=%d profile_skills=%d",
                user_profession, profession_conf, len(extracted_skills), len(merged_skills),
            )

        recommendations = recommend_jobs_for_user(
            user, limit=10, request=request, resume_text=resume_text,
            user_skills=extracted_skills, skill_confidence=skill_confidence,
        )
        specialization, specialization_conf = detect_specialization(
            resume_text, extracted_skills, user_profession or "",
        )

        # Explainability layer (Phase 2 #3, #4, #11, #12). Signals are parsed
        # once here and threaded into everything below, so none of this re-reads
        # or re-embeds the CV.
        signals = extract_cv_signals(resume_text)
        gemini = _gemini_resume_insights(
            resume_text, extracted_skills, recommendations, specialization,
            signals=signals,
        )
        best_match = max([item["match_percentage"] for item in recommendations], default=0)

        top_required = []
        for item in recommendations[:3]:
            top_required.extend(item.get("required_skills") or [])
        quality = analyze_resume_quality(
            resume_text, user_skills=extracted_skills,
            required_skills=top_required, signals=signals,
        )
        action_plan = build_skill_action_plan(recommendations)
        structured_insights = build_structured_insights(
            resume_text, extracted_skills, recommendations,
            specialization, quality, signals,
        )

        # TEMPORARY diagnostic hook (settings.AI_MATCH_TRACE, off by default).
        # Formats values this call already produced - it re-runs nothing, scores
        # nothing, and returns nothing, so it cannot alter the response. Remove
        # together with apps.shared.match_debug once scoring is settled.
        if getattr(settings, "AI_MATCH_TRACE", False):
            try:
                from apps.shared.match_debug import format_live_trace

                logger.info("AI match trace for user %s:\n%s", user.id, format_live_trace(
                    resume_text=resume_text,
                    extracted_skills=extracted_skills,
                    prior_skills=prior_profile_skills,
                    effective_skills=extracted_skills,
                    profession=user_profession,
                    profession_confidence=profession_conf,
                    specialization=specialization,
                    specialization_confidence=specialization_conf,
                    signals=signals,
                    recommendations=recommendations,
                ))
            except Exception:
                logger.warning("AI match trace failed (analysis unaffected)", exc_info=True)

        return {
            "profession": user_profession or "Not determined",
            # Fine-grained role from the CV (e.g. "Flutter Developer"). The
            # coarse `profession` is unchanged so existing consumers keep
            # working; `specialization` is what makes the UI role-specific.
            "specialization": specialization or user_profession or "",
            "specialization_confidence": specialization_conf,
            "profession_confidence": profession_conf,
            "resume_summary": gemini["resume_summary"],
            "resume_score": best_match,
            "skills_extracted": extracted_skills,
            # Where each extracted skill was found, and therefore how much it
            # counted. Lets the UI explain why a skill listed only inside an
            # experience bullet is worth less than one in the Skills section.
            "skill_sources": [
                {
                    "skill": entry["skill"],
                    "sources": entry["sources"],
                    "confidence": entry["confidence"],
                    "declared": "skills_section" in entry["sources"],
                }
                for entry in sorted(skill_sources.values(),
                                    key=lambda e: (-e["confidence"], e["skill"].lower()))
            ],
            "recommended_jobs": recommendations,
            # Per-job score breakdown so the charts plot the candidate against
            # each matched role instead of re-rendering one flat percentage.
            "match_analytics": [
                {
                    "title": item["job"].title,
                    "company": item["job"].company,
                    "match_percentage": item["match_percentage"],
                    "profession_match": item["match_explanation"].get("profession_match", 0),
                    "skills_match": item["match_explanation"].get("skills_match", 0),
                    "experience_match": item["match_explanation"].get("experience_match", 0),
                    "education_match": item["match_explanation"].get("education_match", 0),
                    "semantic_similarity": item["match_explanation"].get("semantic_similarity", 0),
                    "matched_skills": item.get("matched_skills", []),
                    "missing_skills": item.get("missing_skills", []),
                    "is_related_role": item.get("is_related_role", False),
                    # base - deductions = match_percentage, so the charts can
                    # show what the gaps actually cost on this role.
                    "base_score": item.get("base_score", item["match_percentage"]),
                    "total_deduction": item.get("total_deduction", 0),
                }
                for item in recommendations[:6]
            ],
            "resume_insights": gemini["resume_insights"],
            "resume_improvement_suggestions": gemini["resume_improvement_suggestions"],
            # --- Phase 2 explainability additions -------------------------
            "structured_insights": structured_insights,
            "skill_action_plan": action_plan,
            "resume_quality": quality,
            "cv_signals": {
                "experience_years": signals["experience_years"],
                "education_level": signals["education_level"],
                "project_count": signals["project_count"],
                "certification_count": signals["certification_count"],
                "achievement_count": signals["achievement_count"],
                "has_internship": signals["has_internship"],
                "has_open_source": signals["has_open_source"],
                "has_hackathon": signals["has_hackathon"],
                "has_awards": signals["has_awards"],
                "has_research": signals["has_research"],
                "has_publications": signals["has_publications"],
                "github_links": signals["github_links"],
                "portfolio_links": signals["portfolio_links"],
            },
            "score_breakdown": (
                recommendations[0]["match_explanation"] if recommendations else {}
            ),
        }
    except ValueError:
        raise
    except Exception:
        logger.exception("analyze_resume_match: unexpected error for user %s", user.id)
        return {
            "profession": "",
            "specialization": "",
            "specialization_confidence": 0,
            "profession_confidence": 0,
            "resume_summary": "",
            "resume_score": 0,
            "skills_extracted": [],
            "skill_sources": [],
            "recommended_jobs": [],
            "match_analytics": [],
            "resume_insights": [],
            "resume_improvement_suggestions": [],
            "structured_insights": [],
            "skill_action_plan": [],
            "resume_quality": {"score": 0, "band": "needs work",
                               "breakdown": [], "recommendations": []},
            "cv_signals": {},
            "score_breakdown": {},
        }


def extract_resume_skills(resume_text):
    known = set(COMMON_SKILLS)
    for job in JobPosting.objects.filter(is_active=True).only("required_skills")[:100]:
        known.update(job.required_skills or [])

    known_skill_set = set()
    for s in known:
        known_skill_set.add(normalize_skill(s))

    for config in PROFESSION_CONFIGS.values():
        for skill_name in config.get("skills", {}):
            known_skill_set.add(skill_name)

    lowered = resume_text.lower()
    extracted_set = set()

    synonym_matches = 0
    for raw_synonym, canon in SKILL_SYNONYMS.items():
        pattern = r"(?<![a-z0-9+#.])" + re.escape(raw_synonym.lower()) + r"(?![a-z0-9+#.])"
        if re.search(pattern, lowered):
            extracted_set.add(canon)
            synonym_matches += 1

    for skill in sorted(known_skill_set, key=len, reverse=True):
        normalized = str(skill).strip()
        if not normalized:
            continue
        pattern = r"(?<![a-z0-9+#.])" + re.escape(normalized.lower()) + r"(?![a-z0-9+#.])"
        if re.search(pattern, lowered):
            extracted_set.add(normalized)

    return sorted({norm_skill(s) for s in extracted_set}, key=str.lower)


def _build_recommendation(user, profile, job, vector_score, match_explanation=None, request=None,
                          deductions=None, strengths=None, user_skills=None):
    required_skills = list(job.required_skills or [])
    # Must be the SAME skill set the score was computed from, or the matched /
    # missing chips would contradict the percentage next to them.
    effective_skills = list(user_skills) if user_skills is not None else (profile.skills or [])
    matched_skills, missing_skills = split_required_skills(required_skills, effective_skills)

    insight = ""
    if missing_skills:
        insight = f"Focus on {', '.join(missing_skills[:4])} to improve fit for this role."
    else:
        insight = "Your listed skills cover the major requirements for this role."

    explanation = match_explanation or {}
    match_pct = explanation.get("final_score", 50)

    return {
        "job": job,
        "score": match_pct / 100,
        "match_percentage": match_pct,
        # The arithmetic behind match_percentage: base - deductions = final.
        "base_score": explanation.get("base_score", match_pct),
        "total_deduction": explanation.get("total_deduction", 0),
        "required_skills": required_skills,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "recommendation_insight": insight,
        "match_explanation": explanation,
        "deductions": list(deductions or []),
        "strengths": list(strengths or []),
        "why_matched": _why_matched(matched_skills, explanation),
        "why_not_higher": _why_not_higher(missing_skills, explanation),
    }


#: Human labels for score components, used to explain a job match.
_COMPONENT_LABELS = (
    ("profession_match", "profession alignment"),
    ("skills_match", "skills coverage"),
    ("experience_match", "experience level"),
    ("education_match", "education"),
    ("semantic_similarity", "overall CV similarity"),
    ("project_match", "project evidence"),
    ("certification_match", "certifications"),
)


def _why_matched(matched_skills, explanation):
    """Positive drivers behind this job's score (Phase 2 #5, #12)."""
    reasons = []
    strong = [label for key, label in _COMPONENT_LABELS
              if explanation.get(key, 0) >= 75]
    if strong:
        reasons.append("Strong " + ", ".join(strong[:3]))
    if matched_skills:
        reasons.append(
            f"You already have {len(matched_skills)} of the required skills: "
            f"{', '.join(matched_skills[:5])}"
        )
    if not reasons:
        reasons.append("Ranked on overall CV similarity to this posting.")
    return reasons


def _why_not_higher(missing_skills, explanation):
    """Weakest components, so the user knows exactly what caps the score."""
    reasons = []
    weak = sorted(
        ((explanation.get(key, 0), label) for key, label in _COMPONENT_LABELS
         if explanation.get(key, 0) < 70),
        key=lambda pair: pair[0],
    )
    for score, label in weak[:3]:
        reasons.append(f"Your {label} scored {score}%")
    if missing_skills:
        reasons.append(
            f"Missing {len(missing_skills)} required skill(s): "
            f"{', '.join(missing_skills[:5])}"
        )
    if not reasons:
        reasons.append("This role is already a near-complete match.")
    return reasons


def _gemini_resume_insights(resume_text, skills, recommendations, specialization="",
                            signals=None):
    fallback = {
        "resume_summary": _fallback_summary(resume_text, skills, specialization,
                                            recommendations, signals=signals),
        "resume_insights": _fallback_resume_insights(resume_text, skills, recommendations),
        "resume_improvement_suggestions": _fallback_improvement_suggestions(
            resume_text, skills, recommendations
        ),
    }

    if not settings.GEMINI_API_KEY:
        return fallback

    try:
        import google.generativeai as genai

        job_context = [
            {
                "title": item["job"].title,
                "company": item["job"].company,
                "match_percentage": item["match_percentage"],
            }
            for item in recommendations[:5]
        ]
        prompt = f"""
You are an expert AI Career Coach. Analyze this resume using ONLY the provided
resume text. Never invent skills, employers, or experience that is not present.

The candidate has been classified as: {specialization or "unclassified"}.
Keep every observation and suggestion relevant to that role - do not suggest
technologies from unrelated fields.

resume_summary must be a single paragraph covering, in this order: detected
profession, career level, years of experience, strongest skills, weak areas,
education, and overall employability.

Return strict JSON with keys:
resume_summary, resume_insights, resume_improvement_suggestions.
resume_insights and resume_improvement_suggestions must be arrays of short strings.

Resume text:
{resume_text}

Extracted skills:
{skills}

Recommended jobs:
{job_context}
"""
        genai.configure(api_key=settings.GEMINI_API_KEY)
        response = genai.GenerativeModel("gemini-2.5-flash").generate_content(
            prompt,
            generation_config={"temperature": 0.35, "max_output_tokens": 900},
        )
        text = (getattr(response, "text", "") or "").strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        for key, value in fallback.items():
            if key not in data or not data[key]:
                data[key] = value
        return data
    except Exception:
        return fallback


_CAREER_LEVELS = ((0, "Entry-level"), (2, "Junior"), (5, "Mid-level"), (9, "Senior"))


def _career_level_label(years):
    label = "Entry-level"
    for threshold, name in _CAREER_LEVELS:
        if years >= threshold:
            label = name
    return label


def _fallback_summary(resume_text, skills, specialization="", recommendations=None,
                      signals=None):
    """Structured, CV-derived professional summary.

    Every clause below is computed from the uploaded document: role, career
    level, years, strongest skills, weak areas and employability. The previous
    version emitted one fixed sentence with the skill list interpolated, which
    is why summaries looked identical across candidates.

    `signals` is accepted so the caller can pass the parse it already holds
    rather than making this re-read the whole document.
    """
    signals = signals or extract_cv_signals(resume_text)
    years = signals["experience_years"]
    role = specialization or "Professional"
    level = _career_level_label(years)

    parts = []
    if years:
        parts.append(f"{level} {role} with approximately {years:g} year(s) of experience")
    else:
        parts.append(f"{level} {role}")

    if skills:
        parts.append(f"strongest in {', '.join(skills[:6])}")

    education = {
        "phd": "holds a doctorate", "master": "holds a master's degree",
        "bachelor": "holds a bachelor's degree",
        "diploma": "holds a diploma/associate qualification",
    }.get(signals["education_level"])
    if education:
        parts.append(education)

    evidence = []
    if signals["project_count"]:
        evidence.append(f"{signals['project_count']} documented project(s)")
    if signals["certification_count"]:
        evidence.append(f"{signals['certification_count']} certification(s)")
    if signals["has_metrics"]:
        evidence.append("quantified achievements")
    if signals["has_leadership"]:
        evidence.append("leadership experience")
    if evidence:
        parts.append("evidenced by " + ", ".join(evidence))

    summary = ". ".join([", ".join(parts[:3])] + ([". ".join(parts[3:])] if parts[3:] else []))
    summary = summary.rstrip(".") + "."

    gaps = _top_missing_skills(recommendations or [], limit=3)
    if gaps:
        summary += f" Key development areas: {', '.join(gaps)}."

    best = max((item.get("match_percentage", 0) for item in (recommendations or [])),
               default=0)
    if best:
        band = ("strong" if best >= 80 else "moderate" if best >= 60 else "developing")
        summary += (f" Overall employability for {role} roles is {band} "
                    f"({best}% best role match).")
    return summary


def _fallback_resume_insights(resume_text, skills, recommendations):
    lowered = (resume_text or "").lower()
    insights = []

    experience = re.search(r"\b(\d+)\s*\+?\s*years?\b", lowered)
    if experience:
        insights.append(
            f"Resume indicates {experience.group(0)} of professional experience, which is a solid "
            f"foundation for {_top_profession_label(recommendations)} roles."
        )
    else:
        insights.append("No explicit years-of-experience range found in the resume.")

    if re.search(r"\b(projects?|portfolio|github|gitlab|bitbucket)\b", lowered):
        insights.append("Hands-on project or portfolio work is documented in the resume.")
    else:
        insights.append("No projects or portfolio section was detected in the resume.")

    if re.search(r"\b(certified|certification|certificate)\b", lowered):
        insights.append("Professional certifications are listed on the resume.")
    else:
        insights.append("No certifications section was detected in the resume.")

    if re.search(r"\b(led|lead|mentor(ed)?|managed|head of|supervis(ed|or))\b", lowered):
        insights.append("Leadership or mentoring experience was detected in the resume.")

    if re.search(r"\b(\d+(\.\d+)?%|\$\d|\d+k\b|users|revenue|uptime|accuracy)\b", lowered):
        insights.append("Quantified achievements with metrics were detected, which strengthens the resume.")
    else:
        insights.append("Consider adding measurable outcomes such as users, revenue, accuracy, or time saved.")

    if re.search(r"\b(bachelor|master|phd|b\.?sc|m\.?sc|mba|degree|diploma)\b", lowered):
        insights.append("Formal education credentials were detected in the resume.")
    else:
        insights.append("No formal education section was detected in the resume.")

    if skills:
        insights.append(f"A strong skill base of {len(skills)} recognized skills was extracted from the resume.")

    missing = _top_missing_skills(recommendations, limit=4)
    if missing:
        insights.append(f"Closing gaps in {', '.join(missing)} would improve fit for recommended roles.")

    return insights[:8]


def _fallback_improvement_suggestions(resume_text, skills, recommendations):
    lowered = (resume_text or "").lower()
    suggestions = []

    if not re.search(r"\bprojects?\b", lowered):
        suggestions.append("Add a Projects section with concrete deliverables and your specific role in each.")

    if not re.search(r"\b(certified|certification|certificate)\b", lowered):
        suggestions.append("List certifications relevant to your target roles to increase credibility.")

    if not re.search(r"\b(\d+(\.\d+)?%|\$\d|\d+k\b|users|revenue|uptime|accuracy)\b", lowered):
        suggestions.append("Quantify achievements with metrics such as users, revenue, accuracy, speed, or time saved.")

    if not re.search(r"\b(bachelor|master|phd|b\.?sc|m\.?sc|mba|degree|diploma)\b", lowered):
        suggestions.append("Include your education section with degree, institution, and graduation year.")

    if not re.search(r"\b(github|portfolio|linkedin|gitlab|bitbucket)\b", lowered):
        suggestions.append("Add links to your portfolio, GitHub, or LinkedIn profile for recruiters.")

    for skill in _top_missing_skills(recommendations, limit=3):
        suggestions.append(f"Learn {skill} to qualify for the roles recommended for your profile.")

    if not suggestions:
        suggestions.append("Keep the resume focused on verified skills and project outcomes.")
    return suggestions[:6]


#: Rough self-study effort per difficulty tier, in weeks.
_LEARN_WEEKS = {"beginner": 2, "intermediate": 4, "advanced": 8}


def build_skill_action_plan(recommendations, limit=6):
    """Actionable, explainable plan entries for the top missing skills.

    Each entry answers: why is this missing, how important is it, which jobs
    need it, how long will it take, and what will it do to my score
    (Phase 2 #4). Every number is computed from the live recommendation set.
    """
    from apps.skillgap.catalog import get_skill_difficulty

    recs = [r for r in (recommendations or []) if r.get("job") is not None]
    if not recs:
        return []

    total_jobs = len(recs)
    demand = Counter()
    raw_by_norm = {}
    required_counts = []
    for rec in recs:
        required = rec.get("required_skills") or []
        required_counts.append(len(required))
        for skill in rec.get("missing_skills") or []:
            key = norm_skill(skill)
            demand[key] += 1
            raw_by_norm.setdefault(key, skill)

    if not demand:
        return []

    avg_required = max(1, round(sum(required_counts) / len(required_counts)))
    # Judge severity under the profession the recommendations belong to, so a
    # gap is rated the way the deduction layer actually charges it.
    top_job = recs[0].get("job")
    profession = getattr(top_job, "job_category", "") or None

    plan = []
    for key, count in demand.most_common(limit):
        share = round(count / total_jobs * 100)
        difficulty = get_skill_difficulty(key)
        importance = "High" if share >= 60 else ("Medium" if share >= 30 else "Low")
        severity, _ = classify_requirement(raw_by_norm[key], profession=profession)
        plan.append({
            "skill": raw_by_norm[key],
            "importance": importance,
            "required_by_percent": share,
            "required_by_jobs": count,
            "difficulty": difficulty,
            "estimated_weeks": _LEARN_WEEKS.get(difficulty, 4),
            # How the deduction layer bands this gap, and therefore how many
            # penalty points learning it recovers on top of the weighted lift.
            "severity": severity,
            "expected_score_gain": estimate_score_gain(
                avg_required, deduction_recovered=SEVERITY_POINTS[severity],
            ),
            "why": (f"{raw_by_norm[key]} is required by {share}% of your "
                    f"{total_jobs} best-matching roles but was not found in your CV."),
        })
    return plan


def build_structured_insights(resume_text, skills, recommendations,
                              specialization="", quality=None, signals=None):
    """Categorised CV insights (Phase 2 #3).

    Returns a list of {category, items[]} where every item is derived from the
    uploaded document or the live recommendation set - never a fixed sentence.
    """
    signals = signals or extract_cv_signals(resume_text)
    role = specialization or "your target"
    best = max((r.get("match_percentage", 0) for r in (recommendations or [])), default=0)
    gaps = _top_missing_skills(recommendations, limit=5)

    strengths = []
    if skills:
        strengths.append(f"{len(skills)} recognised skills extracted, led by "
                         f"{', '.join(skills[:5])}")
    if signals["experience_years"]:
        strengths.append(f"{signals['experience_years']:g} year(s) of experience evidenced in the CV")
    if signals["achievement_count"]:
        strengths.append(f"{signals['achievement_count']} quantified achievement(s) - "
                         "strong signal for recruiters")
    if signals["has_leadership"]:
        strengths.append("Leadership or mentoring responsibility documented")
    if signals["has_open_source"] or signals["github_links"]:
        strengths.append("Public code or open-source contribution evidence present")
    if signals["has_awards"]:
        strengths.append("Awards or honours listed")
    if signals["has_publications"] or signals["has_research"]:
        strengths.append("Research or publication record present")

    weaknesses = []
    for gap in gaps:
        weaknesses.append(f"{gap} is requested by your best-matching roles but absent from the CV")
    if not signals["achievement_count"]:
        weaknesses.append("No measurable outcomes - results are described without numbers")
    if not signals["certification_count"]:
        weaknesses.append("No certifications listed to corroborate your skills")
    if not signals["project_count"]:
        weaknesses.append("No dedicated Projects section detected")
    if not signals["portfolio_links"]:
        weaknesses.append("No portfolio, GitHub or LinkedIn link provided")

    level = _career_level_label(signals["experience_years"])
    readiness = [
        f"Career level assessed as {level} from {signals['experience_years']:g} year(s) of experience",
        f"Best available role match is {best}%" if best else
        "No matching roles are currently posted for this profile",
    ]
    if signals["has_internship"]:
        readiness.append("Internship or trainee experience detected")
    if signals["has_hackathon"]:
        readiness.append("Hackathon participation detected")

    technical = [
        f"Primary specialisation detected as {role}",
        f"Core stack: {', '.join(skills[:8])}" if skills else
        "No recognised technical skills were extracted",
    ]
    if gaps:
        technical.append(f"Stack gaps relative to market demand: {', '.join(gaps)}")

    employability = []
    if best >= 80:
        employability.append(f"Strong employability - you clear 80% match on {role} roles")
    elif best >= 60:
        employability.append(f"Moderate employability - closing {len(gaps)} gap(s) would move you into the strong band")
    elif best:
        employability.append(f"Developing employability - substantial upskilling needed for {role} roles")
    else:
        employability.append("Employability could not be assessed against current postings")

    risks = []
    if len(gaps) >= 4:
        risks.append(f"{len(gaps)} in-demand skills missing - risk of automated ATS rejection")
    if not signals["has_email"] or not signals["has_phone"]:
        risks.append("Incomplete contact details may prevent recruiters reaching you")
    if signals["sections_missing"]:
        risks.append("Missing CV sections: " + ", ".join(signals["sections_missing"]))
    if signals["experience_years"] == 0:
        risks.append("No explicit experience duration - screeners may assume entry level")

    sections = [
        ("Strengths", strengths),
        ("Weaknesses", weaknesses),
        ("Career Readiness", readiness),
        ("Technical Assessment", technical),
        ("Employability", employability),
        ("Potential Career Risks", risks),
    ]
    if quality:
        sections.append((
            "Resume Quality",
            [f"Overall ATS quality score {quality['score']}% ({quality['band']})"]
            + [f"{b['label']}: {b['score']}% - {b['detail']}" for b in quality["breakdown"][:3]],
        ))
    if recommendations:
        sections.append((
            "Most Competitive Roles",
            [f"{r['job'].title} at {r['job'].company} - {r['match_percentage']}% match"
             for r in recommendations[:4]],
        ))

    return [{"category": name, "items": items} for name, items in sections if items]


def _top_missing_skills(recommendations, limit=4):
    ordered = []
    seen = set()
    for item in sorted(
        (recommendations or []),
        key=lambda r: r.get("match_percentage", 0) or 0,
        reverse=True,
    ):
        for skill in item.get("missing_skills") or []:
            if skill not in seen:
                seen.add(skill)
                ordered.append(skill)
            if len(ordered) >= limit:
                return ordered
    return ordered


def _top_profession_label(recommendations):
    for item in (recommendations or [])[:3]:
        job = item.get("job")
        if job is None:
            continue
        if isinstance(job, dict):
            return job.get("title") or ""
        return getattr(job, "title", "") or ""
    return "your target"


def _application_link(job, request):
    path = f"/jobs/?title={job.title.replace(' ', '+')}"
    if request:
        return request.build_absolute_uri(path)
    return path

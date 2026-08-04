import json

from django.conf import settings

from apps.shared.resume_quality import analyze_resume_quality
from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set

from .analysis_memo import run_once
from .cache import analysis_fingerprint, get_analysis_cached, set_analysis_cached
from .career import CareerAnalyzer


def analyze_skill_gap(user, force=False):
    """Skill gap for the user's current CV, skills and job pool.

    The response is cached per analysis fingerprint, matching how courses and
    roadmaps are already served, so returning to the page repaints the stored
    analysis instead of re-running the pipeline. `force=True` recomputes.
    """
    fingerprint = analysis_fingerprint(user)
    if not force:
        cached = get_analysis_cached("gap", user.id, fingerprint)
        if cached is not None:
            return cached

    context = run_once(user, lambda: CareerAnalyzer.analyze(user))
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = (
        json.loads(resources_path.read_text(encoding="utf-8"))
        if resources_path.exists()
        else []
    )
    missing_lookup = normalize_skill_set(context.missing_names)
    recommended = [
        item
        for item in resources
        if normalize_skill(item.get("skill", "")) in missing_lookup
    ]
    # Keyword coverage is judged against what the best-matched roles ask for.
    top_required = []
    for job in context.jobs[:3]:
        top_required.extend(job.required_skills or [])
    quality = analyze_resume_quality(
        context.resume_text, user_skills=context.user_skills,
        required_skills=top_required, signals=context.signals or None,
    )

    response = {
        "user_skills": context.user_skills,
        "missing_skills": context.missing_names,
        "missing_skill_details": context.missing_skills,
        "recommended_resources": recommended,
        # --- Phase 2 (#7, #11, #12) ---------------------------------------
        "gap_categories": context.gap_categories,
        "coverage": context.coverage,
        "resume_quality": quality,
        "profession": context.profession,
        "profession_score": context.profession_score,
        # Fine-grained role driving the gaps/courses/roadmap.
        "specialization": context.specialization,
        "specialization_score": context.specialization_score,
        "career_level": context.career_level,
        "career_level_label": context.career_level_label,
        "experience_years": context.experience_years,
        "education_level": context.education_level,
        "education_label": context.education_label,
        "recommended_jobs": context.recommended_jobs,
        "match_score": context.match_score,
        "match_explanation": context.match_explanation,
        "has_resume": bool(context.resume_text),
        # Lets the client tell whether a locally cached copy still describes the
        # analysis on file, without downloading it to compare.
        "analysis_fingerprint": fingerprint,
    }
    set_analysis_cached("gap", user.id, fingerprint, response)
    return response

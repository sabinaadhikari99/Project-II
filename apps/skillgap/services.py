import json

from django.conf import settings

from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set

from .analysis_memo import run_once
from .career import CareerAnalyzer


def analyze_skill_gap(user):
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
    return {
        "user_skills": context.user_skills,
        "missing_skills": context.missing_names,
        "missing_skill_details": context.missing_skills,
        "recommended_resources": recommended,
        "profession": context.profession,
        "profession_score": context.profession_score,
        "career_level": context.career_level,
        "career_level_label": context.career_level_label,
        "experience_years": context.experience_years,
        "education_level": context.education_level,
        "education_label": context.education_label,
        "recommended_jobs": context.recommended_jobs,
        "match_score": context.match_score,
        "match_explanation": context.match_explanation,
        "has_resume": bool(context.resume_text),
    }

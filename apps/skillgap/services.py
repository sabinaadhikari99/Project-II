# file path: apps/skillgap/services.py
import json

from django.conf import settings

from apps.jobs.models import JobPosting


def _normalize_skills(skills):
    return {str(skill).strip().lower() for skill in (skills or []) if str(skill).strip()}


def _sorted_unique_skills(skills):
    seen = set()
    normalized = set()
    result = []
    for skill in (skills or []):
        if not isinstance(skill, str):
            skill = str(skill)
        value = skill.strip()
        if not value:
            continue
        key = value.lower()
        if key in normalized:
            continue
        normalized.add(key)
        result.append(value)
    return sorted(result, key=str.lower)


def analyze_skill_gap(user):
    profile = getattr(user, "profile", None)
    user_skills = _sorted_unique_skills(profile.skills if profile else [])
    user_lookup = _normalize_skills(user_skills)
    required = set()
    for job in JobPosting.objects.filter(is_active=True).only("required_skills")[:50]:
        required.update(
            skill for skill in (job.required_skills or [])
            if isinstance(skill, str) and skill.strip()
        )
    missing = sorted(
        {skill for skill in required if skill.lower() not in user_lookup},
        key=str.lower
    )
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else []
    missing_lookup = {skill.lower() for skill in missing}
    recommended = [
        item for item in resources
        if item.get("skill", "").strip().lower() in missing_lookup
    ]
    return {
        "user_skills": user_skills,
        "missing_skills": missing,
        "recommended_resources": recommended,
    }

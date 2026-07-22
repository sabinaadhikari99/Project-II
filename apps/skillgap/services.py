import json

from django.conf import settings

from apps.jobs.models import JobPosting
from apps.jobs.services import extract_resume_skills
from apps.shared.profession_classifier import (
    classify_profession_with_resume,
    get_related_profession_titles,
)
from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set


def _sorted_unique_skills(skills):
    normalized = set()
    result = []
    for skill in (skills or []):
        if not isinstance(skill, str):
            skill = str(skill)
        value = skill.strip()
        if not value:
            continue
        key = normalize_skill(value)
        if key in normalized:
            continue
        normalized.add(key)
        result.append(value)
    return sorted(result, key=str.lower)


def _latest_resume_skills(profile):
    if not profile or not profile.resume_text:
        return []
    return extract_resume_skills(profile.resume_text)


def _required_skills_for_profession(resume_text, user_skills):
    profession, _ = classify_profession_with_resume(resume_text, extracted_skills=user_skills)
    if profession:
        titles = get_related_profession_titles(profession)
        jobs = JobPosting.objects.filter(is_active=True, job_category__in=titles)
    else:
        jobs = JobPosting.objects.filter(is_active=True)
    required = set()
    for job in jobs.only("required_skills")[:50]:
        required.update(
            skill for skill in (job.required_skills or [])
            if isinstance(skill, str) and skill.strip()
        )
    return required


def analyze_skill_gap(user):
    profile = getattr(user, "profile", None)
    resume_text = profile.resume_text if profile else ""
    user_skills = _sorted_unique_skills(_latest_resume_skills(profile))
    user_lookup = normalize_skill_set(user_skills)
    if resume_text:
        required = _required_skills_for_profession(resume_text, user_skills)
    else:
        required = set()
    missing = sorted(
        {skill for skill in required if normalize_skill(skill) not in user_lookup},
        key=str.lower
    )
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else []
    missing_lookup = normalize_skill_set(missing)
    recommended = [
        item for item in resources
        if normalize_skill(item.get("skill", "")) in missing_lookup
    ]
    return {
        "user_skills": user_skills,
        "missing_skills": missing,
        "recommended_resources": recommended,
    }

# file path: apps/skillgap/services.py
import json

from django.conf import settings

from apps.jobs.models import JobPosting


def analyze_skill_gap(user):
    profile = getattr(user, "profile", None)
    user_skills = set(skill.lower() for skill in (profile.skills if profile else []))
    required = set()
    for job in JobPosting.objects.filter(is_active=True)[:50]:
        required.update(skill.lower() for skill in (job.required_skills or []))
    missing = sorted(required - user_skills)
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else []
    recommended = [item for item in resources if item.get("skill", "").lower() in missing]
    return {
        "user_skills": sorted(user_skills),
        "missing_skills": missing,
        "recommended_resources": recommended,
    }

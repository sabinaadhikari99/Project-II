from datetime import datetime
from urllib.parse import quote

from django.conf import settings

from .analysis_memo import run_once
from .cache import get_cached, set_cached
from .career import CareerAnalyzer
from .catalog import (
    BASE_HOURS,
    SKILL_FAMILY_ALIASES,
    get_course_entry,
    get_skill_difficulty,
    is_skill_relevant,
)
from .models import CourseRecommendation

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
LEVEL_FACTORS = {"junior": 1.2, "mid": 1.0, "senior": 0.85}
DIFFICULTY_RANK = {"beginner": 1, "intermediate": 2, "advanced": 3}
JUNIOR_MAX_DIFFICULTY = "intermediate"

TOP_COURSES = 5

LINKEDIN_SEARCH = "https://www.linkedin.com/learning/search?keywords={query}"
COURSERA_SEARCH = "https://www.coursera.org/search?query={query}"
UDEMY_SEARCH = "https://www.udemy.com/courses/search/?q={query}"

PROVIDER_BY_PROFESSION = {
    "Data Scientist": ("Coursera", COURSERA_SEARCH),
    "Machine Learning Engineer": ("Coursera", COURSERA_SEARCH),
    "Data Engineer": ("Coursera", COURSERA_SEARCH),
    "Data Analyst": ("Coursera", COURSERA_SEARCH),
    "Software Engineer": ("Coursera", COURSERA_SEARCH),
    "DevOps Engineer": ("Udemy", UDEMY_SEARCH),
    "Cybersecurity Engineer": ("Udemy", UDEMY_SEARCH),
    "Backend Developer": ("Udemy", UDEMY_SEARCH),
    "Full Stack Developer": ("Udemy", UDEMY_SEARCH),
}

DEFAULT_PROVIDER = ("LinkedIn Learning", LINKEDIN_SEARCH)

OUTCOMES = {
    "beginner": "Master the fundamentals of {skill} and apply it confidently to entry-level {role} work.",
    "intermediate": "Build practical, portfolio-ready expertise in {skill} and integrate it into real {role} workflows.",
    "advanced": "Reach expert-level command of {skill} and apply it to complex, production-grade {role} challenges.",
}


class CourseRecommendationService:
    def __init__(self, context=None):
        self.context = context

    @classmethod
    def get_or_generate(cls, user, force=False):
        context = run_once(user, lambda: CareerAnalyzer.analyze(user))
        service = cls(context)
        if not context.resume_text or not context.has_skills:
            return service._response([])
        cached = get_cached("courses", user.id, context.resume_text)
        if cached is not None and not force:
            return cached
        existing = CourseRecommendation.objects.filter(
            user=user, resume_hash=context.resume_hash
        ).first()
        if existing is not None and not force:
            response = service._response(existing.payload, existing.updated_at)
        else:
            courses = service.generate()
            obj, _ = CourseRecommendation.objects.update_or_create(
                user=user,
                resume_hash=context.resume_hash,
                defaults={
                    "profession": context.profession,
                    "career_level": context.career_level,
                    "payload": courses,
                },
            )
            CourseRecommendation.objects.filter(user=user).exclude(pk=obj.pk).delete()
            response = service._response(courses, obj.updated_at)
        set_cached("courses", user.id, context.resume_text, response)
        return response

    def generate(self):
        courses = []
        for info in self._rank_missing_skills()[:TOP_COURSES]:
            courses.append(self._build_course(info))
        return courses

    def _rank_missing_skills(self):
        context = self.context
        relevant = [
            info for info in context.missing_skills
            if is_skill_relevant(info["skill_key"], context.user_skills_norm)
        ] or list(context.missing_skills)
        seen_families = set()
        ranked = []
        for info in sorted(relevant, key=self._rank_key):
            family = SKILL_FAMILY_ALIASES.get(info["skill_key"], info["skill_key"])
            if family in seen_families:
                continue
            seen_families.add(family)
            ranked.append(info)
        return ranked

    @staticmethod
    def _rank_key(info):
        return (
            0 if info.get("profession_weight") else 1,
            -int(info.get("importance", 0)),
            -int(info.get("job_count", 0)),
            PRIORITY_ORDER.get(info.get("priority"), 2),
            info["skill_key"],
        )

    def _build_course(self, info):
        context = self.context
        entry = get_course_entry(info["skill_key"]) or self._fallback_entry(info)
        difficulty = self._adjusted_difficulty(entry["difficulty"])
        hours = max(4, round(entry["hours"] * LEVEL_FACTORS[context.career_level] / 2) * 2)
        role = context.profession or "your target role"
        return {
            "course_title": entry["title"],
            "skill_covered": info["skill"],
            "missing_skill": info["skill"],
            "provider": entry["provider"],
            "difficulty": difficulty,
            "estimated_duration": {
                "hours": hours,
                "weeks": round(hours / settings.SKILLGAP_WEEKLY_HOURS, 1),
            },
            "priority": info["priority"],
            "why_recommended": self._why_recommended(info, role),
            "learning_outcome": OUTCOMES[difficulty].format(skill=info["skill"], role=role),
            "url": entry["url"],
            "is_free": bool(entry["free"]),
            "importance": info["importance"],
            "job_demand": info["job_count"],
        }

    def _fallback_entry(self, info):
        context = self.context
        profession = context.profession or ""
        provider, search = PROVIDER_BY_PROFESSION.get(profession, DEFAULT_PROVIDER)
        role = f"{profession}s" if profession and not profession.endswith("s") else (profession or "Professionals")
        query = quote(info["skill"])
        difficulty = get_skill_difficulty(info["skill_key"])
        return {
            "title": f"{info['skill']} for {role}",
            "provider": provider,
            "url": search.format(query=query),
            "difficulty": difficulty,
            "hours": BASE_HOURS[difficulty],
            "free": False,
        }

    def _adjusted_difficulty(self, difficulty):
        context = self.context
        if context.career_level == "junior":
            if DIFFICULTY_RANK[difficulty] > DIFFICULTY_RANK[JUNIOR_MAX_DIFFICULTY]:
                return JUNIOR_MAX_DIFFICULTY
        return difficulty

    def _why_recommended(self, info, role):
        context = self.context
        base = f"{info['skill']} is a {info['priority']}-priority gap for {role} roles"
        if info["job_count"]:
            return (
                f"{base} — required by {info['job_count']} active job posting"
                f"{'s' if info['job_count'] != 1 else ''} and rated {info['importance']}/10 in importance."
            )
        return f"{base}, rated {info['importance']}/10 in importance."

    def _response(self, courses, generated_at=None):
        context = self.context
        return {
            "profession": context.profession,
            "career_level": context.career_level_label,
            "courses": courses,
            "generated_at": generated_at.isoformat() if generated_at else None,
            "has_resume": bool(context.resume_text),
        }

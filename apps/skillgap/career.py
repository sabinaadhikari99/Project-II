import hashlib
from collections import Counter
from dataclasses import dataclass, field

from apps.jobs.models import JobPosting
from apps.jobs.services import compute_match_score, extract_resume_skills
from apps.shared.profession_classifier import (
    PROFESSION_CONFIGS,
    classify_profession_with_resume,
    get_related_profession_titles,
)
from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set

CAREER_LABELS = {"junior": "Junior", "mid": "Mid-Level", "senior": "Senior"}
EDUCATION_LABELS = {
    "phd": "PhD",
    "master": "Master's Degree",
    "bachelor": "Bachelor's Degree",
    "diploma": "Diploma / Associate Degree",
    "unknown": "Not specified",
}
JOB_POOL_LIMIT = 100
JOB_POOL_RANK_LIMIT = 6


@dataclass
class CareerContext:
    user: object
    profile: object
    resume_text: str
    resume_hash: str
    user_skills: list = field(default_factory=list)
    user_skills_norm: set = field(default_factory=set)
    profession: str = ""
    profession_score: int = 0
    career_level: str = "junior"
    career_level_label: str = "Junior"
    experience_years: float = 0
    education_level: str = "unknown"
    education_label: str = "Not specified"
    jobs: list = field(default_factory=list)
    recommended_jobs: list = field(default_factory=list)
    match_score: int = 0
    match_explanation: dict = field(default_factory=dict)
    missing_skills: list = field(default_factory=list)
    missing_names: list = field(default_factory=list)

    @property
    def has_skills(self):
        return bool(self.user_skills_norm)

    @property
    def has_gaps(self):
        return bool(self.missing_skills)


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


def _career_level_for_experience(years):
    if not years:
        return "junior"
    if years < 2:
        return "junior"
    if years <= 5:
        return "mid"
    return "senior"


def _education_level(text):
    lowered = (text or "").lower()
    if any(token in lowered for token in ("phd", "ph.d", "doctorate", "doctoral")):
        return "phd"
    if any(token in lowered for token in ("master", "m.sc", "msc", "mba", "m.tech", "m.e.")):
        return "master"
    if any(token in lowered for token in ("bachelor", "b.sc", "bsc", "b.tech", "b.e.", "degree", "b.com", "ba ")):
        return "bachelor"
    if any(token in lowered for token in ("diploma", "associate", "hnd", "certificate")):
        return "diploma"
    return "unknown"


class CareerAnalyzer:
    @classmethod
    def analyze(cls, user):
        profile = getattr(user, "profile", None)
        resume_text = (profile.resume_text if profile else "") or ""
        resume_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()

        extracted = extract_resume_skills(resume_text) if resume_text else []
        profile_skills = list(profile.skills or []) if profile else []
        user_skills = _sorted_unique_skills(profile_skills + extracted)
        user_skills_norm = normalize_skill_set(user_skills)

        profession, profession_score = cls._classify(resume_text, user_skills, user_skills_norm)
        jobs = cls._profession_jobs(profession, user_skills_norm)

        ranked = cls._rank_jobs(jobs, user_skills, user_skills_norm, profile, profession)
        recommended_jobs = [
            {
                "title": job.title,
                "company": job.company,
                "match_percentage": percentage,
                "missing_skills_count": missing_count,
                "match_explanation": explanation,
            }
            for job, percentage, missing_count, explanation in ranked
        ]
        top_required_norm = set()
        for _, _, _, explanation in ranked:
            if explanation.get("skills_match", 0) > 0:
                top_required_norm.update(
                    normalize_skill_set(explanation.get("_required_skills", []))
                )

        required_raw = []
        for job in jobs:
            required_raw.extend(
                skill for skill in (job.required_skills or [])
                if isinstance(skill, str) and skill.strip()
            )
        raw_by_norm = {}
        for raw in required_raw:
            key = normalize_skill(raw)
            raw_by_norm.setdefault(key, raw)
        frequency = Counter(normalize_skill(raw) for raw in required_raw)
        required_norm = set(frequency)
        missing_norm = sorted(required_norm - user_skills_norm, key=str.lower)

        config_skills = PROFESSION_CONFIGS.get(profession, {}).get("skills", {}) if profession else {}
        config_weights = {normalize_skill(name): weight for name, weight in config_skills.items()}
        job_count = len(jobs) or 1

        missing_skills = []
        for norm in missing_norm:
            weight = config_weights.get(norm, 0)
            count = frequency[norm]
            share = count / job_count
            if weight == 0:
                share *= 0.5
            importance = weight or round(3 + share * 7)
            if norm in top_required_norm:
                importance = max(importance, 8)
            priority = "high" if importance >= 8 or share >= 0.5 else (
                "medium" if importance >= 5 or share >= 0.25 else "low"
            )
            missing_skills.append({
                "skill": raw_by_norm.get(norm, norm),
                "skill_key": norm,
                "importance": importance,
                "priority": priority,
                "job_count": count,
                "profession_weight": weight,
            })

        experience_years = float(getattr(profile, "experience_years", 0) or 0) if profile else 0
        career_level = _career_level_for_experience(experience_years)
        education_level = _education_level(getattr(profile, "education", "") if profile else "")

        best_match = recommended_jobs[0] if recommended_jobs else {}

        return CareerContext(
            user=user,
            profile=profile,
            resume_text=resume_text,
            resume_hash=resume_hash,
            user_skills=user_skills,
            user_skills_norm=user_skills_norm,
            profession=profession or "",
            profession_score=profession_score,
            career_level=career_level,
            career_level_label=CAREER_LABELS[career_level],
            experience_years=experience_years,
            education_level=education_level,
            education_label=EDUCATION_LABELS[education_level],
            jobs=jobs,
            recommended_jobs=recommended_jobs,
            match_score=best_match.get("match_percentage", 0),
            match_explanation=best_match.get("match_explanation", {}),
            missing_skills=missing_skills,
            missing_names=[item["skill"] for item in missing_skills],
        )

    @classmethod
    def _classify(cls, resume_text, user_skills, user_skills_norm):
        if not user_skills_norm:
            return None, 0
        return classify_profession_with_resume(resume_text, extracted_skills=user_skills)

    @classmethod
    def _profession_jobs(cls, profession, user_skills_norm):
        queryset = JobPosting.objects.filter(is_active=True)
        if profession:
            titles = get_related_profession_titles(profession)
            jobs = list(
                queryset.filter(job_category__in=titles).only(
                    "id", "title", "company", "required_skills"
                )[:JOB_POOL_LIMIT]
            )
            if jobs:
                return jobs
        return list(queryset.only("id", "title", "company", "required_skills")[:JOB_POOL_LIMIT])

    @classmethod
    def _rank_jobs(cls, jobs, user_skills, user_skills_norm, profile, user_profession):
        scored = []
        for job in jobs:
            result = compute_match_score(
                user_skills=user_skills,
                user_profession=user_profession,
                profile=profile,
                job=job,
                vector_score=0.0,
            )
            percentage = result["final_score"]
            explanation = result["match_explanation"]
            explanation["_required_skills"] = list(job.required_skills or [])
            scored.append((job, percentage, result["missing_count"], explanation))
        scored.sort(key=lambda item: (-item[1], item[2]))
        return scored[:JOB_POOL_RANK_LIMIT]

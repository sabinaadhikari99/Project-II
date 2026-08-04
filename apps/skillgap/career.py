import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field

from apps.jobs.models import JobPosting
from apps.jobs.services import compute_match_score, extract_resume_skills
from apps.shared.constants import JOB_VECTOR_PREFIX
from apps.shared.cv_signals import extract_cv_signals
from apps.shared.embedding_client import get_embedding
from apps.shared.profession_classifier import (
    PROFESSION_CONFIGS,
    classify_profession_with_resume,
    extract_resume_sections,
    get_related_profession_titles,
)
from apps.shared.skill_normalizer import normalize_skill, normalize_skill_set
from apps.shared.specializations import (
    detect_specialization,
    get_adjacent_parents,
    get_core_skills,
)
from apps.shared.vector_db import get_vector_manager

logger = logging.getLogger(__name__)

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

#: How many of the BEST-MATCHED jobs define the skill gap.
#: Gaps used to be taken from the union of required_skills across the entire
#: 100-job pool, which produced a near-identical "everything you don't know"
#: list for every candidate - the root cause of identical gaps, courses and
#: roadmaps across different CVs.
GAP_JOB_LIMIT = 3

#: Below this many on-profession postings we top up with semantically similar
#: roles from ADJACENT categories only, flagged as related.
MIN_DIRECT_JOBS = 4
RELATED_JOB_LIMIT = 4


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
    #: Fine-grained role detected from the CV (e.g. "Flutter Developer").
    #: `profession` stays coarse so job filtering and the existing APIs are
    #: unchanged; `specialization` is what makes gaps/courses/roadmap specific.
    specialization: str = ""
    specialization_score: int = 0
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
    #: Gaps bucketed by urgency: critical / important / optional / future.
    gap_categories: dict = field(default_factory=dict)
    #: Coverage + readiness percentages driving the skill-gap dashboard.
    coverage: dict = field(default_factory=dict)
    #: Parsed CV evidence, reused by callers instead of re-parsing the text.
    signals: dict = field(default_factory=dict)

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

        sections = extract_resume_sections(resume_text) if resume_text else None
        specialization, specialization_score = (
            detect_specialization(resume_text, user_skills, profession, sections)
            if profession else ("", 0)
        )

        jobs, related_ids = cls._profession_jobs(profession, specialization, resume_text)

        ranked = cls._rank_jobs(jobs, user_skills, user_skills_norm, profile, profession, resume_text)
        recommended_jobs = [
            {
                "title": job.title,
                "company": job.company,
                "match_percentage": percentage,
                "missing_skills_count": missing_count,
                "match_explanation": explanation,
                "is_related_role": job.id in related_ids,
            }
            for job, percentage, missing_count, explanation in ranked
        ]

        # ------------------------------------------------------------------
        # Skill gap universe
        # ------------------------------------------------------------------
        # Only two things may define a gap:
        #   1. what the candidate's BEST-MATCHED jobs actually require, and
        #   2. the canonical skill set of their detected specialisation.
        # Everything else in the job pool is irrelevant to this candidate. This
        # is what makes a Flutter CV surface Firebase/Riverpod instead of React.
        top_jobs = [job for job, _, _, _ in ranked[:GAP_JOB_LIMIT]]
        gap_universe = {}
        job_required_norm = set()
        for job in top_jobs:
            for raw in (job.required_skills or []):
                if isinstance(raw, str) and raw.strip():
                    key = normalize_skill(raw)
                    gap_universe.setdefault(key, raw)
                    job_required_norm.add(key)
        for raw in get_core_skills(specialization):
            gap_universe.setdefault(normalize_skill(raw), raw)

        top_required_norm = set()
        for _, _, _, explanation in ranked:
            if explanation.get("skills_match", 0) > 0:
                top_required_norm.update(
                    normalize_skill_set(explanation.get("_required_skills", []))
                )

        # Demand counts still come from the whole on-profession pool so
        # "required by N postings" stays truthful, but they only annotate skills
        # that are already in the candidate-specific gap universe.
        required_raw = []
        for job in jobs:
            required_raw.extend(
                skill for skill in (job.required_skills or [])
                if isinstance(skill, str) and skill.strip()
            )
        raw_by_norm = dict(gap_universe)
        for raw in required_raw:
            raw_by_norm.setdefault(normalize_skill(raw), raw)
        frequency = Counter(normalize_skill(raw) for raw in required_raw)
        missing_norm = sorted(set(gap_universe) - user_skills_norm, key=str.lower)

        config_skills = PROFESSION_CONFIGS.get(profession, {}).get("skills", {}) if profession else {}
        config_weights = {normalize_skill(name): weight for name, weight in config_skills.items()}
        core_norm = {normalize_skill(s) for s in get_core_skills(specialization)}
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
            # A canonical skill of the detected specialisation is core to the
            # role even when the small local job pool happens not to list it.
            if norm in core_norm:
                importance = max(importance, 7)
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
                # "job"  -> an actual matched posting requires this
                # "core" -> canonical for the specialisation but not demanded by
                #           the current local postings. Job-readiness is judged
                #           on "job" gaps only, so canonical extras enrich the
                #           roadmap without ever making a qualified candidate
                #           look unqualified.
                "source": "job" if norm in job_required_norm else "core",
            })

        # Career level and education now come from the uploaded CV first, with
        # the profile columns only as a fallback. Previously both were read
        # exclusively from the profile, so uploading a different CV could not
        # change the career level, the education label, or any score derived
        # from them.
        signals = extract_cv_signals(resume_text)
        profile_years = float(getattr(profile, "experience_years", 0) or 0) if profile else 0
        experience_years = signals["experience_years"] or profile_years
        career_level = _career_level_for_experience(experience_years)
        education_level = signals["education_level"]
        if education_level == "unknown":
            education_level = _education_level(getattr(profile, "education", "") if profile else "")

        best_match = recommended_jobs[0] if recommended_jobs else {}

        # ------------------------------------------------------------------
        # Gap categorisation + readiness metrics (Phase 2 #7)
        # ------------------------------------------------------------------
        # "future" = canonical for the role but not demanded by the postings we
        # can currently see, so it is career investment rather than a blocker.
        gap_categories = {"critical": [], "important": [], "optional": [], "future": []}
        for info in missing_skills:
            if info["source"] == "core" and not info["job_count"]:
                bucket = "future"
            elif info["priority"] == "high":
                bucket = "critical"
            elif info["priority"] == "medium":
                bucket = "important"
            else:
                bucket = "optional"
            info["gap_category"] = bucket
            gap_categories[bucket].append(info["skill"])

        required_from_top = len(gap_universe) or 1
        covered = required_from_top - len(missing_norm)
        core_total = len(core_norm) or 0
        core_covered = len(core_norm & user_skills_norm) if core_total else 0

        coverage = {
            # How much of what the best-matched jobs ask for is already held.
            "current_skill_coverage": round(covered / required_from_top * 100),
            "missing_skill_coverage": round(len(missing_norm) / required_from_top * 100),
            # How much of the canonical role skill set is held.
            "industry_readiness": round(core_covered / core_total * 100) if core_total else 0,
            # Best achievable match against a real posting right now.
            "job_readiness": best_match.get("match_percentage", 0),
            "critical_gap_count": len(gap_categories["critical"]),
            "total_gap_count": len(missing_skills),
        }

        return CareerContext(
            user=user,
            profile=profile,
            resume_text=resume_text,
            resume_hash=resume_hash,
            user_skills=user_skills,
            user_skills_norm=user_skills_norm,
            profession=profession or "",
            profession_score=profession_score,
            specialization=specialization or profession or "",
            specialization_score=specialization_score,
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
            gap_categories=gap_categories,
            coverage=coverage,
            signals=signals,
        )

    @classmethod
    def _classify(cls, resume_text, user_skills, user_skills_norm):
        if not user_skills_norm:
            return None, 0
        return classify_profession_with_resume(resume_text, extracted_skills=user_skills)

    @classmethod
    def _profession_jobs(cls, profession, specialization, resume_text):
        """On-profession postings, topped up with adjacent roles when thin.

        Returns (jobs, related_ids). Previously this fell back to the ENTIRE job
        table whenever the profession filter came up empty, which flooded a
        designer or analyst with backend postings and poisoned their skill gap
        with the whole catalogue. The fallback is now restricted to the
        specialisation's declared adjacent categories and ranked semantically,
        so the list is never empty and never crosses fields.
        """
        queryset = JobPosting.objects.filter(is_active=True)
        if not profession:
            return [], set()

        # NB: embedding_text is a model PROPERTY, not a column - never .only() it.
        fields = ("id", "title", "company", "required_skills", "job_category",
                  "experience_required", "education_required")
        titles = get_related_profession_titles(profession)
        direct = list(
            queryset.filter(job_category__in=titles).only(*fields)[:JOB_POOL_LIMIT]
        )
        if len(direct) >= MIN_DIRECT_JOBS:
            return direct, set()

        adjacent = set(get_adjacent_parents(specialization)) | set(titles)
        adjacent.discard(None)
        extra = list(
            queryset.filter(job_category__in=adjacent)
            .exclude(id__in=[job.id for job in direct])
            .only(*fields)[:JOB_POOL_LIMIT]
        )
        if not extra:
            return direct, set()

        related = cls._semantic_top(extra, resume_text, RELATED_JOB_LIMIT)
        return direct + related, {job.id for job in related}

    @classmethod
    def _semantic_top(cls, jobs, resume_text, limit):
        """Rank `jobs` by embedding similarity to the CV, best first."""
        if not resume_text or not jobs:
            return jobs[:limit]
        scores = cls._vector_scores(resume_text, len(jobs) * 2)
        if not scores:
            return jobs[:limit]
        return sorted(jobs, key=lambda j: -scores.get(j.id, 0.0))[:limit]

    @staticmethod
    def _vector_scores(resume_text, top_k):
        """FAISS similarity of the CV against indexed job postings.

        The skill-gap path used to hardcode vector_score=0.0, so the semantic
        component of every match score was a constant zero and the existing
        vector index was never consulted here at all.
        """
        if not resume_text:
            return {}
        try:
            matches = get_vector_manager().search_similar(
                get_embedding(resume_text),
                top_k=max(10, min(top_k, 100)),
                prefix=f"{JOB_VECTOR_PREFIX}:",
            )
        except Exception:
            logger.warning("CareerAnalyzer: vector search unavailable", exc_info=True)
            return {}
        scores = {}
        for object_id, score in matches:
            try:
                scores[int(str(object_id).split(":")[1])] = score
            except (IndexError, ValueError):
                continue
        return scores

    @classmethod
    def _rank_jobs(cls, jobs, user_skills, user_skills_norm, profile, user_profession, resume_text=""):
        vector_scores = cls._vector_scores(resume_text, len(jobs) * 2) if jobs else {}
        cv_signals = extract_cv_signals(resume_text)
        scored = []
        for job in jobs:
            result = compute_match_score(
                user_skills=user_skills,
                user_profession=user_profession,
                profile=profile,
                job=job,
                vector_score=vector_scores.get(job.id, 0.0),
                cv_signals=cv_signals,
            )
            percentage = result["final_score"]
            explanation = result["match_explanation"]
            explanation["_required_skills"] = list(job.required_skills or [])
            scored.append((job, percentage, result["missing_count"], explanation))
        scored.sort(key=lambda item: (-item[1], item[2]))
        return scored[:JOB_POOL_RANK_LIMIT]

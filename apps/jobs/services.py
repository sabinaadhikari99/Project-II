import json
import logging
import re

from django.conf import settings
from django.db import transaction

from apps.notifications.services import send_application_email
from apps.notifications.services import notify_job_match
from apps.shared.constants import JOB_VECTOR_PREFIX, PROFILE_VECTOR_PREFIX
from apps.shared.embedding_client import get_embedding
from apps.shared.pdf_utils import extract_pdf_text
from apps.shared.profession_classifier import (
    classify_job,
    classify_profession_from_skills,
    classify_profession_with_resume,
    get_related_profession_titles,
    normalize_skill,
    SKILL_SYNONYMS,
    PROFESSION_CONFIGS,
)
from apps.shared.skill_normalizer import normalize_skill as norm_skill, normalize_skill_set
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
    "profession": float(getattr(settings, "AI_WEIGHT_PROFESSION", 35)),
    "skills": float(getattr(settings, "AI_WEIGHT_SKILLS", 30)),
    "experience": float(getattr(settings, "AI_WEIGHT_EXPERIENCE", 15)),
    "education": float(getattr(settings, "AI_WEIGHT_EDUCATION", 10)),
    "semantic": float(getattr(settings, "AI_WEIGHT_SEMANTIC", 10)),
}

AI_MATCH_THRESHOLD = int(getattr(settings, "AI_MATCH_THRESHOLD", 70))
AI_MATCH_NOTIFICATION_THRESHOLD = int(getattr(settings, "AI_MATCH_NOTIFICATION_THRESHOLD", 80))


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


def recommend_jobs_for_user(user, limit=10, request=None, resume_text=None):
    profile = getattr(user, "profile", None)
    if not profile:
        return []

    user_skills = profile.skills or []
    if resume_text:
        user_profession, profession_conf = classify_profession_with_resume(
            resume_text, extracted_skills=user_skills,
        )
        is_debug = getattr(settings, "AI_MATCH_DEBUG", False)
        if is_debug:
            logger.info(
                "Hybrid classify: profession=%s confidence=%d skills=%s",
                user_profession, profession_conf, user_skills,
            )
    else:
        user_profession = classify_profession_from_skills(user_skills)

    if not user_profession:
        return []
    profession_titles = get_related_profession_titles(user_profession)

    is_debug = getattr(settings, "AI_MATCH_DEBUG", False)
    if is_debug:
        logger.info(
            "Job filter: profession=%s related=%s",
            user_profession, profession_titles,
        )

    candidate_jobs = JobPosting.objects.filter(
        is_active=True,
        job_category__in=profession_titles,
    )
    if not candidate_jobs.exists():
        if is_debug:
            logger.info("No candidate jobs found for categories: %s", profession_titles)
        return []

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


def _hybrid_rank_jobs(user, profile, user_skills, user_profession, candidate_jobs, limit, request=None, resume_text=None):
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

    scored_jobs = []
    for job in candidate_jobs:
        vector_score = vector_scores.get(job.id, 0.0)
        result = _compute_weighted_score(
            user_skills=user_skills,
            user_profession=user_profession,
            profile=profile,
            job=job,
            vector_score=vector_score,
        )
        scored_jobs.append(result)

    scored_jobs.sort(key=lambda x: x["final_score"], reverse=True)
    return scored_jobs[:limit]


def _compute_weighted_score(user_skills, user_profession, profile, job, vector_score):
    user_profession_lower = user_profession.lower() if user_profession else ""

    job_profession = (job.job_category or "").lower()
    profession_match = 1.0 if user_profession_lower == job_profession else 0.3
    related = {p.lower() for p in get_related_profession_titles(user_profession or "")}
    if job_profession in related:
        profession_match = 0.7
    profession_score = round(profession_match * 100)

    required = normalize_skill_set(job.required_skills or [])
    user_skills_norm = normalize_skill_set(user_skills)
    if required:
        matched_skills = user_skills_norm & required
        skills_pct = len(matched_skills) / len(required)
    else:
        skills_pct = 0.5
    skills_score = round(skills_pct * 100)

    user_exp = float(getattr(profile, "experience_years", 0) or 0)
    job_exp = float(job.experience_required or 0)
    if job_exp == 0:
        exp_pct = 1.0
    else:
        exp_pct = 1.0 if user_exp >= job_exp else max(0.1, user_exp / job_exp)
    experience_score = round(exp_pct * 100)

    user_education = (getattr(profile, "education", "") or "").lower()
    job_education = (getattr(job, "education_required", "") or "").lower()
    if not job_education:
        education_pct = 0.7
    elif user_education and (job_education in user_education or user_education in job_education):
        education_pct = 1.0
    else:
        education_pct = 0.3
    education_score = round(education_pct * 100)

    semantic_pct = max(0.0, min(float(vector_score), 1.0))
    semantic_score = round(semantic_pct * 100)

    w = SCORE_WEIGHTS
    total_weight = w["profession"] + w["skills"] + w["experience"] + w["education"] + w["semantic"]
    final_score = round(
        (profession_score * w["profession"]
         + skills_score * w["skills"]
         + experience_score * w["experience"]
         + education_score * w["education"]
         + semantic_score * w["semantic"])
        / total_weight
    )
    final_score = max(1, min(final_score, 100))

    match_explanation = {
        "profession_match": profession_score,
        "skills_match": skills_score,
        "experience_match": experience_score,
        "education_match": education_score,
        "semantic_similarity": semantic_score,
        "final_score": final_score,
    }

    return {
        "job": job,
        "score": final_score / 100,
        "final_score": final_score,
        "profession_match": profession_score,
        "skills_score": skills_score,
        "experience_score": experience_score,
        "education_score": education_score,
        "semantic_score": semantic_score,
        "match_explanation": match_explanation,
    }


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
        merged_skills = sorted(set(profile.skills or []) | set(extracted_skills))
        profile.skills = merged_skills
        profile.save()

        user_profession, profession_conf = classify_profession_with_resume(
            resume_text, extracted_skills=merged_skills,
        )
        is_debug = getattr(settings, "AI_MATCH_DEBUG", False)
        if is_debug:
            logger.info(
                "Resume analysis: profession=%s confidence=%d skills=%d",
                user_profession, profession_conf, len(merged_skills),
            )

        recommendations = recommend_jobs_for_user(
            user, limit=10, request=request, resume_text=resume_text,
        )
        missing_skills = sorted({skill for item in recommendations for skill in item["missing_skills"]})
        resources = _resources_for_skills(missing_skills)
        gemini = _gemini_resume_insights(resume_text, extracted_skills, missing_skills, recommendations)
        best_match = max([item["match_percentage"] for item in recommendations], default=0)

        return {
            "profession": user_profession or "Not determined",
            "resume_summary": gemini["resume_summary"],
            "resume_score": best_match,
            "skills_extracted": extracted_skills,
            "missing_skills": missing_skills,
            "skill_gap_analysis": gemini["skill_gap_analysis"],
            "recommended_courses": resources,
            "recommended_jobs": recommendations,
            "match_analytics": [
                {
                    "title": item["job"].title,
                    "company": item["job"].company,
                    "match_percentage": item["match_percentage"],
                }
                for item in recommendations[:6]
            ],
            "learning_roadmap": gemini["learning_roadmap"],
            "resume_insights": gemini["resume_insights"],
            "resume_improvement_suggestions": gemini["resume_improvement_suggestions"],
        }
    except ValueError:
        raise
    except Exception:
        logger.exception("analyze_resume_match: unexpected error for user %s", user.id)
        return {
            "profession": "",
            "resume_summary": "",
            "resume_score": 0,
            "skills_extracted": [],
            "missing_skills": [],
            "skill_gap_analysis": "",
            "recommended_courses": [],
            "recommended_jobs": [],
            "match_analytics": [],
            "learning_roadmap": [],
            "resume_insights": [],
            "resume_improvement_suggestions": [],
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


def _build_recommendation(user, profile, job, vector_score, match_explanation=None, request=None):
    user_skills = normalize_skill_set(profile.skills or [])
    required_skills = list(job.required_skills or [])
    required_lookup = normalize_skill_set(required_skills)
    matched_lookup = user_skills & required_lookup
    matched_skills = [skill for skill in required_skills if norm_skill(skill) in matched_lookup]
    missing_skills = [skill for skill in required_skills if norm_skill(skill) not in matched_lookup]

    exp = getattr(profile, "experience_years", 0) or 0
    gap = ""
    if missing_skills:
        gap = f"Focus on {', '.join(missing_skills[:4])} to improve fit for this role."
    else:
        gap = "Your listed skills cover the major requirements for this role."

    resources = _resources_for_skills(missing_skills)
    roadmap = _roadmap_for(missing_skills, job)
    match_pct = match_explanation.get("final_score", 50) if match_explanation else 50

    return {
        "job": job,
        "score": match_pct / 100,
        "match_percentage": match_pct,
        "required_skills": required_skills,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "skill_gap_analysis": gap,
        "career_roadmap": roadmap,
        "recommended_resources": resources,
        "match_explanation": match_explanation or {},
    }


def _resources_for_skills(skills):
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else []
    missing = normalize_skill_set(skills)
    return [item for item in resources if norm_skill(item.get("skill", "")) in missing]


def _gemini_resume_insights(resume_text, skills, missing_skills, recommendations):
    fallback = {
        "resume_summary": _fallback_summary(resume_text, skills),
        "skill_gap_analysis": (
            f"Primary gaps based on active jobs: {', '.join(missing_skills[:6])}."
            if missing_skills else "Your resume covers the most common requirements in the current active jobs."
        ),
        "learning_roadmap": _roadmap_for(missing_skills, recommendations[0]["job"]) if recommendations else [
            "Add a clear target role and measurable project outcomes.",
            "Build one portfolio project aligned to your target job family.",
            "Apply to roles that match your strongest listed skills.",
        ],
        "resume_insights": [
            "Keep the resume focused on verified skills and project outcomes.",
            "Add measurable impact where possible, such as users, revenue, accuracy, speed, or time saved.",
        ],
        "resume_improvement_suggestions": [
            "Add a concise professional summary at the top.",
            "Group technical skills by category.",
            "Use action verbs and measurable outcomes in project bullets.",
        ],
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
                "missing_skills": item["missing_skills"],
            }
            for item in recommendations[:5]
        ]
        prompt = f"""
You are an expert AI Career Coach. Analyze this resume using only the provided resume text.
Return strict JSON with keys:
resume_summary, skill_gap_analysis, learning_roadmap, resume_insights, resume_improvement_suggestions.
learning_roadmap, resume_insights, and resume_improvement_suggestions must be arrays of short strings.

Resume text:
{resume_text}

Extracted skills:
{skills}

Missing skills:
{missing_skills}

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


def _fallback_summary(resume_text, skills):
    first_line = next((line.strip() for line in resume_text.splitlines() if line.strip()), "")
    skill_text = ", ".join(skills[:8]) if skills else "skills listed in the resume"
    return f"{first_line or 'The candidate'} presents experience around {skill_text}. Recommendations are based on the uploaded resume and active job requirements."


def _roadmap_for(missing_skills, job):
    if not missing_skills:
        return [
            "Polish one portfolio case study that proves your fit for this role.",
            "Prepare interview stories around the listed responsibilities.",
            "Apply now and tailor your cover letter to the company context.",
        ]
    return [
        f"Week 1-2: Learn the fundamentals of {', '.join(missing_skills[:2])}.",
        "Week 3-4: Build a small project using the missing skills in a realistic workflow.",
        f"Week 5: Update your resume with a project aligned to {job.title}.",
        "Week 6: Apply to similar roles and practice interview questions around the new skills.",
    ]


def _application_link(job, request):
    path = f"/jobs/?title={job.title.replace(' ', '+')}"
    if request:
        return request.build_absolute_uri(path)
    return path

import json
import re

from django.conf import settings
from django.db import transaction

from apps.src.job_recommendation import rank_jobs_for_user
from apps.notifications.services import send_application_email
from apps.notifications.services import notify_job_match
from apps.shared.constants import JOB_VECTOR_PREFIX, PROFILE_VECTOR_PREFIX
from apps.shared.embedding_client import get_embedding
from apps.shared.pdf_utils import extract_pdf_text
from apps.shared.vector_db import get_vector_manager

from .models import Application, JobPosting


COMMON_SKILLS = [
    "Python", "Django", "Django REST Framework", "DRF", "FastAPI", "JavaScript",
    "React", "Bootstrap", "HTML", "CSS", "SQL", "SQLite", "PostgreSQL", "MySQL",
    "Pandas", "NumPy", "Machine Learning", "NLP", "FAISS", "APIs", "Git",
    "Docker", "AWS", "Excel", "Power BI", "Communication", "Leadership",
]


def create_job_with_embedding(recruiter, data) -> JobPosting:
    with transaction.atomic():
        job = JobPosting.objects.create(recruiter=recruiter, **data)
        get_vector_manager().update_embedding(f"{JOB_VECTOR_PREFIX}:{job.id}", get_embedding(job.embedding_text))
    return job


def update_job_embedding(job: JobPosting):
    get_vector_manager().update_embedding(f"{JOB_VECTOR_PREFIX}:{job.id}", get_embedding(job.embedding_text))


def recommend_jobs_for_user(user, limit=10, request=None):
    profile = getattr(user, "profile", None)
    if not profile:
        return []

    ranked = rank_jobs_for_user(user, limit=limit)
    if not ranked:
        ranked = [{"job": job, "score": 0.45} for job in JobPosting.objects.filter(is_active=True)[:limit]]

    recommendations = []
    for item in ranked:
        recommendation = _build_recommendation(user, profile, item["job"], item.get("score", 0), request)
        recommendations.append(recommendation)
        if recommendation["match_percentage"] >= 80:
            notify_job_match(
                user,
                item["job"],
                recommendation["match_percentage"],
                recommendation["required_skills"],
                _application_link(item["job"], request),
            )
    return sorted(recommendations, key=lambda row: row["match_percentage"], reverse=True)[:limit]


def match_candidates_for_job(job: JobPosting, limit=10):
    matches = get_vector_manager().search_similar(get_embedding(job.embedding_text), top_k=limit, prefix=f"{PROFILE_VECTOR_PREFIX}:")
    user_ids = [int(object_id.split(":")[1]) for object_id, _ in matches]
    from apps.accounts.models import User

    users = {user.id: user for user in User.objects.filter(id__in=user_ids).select_related("profile")}
    return [{"candidate": users[user_id], "score": score} for object_id, score in matches for user_id in [int(object_id.split(":")[1])] if user_id in users]


def apply_to_job(user, job, cover_letter=""):
    application, _ = Application.objects.get_or_create(job=job, applicant=user, defaults={"cover_letter": cover_letter})
    send_application_email(application)
    return application


def analyze_resume_match(user, resume_file, request=None):
    from apps.accounts.models import UserProfile

    resume_text = extract_pdf_text(resume_file)
    if len(resume_text.strip()) < 80:
        raise ValueError("The uploaded PDF text looks empty or unclear.")

    extracted_skills = extract_resume_skills(resume_text)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.resume_text = resume_text
    profile.skills = sorted(set(profile.skills or []) | set(extracted_skills))
    profile.save()

    recommendations = recommend_jobs_for_user(user, limit=10, request=request)
    missing_skills = sorted({skill for item in recommendations for skill in item["missing_skills"]})
    resources = _resources_for_skills(missing_skills)
    gemini = _gemini_resume_insights(resume_text, extracted_skills, missing_skills, recommendations)
    best_match = max([item["match_percentage"] for item in recommendations], default=0)

    return {
        "resume_summary": gemini["resume_summary"],
        "resume_score": best_match,
        "skills_extracted": extracted_skills,
        "missing_skills": missing_skills,
        "skill_gap_analysis": gemini["skill_gap_analysis"],
        "recommended_courses": resources,
        "recommended_jobs": recommendations,
        "match_analytics": [
            {"title": item["job"].title, "company": item["job"].company, "match_percentage": item["match_percentage"]}
            for item in recommendations[:6]
        ],
        "learning_roadmap": gemini["learning_roadmap"],
        "resume_insights": gemini["resume_insights"],
        "resume_improvement_suggestions": gemini["resume_improvement_suggestions"],
    }


def extract_resume_skills(resume_text):
    known = set(COMMON_SKILLS)
    for job in JobPosting.objects.filter(is_active=True).only("required_skills")[:100]:
        known.update(job.required_skills or [])

    lowered = resume_text.lower()
    extracted = []
    for skill in sorted(known, key=len, reverse=True):
        normalized = str(skill).strip()
        if not normalized:
            continue
        pattern = r"(?<![a-z0-9+#.])" + re.escape(normalized.lower()) + r"(?![a-z0-9+#.])"
        if re.search(pattern, lowered):
            extracted.append(normalized)
    return sorted(set(extracted), key=str.lower)


def _build_recommendation(user, profile, job, vector_score, request):
    user_skills = _normalize_skills(profile.skills or [])
    required_skills = list(job.required_skills or [])
    required_lookup = _normalize_skills(required_skills)
    matched_lookup = user_skills & required_lookup
    matched_skills = [skill for skill in required_skills if skill.lower() in matched_lookup]
    missing_skills = [skill for skill in required_skills if skill.lower() not in matched_lookup]

    skill_score = len(matched_lookup) / len(required_lookup) if required_lookup else 0.5
    vector_component = max(0.0, min(float(vector_score or 0), 1.0))
    experience = float(getattr(profile, "experience_years", 0) or 0)
    experience_score = 1.0 if experience >= float(job.experience_required or 0) else max(0.25, experience / max(float(job.experience_required or 1), 1.0))
    match_percentage = round((skill_score * 0.6 + vector_component * 0.25 + experience_score * 0.15) * 100)
    match_percentage = max(1, min(match_percentage, 100))

    resources = _resources_for_skills(missing_skills)
    roadmap = _roadmap_for(missing_skills, job)
    if missing_skills:
        gap = f"Focus on {', '.join(missing_skills[:4])} to improve fit for this role."
    else:
        gap = "Your listed skills cover the major requirements for this role."

    return {
        "job": job,
        "score": match_percentage / 100,
        "match_percentage": match_percentage,
        "required_skills": required_skills,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "skill_gap_analysis": gap,
        "career_roadmap": roadmap,
        "recommended_resources": resources,
    }


def _normalize_skills(skills):
    return {str(skill).strip().lower() for skill in skills if str(skill).strip()}


def _resources_for_skills(skills):
    resources_path = settings.DATA_DIR / "learning_resources.json"
    resources = json.loads(resources_path.read_text(encoding="utf-8")) if resources_path.exists() else []
    missing = _normalize_skills(skills)
    return [item for item in resources if item.get("skill", "").lower() in missing]


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

from apps.shared.constants import JOB_VECTOR_PREFIX
from apps.shared.embedding_client import get_embedding
from apps.shared.vector_db import get_vector_manager


def build_recommendation_text(profile) -> str:
    return " ".join([
        " ".join(profile.skills or []),
        profile.resume_text or "",
        profile.education or "",
        str(profile.experience_years or 0),
    ])


def rank_jobs_for_user(user, limit=10):
    profile = getattr(user, "profile", None)
    if not profile:
        return []

    from apps.jobs.models import JobPosting

    matches = get_vector_manager().search_similar(
        get_embedding(build_recommendation_text(profile)),
        top_k=limit,
        prefix=f"{JOB_VECTOR_PREFIX}:",
    )
    jobs = {
        job.id: job
        for job in JobPosting.objects.filter(
            id__in=[int(object_id.split(":")[1]) for object_id, _ in matches],
            is_active=True,
        )
    }
    return [
        {"job": jobs[job_id], "score": score}
        for object_id, score in matches
        for job_id in [int(object_id.split(":")[1])]
        if job_id in jobs
    ]

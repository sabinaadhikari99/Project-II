import hashlib

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max

from apps.shared.fingerprint import resume_fingerprint

#: How long the job-pool signature may be reused. It only exists to keep the
#: analysis fingerprint honest when recruiters post or retire roles, so a short
#: window is enough and costs one small aggregate per window instead of one per
#: request.
POOL_SIGNATURE_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Analysis fingerprint
# ---------------------------------------------------------------------------
def job_pool_signature():
    """Cheap signature of the active job pool.

    A skill gap is defined against live postings, so a new or retired role has
    to invalidate a stored analysis just as a new CV does.
    """
    cached = cache.get("skillgap_pool_signature")
    if cached is not None:
        return cached

    from apps.jobs.models import JobPosting

    stats = JobPosting.objects.filter(is_active=True).aggregate(
        total=Count("id"), latest=Max("created_at"),
    )
    signature = f"{stats['total'] or 0}:{stats['latest'].isoformat() if stats['latest'] else '-'}"
    cache.set("skillgap_pool_signature", signature, POOL_SIGNATURE_TIMEOUT)
    return signature


def analysis_fingerprint(user):
    """Identity of everything a career analysis is computed from.

    The CV alone is not enough: the analysis also reads the profile's skills,
    experience and education, and the pool of active jobs. Keying a cached
    analysis on the CV only would keep serving the previous answer after the
    user edited their profile or a recruiter posted a matching role.
    """
    profile = getattr(user, "profile", None)
    parts = [
        resume_fingerprint(getattr(profile, "resume_text", "") if profile else ""),
        "|".join(sorted(str(s).strip().lower() for s in (getattr(profile, "skills", None) or []))),
        str(getattr(profile, "experience_years", 0) or 0) if profile else "0",
        (getattr(profile, "education", "") or "") if profile else "",
        job_pool_signature(),
    ]
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()


def get_analysis_cached(kind, user_id, fingerprint):
    return cache.get(f"skillgap_v3_{kind}_{user_id}_{fingerprint}")


def set_analysis_cached(kind, user_id, fingerprint, payload):
    timeout = getattr(settings, "SKILLGAP_CACHE_TIMEOUT", 86400)
    cache.set(f"skillgap_v3_{kind}_{user_id}_{fingerprint}", payload, timeout)

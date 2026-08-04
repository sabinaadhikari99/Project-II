"""Single shared career analysis per user state.

``CareerAnalyzer.analyze`` is the expensive step: skill extraction, profession
classification, specialisation detection, embedding lookups and job ranking.
Three endpoints need it (gap, courses, roadmap) and they arrive as three
separate HTTP requests, so a per-request memo alone still ran the pipeline
three times for one page load.

Two tiers now cover both cases:

1. **Thread-local** - one analysis per request, exactly as before.
2. **Cache, keyed by analysis fingerprint** - the same analysis is reused
   across requests, page loads and sessions.

The fingerprint covers every input the analysis reads (CV, profile skills,
experience, education, and the active job pool), so a stored analysis is
served only while it would be recomputed identically. Upload a new CV, edit
your skills or let a recruiter post a matching role, and the key moves.
"""

import logging
import threading
from dataclasses import replace

from django.conf import settings
from django.core.cache import cache

from .cache import analysis_fingerprint

logger = logging.getLogger(__name__)

_local = threading.local()

CACHE_VERSION = "v2"


def _timeout():
    return getattr(settings, "CAREER_CONTEXT_CACHE_TIMEOUT", 86400)


def cache_key(user, fingerprint):
    return f"careerctx_{CACHE_VERSION}_{user.pk}_{fingerprint}"


def run_once(user, analyzer):
    """Return the CareerContext for this user, computing it once per state."""
    fingerprint = analysis_fingerprint(user)
    identity = (user.pk, fingerprint)

    # The per-request memo is validated against the fingerprint as well as the
    # user, so a worker thread reused by a later request can never hand back an
    # analysis of state that has since changed.
    entry = getattr(_local, "entry", None)
    if entry is not None and entry[0] == identity:
        return entry[1]

    shared = None
    try:
        shared = cache.get(cache_key(user, fingerprint))
    except Exception:  # pragma: no cover - a cache backend must never break analysis
        logger.warning("career context cache unavailable", exc_info=True)

    if shared is not None:
        # Re-attach the live user/profile instances: the cached copy carries the
        # objects from the request that computed it.
        context = replace(shared, user=user, profile=getattr(user, "profile", None))
        _local.entry = (identity, context)
        return context

    context = analyzer()
    try:
        cache.set(cache_key(user, fingerprint), context, _timeout())
    except Exception:  # pragma: no cover
        logger.warning("career context could not be cached", exc_info=True)
    _local.entry = (identity, context)
    return context


def clear():
    """Drop the per-request memo. The shared entry is fingerprinted and stays."""
    if hasattr(_local, "entry"):
        del _local.entry


def invalidate(user):
    """Drop the shared analysis for a user, e.g. to force a re-analysis."""
    clear()
    cache.delete(cache_key(user, analysis_fingerprint(user)))

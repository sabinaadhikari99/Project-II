import hashlib

from django.conf import settings
from django.core.cache import cache


def quiz_cache_key(user_id: int, resume_text: str) -> str:
    """
    Build a deterministic cache key for a user's quiz.

    Combines user_id with a hash of their resume text so that:
    - The same user + same resume always yields the same key (cache HIT).
    - A new resume produces a different key (cache MISS).
    - No timestamps or random values are included.
    """
    resume_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()
    return f"quiz_{user_id}_{resume_hash}"


def get_cached_quiz(cache_key: str) -> list | None:
    """Return the cached quiz questions list, or None if not found."""
    return cache.get(cache_key)


def set_cached_quiz(cache_key: str, questions: list) -> None:
    """Store quiz questions in cache with the configured timeout."""
    timeout = getattr(settings, "QUIZ_CACHE_TIMEOUT", 3600)
    cache.set(cache_key, questions, timeout)


def get_cache_timeout() -> int:
    """Return the configured quiz cache timeout in seconds."""
    return getattr(settings, "QUIZ_CACHE_TIMEOUT", 3600)

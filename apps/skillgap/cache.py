import hashlib

from django.conf import settings
from django.core.cache import cache


def resume_hash(resume_text):
    return hashlib.sha256((resume_text or "").encode("utf-8")).hexdigest()


def cache_key(kind, user_id, resume_text):
    return f"skillgap_v2_{kind}_{user_id}_{resume_hash(resume_text)}"


def get_cached(kind, user_id, resume_text):
    return cache.get(cache_key(kind, user_id, resume_text))


def set_cached(kind, user_id, resume_text, payload):
    timeout = getattr(settings, "SKILLGAP_CACHE_TIMEOUT", 86400)
    cache.set(cache_key(kind, user_id, resume_text), payload, timeout)

"""Canonical content fingerprints.

Several subsystems (skill gap cache, quiz cache, persistent analysis session)
independently hashed the CV text to decide "is this still the same CV?". They
must agree, otherwise the same upload produces different keys and the work is
recomputed. This module is the single implementation they all call.
"""

import hashlib


def resume_fingerprint(resume_text):
    """SHA-256 of the CV text. Stable for the same document, cheap to compute."""
    return hashlib.sha256((resume_text or "").encode("utf-8")).hexdigest()


def profile_resume_fingerprint(user):
    """Fingerprint of the CV currently stored on the user's profile.

    Returns ``""`` when the user has no CV yet, so callers can distinguish
    "no CV" from "CV that happens to hash to the empty digest".
    """
    profile = getattr(user, "profile", None)
    resume_text = (getattr(profile, "resume_text", "") or "") if profile else ""
    if not resume_text.strip():
        return ""
    return resume_fingerprint(resume_text)
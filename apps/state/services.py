"""Service layer for persistent user state.

Every read goes through a short-lived cache so restoring a page costs at most
one query per user, and every write invalidates that cache. Views never touch
the ORM for state directly - they call these services, which keeps the caching
and normalisation rules in one place.
"""

import json

from django.conf import settings
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from apps.shared.fingerprint import profile_resume_fingerprint

from .models import AnalysisSession, QuizSession, UIState

#: Cached state is authoritative only until the next write, which busts the key
#: explicitly. The TTL is a safety net for multi-process deployments.
STATE_CACHE_TIMEOUT = getattr(settings, "STATE_CACHE_TIMEOUT", 900)

#: Guard rail so a runaway client cannot push megabytes into the state table.
MAX_STATE_BYTES = 256 * 1024

#: Keys the client is allowed to create. Everything the product persists is
#: listed here; unknown keys are rejected rather than silently stored, which
#: keeps the table from becoming a dumping ground.
ALLOWED_UI_STATE_PREFIXES = (
    "jobs.",
    "recommendations.",
    "skillgap.",
    "quiz.",
    "chat.",
    "interview.",
    "notifications.",
    "dashboard.",
    "cvgen.",
    "profile.",
    "settings.",
    "linkedin.",
    "recruiter.",
    "admin.",
)


def _json_safe(value):
    """Round-trip through JSON so DRF/ORM objects become plain JSON types."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _payload_size(value):
    return len(json.dumps(value, cls=DjangoJSONEncoder).encode("utf-8"))


class StateKeyError(ValueError):
    """Raised for a rejected UI state key or an oversized payload."""


# ---------------------------------------------------------------------------
# AI analysis session
# ---------------------------------------------------------------------------
class AnalysisSessionService:
    """The single shared AI analysis session.

    AI Job Match writes it after every upload; AI Job Match, Skill Gap Analysis
    and the dashboard all read it back instead of re-running the pipeline.
    """

    @staticmethod
    def cache_key(user_id):
        return f"state:analysis:{user_id}"

    @classmethod
    def get(cls, user):
        """Return the stored session, or None. Cached per user."""
        key = cls.cache_key(user.id)
        cached = cache.get(key)
        if cached is not None:
            return cached or None
        session = AnalysisSession.objects.filter(user=user).first()
        # `False` is cached for "known to be absent" so a user without an
        # analysis does not re-query on every page load.
        cache.set(key, session or False, STATE_CACHE_TIMEOUT)
        return session

    @classmethod
    def invalidate(cls, user_id):
        cache.delete(cls.cache_key(user_id))

    @classmethod
    def save(cls, user, payload, resume_fingerprint, cv_filename="",
             source=AnalysisSession.SOURCE_AI_MATCH):
        """Persist a completed analysis, replacing any previous one.

        A user has exactly one live analysis session: uploading a new CV
        explicitly replaces the old result, which is the only way stored work
        is ever discarded.
        """
        payload = _json_safe(payload or {})
        defaults = {
            "resume_fingerprint": resume_fingerprint,
            "source": source,
            "cv_filename": (cv_filename or "")[:255],
            "profession": (payload.get("profession") or "")[:120],
            "specialization": (payload.get("specialization") or "")[:120],
            "career_level": (payload.get("career_level") or "")[:20],
            "match_score": int(payload.get("resume_score") or 0),
            "skills": payload.get("skills_extracted") or [],
            "payload": payload,
        }
        with transaction.atomic():
            session, _ = AnalysisSession.objects.update_or_create(
                user=user, defaults=defaults,
            )
        cls.invalidate(user.id)
        return session

    @staticmethod
    def cv_metadata(session):
        """Identity of the CV a session was produced from.

        The browser cannot repopulate a file input after a reload, so the UI
        shows this instead of relying on the input to remember anything.
        """
        return {
            "id": session.pk,
            "filename": session.cv_filename,
            "uploaded_at": session.updated_at.isoformat(),
        }

    @classmethod
    def restore(cls, user):
        """Everything the AI Job Match page needs to repaint a past analysis.

        ``is_current`` tells the UI whether the stored analysis still describes
        the CV on the profile; the analysis is returned either way, because a
        superseded result is still the user's work until they replace it.
        """
        session = cls.get(user)
        if session is None:
            return {"has_analysis": False, "analysis": None, "cv": None}

        fingerprint = profile_resume_fingerprint(user)
        return {
            "has_analysis": True,
            "analysis": session.payload or {},
            "cv": cls.cv_metadata(session),
            "cv_filename": session.cv_filename,
            "source": session.source,
            "resume_fingerprint": session.resume_fingerprint,
            "is_current": session.matches(fingerprint) if fingerprint else True,
            "analyzed_at": session.updated_at.isoformat(),
        }

    @classmethod
    def summary(cls, user):
        """Lightweight header used by dashboards and the bootstrap endpoint."""
        session = cls.get(user)
        if session is None:
            return {"has_analysis": False, "cv": None}
        return {
            "has_analysis": True,
            "cv": cls.cv_metadata(session),
            "profession": session.profession,
            "specialization": session.specialization,
            "match_score": session.match_score,
            "skill_count": len(session.skills or []),
            "cv_filename": session.cv_filename,
            "analyzed_at": session.updated_at.isoformat(),
            "is_current": session.matches(profile_resume_fingerprint(user)),
        }


# ---------------------------------------------------------------------------
# Generic UI state
# ---------------------------------------------------------------------------
class UIStateService:
    """Filters, drafts, tabs, transcripts - anything the UI wants to survive."""

    @staticmethod
    def cache_key(user_id):
        return f"state:ui:{user_id}"

    @classmethod
    def validate_key(cls, key):
        key = (key or "").strip()
        if not key or len(key) > 120:
            raise StateKeyError("State key must be 1-120 characters.")
        if not key.startswith(ALLOWED_UI_STATE_PREFIXES):
            raise StateKeyError(f"Unsupported state key: {key}")
        return key

    @classmethod
    def all(cls, user):
        """Every stored key for the user as ``{key: {value, revision, updated_at}}``."""
        cache_key = cls.cache_key(user.id)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
        rows = {
            row.key: {
                "value": row.value,
                "revision": row.revision,
                "updated_at": row.updated_at.isoformat(),
            }
            for row in UIState.objects.filter(user=user)
        }
        cache.set(cache_key, rows, STATE_CACHE_TIMEOUT)
        return rows

    @classmethod
    def get(cls, user, key):
        return cls.all(user).get(key)

    @classmethod
    def invalidate(cls, user_id):
        cache.delete(cls.cache_key(user_id))

    @classmethod
    def set(cls, user, key, value):
        key = cls.validate_key(key)
        value = _json_safe(value)
        if _payload_size(value) > MAX_STATE_BYTES:
            raise StateKeyError("State payload is too large.")

        with transaction.atomic():
            row, created = UIState.objects.select_for_update().get_or_create(
                user=user, key=key, defaults={"value": value},
            )
            if not created:
                row.value = value
                row.revision = row.revision + 1
                row.save(update_fields=["value", "revision", "updated_at"])
        cls.invalidate(user.id)
        return {
            "key": row.key,
            "value": row.value,
            "revision": row.revision,
            "updated_at": row.updated_at.isoformat(),
        }

    @classmethod
    def set_many(cls, user, items):
        """Persist several keys in one round trip (used by the debounced client)."""
        saved = {}
        for key, value in (items or {}).items():
            saved[key] = cls.set(user, key, value)
        return saved

    @classmethod
    def delete(cls, user, key):
        deleted, _ = UIState.objects.filter(user=user, key=key).delete()
        cls.invalidate(user.id)
        return bool(deleted)


# ---------------------------------------------------------------------------
# Quiz session
# ---------------------------------------------------------------------------
class QuizSessionService:
    """Durable quiz state: questions, autosaved answers and the final result."""

    @staticmethod
    def cache_key(user_id):
        return f"state:quiz:{user_id}"

    @classmethod
    def get(cls, user):
        key = cls.cache_key(user.id)
        cached = cache.get(key)
        if cached is not None:
            return cached or None
        session = QuizSession.objects.filter(user=user).first()
        cache.set(key, session or False, STATE_CACHE_TIMEOUT)
        return session

    @classmethod
    def invalidate(cls, user_id):
        cache.delete(cls.cache_key(user_id))

    @classmethod
    def start(cls, user, questions, resume_fingerprint):
        """Replace any previous quiz with a freshly generated one."""
        with transaction.atomic():
            session, _ = QuizSession.objects.update_or_create(
                user=user,
                defaults={
                    "resume_fingerprint": resume_fingerprint,
                    "questions": _json_safe(questions or []),
                    "answers": {},
                    "status": QuizSession.STATUS_IN_PROGRESS,
                    "score": 0,
                    "total": len(questions or []),
                    "percentage": 0,
                    "results": [],
                    "completed_at": None,
                },
            )
        cls.invalidate(user.id)
        return session

    @classmethod
    def save_answers(cls, user, answers):
        """Autosave partial answers so a refresh never costs progress."""
        session = cls.get(user)
        if session is None:
            return None
        session.answers = _json_safe(answers or {})
        session.save(update_fields=["answers", "updated_at"])
        cls.invalidate(user.id)
        return session

    @classmethod
    def complete(cls, user, answers, score, total, percentage, results):
        session = cls.get(user)
        if session is None:
            return None
        session.answers = _json_safe(answers or {})
        session.score = score
        session.total = total
        session.percentage = percentage
        session.results = _json_safe(results or [])
        session.status = QuizSession.STATUS_COMPLETED
        session.completed_at = timezone.now()
        session.save(update_fields=[
            "answers", "score", "total", "percentage", "results",
            "status", "completed_at", "updated_at",
        ])
        cls.invalidate(user.id)
        return session

    @classmethod
    def reset(cls, user):
        """Explicit user action: discard the stored quiz so the next load regenerates."""
        QuizSession.objects.filter(user=user).delete()
        cls.invalidate(user.id)

    @staticmethod
    def public_questions(questions):
        """Questions without the correct answers.

        `difficulty` is intentionally included - it's a UI hint (shown as a
        badge), not the answer itself, so exposing it doesn't let anyone
        game the quiz the way exposing `answer` would.
        """
        return [
            {
                "id": q.get("id"),
                "question": q.get("question"),
                "options": q.get("options", []),
                "difficulty": q.get("difficulty"),
            }
            for q in (questions or [])
        ]

    @classmethod
    def restore(cls, user, fingerprint):
        """Return the resumable quiz for this CV, or None when it is stale."""
        session = cls.get(user)
        if session is None or not session.questions:
            return None
        if fingerprint and session.resume_fingerprint != fingerprint:
            # The CV changed - the old quiz no longer reflects it.
            return None
        payload = {
            "questions": cls.public_questions(session.questions),
            "answers": session.answers or {},
            "status": session.status,
            "restored": True,
            "started_at": session.started_at.isoformat(),
        }
        if session.is_completed:
            payload.update({
                "completed": True,
                "score": session.score,
                "total": session.total,
                "percentage": session.percentage,
                "results": session.results or [],
                "completed_at": session.completed_at.isoformat() if session.completed_at else None,
            })
        return payload


def bootstrap_state(user):
    """Everything a freshly loaded page needs to restore itself, in one call."""
    fingerprint = profile_resume_fingerprint(user)
    quiz = QuizSessionService.get(user)
    return {
        "analysis": AnalysisSessionService.summary(user),
        "ui": UIStateService.all(user),
        "quiz": {
            "has_session": quiz is not None,
            "status": quiz.status if quiz else None,
            "answered": len(quiz.answers or {}) if quiz else 0,
            "total": quiz.total if quiz else 0,
            "is_current": bool(quiz and fingerprint and quiz.resume_fingerprint == fingerprint),
        },
        "resume_fingerprint": fingerprint,
        "has_resume": bool(fingerprint),
    }
# file path: apps/state/models.py
"""Server-side persistence for everything the user has already done.

The product previously kept per-user working state in three volatile places:

* browser memory (AI Match results vanished on refresh),
* ``request.session`` (the quiz died with the session cookie), and
* ``localStorage`` (filters and drafts, lost on another device or after logout).

These models make that state durable and user-scoped, so navigation, refresh,
re-login and a different device all resume exactly where the user left off.
Nothing here recomputes or reinterprets AI output - it only stores what the
existing services already produced.
"""

from django.conf import settings
from django.db import models


class AnalysisSession(models.Model):
    """The single shared AI analysis session for a user.

    Written once per CV upload by AI Job Match and read by every consumer
    (AI Job Match restore, Skill Gap Analysis, dashboard). ``resume_fingerprint``
    ties the snapshot to the exact CV it was produced from, so a stale snapshot
    is detectable without re-running the analysis.
    """

    SOURCE_AI_MATCH = "ai_match"
    SOURCE_PROFILE = "profile"
    SOURCE_CHOICES = (
        (SOURCE_AI_MATCH, "AI Job Match upload"),
        (SOURCE_PROFILE, "Profile CV"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="analysis_session",
    )
    resume_fingerprint = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_AI_MATCH)
    cv_filename = models.CharField(max_length=255, blank=True, default="")

    # Denormalised headline fields. They duplicate values inside `payload` on
    # purpose: dashboards and admin lists can read them without loading and
    # parsing the full analysis blob.
    profession = models.CharField(max_length=120, blank=True, default="")
    specialization = models.CharField(max_length=120, blank=True, default="")
    career_level = models.CharField(max_length=20, blank=True, default="")
    match_score = models.PositiveIntegerField(default=0)
    skills = models.JSONField(default=list, blank=True)

    #: The complete, already-serialized AI Match response.
    payload = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI Analysis Session"
        verbose_name_plural = "AI Analysis Sessions"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Analysis session for {self.user.email} ({self.profession or 'unknown'})"

    def matches(self, fingerprint):
        """True when this snapshot was produced from `fingerprint`'s CV."""
        return bool(fingerprint) and self.resume_fingerprint == fingerprint


class UIState(models.Model):
    """Per-user, per-key UI state: filters, drafts, tabs, dashboard layout.

    A key/value store rather than a column per feature, so a new persisted
    control needs no migration. Keys are namespaced by page, e.g.
    ``jobs.filters``, ``chat.transcript``, ``notifications.view``.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ui_states",
    )
    key = models.CharField(max_length=120, db_index=True)
    value = models.JSONField(default=dict, blank=True)
    #: Incremented on every write; the client uses it to detect a newer
    #: server-side value without comparing whole payloads.
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "UI State"
        verbose_name_plural = "UI States"
        unique_together = ("user", "key")
        ordering = ["key"]

    def __str__(self):
        return f"{self.user.email} · {self.key}"


class QuizSession(models.Model):
    """A quiz that survives refresh, navigation and re-login.

    Questions used to live only in ``request.session``, so leaving the page
    mid-quiz lost every answer and a completed score was never shown again.
    """

    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="quiz_session",
    )
    resume_fingerprint = models.CharField(max_length=64, db_index=True)
    #: Full question objects including the correct answer. Never serialized to
    #: the client as-is - the API strips `answer` until the quiz is submitted.
    questions = models.JSONField(default=list, blank=True)
    #: Autosaved answers, keyed by question id.
    answers = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    score = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    percentage = models.FloatField(default=0)
    results = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Quiz Session"
        verbose_name_plural = "Quiz Sessions"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Quiz for {self.user.email} ({self.status})"

    @property
    def is_completed(self):
        return self.status == self.STATUS_COMPLETED

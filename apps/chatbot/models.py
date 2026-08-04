# file path: apps/chatbot/models.py
"""Conversation history for the AI Career Assistant.

The assistant is a career coach that remembers the discussion, so the exchange
has to outlive the browser tab. One active conversation per user at a time;
starting a new one archives the previous thread rather than deleting it.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Conversation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assistant_conversations",
    )
    #: Derived from the first question so archived threads are recognisable.
    title = models.CharField(max_length=180, blank=True, default="")
    #: Working memory for the thread: the job in focus, the profile facts already
    #: established, the topics covered, the last thing each side said. Kept here
    #: rather than re-derived from the transcript because "compare it" needs a
    #: job id, not a paragraph to guess from. See `apps.chatbot.memory`.
    memory = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Assistant Conversation"
        verbose_name_plural = "Assistant Conversations"
        indexes = [
            models.Index(fields=["user", "is_active"], name="idx_conv_user_active"),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.title or 'New conversation'}"


class ChatMessage(models.Model):
    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = (
        (ROLE_USER, "User"),
        (ROLE_ASSISTANT, "Assistant"),
    )

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField()
    #: Which slices of the user's SkillSync data grounded this answer. Kept so
    #: an answer can be explained - and audited - after the fact.
    context_used = models.JSONField(default=list, blank=True)
    #: Follow-up questions offered alongside an assistant reply.
    suggestions = models.JSONField(default=list, blank=True)
    #: How the message was routed - "greeting", "job_fit", "compare". Stored so
    #: the split between conversation and career work is measurable rather than
    #: assumed, and so a thread can be replayed with its routing intact.
    intent = models.CharField(max_length=40, blank=True, default="")
    #: False when the model was unavailable and the deterministic answer built
    #: straight from the user's data was returned instead.
    is_ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "Assistant Message"
        verbose_name_plural = "Assistant Messages"
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="idx_msg_conv_created"),
        ]

    def __str__(self):
        return f"{self.role}: {self.content[:60]}"


class InterviewSession(models.Model):
    """One interview preparation run for a user and a target role.

    A session owns everything generated for that role - the question bank, the
    coaching tips, the improvement plan and the readiness snapshot - so the page
    can be restored without spending another AI call. Regeneration is deliberate
    and rare: a new target role, a new CV, or the user explicitly asking for a
    fresh interview. See `apps.chatbot.interview` for the rules.
    """

    STATUS_READY = "ready"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_CHOICES = (
        (STATUS_READY, "Ready"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    )

    LEVEL_BEGINNER = "beginner"
    LEVEL_INTERMEDIATE = "intermediate"
    LEVEL_ADVANCED = "advanced"
    LEVEL_MIXED = "mixed"
    LEVEL_CHOICES = (
        (LEVEL_BEGINNER, "Beginner"),
        (LEVEL_INTERMEDIATE, "Intermediate"),
        (LEVEL_ADVANCED, "Advanced"),
        (LEVEL_MIXED, "Mixed"),
    )

    #: The round the candidate is sitting. A plain-language front for the
    #: question categories: picking "Behavioral" is one choice, not four
    #: checkboxes. `interview.CATEGORIES_FOR_TYPE` does the translation, and
    #: explicit categories still win when a caller sends them.
    TYPE_TECHNICAL = "technical"
    TYPE_BEHAVIORAL = "behavioral"
    TYPE_HR = "hr"
    TYPE_MIXED = "mixed"
    TYPE_CHOICES = (
        (TYPE_TECHNICAL, "Technical"),
        (TYPE_BEHAVIORAL, "Behavioral"),
        (TYPE_HR, "HR"),
        (TYPE_MIXED, "Mixed"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="interview_sessions",
    )
    target_role = models.CharField(max_length=180)
    #: Ties the question bank to the CV it was built from, so a new upload is
    #: detectable without re-running the analysis.
    resume_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)
    difficulty = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_MIXED)
    interview_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_MIXED)
    #: What the candidate asked for. The bank can come back shorter if the role
    #: profile has fewer questions to offer, so this is the request, not a count.
    question_count = models.PositiveSmallIntegerField(default=8)
    #: Planned length in minutes; 0 means untimed. The clock is advisory - it
    #: paces the candidate, it does not cut them off mid-answer.
    duration_minutes = models.PositiveSmallIntegerField(default=0)
    #: Set when the first answer is submitted, so history shows how long the
    #: interview actually took rather than how long ago it was generated.
    started_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_READY, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    #: The generated bank: [{id, question, category, difficulty, why_asked,
    #: expected_points, skill}]. Ordered as the mock interview asks them.
    questions = models.JSONField(default=list, blank=True)
    #: Coaching tips written against this user's strengths and gaps.
    tips = models.JSONField(default=list, blank=True)
    #: {skills_to_improve, recommended_projects, portfolio, certifications,
    #: learning_priorities} - what to do before the real interview.
    improvement_plan = models.JSONField(default=dict, blank=True)
    #: Readiness snapshot as it stood when the session was generated, so a past
    #: session still shows the numbers the user actually saw.
    readiness = models.JSONField(default=dict, blank=True)

    #: Index of the next unanswered question in `questions`.
    current_index = models.PositiveIntegerField(default=0)
    #: False when Gemini was unavailable and the bank was composed from the
    #: user's own data and the role profile instead.
    is_ai_generated = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Interview Session"
        verbose_name_plural = "Interview Sessions"
        indexes = [
            models.Index(fields=["user", "is_active"], name="idx_interview_user_active"),
        ]

    def __str__(self):
        return f"{self.user.email}: {self.target_role} ({self.status})"

    @property
    def total_questions(self):
        return len(self.questions or [])

    @property
    def is_completed(self):
        return self.status == self.STATUS_COMPLETED

    def question_at(self, index):
        questions = self.questions or []
        if 0 <= index < len(questions):
            return questions[index]
        return None

    def matches(self, target_role, fingerprint):
        """True when this bank was built for the same role and the same CV."""
        same_role = (self.target_role or "").strip().lower() == (target_role or "").strip().lower()
        same_cv = not fingerprint or not self.resume_fingerprint or self.resume_fingerprint == fingerprint
        return same_role and same_cv

    @property
    def elapsed_seconds(self):
        """How long the interview has been running, or how long it took.

        None until the first answer: a session sitting unopened has no elapsed
        time, and counting from generation would report days.
        """
        if self.started_at is None:
            return None
        end = self.completed_at or timezone.now()
        return max(0, int((end - self.started_at).total_seconds()))


class InterviewTurn(models.Model):
    """One answered question, with the coach's evaluation of the answer."""

    session = models.ForeignKey(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="turns",
    )
    question_index = models.PositiveIntegerField()
    question = models.TextField()
    category = models.CharField(max_length=40, blank=True, default="")
    difficulty = models.CharField(max_length=20, blank=True, default="")
    answer = models.TextField(blank=True, default="")

    score = models.PositiveIntegerField(default=0)
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    #: Short delivery cues for *this* answer - "lead with the result", "add a
    #: number", "use the STAR structure". What used to be a static tips panel
    #: written once per session, now written against what was actually said.
    coaching = models.JSONField(default=list, blank=True)
    #: A model answer the user can compare against - the point of practising.
    better_answer = models.TextField(blank=True, default="")
    is_ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["question_index", "id"]
        unique_together = ("session", "question_index")
        verbose_name = "Interview Turn"
        verbose_name_plural = "Interview Turns"

    def __str__(self):
        return f"Q{self.question_index + 1} · {self.score}/100"


class InterviewReport(models.Model):
    """The debrief written once a session is finished.

    Scores are computed from the turns that were actually answered; the
    narrative sections are AI-written when available and composed from the same
    numbers when not.
    """

    session = models.OneToOneField(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="report",
    )
    overall_score = models.PositiveIntegerField(default=0)
    technical_score = models.PositiveIntegerField(default=0)
    hr_score = models.PositiveIntegerField(default=0)
    #: Every non-technical question - behavioral, scenario and HR. This is the
    #: "how did I handle the human side" number a candidate looks for.
    behavioral_score = models.PositiveIntegerField(default=0)
    #: Narrower than `behavioral_score` on purpose: only the story-telling
    #: rounds (behavioral and scenario), where how you structure the answer is
    #: what is being graded.
    communication_score = models.PositiveIntegerField(default=0)
    confidence_score = models.PositiveIntegerField(default=0)

    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    missing_skills = models.JSONField(default=list, blank=True)
    improvement_plan = models.JSONField(default=list, blank=True)
    #: Reused from Skill Gap Analysis rather than regenerated here.
    recommended_courses = models.JSONField(default=list, blank=True)
    next_topics = models.JSONField(default=list, blank=True)
    is_ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Interview Report"
        verbose_name_plural = "Interview Reports"

    def __str__(self):
        return f"Report for {self.session.target_role}: {self.overall_score}/100"

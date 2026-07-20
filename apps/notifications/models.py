from django.conf import settings
from django.db import models

from apps.jobs.models import JobPosting


class Notification(models.Model):

    class NotificationType(models.TextChoices):
        JOB_MATCH = "job_match", "Job Match"
        APPLICATION = "application", "Application"
        INTERVIEW = "interview", "Interview"
        AI_MATCH = "ai_match", "AI Match"
        RESUME = "resume", "Resume"
        SKILL_GAP = "skill_gap", "Skill Gap"
        RECRUITER = "recruiter", "Recruiter"
        ADMIN = "admin", "Admin"
        PROFILE = "profile", "Profile"
        SECURITY = "security", "Security"
        SYSTEM = "system", "System"
        MESSAGE = "message", "Message"
        COMPANY = "company", "Company"
        VERIFICATION = "verification", "Verification"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_notifications")
    recruiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="sent_match_notifications")
    job = models.ForeignKey(JobPosting, on_delete=models.SET_NULL, null=True, blank=True, related_name="match_notifications")
    match_percentage = models.PositiveIntegerField(default=0)
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices, default=NotificationType.SYSTEM, db_index=True)
    title = models.CharField(max_length=180)
    message = models.TextField()
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    is_read = models.BooleanField(default=False, db_index=True)
    is_email_sent = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="idx_notif_user_created"),
            models.Index(fields=["user", "is_read"], name="idx_notif_user_unread"),
            models.Index(fields=["user", "notification_type"], name="idx_notif_user_type"),
        ]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"

    def __str__(self):
        return f"[{self.notification_type}] {self.title} -> {self.user.email}"

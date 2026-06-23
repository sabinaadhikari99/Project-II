from django.conf import settings
from django.db import models

from apps.jobs.models import JobPosting


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    recruiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sent_match_notifications")
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="match_notifications")
    match_percentage = models.PositiveIntegerField(default=0)
    title = models.CharField(max_length=180)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "job")
        verbose_name = "Job Match Notification"
        verbose_name_plural = "Job Match Notifications"

    def __str__(self):
        return f"{self.match_percentage}% {self.job.title} -> {self.user.email}"

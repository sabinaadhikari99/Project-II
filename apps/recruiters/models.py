from django.conf import settings
from django.db import models


class RecruiterActivity(models.Model):
    ACTIVITY_TYPES = (
        ("job_created", "Job Created"),
        ("job_updated", "Job Updated"),
        ("job_published", "Job Published"),
        ("job_closed", "Job Closed"),
        ("job_reopened", "Job Reopened"),
        ("draft_saved", "Draft Saved"),
        ("draft_deleted", "Draft Deleted"),
    )

    recruiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recruiter_activities")
    job = models.ForeignKey("jobs.JobPosting", on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    activity_type = models.CharField(max_length=30, choices=ACTIVITY_TYPES)
    description = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Recruiter Activity"
        verbose_name_plural = "Recruiter Activities"

    def __str__(self):
        return f"{self.recruiter.email} - {self.get_activity_type_display()} - {self.created_at:%Y-%m-%d %H:%M}"

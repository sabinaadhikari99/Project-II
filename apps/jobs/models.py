# file path: apps/jobs/models.py
from django.conf import settings
from django.db import models


class JobPosting(models.Model):
    WORK_MODE_CHOICES = (
        ("onsite", "On-site"),
        ("remote", "Remote"),
        ("hybrid", "Hybrid"),
    )

    recruiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="job_posts")
    title = models.CharField(max_length=180)
    company = models.CharField(max_length=180)
    company_logo = models.TextField(blank=True, default="")
    location = models.CharField(max_length=180, blank=True)
    work_mode = models.CharField(max_length=20, choices=WORK_MODE_CHOICES, default="onsite")
    description = models.TextField()
    required_skills = models.JSONField(default=list, blank=True)
    experience_required = models.FloatField(default=0)
    education_required = models.CharField(max_length=100, blank=True, default="")
    salary_range = models.CharField(max_length=120, blank=True)
    job_category = models.CharField(max_length=80, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Job Posting"
        verbose_name_plural = "Job Postings"

    def __str__(self):
        return f"{self.title} at {self.company}"

    @property
    def embedding_text(self):
        return " ".join([
            self.title,
            self.company,
            self.location,
            self.work_mode,
            self.description,
            " ".join(self.required_skills or []),
            str(self.experience_required),
        ])


class Application(models.Model):
    STATUS_CHOICES = (
        ("submitted", "Submitted"),
        ("reviewing", "Reviewing"),
        ("shortlisted", "Shortlisted"),
        ("rejected", "Rejected"),
        ("hired", "Hired"),
    )
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="applications")
    cover_letter = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="submitted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("job", "applicant")
        ordering = ["-created_at"]
        verbose_name = "Application"
        verbose_name_plural = "Applications"

    def __str__(self):
        return f"{self.applicant.email} -> {self.job.title}"


class SavedJob(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_jobs")
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="saved_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "job")
        ordering = ["-created_at"]
        verbose_name = "Bookmarked Job"
        verbose_name_plural = "Bookmarked Jobs"

    def __str__(self):
        return f"{self.user.email} saved {self.job.title}"


class RecentlyViewedJob(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="recently_viewed_jobs")
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="recent_views")
    viewed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user", "job")
        ordering = ["-viewed_at"]
        verbose_name = "Recently Viewed Job"
        verbose_name_plural = "Recently Viewed Jobs"

    def __str__(self):
        return f"{self.user.email} viewed {self.job.title}"

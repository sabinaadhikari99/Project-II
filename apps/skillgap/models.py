from django.conf import settings
from django.db import models


class CourseRecommendation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_recommendations",
    )
    profession = models.CharField(max_length=100, blank=True, default="")
    career_level = models.CharField(max_length=20, blank=True, default="")
    resume_hash = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Course Recommendation"
        verbose_name_plural = "Course Recommendations"
        unique_together = ("user", "resume_hash")

    def __str__(self):
        return f"Course recommendations for {self.user.email} ({self.profession or 'unknown'})"


class LearningRoadmap(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="learning_roadmaps",
    )
    profession = models.CharField(max_length=100, blank=True, default="")
    career_level = models.CharField(max_length=20, blank=True, default="")
    resume_hash = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Learning Roadmap"
        verbose_name_plural = "Learning Roadmaps"
        unique_together = ("user", "resume_hash")

    def __str__(self):
        return f"Learning roadmap for {self.user.email} ({self.profession or 'unknown'})"


class RoadmapStepProgress(models.Model):
    STATUS_NOT_STARTED = "not_started"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = (
        (STATUS_NOT_STARTED, "Not Started"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COMPLETED, "Completed"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roadmap_step_progress",
    )
    roadmap = models.ForeignKey(
        LearningRoadmap,
        on_delete=models.CASCADE,
        related_name="step_progress",
    )
    step_number = models.PositiveIntegerField()
    skill_name = models.CharField(max_length=150)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_NOT_STARTED,
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["step_number"]
        verbose_name = "Roadmap Step Progress"
        verbose_name_plural = "Roadmap Step Progress"
        unique_together = ("roadmap", "step_number")

    def __str__(self):
        return f"Step {self.step_number} {self.skill_name} ({self.status})"

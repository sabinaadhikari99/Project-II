# file path: apps/accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.shared.constants import ROLE_JOB_SEEKER, USER_ROLES


class User(AbstractUser):
    email = models.EmailField(unique=True)
    profile_picture = models.TextField(blank=True, default="")
    role = models.CharField(
        max_length=20,
        choices=USER_ROLES,
        default=ROLE_JOB_SEEKER
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return f"{self.email} ({self.role})"


class UserProfile(models.Model):
    user = models.OneToOneField(User,on_delete=models.CASCADE,related_name="profile")
    skills = models.JSONField(default=list, blank=True)
    resume_text = models.TextField(blank=True)
    cv_url = models.URLField(blank=True)
    experience_years = models.FloatField(default=0)
    education = models.TextField(blank=True)

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user.email}"
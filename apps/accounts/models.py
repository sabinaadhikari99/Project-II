# file path: apps/accounts/models.py
from django.contrib.auth.models import AbstractUser
from django.core.files.storage import FileSystemStorage
from django.db import models

from apps.shared.constants import ROLE_JOB_SEEKER, USER_ROLES

# Resumes are stored on the LOCAL filesystem explicitly, bypassing whatever
# the project's default file storage backend is (Cloudinary, in this
# project) - that backend requires cloud credentials (CLOUD_NAME, API_KEY,
# API_SECRET) that aren't configured here, and every FileField.save() would
# otherwise fail with django.core.exceptions.ImproperlyConfigured the moment
# Django tries to initialize it. This keeps resume uploads working with zero
# external account setup. If you later configure real Cloudinary credentials
# and want resumes to live there too, just remove the storage=... kwarg
# below so the field falls back to the project's default storage.
_resume_storage = FileSystemStorage()


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
    phone = models.CharField(max_length=20, blank=True, default="")
    skills = models.JSONField(default=list, blank=True)
    resume_text = models.TextField(blank=True)
    # The actual uploaded CV file. Previously only `resume_text` (the
    # extracted plain text) was ever saved - the original PDF itself was
    # discarded after extraction, so there was nothing to link/attach in
    # emails or elsewhere. This stores the file itself; `cv_url` below is
    # kept in sync with its accessible URL for anything that just wants a
    # link without touching the file field directly (e.g. serializers,
    # email templates).
    resume_file = models.FileField(
        upload_to="resumes/%Y/%m/",
        storage=_resume_storage,
        blank=True,
        null=True,
    )
    cv_url = models.URLField(blank=True)
    experience_years = models.FloatField(default=0)
    education = models.TextField(blank=True)
    location = models.CharField(max_length=255, blank=True, default="")
    bio = models.TextField(blank=True, default="")
    headline = models.CharField(max_length=255, blank=True, default="")
    linkedin_url = models.URLField(blank=True, default="")
    github_url = models.URLField(blank=True, default="")
    portfolio_url = models.URLField(blank=True, default="")

    class Meta:
        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self):
        return f"Profile for {self.user.email}"
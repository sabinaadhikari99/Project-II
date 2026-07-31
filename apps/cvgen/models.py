from django.db import models

from .cv_templates import TEMPLATE_CHOICES, DEFAULT_TEMPLATE_ID


class JobSeekerProfile(models.Model):
    """Stores detailed job seeker profile data for CV generation."""
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone_number = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=500, blank=True)
    education = models.TextField(blank=True, help_text='Use separate lines for education entries.')
    skills = models.TextField(blank=True, help_text='Use commas or lines to separate skills.')
    work_experience = models.TextField(blank=True, help_text='Use separate lines for each experience entry.')
    projects = models.TextField(blank=True, help_text='Use separate lines for each project entry.')
    certifications = models.TextField(blank=True, help_text='Use separate lines for each certification.')
    linkedin_url = models.URLField(blank=True)
    github_url = models.URLField(blank=True)
    selected_template = models.CharField(
        max_length=50,
        choices=TEMPLATE_CHOICES,
        default=DEFAULT_TEMPLATE_ID,
        help_text='The CV template last chosen for this profile.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CV Profile: {self.full_name}"
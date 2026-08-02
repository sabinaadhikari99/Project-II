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
    projects = models.TextField(
        blank=True,
        help_text=(
            'Separate each project with a blank line. The first line of each block '
            'is shown as the project title (bold); the following lines are shown as bullet points.'
        ),
    )
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


class AdditionalInfoEntry(models.Model):
    """A user-defined custom section (e.g. Achievements, Publications,
    Volunteering) with its own title and bullet-point details. A profile can
    have any number of these - the CV builder lets the user add as many as
    they like."""
    profile = models.ForeignKey(
        JobSeekerProfile, related_name='additional_info', on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=255, help_text='Section heading, e.g. "Achievements".')
    details = models.TextField(blank=True, help_text='Use separate lines for each point.')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.title} ({self.profile.full_name})"
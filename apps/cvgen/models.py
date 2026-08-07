from django.db import models

from .cv_templates import TEMPLATE_CHOICES, DEFAULT_TEMPLATE_ID


class JobSeekerProfile(models.Model):
    """Stores detailed job seeker profile data for CV generation."""
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone_number = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=500, blank=True)
    skills = models.TextField(blank=True, help_text='Use commas or lines to separate skills.')
    work_experience = models.TextField(blank=True, help_text='Use separate lines for each experience entry.')
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


class EducationEntry(models.Model):
    """A single degree/qualification, with its own Degree, Institution, and
    Year fields - e.g. "Bachelor of Science in Computer Science" at
    "Pokhara University", "2020 - 2024". A profile can have any number of
    these (Bachelor's, Master's, diplomas, etc.), each shown with the degree
    name in bold."""
    profile = models.ForeignKey(
        JobSeekerProfile, related_name='education', on_delete=models.CASCADE,
    )
    degree = models.CharField(
        max_length=255,
        help_text='e.g. "Bachelor of Software Engineering" or "Master of Business Administration".',
    )
    institution = models.CharField(max_length=255, blank=True, help_text='School or university name.')
    year = models.CharField(max_length=50, blank=True, help_text='e.g. "2020 - 2024" or "Expected 2026".')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.degree} ({self.profile.full_name})"


class ProjectEntry(models.Model):
    """A single project, with its own title (always shown bold) and its own
    bullet-point details. Projects used to be one big free-text field where
    the first "line" of a blank-line-separated block was guessed to be the
    title - that broke whenever someone put blank lines between every line
    instead of only between projects. A dedicated Title field removes the
    ambiguity entirely: the title is whatever's typed in the Title box,
    full stop."""
    profile = models.ForeignKey(
        JobSeekerProfile, related_name='projects', on_delete=models.CASCADE,
    )
    title = models.CharField(max_length=255, help_text='Project name, e.g. "Cyber Scam Detection System".')
    details = models.TextField(blank=True, help_text='Use separate lines for each point (technologies, description, impact, etc.).')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.title} ({self.profile.full_name})"


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
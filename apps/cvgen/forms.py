from django import forms
from django.forms import inlineformset_factory
from .models import JobSeekerProfile, EducationEntry, ProjectEntry, AdditionalInfoEntry


class JobSeekerProfileForm(forms.ModelForm):
    """Form for the CV generation job seeker profile."""

    class Meta:
        model = JobSeekerProfile
        fields = [
            'full_name',
            'email',
            'phone_number',
            'address',
            'skills',
            'work_experience',
            'certifications',
            'linkedin_url',
            'github_url',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name', 'required': True}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email', 'required': True}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'skills': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Skills, separated by commas or lines'}),
            'work_experience': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Work experience details, one entry per line'}),
            'certifications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Certification details, one entry per line'}),
            'linkedin_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'LinkedIn URL'}),
            'github_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'GitHub URL'}),
        }


# Each degree gets its own Degree / Institution / Year fields - so a
# Bachelor's and a Master's (or a diploma, certificate program, etc.) are
# always kept as separate, cleanly labeled entries rather than guessed from
# free text. extra=1 shows one empty entry to start; "Add another degree"
# adds more client-side by bumping the formset's TOTAL_FORMS counter.
EducationFormSet = inlineformset_factory(
    JobSeekerProfile,
    EducationEntry,
    fields=['degree', 'institution', 'year'],
    extra=1,
    can_delete=False,
    widgets={
        'degree': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': "e.g. Bachelor of Software Engineering , or Master of Business Administration",
        }),
        'institution': forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'e.g. Pokhara University',
        }),
        'year': forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'e.g. 2020 - 2024',
        }),
    },
)

# Each project gets its own Title (always shown bold, no parsing/guessing
# involved) + Details (bullet points, one per line). extra=1 shows one empty
# project to start; "Add another project" adds more client-side by bumping
# the formset's TOTAL_FORMS counter.
ProjectFormSet = inlineformset_factory(
    JobSeekerProfile,
    ProjectEntry,
    fields=['title', 'details'],
    extra=1,
    can_delete=False,
    widgets={
        'title': forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Project title, e.g. Cyber Scam Detection System',
        }),
        'details': forms.Textarea(attrs={
            'class': 'form-control', 'rows': 4,
            'placeholder': 'One point per line - technologies used, what you built, the impact it had...',
        }),
    },
)

# Lets the user add any number of custom sections (Achievements, Publications,
# Volunteering, etc.), each with its own title and bullet-point details.
# extra=1 shows one empty section to start; more are added client-side via JS,
# which only needs to bump the formset's TOTAL_FORMS counter.
AdditionalInfoFormSet = inlineformset_factory(
    JobSeekerProfile,
    AdditionalInfoEntry,
    fields=['title', 'details'],
    extra=1,
    can_delete=False,
    widgets={
        'title': forms.TextInput(attrs={
            'class': 'form-control', 'placeholder': 'Section title, e.g. Achievements',
        }),
        'details': forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3, 'placeholder': 'One point per line',
        }),
    },
)
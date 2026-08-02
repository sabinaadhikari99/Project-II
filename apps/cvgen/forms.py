from django import forms
from django.forms import inlineformset_factory
from .models import JobSeekerProfile, AdditionalInfoEntry


class JobSeekerProfileForm(forms.ModelForm):
    """Form for the CV generation job seeker profile."""

    class Meta:
        model = JobSeekerProfile
        fields = [
            'full_name',
            'email',
            'phone_number',
            'address',
            'education',
            'skills',
            'work_experience',
            'projects',
            'certifications',
            'linkedin_url',
            'github_url',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name', 'required': True}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email', 'required': True}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'education': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Education details, one entry per line'}),
            'skills': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Skills, separated by commas or lines'}),
            'work_experience': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Work experience details, one entry per line'}),
            'projects': forms.Textarea(attrs={
                'class': 'form-control', 'rows': 5,
                'placeholder': 'Project Title\nWhat you built and the impact it had\nKey technologies used\n\nSecond Project Title\nDetails for the second project...',
            }),
            'certifications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Certification details, one entry per line'}),
            'linkedin_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'LinkedIn URL'}),
            'github_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'GitHub URL'}),
        }


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
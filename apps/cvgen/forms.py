from django import forms
from .models import JobSeekerProfile


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
            'profile_photo',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name', 'required': True}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email', 'required': True}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),
            'education': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Education details, one entry per line'}),
            'skills': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Skills, separated by commas or lines'}),
            'work_experience': forms.Textarea(attrs={'class': 'form-control', 'rows': 5, 'placeholder': 'Work experience details, one entry per line'}),
            'projects': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Project details, one entry per line'}),
            'certifications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Certification details, one entry per line'}),
            'linkedin_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'LinkedIn URL'}),
            'github_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'GitHub URL'}),
            'profile_photo': forms.ClearableFileInput(attrs={'class': 'form-control form-control-file'}),
        }
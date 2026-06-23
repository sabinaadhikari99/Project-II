from django import forms
from .models import JobSeekerProfile


class JobSeekerProfileForm(forms.ModelForm):
    """Form for CV generation profile"""

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
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full Name'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Phone Number'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Address'}),

            'education': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'skills': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'work_experience': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'projects': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'certifications': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),

            'linkedin_url': forms.URLInput(attrs={'class': 'form-control'}),
            'github_url': forms.URLInput(attrs={'class': 'form-control'}),

            'profile_photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }
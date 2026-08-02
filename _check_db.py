import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.contrib.auth import get_user_model
from apps.accounts.models import UserProfile
from apps.jobs.models import JobPosting
User = get_user_model()
print(f"Users: {User.objects.count()}")
print(f"Recruiters: {User.objects.filter(role='recruiter').count()}")
print(f"Seekers: {User.objects.filter(role='job_seeker').count()}")
print(f"Profiles: {UserProfile.objects.count()}")
print(f"Jobs: {JobPosting.objects.count()}")

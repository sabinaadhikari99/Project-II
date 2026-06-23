# file path: apps/recruiters/urls.py
from django.urls import path

from .views import JobCandidatesAPIView, RecruiterJobDetailAPIView, RecruiterJobsAPIView

urlpatterns = [
    path("jobs/", RecruiterJobsAPIView.as_view(), name="recruiter-jobs"),
    path("jobs/<int:pk>/", RecruiterJobDetailAPIView.as_view(), name="recruiter-job-detail"),
    path("jobs/<int:pk>/candidates/", JobCandidatesAPIView.as_view(), name="recruiter-job-candidates"),
]

# file path: apps/external/urls.py
from django.urls import path

from .views import LinkedInJobsAPIView

urlpatterns = [path("linkedin/", LinkedInJobsAPIView.as_view(), name="external-linkedin")]

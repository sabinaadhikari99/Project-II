# file path: apps/jobs/urls.py
from django.urls import path

from .views import (
    ApplyJobAPIView,
    AIMatchAPIView,
    FilterJobsAPIView,
    MarkRecentlyViewedJobAPIView,
    RecentlyViewedJobsAPIView,
    RecommendedJobsAPIView,
    SavedJobsAPIView,
    ToggleSavedJobAPIView,
)

urlpatterns = [
    path("recommended/", RecommendedJobsAPIView.as_view(), name="jobs-recommended"),
    path("ai-match/", AIMatchAPIView.as_view(), name="jobs-ai-match"),
    path("apply/<int:pk>/", ApplyJobAPIView.as_view(), name="jobs-apply"),
    path("filter/", FilterJobsAPIView.as_view(), name="jobs-filter"),
    path("saved/", SavedJobsAPIView.as_view(), name="jobs-saved"),
    path("saved/<int:pk>/", ToggleSavedJobAPIView.as_view(), name="jobs-save-toggle"),
    path("recent/", RecentlyViewedJobsAPIView.as_view(), name="jobs-recent"),
    path("viewed/<int:pk>/", MarkRecentlyViewedJobAPIView.as_view(), name="jobs-viewed"),
]

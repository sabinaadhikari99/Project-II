# file path: apps/skillgap/urls.py
from django.urls import path

from .views import (
    LearningRoadmapAPIView,
    RecommendedCoursesAPIView,
    RoadmapProgressAPIView,
    SkillGapAPIView,
)

urlpatterns = [
    path("", SkillGapAPIView.as_view()),
    path("courses/", RecommendedCoursesAPIView.as_view()),
    path("roadmap/", LearningRoadmapAPIView.as_view()),
    path("roadmap/progress/", RoadmapProgressAPIView.as_view()),
]

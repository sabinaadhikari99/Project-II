# file path: apps/state/urls.py
from django.urls import path

from .views import (
    AnalysisStateAPIView,
    BootstrapStateAPIView,
    QuizStateAPIView,
    UIStateDetailAPIView,
    UIStateListAPIView,
)

urlpatterns = [
    path("bootstrap/", BootstrapStateAPIView.as_view(), name="state-bootstrap"),
    path("analysis/", AnalysisStateAPIView.as_view(), name="state-analysis"),
    path("quiz/", QuizStateAPIView.as_view(), name="state-quiz"),
    path("ui/", UIStateListAPIView.as_view(), name="state-ui-list"),
    path("ui/<str:key>/", UIStateDetailAPIView.as_view(), name="state-ui-detail"),
]

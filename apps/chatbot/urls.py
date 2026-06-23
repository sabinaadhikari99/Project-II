# file path: apps/chatbot/urls.py
from django.urls import path

from .views import ChatbotAPIView, InterviewAPIView

urlpatterns = [
    path("", ChatbotAPIView.as_view(), name="chatbot"),
    path("interview/", InterviewAPIView.as_view(), name="interview"),
]

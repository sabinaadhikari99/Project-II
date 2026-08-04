# file path: apps/chatbot/urls.py
from django.urls import path

from .views import (
    ChatHistoryAPIView,
    ChatSuggestionsAPIView,
    ChatbotAPIView,
    InterviewAPIView,
    InterviewAnswerAPIView,
    InterviewCompleteAPIView,
    InterviewHistoryAPIView,
    InterviewReadinessAPIView,
    InterviewResetAPIView,
    InterviewSessionAPIView,
    InterviewSessionDetailAPIView,
    NewConversationAPIView,
)

urlpatterns = [
    path("", ChatbotAPIView.as_view(), name="chatbot"),
    path("history/", ChatHistoryAPIView.as_view(), name="chatbot-history"),
    path("new/", NewConversationAPIView.as_view(), name="chatbot-new"),
    path("suggestions/", ChatSuggestionsAPIView.as_view(), name="chatbot-suggestions"),

    # Legacy flat question list - kept unchanged so existing clients still work.
    path("interview/", InterviewAPIView.as_view(), name="interview"),

    # Interview practice
    path("interview/session/", InterviewSessionAPIView.as_view(), name="interview-session"),
    path("interview/answer/", InterviewAnswerAPIView.as_view(), name="interview-answer"),
    path("interview/complete/", InterviewCompleteAPIView.as_view(), name="interview-complete"),
    path("interview/reset/", InterviewResetAPIView.as_view(), name="interview-reset"),
    path("interview/readiness/", InterviewReadinessAPIView.as_view(), name="interview-readiness"),
    path("interview/sessions/", InterviewHistoryAPIView.as_view(), name="interview-sessions"),
    path("interview/sessions/<int:session_id>/", InterviewSessionDetailAPIView.as_view(),
         name="interview-session-detail"),
]

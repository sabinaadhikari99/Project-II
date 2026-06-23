# file path: apps/quiz/urls.py
from django.urls import path

from .views import QuizAPIView, QuizSubmitAPIView

urlpatterns = [
    path("", QuizAPIView.as_view(), name="quiz"),
    path("submit/", QuizSubmitAPIView.as_view(), name="quiz-submit"),
]

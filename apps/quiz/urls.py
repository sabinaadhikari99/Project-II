from django.urls import path

from .views import QuizAPIView, QuizProgressAPIView, QuizResetAPIView, QuizSubmitAPIView

urlpatterns = [
    path("", QuizAPIView.as_view()),
    path("progress/", QuizProgressAPIView.as_view(), name="quiz-progress"),
    path("reset/", QuizResetAPIView.as_view(), name="quiz-reset"),
    path("submit/", QuizSubmitAPIView.as_view(), name="quiz-submit"),
]

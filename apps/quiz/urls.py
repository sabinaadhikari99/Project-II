from django.urls import path

from .views import QuizAPIView, QuizSubmitAPIView

urlpatterns = [
    path("", QuizAPIView.as_view()),
    path("submit/", QuizSubmitAPIView.as_view(), name="quiz-submit"),
]
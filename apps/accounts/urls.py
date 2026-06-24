# file path: apps/accounts/urls.py
from django.urls import path

from .views import (
    LoginAPIView,
    ProfileAPIView,
    RegisterAPIView,
    ResumeUploadAPIView,
)

urlpatterns = [
    path("register/", RegisterAPIView.as_view(), name="auth-register"),
    path("login/", LoginAPIView.as_view(), name="auth-login"),
    path("profile/", ProfileAPIView.as_view(), name="auth-profile"),
    path("resume/", ResumeUploadAPIView.as_view(), name="auth-resume"),
]
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginAPIView,
    GetTokenAPIView,
    LogoutAPIView,
    ProfileAPIView,
    RegisterAPIView,
    ResumeUploadAPIView,
)

urlpatterns = [
    path("register/", RegisterAPIView.as_view(), name="auth-register"),
    path("login/", LoginAPIView.as_view(), name="auth-login"),
    path("token/", GetTokenAPIView.as_view(), name="auth-token"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("profile/", ProfileAPIView.as_view(), name="auth-profile"),
    path("resume/", ResumeUploadAPIView.as_view(), name="auth-resume"),
]

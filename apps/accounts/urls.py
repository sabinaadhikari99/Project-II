from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    LoginAPIView,
    GetTokenAPIView,
    LogoutAPIView,
    ProfileAPIView,
    RegisterAPIView,
    ResumeUploadAPIView,
    LinkedInLoginAPIView,
    LinkedInCallbackAPIView,
    LinkedInRoleSelectAPIView,
    LinkedInConflictResolveAPIView,
)

urlpatterns = [
    path("register/", RegisterAPIView.as_view(), name="auth-register"),
    path("login/", LoginAPIView.as_view(), name="auth-login"),
    path("token/", GetTokenAPIView.as_view(), name="auth-token"),
    path("refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("profile/", ProfileAPIView.as_view(), name="auth-profile"),
    path("resume/", ResumeUploadAPIView.as_view(), name="auth-resume"),
    path("linkedin/login/", LinkedInLoginAPIView.as_view(), name="auth-linkedin-login"),
    path("linkedin/callback/", LinkedInCallbackAPIView.as_view(), name="auth-linkedin-callback"),
    path("linkedin/role-select/", LinkedInRoleSelectAPIView.as_view(), name="auth-linkedin-role-select"),
    path("linkedin/conflict-resolve/", LinkedInConflictResolveAPIView.as_view(), name="auth-linkedin-conflict-resolve"),
]

# file path: apps/admin_panel/urls.py
from django.urls import path

from .views import AdminReportsAPIView, AdminUserDetailAPIView, AdminUsersAPIView, SystemSettingDetailAPIView, SystemSettingsAPIView

urlpatterns = [
    path("users/", AdminUsersAPIView.as_view(), name="admin-users"),
    path("users/<int:pk>/", AdminUserDetailAPIView.as_view(), name="admin-user-detail"),
    path("reports/", AdminReportsAPIView.as_view(), name="admin-reports"),
    path("settings/", SystemSettingsAPIView.as_view(), name="admin-settings"),
    path("settings/<int:pk>/", SystemSettingDetailAPIView.as_view(), name="admin-setting-detail"),
]

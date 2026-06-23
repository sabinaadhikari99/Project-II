# file path: apps/admin_panel/views.py
from django.db.models import Count
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.jobs.models import Application, JobPosting
from apps.shared.permissions import IsAdmin

from .models import SystemSetting
from .serializers import AdminUserSerializer, SystemSettingSerializer


class AdminUsersAPIView(generics.ListAPIView):
    queryset = User.objects.all().select_related("profile")
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdmin]


class AdminUserDetailAPIView(generics.RetrieveDestroyAPIView):
    queryset = User.objects.all().select_related("profile")
    serializer_class = AdminUserSerializer
    permission_classes = [IsAdmin]


class AdminReportsAPIView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request):
        return Response({
            "users_by_role": list(User.objects.values("role").annotate(total=Count("id"))),
            "total_jobs": JobPosting.objects.count(),
            "active_jobs": JobPosting.objects.filter(is_active=True).count(),
            "total_applications": Application.objects.count(),
            "applications_by_status": list(Application.objects.values("status").annotate(total=Count("id"))),
        })


class SystemSettingsAPIView(generics.ListCreateAPIView):
    queryset = SystemSetting.objects.all()
    serializer_class = SystemSettingSerializer
    permission_classes = [IsAdmin]


class SystemSettingDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = SystemSetting.objects.all()
    serializer_class = SystemSettingSerializer
    permission_classes = [IsAdmin]

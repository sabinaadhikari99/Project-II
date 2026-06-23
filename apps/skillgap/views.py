# file path: apps/skillgap/views.py
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker

from .services import analyze_skill_gap


class SkillGapAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        return Response(analyze_skill_gap(request.user))

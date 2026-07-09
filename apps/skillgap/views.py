from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import PermissionDenied

from .services import analyze_skill_gap


class SkillGapAPIView(APIView):
    # Explicitly use JWT authentication
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Role check (optional, but keep for safety)
        if request.user.role != 'job_seeker':
            raise PermissionDenied("Only job seekers can access skill gap analysis.")
        
        return Response(analyze_skill_gap(request.user))
    


from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from .analysis_memo import clear as clear_analysis_memo
from .course_service import CourseRecommendationService
from .roadmap_service import LearningRoadmapService, RoadmapNotFoundError
from .serializers import RoadmapProgressUpdateSerializer
from .services import analyze_skill_gap


class SkillGapAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        self._require_job_seeker(request.user)
        try:
            return Response(analyze_skill_gap(request.user))
        finally:
            clear_analysis_memo()

    @staticmethod
    def _require_job_seeker(user):
        if user.role != "job_seeker":
            raise PermissionDenied("Only job seekers can access skill gap analysis.")


class RecommendedCoursesAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        self._require_job_seeker(request.user)
        force = request.query_params.get("refresh") == "1"
        try:
            return Response(CourseRecommendationService.get_or_generate(request.user, force=force))
        finally:
            clear_analysis_memo()

    @staticmethod
    def _require_job_seeker(user):
        if user.role != "job_seeker":
            raise PermissionDenied("Only job seekers can access course recommendations.")


class LearningRoadmapAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        self._require_job_seeker(request.user)
        force = request.query_params.get("refresh") == "1"
        try:
            return Response(LearningRoadmapService.get_or_generate(request.user, force=force))
        finally:
            clear_analysis_memo()

    @staticmethod
    def _require_job_seeker(user):
        if user.role != "job_seeker":
            raise PermissionDenied("Only job seekers can access learning roadmaps.")


class RoadmapProgressAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        self._require_job_seeker(request.user)
        serializer = RoadmapProgressUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            summary = LearningRoadmapService.update_step_status(
                request.user,
                serializer.validated_data["step_number"],
                serializer.validated_data["status"],
            )
        except RoadmapNotFoundError as exc:
            return Response({"detail": str(exc)}, status=404)
        return Response(summary)

    @staticmethod
    def _require_job_seeker(user):
        if user.role != "job_seeker":
            raise PermissionDenied("Only job seekers can update roadmap progress.")

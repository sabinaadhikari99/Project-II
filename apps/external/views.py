# file path: apps/external/views.py
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker

from .services import fetch_linkedin_jobs


class LinkedInJobsAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        jobs = fetch_linkedin_jobs(
            request.query_params.get("query", "python"),
            request.query_params.get("location", ""),
            int(request.query_params.get("limit", 10)),
        )
        return Response({"jobs": jobs})

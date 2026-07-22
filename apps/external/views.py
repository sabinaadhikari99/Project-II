from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker
from apps.shared.performance import PerformanceTimer

from .services import fetch_linkedin_jobs


class LinkedInJobsAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        timer = PerformanceTimer("External Integration API")

        query = request.query_params.get("query", "python")
        location = request.query_params.get("location", "")
        limit = int(request.query_params.get("limit", 10))

        timer.reset_queries()

        with timer.measure("Fetch LinkedIn Jobs"):
            jobs = fetch_linkedin_jobs(query, location=location, limit=limit)

        timer.count_queries()

        with timer.measure("Serialize Response"):
            response = Response({"jobs": jobs})

        timer.flush("External Integration: LinkedInJobsAPIView")
        return response

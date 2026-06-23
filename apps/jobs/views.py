# file path: apps/jobs/views.py
from rest_framework import generics, parsers, response, views

from apps.shared.permissions import IsJobSeeker

from .models import JobPosting, RecentlyViewedJob, SavedJob
from .serializers import (
    ApplicationSerializer,
    JobPostingSerializer,
    RecentlyViewedJobSerializer,
    RecommendedJobSerializer,
    SavedJobSerializer,
)
from .services import analyze_resume_match, apply_to_job, recommend_jobs_for_user


class RecommendedJobsAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        data = recommend_jobs_for_user(request.user, request=request)
        return response.Response(RecommendedJobSerializer(data, many=True, context={"request": request}).data)


class AIMatchAPIView(views.APIView):
    permission_classes = [IsJobSeeker]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        resume = request.FILES.get("resume")
        if not resume:
            return response.Response({"detail": "Resume PDF is required."}, status=400)
        try:
            data = analyze_resume_match(request.user, resume, request=request)
        except ValueError as error:
            return response.Response({"detail": str(error)}, status=400)

        data["recommended_jobs"] = RecommendedJobSerializer(
            data["recommended_jobs"],
            many=True,
            context={"request": request},
        ).data
        return response.Response(data)


class ApplyJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        application = apply_to_job(request.user, job, request.data.get("cover_letter", ""))
        return response.Response(ApplicationSerializer(application).data, status=201)


class FilterJobsAPIView(generics.ListAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        queryset = JobPosting.objects.filter(is_active=True)
        title = self.request.query_params.get("title") or self.request.query_params.get("role")
        location = self.request.query_params.get("location")
        skill = self.request.query_params.get("skill")
        experience = self.request.query_params.get("experience")
        work_mode = self.request.query_params.get("work_mode")
        if title:
            queryset = queryset.filter(title__icontains=title)
        if location:
            queryset = queryset.filter(location__icontains=location)
        if skill:
            queryset = queryset.filter(required_skills__icontains=skill)
        if experience:
            queryset = queryset.filter(experience_required__lte=experience)
        if work_mode:
            queryset = queryset.filter(work_mode=work_mode)
        return queryset


class SavedJobsAPIView(generics.ListAPIView):
    serializer_class = SavedJobSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        return SavedJob.objects.filter(user=self.request.user).select_related("job")


class ToggleSavedJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        saved, created = SavedJob.objects.get_or_create(user=request.user, job=job)
        if not created:
            saved.delete()
        return response.Response({"saved": created})


class RecentlyViewedJobsAPIView(generics.ListAPIView):
    serializer_class = RecentlyViewedJobSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        return RecentlyViewedJob.objects.filter(user=self.request.user).select_related("job")[:8]


class MarkRecentlyViewedJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        RecentlyViewedJob.objects.update_or_create(user=request.user, job=job)
        return response.Response({"viewed": True})

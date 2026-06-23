# file path: apps/recruiters/views.py
from rest_framework import generics, response, views

from apps.jobs.models import JobPosting
from apps.jobs.serializers import JobPostingSerializer
from apps.jobs.services import create_job_with_embedding, match_candidates_for_job, update_job_embedding
from apps.shared.permissions import IsRecruiter

from .serializers import CandidateMatchSerializer


class RecruiterJobsAPIView(generics.ListCreateAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return JobPosting.objects.filter(recruiter=self.request.user)

    def perform_create(self, serializer):
        job = create_job_with_embedding(self.request.user, serializer.validated_data)
        serializer.instance = job


class RecruiterJobDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return JobPosting.objects.filter(recruiter=self.request.user)

    def perform_update(self, serializer):
        job = serializer.save()
        update_job_embedding(job)


class JobCandidatesAPIView(views.APIView):
    permission_classes = [IsRecruiter]

    def get(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, recruiter=request.user)
        return response.Response(CandidateMatchSerializer(match_candidates_for_job(job), many=True).data)

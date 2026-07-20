from rest_framework import generics, response, views

from apps.jobs.models import JobPosting
from apps.jobs.serializers import JobPostingSerializer
from apps.jobs.services import create_job_with_embedding, match_candidates_for_job, update_job_embedding
from apps.shared.permissions import IsRecruiter

from .models import RecruiterActivity
from .serializers import CandidateMatchSerializer, RecruiterActivitySerializer


def log_activity(recruiter, activity_type, job, description=""):
    RecruiterActivity.objects.create(
        recruiter=recruiter,
        job=job,
        activity_type=activity_type,
        description=description or "",
    )


class RecruiterJobsAPIView(generics.ListCreateAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return JobPosting.objects.filter(recruiter=self.request.user)

    def perform_create(self, serializer):
        job = create_job_with_embedding(self.request.user, serializer.validated_data)
        serializer.instance = job
        activity_type = "job_published" if job.is_active else "draft_saved"
        label = "Published" if job.is_active else "Saved as draft"
        log_activity(self.request.user, activity_type, job, f'{label} "{job.title}"')


class RecruiterJobDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return JobPosting.objects.filter(recruiter=self.request.user)

    def perform_update(self, serializer):
        old_job = self.get_object()
        old_active = old_job.is_active
        job = serializer.save()
        update_job_embedding(job)

        if old_active != job.is_active:
            if job.is_active:
                log_activity(self.request.user, "job_reopened", job, f'Reopened "{job.title}"')
            else:
                log_activity(self.request.user, "job_closed", job, f'Closed "{job.title}"')
        else:
            log_activity(self.request.user, "job_updated", job, f'Updated "{job.title}"')

    def perform_destroy(self, instance):
        log_activity(self.request.user, "draft_deleted", None, f'Deleted "{instance.title}"')
        instance.delete()


class JobCandidatesAPIView(views.APIView):
    permission_classes = [IsRecruiter]

    def get(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, recruiter=request.user)
        return response.Response(CandidateMatchSerializer(match_candidates_for_job(job), many=True).data)


class RecruiterActivitiesAPIView(generics.ListAPIView):
    serializer_class = RecruiterActivitySerializer
    permission_classes = [IsRecruiter]

    def get_queryset(self):
        return RecruiterActivity.objects.filter(recruiter=self.request.user).select_related("job")[:10]

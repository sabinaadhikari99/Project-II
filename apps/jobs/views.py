# file path: apps/jobs/views.py
import logging

from django.utils import timezone
from rest_framework import generics, parsers, response, views

from apps.shared.fingerprint import profile_resume_fingerprint
from apps.shared.permissions import IsJobSeeker
from apps.state.services import AnalysisSessionService

from .models import JobPosting, RecentlyViewedJob, SavedJob
from .serializers import (
    ApplicationSerializer,
    JobPostingSerializer,
    RecentlyViewedJobSerializer,
    RecommendedJobSerializer,
    SavedJobSerializer,
)
# Re-exported: `apps.accounts.views` imports `parse_terms` from here, and the
# synonym vocabulary now lives with the search engine that uses it.
from .search import SYNONYM_MAP, normalize, parse_terms, search_jobs  # noqa: F401
from .services import analyze_resume_match, apply_to_job, recommend_jobs_for_user

logger = logging.getLogger(__name__)


class RecommendedJobsAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        data = recommend_jobs_for_user(request.user, request=request)
        return response.Response(RecommendedJobSerializer(data, many=True, context={"request": request}).data)


class AIMatchAPIView(views.APIView):
    """Analyse an uploaded CV (POST) or replay the stored analysis (GET).

    The analysis is expensive and, until now, existed only in the browser tab
    that produced it: a refresh or a trip to another page threw it away and the
    user had to re-upload. Every successful POST is persisted as the user's
    single shared analysis session, and GET replays it verbatim - no models are
    re-run, no AI calls are made - until a new upload replaces it.
    """

    permission_classes = [IsJobSeeker]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get(self, request):
        return response.Response(AnalysisSessionService.restore(request.user))

    def post(self, request):
        resume = request.FILES.get("resume")
        if not resume:
            return response.Response({"success": False, "message": "Resume PDF is required."}, status=400)

        try:
            data = analyze_resume_match(request.user, resume, request=request)
        except ValueError as e:
            return response.Response({"success": False, "message": str(e)}, status=400)
        except Exception as e:
            logger.error("AI Match unexpected error for user %s: %s", request.user.id, e, exc_info=True)
            return response.Response(
                {"success": False, "message": "An unexpected error occurred while analyzing your resume. Please try again."},
                status=500,
            )

        recommended_jobs = data.get("recommended_jobs", [])
        serialized_jobs = RecommendedJobSerializer(recommended_jobs, many=True, context={"request": request}).data

        from apps.notifications.services import notify_resume_analysis_complete
        best_match = data.get("resume_score", 0)
        notify_resume_analysis_complete(request.user, best_match)

        result = {
            "success": True,
            "count": len(serialized_jobs),
            "matched_jobs": serialized_jobs,
            "profession": data.get("profession", ""),
            "specialization": data.get("specialization", ""),
            "specialization_confidence": data.get("specialization_confidence", 0),
            "profession_confidence": data.get("profession_confidence", 0),
            "resume_score": best_match,
            "resume_summary": data.get("resume_summary", ""),
            "skills_extracted": data.get("skills_extracted", []),
            "skill_sources": data.get("skill_sources", []),
            "match_analytics": data.get("match_analytics", []),
            "resume_insights": data.get("resume_insights", []),
            "resume_improvement_suggestions": data.get("resume_improvement_suggestions", []),
            # Phase 2: everything below explains WHY a number was produced.
            "score_breakdown": data.get("score_breakdown", {}),
            "structured_insights": data.get("structured_insights", []),
            "skill_action_plan": data.get("skill_action_plan", []),
            "resume_quality": data.get("resume_quality", {}),
            "cv_signals": data.get("cv_signals", {}),
        }
        if len(serialized_jobs) == 0:
            result["message"] = "No matching jobs found based on your current resume. Try updating your skills or check back later."

        result["analyzed_at"] = timezone.now().isoformat()
        result["cv_filename"] = getattr(resume, "name", "") or ""

        # Persist the finished analysis as the user's shared session. A storage
        # failure must never lose the response the user just waited for, so it
        # is logged and the analysis is still returned.
        try:
            session = AnalysisSessionService.save(
                request.user,
                result,
                resume_fingerprint=profile_resume_fingerprint(request.user),
                cv_filename=result["cv_filename"],
            )
            # Same shape the restore endpoint returns, so the page stores one
            # kind of CV record whether it just uploaded or is coming back.
            result["cv"] = AnalysisSessionService.cv_metadata(session)
        except Exception:
            logger.exception("AI Match: could not persist analysis session for user %s", request.user.id)
            result["cv"] = None

        return response.Response(result)


class ApplyJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        application = apply_to_job(request.user, job, request.data.get("cover_letter", ""))
        return response.Response(ApplicationSerializer(application).data, status=201)


def saved_job_ids_for(user):
    """The ids this user has bookmarked, in one query.

    `JobPostingSerializer.is_saved` otherwise asks the database once per job
    in the list. Views that serialise more than one job hand the set in.
    """
    if not user or not user.is_authenticated:
        return set()
    return set(SavedJob.objects.filter(user=user).values_list("job_id", flat=True))


class SavedIdsContextMixin:
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["saved_job_ids"] = saved_job_ids_for(self.request.user)
        return context


class FilterJobsAPIView(SavedIdsContextMixin, generics.ListAPIView):
    """The job search: every filter narrows, and results come back ranked.

    The query itself lives in `search.py`. This view only reads the request
    and hands it over, so the search rules stay testable without a request.
    """

    serializer_class = JobPostingSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        params = self.request.query_params
        return search_jobs(
            JobPosting.objects.filter(is_active=True),
            role=params.get("title") or params.get("role") or "",
            skill=params.get("skill") or "",
            experience=params.get("experience"),
            work_mode=params.get("work_mode"),
            work_modes=[value for value, _ in JobPosting.WORK_MODE_CHOICES],
        )


class SavedJobsAPIView(SavedIdsContextMixin, generics.ListAPIView):
    serializer_class = SavedJobSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        return SavedJob.objects.filter(user=self.request.user).select_related(
            "job", "job__recruiter"
        )


class ToggleSavedJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        saved, created = SavedJob.objects.get_or_create(user=request.user, job=job)
        if not created:
            saved.delete()
        return response.Response({"saved": created})


class RecentlyViewedJobsAPIView(SavedIdsContextMixin, generics.ListAPIView):
    serializer_class = RecentlyViewedJobSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        return RecentlyViewedJob.objects.filter(user=self.request.user).select_related(
            "job", "job__recruiter"
        )[:8]


class MarkRecentlyViewedJobAPIView(views.APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request, pk):
        job = generics.get_object_or_404(JobPosting, pk=pk, is_active=True)
        RecentlyViewedJob.objects.update_or_create(user=request.user, job=job)
        return response.Response({"viewed": True})

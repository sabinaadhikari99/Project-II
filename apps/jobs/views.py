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


SYNONYM_MAP = {
    "javascript": "js", "js": "javascript",
    "typescript": "ts", "ts": "typescript",
    "react": "reactjs", "reactjs": "react",
    "next.js": "nextjs", "nextjs": "next.js",
    "node.js": "nodejs", "nodejs": "node.js",
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "cybersecurity": "cyber security",
    "cyber security": "cybersecurity",
}


def normalize(word):
    w = word.strip().lower()
    return SYNONYM_MAP.get(w, w)


def parse_terms(raw):
    if not raw:
        return []
    return [normalize(t) for t in raw.replace(",", " ").split() if t.strip()]


class FilterJobsAPIView(generics.ListAPIView):
    serializer_class = JobPostingSerializer
    permission_classes = [IsJobSeeker]

    def get_queryset(self):
        queryset = JobPosting.objects.filter(is_active=True)

        title = self.request.query_params.get("title") or self.request.query_params.get("role")
        skill = self.request.query_params.get("skill")
        experience = self.request.query_params.get("experience")
        work_mode = self.request.query_params.get("work_mode")

        title_terms = parse_terms(title)
        skill_terms = parse_terms(skill)

        from django.db.models import Q

        title_q = None
        if title_terms:
            title_q = Q()
            for t in title_terms:
                title_q |= Q(title__icontains=t)

        skill_q = None
        if len(skill_terms) == 1:
            skill_q = (
                Q(required_skills__icontains=skill_terms[0])
                | Q(title__icontains=skill_terms[0])
                | Q(description__icontains=skill_terms[0])
            )
        elif len(skill_terms) >= 2:
            from itertools import combinations

            unit_qs = []
            for t in skill_terms:
                unit_qs.append(
                    Q(required_skills__icontains=t)
                    | Q(title__icontains=t)
                    | Q(description__icontains=t)
                )
            skill_q = Q()
            for a, b in combinations(unit_qs, 2):
                skill_q |= a & b

        combined = Q()
        if title_q:
            combined |= title_q
        if skill_q:
            combined |= skill_q

        if combined:
            queryset = queryset.filter(combined)

        if experience:
            queryset = queryset.filter(experience_required__lte=experience)
        if work_mode:
            queryset = queryset.filter(work_mode=work_mode)

        return queryset.order_by("-created_at")


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

# file path: apps/chatbot/context.py
"""Career context builder.

The assistant answers from the user's own SkillSync data, so something has to
collect that data before the model is called. This module is that collector -
and *only* that. Every figure it returns is produced by an existing service:

    CV + analysis      -> apps.state.services.AnalysisSessionService
    skill gap          -> apps.skillgap.services.analyze_skill_gap
    courses / roadmap  -> apps.skillgap.{course_service,roadmap_service}
    jobs / applications-> apps.jobs.models
    quiz               -> apps.state.services.QuizSessionService
    notifications      -> apps.notifications.models

Nothing here re-scores a CV, re-ranks a job or re-computes a gap. If a number
appears in an answer, it is the same number the corresponding page shows.

Sections are built on demand: a question about applications must not pay for a
roadmap generation. Each section is independently guarded, so one unavailable
source degrades that section instead of the whole answer.
"""

import logging

from django.db.models import Count

logger = logging.getLogger(__name__)

#: Caps that keep a prompt small enough to stay fast and cheap while still
#: carrying everything an answer needs.
MAX_JOBS = 6
MAX_SKILLS = 40
MAX_GAPS = 12
MAX_COURSES = 5
MAX_ROADMAP_STEPS = 10
MAX_APPLICATIONS = 12
MAX_SAVED = 8
MAX_NOTIFICATIONS = 6
MAX_MARKET_ROWS = 8


def _safe(section):
    """Never let one unavailable data source break the whole answer."""
    def wrapper(self):
        try:
            return section(self)
        except Exception:
            logger.warning("assistant context: %s unavailable", section.__name__, exc_info=True)
            return {}
    wrapper.__name__ = section.__name__
    return wrapper


class CareerContextBuilder:
    """Assembles the slices of a user's SkillSync data an answer needs.

    One instance per request: each section is computed at most once, and the
    underlying services keep their own caches, so repeated questions in a
    conversation do not re-run any analysis.
    """

    #: Section name -> builder method. The router picks from these names.
    SECTIONS = (
        "profile", "cv", "match", "skill_gap", "roadmap", "courses",
        "applications", "saved_jobs", "quiz", "activity", "market",
    )

    def __init__(self, user):
        self.user = user
        self._memo = {}

    # -- public API ---------------------------------------------------------
    def build(self, sections):
        """Return ``{section: data}`` for the requested section names."""
        context = {}
        for name in sections:
            if name not in self.SECTIONS:
                continue
            data = self._section(name)
            if data:
                context[name] = data
        return context

    def snapshot(self):
        """Small always-on header: who the user is and where they stand."""
        cv = self._section("cv")
        gap = self._section("skill_gap")
        return {
            "has_cv": bool(cv.get("filename") or cv.get("profession")),
            "profession": cv.get("profession") or "",
            "specialization": cv.get("specialization") or "",
            "match_score": cv.get("match_score", 0),
            "career_level": gap.get("career_level_label") or "",
            "skill_count": len(gap.get("skills") or cv.get("skills") or []),
            "gap_count": gap.get("total_gaps", 0),
        }

    # -- section dispatch ---------------------------------------------------
    def _section(self, name):
        if name not in self._memo:
            self._memo[name] = getattr(self, f"_build_{name}")()
        return self._memo[name]

    @property
    def _analysis_payload(self):
        """The stored AI Match result - the single shared analysis session."""
        if "_payload" not in self._memo:
            from apps.state.services import AnalysisSessionService

            session = AnalysisSessionService.get(self.user)
            self._memo["_payload"] = {
                "session": session,
                "payload": (session.payload or {}) if session else {},
            }
        return self._memo["_payload"]

    # -- sections -----------------------------------------------------------
    @_safe
    def _build_profile(self):
        profile = getattr(self.user, "profile", None)
        return {
            "name": self.user.get_full_name() or self.user.username,
            "email": self.user.email,
            "headline": getattr(profile, "headline", "") or "",
            "location": getattr(profile, "location", "") or "",
            "bio": (getattr(profile, "bio", "") or "")[:400],
            "experience_years": getattr(profile, "experience_years", 0) or 0,
            "education": (getattr(profile, "education", "") or "")[:200],
            "skills": list(getattr(profile, "skills", None) or [])[:MAX_SKILLS],
            "links": {
                "linkedin": getattr(profile, "linkedin_url", "") or "",
                "github": getattr(profile, "github_url", "") or "",
                "portfolio": getattr(profile, "portfolio_url", "") or "",
            },
        }

    @_safe
    def _build_cv(self):
        record = self._analysis_payload
        session, payload = record["session"], record["payload"]
        if session is None:
            profile = getattr(self.user, "profile", None)
            return {
                "uploaded": bool(getattr(profile, "resume_text", "")),
                "note": "No AI Match analysis on record. The user has not analysed a CV yet.",
            }

        quality = payload.get("resume_quality") or {}
        return {
            "uploaded": True,
            "filename": session.cv_filename,
            "analysed_at": session.updated_at.isoformat(),
            "profession": session.profession,
            "specialization": session.specialization,
            "profession_confidence": payload.get("profession_confidence", 0),
            "match_score": session.match_score,
            "summary": payload.get("resume_summary", ""),
            "skills": list(session.skills or [])[:MAX_SKILLS],
            "signals": payload.get("cv_signals") or {},
            "quality": {
                "score": quality.get("score"),
                "breakdown": [
                    {"label": b.get("label"), "score": b.get("score"), "detail": b.get("detail")}
                    for b in (quality.get("breakdown") or [])
                ],
                "recommendations": (quality.get("recommendations") or [])[:6],
            },
            "insights": payload.get("structured_insights") or payload.get("resume_insights") or [],
            "improvements": (payload.get("resume_improvement_suggestions") or [])[:6],
        }

    @_safe
    def _build_match(self):
        payload = self._analysis_payload["payload"]
        if not payload:
            return {}

        jobs = []
        for item in (payload.get("matched_jobs") or [])[:MAX_JOBS]:
            job = item.get("job") or {}
            jobs.append({
                "id": job.get("id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "work_mode": job.get("work_mode"),
                "salary_range": job.get("salary_range"),
                "experience_required": job.get("experience_required"),
                "match_percentage": item.get("match_percentage"),
                "matched_skills": item.get("matched_skills") or [],
                "missing_skills": item.get("missing_skills") or [],
                "why_matched": item.get("why_matched") or [],
                "why_not_higher": item.get("why_not_higher") or [],
                "score_breakdown": item.get("match_explanation") or {},
                "is_related_role": item.get("is_related_role", False),
            })

        return {
            "best_score": payload.get("resume_score", 0),
            "score_breakdown": payload.get("score_breakdown") or {},
            "score_components_explained": (
                "Each job score combines profession fit, skills overlap, experience, "
                "education, projects, certifications and semantic similarity."
            ),
            "analytics": (payload.get("match_analytics") or [])[:MAX_JOBS],
            "recommended_jobs": jobs,
            "action_plan": (payload.get("skill_action_plan") or [])[:MAX_GAPS],
        }

    @_safe
    def _build_skill_gap(self):
        from apps.skillgap.services import analyze_skill_gap

        gap = analyze_skill_gap(self.user)
        if not gap.get("has_resume"):
            return {"has_resume": False,
                    "note": "No CV on file, so no skill gap has been computed."}

        details = []
        for info in (gap.get("missing_skill_details") or [])[:MAX_GAPS]:
            details.append({
                "skill": info.get("skill"),
                "priority": info.get("priority"),
                "importance": info.get("importance"),
                "required_by_jobs": info.get("job_count"),
                "category": info.get("gap_category"),
            })

        return {
            "has_resume": True,
            "skills": (gap.get("user_skills") or [])[:MAX_SKILLS],
            "missing_skills": (gap.get("missing_skills") or [])[:MAX_GAPS],
            "missing_details": details,
            "gap_categories": gap.get("gap_categories") or {},
            "coverage": gap.get("coverage") or {},
            "career_level": gap.get("career_level"),
            "career_level_label": gap.get("career_level_label"),
            "experience_years": gap.get("experience_years"),
            "education_label": gap.get("education_label"),
            "profession": gap.get("profession"),
            "specialization": gap.get("specialization"),
            "match_score": gap.get("match_score"),
            "match_explanation": gap.get("match_explanation") or {},
            "total_gaps": len(gap.get("missing_skills") or []),
        }

    @_safe
    def _build_roadmap(self):
        from apps.skillgap.roadmap_service import LearningRoadmapService

        data = LearningRoadmapService.get_or_generate(self.user)
        progress = data.get("progress") or {}
        roadmap = data.get("roadmap") or {}
        if not progress:
            return {"has_roadmap": False}

        steps = []
        for step in (progress.get("steps") or [])[:MAX_ROADMAP_STEPS]:
            steps.append({
                "step": step.get("step_number"),
                "skill": step.get("skill_name"),
                "status": step.get("status"),
                "hours": step.get("estimated_hours"),
                "difficulty": step.get("difficulty"),
                "priority": step.get("priority"),
                "outcome": step.get("expected_outcome"),
            })

        return {
            "has_roadmap": True,
            "job_ready": roadmap.get("job_ready"),
            "total_steps": progress.get("total"),
            "completed": progress.get("completed"),
            "in_progress": progress.get("in_progress"),
            "percentage": progress.get("percentage"),
            "remaining_hours": progress.get("remaining_hours"),
            "estimated_completion_date": progress.get("estimated_completion_date"),
            "weekly_hours": roadmap.get("weekly_hours"),
            "steps": steps,
        }

    @_safe
    def _build_courses(self):
        from apps.skillgap.course_service import CourseRecommendationService

        data = CourseRecommendationService.get_or_generate(self.user)
        courses = []
        for course in (data.get("courses") or [])[:MAX_COURSES]:
            duration = course.get("estimated_duration") or {}
            courses.append({
                "title": course.get("course_title"),
                "provider": course.get("provider"),
                "skill": course.get("skill_covered"),
                "closes_gap": course.get("missing_skill"),
                "priority": course.get("priority"),
                "difficulty": course.get("difficulty"),
                "hours": duration.get("hours"),
                "weeks": duration.get("weeks"),
                "is_free": course.get("is_free"),
                "why": course.get("why_recommended"),
                "expected_score_gain": course.get("expected_score_gain"),
                "url": course.get("url"),
            })
        return {"has_resume": data.get("has_resume", False), "courses": courses}

    @_safe
    def _build_applications(self):
        from apps.jobs.models import Application

        rows = (
            Application.objects
            .filter(applicant=self.user)
            .select_related("job")
            .order_by("-created_at")[:MAX_APPLICATIONS]
        )
        applications = [{
            "job_id": row.job_id,
            "title": row.job.title,
            "company": row.job.company,
            "status": row.status,
            "status_label": row.get_status_display(),
            "applied_on": row.created_at.date().isoformat(),
        } for row in rows]

        by_status = {}
        for item in applications:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1

        return {
            "total": Application.objects.filter(applicant=self.user).count(),
            "by_status": by_status,
            "recent": applications,
        }

    @_safe
    def _build_saved_jobs(self):
        from apps.jobs.models import SavedJob

        rows = (
            SavedJob.objects
            .filter(user=self.user)
            .select_related("job")
            .order_by("-created_at")[:MAX_SAVED]
        )
        return {
            "total": SavedJob.objects.filter(user=self.user).count(),
            "jobs": [{
                "job_id": row.job_id,
                "title": row.job.title,
                "company": row.job.company,
                "work_mode": row.job.work_mode,
                "required_skills": (row.job.required_skills or [])[:10],
            } for row in rows],
        }

    @_safe
    def _build_quiz(self):
        from apps.state.services import QuizSessionService

        session = QuizSessionService.get(self.user)
        if session is None:
            return {"taken": False}
        return {
            "taken": True,
            "status": session.status,
            "answered": len(session.answers or {}),
            "total": session.total,
            "score": session.score,
            "percentage": session.percentage,
            "last_activity": session.updated_at.isoformat(),
            "weak_areas": [
                row.get("question")
                for row in (session.results or [])
                if row.get("correct") is False
            ][:6],
        }

    @_safe
    def _build_activity(self):
        from apps.jobs.models import RecentlyViewedJob
        from apps.notifications.models import Notification

        viewed = (
            RecentlyViewedJob.objects
            .filter(user=self.user)
            .select_related("job")
            .order_by("-viewed_at")[:MAX_SAVED]
        )
        notifications = (
            Notification.objects
            .filter(user=self.user)
            .order_by("-created_at")[:MAX_NOTIFICATIONS]
        )
        return {
            "recently_viewed": [
                {"title": row.job.title, "company": row.job.company} for row in viewed
            ],
            "unread_notifications": Notification.objects.filter(
                user=self.user, is_read=False,
            ).count(),
            "recent_notifications": [{
                "type": row.notification_type,
                "title": row.title,
                "message": row.message[:160],
                "created_at": row.created_at.date().isoformat(),
            } for row in notifications],
        }

    @_safe
    def _build_market(self):
        """Aggregate view of live postings. No recruiter personal data leaves here."""
        from apps.jobs.models import JobPosting

        active = JobPosting.objects.filter(is_active=True)
        profession = self._section("cv").get("profession") or ""

        in_field = active.filter(job_category=profession) if profession else active.none()
        skill_demand = {}
        for row in in_field.values_list("required_skills", flat=True)[:120]:
            for skill in (row or []):
                if isinstance(skill, str) and skill.strip():
                    key = skill.strip()
                    skill_demand[key] = skill_demand.get(key, 0) + 1

        top_skills = sorted(skill_demand.items(), key=lambda kv: -kv[1])[:MAX_MARKET_ROWS]

        return {
            "total_active_jobs": active.count(),
            "jobs_in_user_field": in_field.count() if profession else 0,
            "top_categories": [
                {"category": row["job_category"] or "Uncategorised", "jobs": row["n"]}
                for row in active.values("job_category").annotate(n=Count("id")).order_by("-n")[:MAX_MARKET_ROWS]
            ],
            "top_companies": [
                {"company": row["company"], "jobs": row["n"]}
                for row in active.values("company").annotate(n=Count("id")).order_by("-n")[:MAX_MARKET_ROWS]
            ],
            "most_demanded_skills_in_field": [
                {"skill": skill, "postings": count} for skill, count in top_skills
            ],
        }

    # -- targeted lookups ---------------------------------------------------
    def find_jobs(self, terms, limit=3):
        """Resolve job titles or companies named in a question.

        Lets the assistant answer "compare my CV with the Flutter role at Acme"
        about the actual posting rather than a guess.
        """
        from apps.jobs.models import JobPosting
        from django.db.models import Q

        terms = [t for t in (terms or []) if len(t) > 3]
        if not terms:
            return []

        query = Q()
        for term in terms[:4]:
            query |= Q(title__icontains=term) | Q(company__icontains=term)

        matches = JobPosting.objects.filter(is_active=True).filter(query)[:limit]
        skills = {s.lower() for s in (self._section("skill_gap").get("skills") or [])}

        results = []
        for job in matches:
            required = [s for s in (job.required_skills or []) if isinstance(s, str)]
            results.append({
                "id": job.id,
                "title": job.title,
                "company": job.company,
                "location": job.location,
                "work_mode": job.work_mode,
                "salary_range": job.salary_range,
                "experience_required": job.experience_required,
                "education_required": job.education_required,
                "required_skills": required,
                "skills_user_has": [s for s in required if s.lower() in skills],
                "skills_user_lacks": [s for s in required if s.lower() not in skills],
                "description": (job.description or "")[:400],
            })
        return results

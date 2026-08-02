import heapq
import math
from datetime import date, timedelta
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

from .analysis_memo import run_once
from .cache import get_cached, set_cached
from .career import CareerAnalyzer
from .catalog import (
    BASE_HOURS,
    DIFFICULTY_RANK,
    JUNIOR_MAX,
    SKILL_FAMILY_ALIASES,
    get_course_entry,
    get_skill_dependencies,
    get_skill_difficulty,
    is_skill_relevant,
    display_for_key,
)
from .models import LearningRoadmap, RoadmapStepProgress

PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
LEVEL_FACTORS = {"junior": 1.2, "mid": 1.0, "senior": 0.85}
MAX_STEPS = 25
PHASE_SIZE = 3
MAX_SKILL_PHASES = 5
CAPSTONE_PHASE_NUMBER = "capstone"

LINKEDIN_SEARCH = "https://www.linkedin.com/learning/search?keywords={query}"
FALLBACK_PROVIDER = "LinkedIn Learning"

OUTCOMES = {
    "beginner": "Confidently apply {skill} fundamentals to {role} projects and entry-level tasks.",
    "intermediate": "Integrate {skill} into production-style {role} workflows and demonstrate measurable results.",
    "advanced": "Architect and lead complex {role} solutions with {skill} at an expert level.",
}

GENERIC_PHASE_TITLES = (
    "Core Foundations",
    "Applied Skills",
    "Advanced Proficiency",
    "Expert Mastery",
    "Specialization",
)

PROFESSION_PHASE_THEMES = {
    "Frontend Developer": ("Frontend Fundamentals", "Advanced UI & State", "Testing & Performance", "Production Web Apps"),
    "Backend Developer": ("Backend Foundations", "APIs & Data", "Scalability & Reliability", "Production Backend Systems"),
    "Full Stack Developer": ("Full Stack Foundations", "End-to-End Features", "Testing & Deployment", "Production Full Stack Apps"),
    "Software Engineer": ("Engineering Fundamentals", "System Design & Patterns", "Quality & Tooling", "Production Engineering"),
    "Mobile Developer": ("Mobile App Foundations", "App Architecture & State", "Quality, Testing & Deployment", "Production Readiness"),
    "DevOps Engineer": ("Infrastructure Foundations", "Containers & Orchestration", "Automation & Observability", "Production Operations"),
    "Cybersecurity Engineer": ("Security Foundations", "Threat Detection & Defense", "Offensive Security & Audits", "Security Operations"),
    "Data Analyst": ("Data Foundations", "Analysis & Visualization", "Statistical Modeling", "Data Storytelling"),
    "Data Engineer": ("Data Engineering Foundations", "Pipelines & Orchestration", "Warehousing & Streaming", "Production Data Platforms"),
    "Data Scientist": ("Data Science Foundations", "Modeling & Experimentation", "Advanced ML & Deep Learning", "Production ML"),
    "Machine Learning Engineer": ("ML Foundations", "Model Development", "MLOps & Deployment", "Production ML Systems"),
    "UI/UX Designer": ("Design Foundations", "Research & Ideation", "Interaction & Systems", "Design Leadership"),
    "Graphic Designer": ("Design Fundamentals", "Brand & Identity", "Digital & Motion", "Creative Direction"),
    "Product Manager": ("Product Foundations", "Discovery & Strategy", "Delivery & Metrics", "Product Leadership"),
    "Marketing Manager": ("Marketing Foundations", "Channels & Content", "Analytics & Optimization", "Marketing Leadership"),
    "Accountant": ("Accounting Foundations", "Reporting & Compliance", "Analysis & Systems", "Accounting Leadership"),
    "Human Resources Manager": ("HR Foundations", "Talent & Culture", "Compliance & Systems", "HR Leadership"),
}

PROJECT_DOMAIN = {
    "Frontend Developer": "Web App",
    "Backend Developer": "API Service",
    "Full Stack Developer": "Web Platform",
    "Software Engineer": "Software Service",
    "Mobile Developer": "Mobile App",
    "DevOps Engineer": "Delivery Pipeline",
    "Cybersecurity Engineer": "Security Lab",
    "Data Analyst": "Analytics Dashboard",
    "Data Engineer": "Data Pipeline",
    "Data Scientist": "Prediction Model",
    "Machine Learning Engineer": "ML Service",
    "UI/UX Designer": "Design System",
    "Graphic Designer": "Brand Kit",
    "Product Manager": "Product Plan",
    "Marketing Manager": "Campaign Playbook",
    "Accountant": "Ledger System",
    "Human Resources Manager": "HR Program",
}

# Advanced topics offered when the candidate has no remaining skill gaps.
# Each entry maps a catalog skill key to why it matters for that profession.
# Topics the candidate already masters are skipped automatically.
JOB_READY_ADVANCED = {
    "Frontend Developer": [
        ("systemdesign", "Scaling state, data flow and performance budgets is what separates senior front-end work."),
        ("webpack", "Bundle optimization keeps large front-ends fast for real users."),
        ("graphql", "Modern front-ends consume GraphQL APIs; it is a differentiating skill on the market."),
        ("tdd", "Test-driven development signals production-grade, regression-safe front-end quality."),
        ("microservices", "Understanding how front-ends talk to distributed backends unlocks senior architecture roles."),
    ],
    "Backend Developer": [
        ("systemdesign", "Designing APIs and services that scale is what separates mid-level from senior backend work."),
        ("microservices", "Most senior backend roadmaps lead here: small, independently deployable services."),
        ("kafka", "Event-driven architectures rely on streaming platforms like Kafka."),
        ("redis", "Caching and job queues are the core performance levers of production backends."),
        ("kubernetes", "Running backend services in production today means containers and orchestration."),
    ],
    "Full Stack Developer": [
        ("systemdesign", "Owning the full stack means thinking in systems, not just pages."),
        ("microservices", "Breaking a monolith into services is the classic senior full stack challenge."),
        ("graphql", "GraphQL unifies front-end and back-end data contracts in modern platforms."),
        ("aws", "Cloud deployment of full stack apps is expected in most hiring pipelines."),
        ("tdd", "Automated tests let you ship full stack features with confidence."),
    ],
    "Software Engineer": [
        ("systemdesign", "System design interviews and real-world architecture both live here."),
        ("microservices", "Service decomposition, ownership and failure isolation are core engineering skills."),
        ("cleanarchitecture", "Keeps codebases maintainable as teams and features grow."),
        ("kubernetes", "Deploying and operating software at scale now means orchestrated containers."),
        ("algorithms", "Sharp algorithms keep you competitive in interviews and hard problems."),
    ],
    "Mobile Developer": [
        ("mobilearchitecture", "Well-structured mobile codebases are exactly what teams hire senior devs for."),
        ("mobiletesting", "Automated tests protect the release quality of mobile apps."),
        ("systemdesign", "Offline sync, auth and API design are the hard parts of mobile engineering."),
        ("aws", "Mobile backends, notifications and analytics commonly run on the cloud."),
    ],
    "DevOps Engineer": [
        ("helm", "Helm is the standard way to package and deploy Kubernetes workloads."),
        ("terraform", "Infrastructure as code is the core skill of modern platform teams."),
        ("prometheus", "Monitoring is how SRE teams detect failures before users do."),
        ("grafana", "Dashboards turn raw metrics into operational insight."),
        ("kafka", "Event streaming underpins reliable, decoupled data pipelines."),
    ],
    "Cybersecurity Engineer": [
        ("cissp", "The most recognized credential for senior security roles."),
        ("penetrationtesting", "Offensive skill deepens your defensive expertise."),
        ("cryptography", "The math and engineering behind modern security controls."),
        ("kubernetes", "Securing containerized environments is a growing security mandate."),
        ("compliance", "Security leaders must map technical controls to regulations."),
    ],
    "Data Analyst": [
        ("statistics", "Stronger statistics turns the same dashboards into sharper insights."),
        ("a/btesting", "Causal analysis separates analysts from senior analysts."),
        ("machinelearning", "Foundational ML lets analysts move from reporting to prediction."),
        ("tableau", "Interactive storytelling with data is a signature analyst skill."),
        ("datavisualization", "Visual craft is how insights get understood and acted on."),
    ],
    "Data Engineer": [
        ("spark", "Distributed processing is how data teams scale to petabyte workloads."),
        ("kafka", "Streaming data is a core ingredient of modern pipelines."),
        ("airflow", "Orchestration is the backbone of reliable, rerunnable pipelines."),
        ("snowflake", "Cloud warehousing is the most common destination for curated data."),
        ("kubernetes", "Data platforms increasingly run on orchestrated clusters."),
    ],
    "Data Scientist": [
        ("mlops", "Models that never ship have zero impact; MLOps fixes that."),
        ("modeldeployment", "Putting models behind APIs is the highest-leverage production skill."),
        ("deeplearning", "Deepen beyond standard ML to solve harder problems."),
        ("spark", "Scaling data work beyond a single notebook unlocks real-world impact."),
        ("a/btesting", "Rigorous experimentation is how data science earns trust."),
    ],
    "Machine Learning Engineer": [
        ("mlops", "The discipline that turns models into dependable products."),
        ("modeldeployment", "Serving models behind low-latency APIs is the core ML engineer craft."),
        ("kubernetes", "Scalable model serving and training infrastructure run on clusters."),
        ("systemdesign", "Designing end-to-end ML platforms separates engineers from builders."),
        ("kafka", "Streaming features and online inference start with event platforms."),
    ],
    "UI/UX Designer": [
        ("designsystems", "Design systems are how mature teams scale UI without chaos."),
        ("usabilitytesting", "Evidence-based design beats opinion every time."),
        ("interactiondesign", "Micro-interactions and motion make products feel polished."),
        ("informationarchitecture", "Structure is what makes complex products genuinely navigable."),
    ],
    "Graphic Designer": [
        ("branding", "Brand systems are the highest-value work a designer can own."),
        ("logos", "Identity design is a signature skill for senior designers."),
        ("visualdesign", "Deeper color and typography craft elevates every deliverable."),
        ("printdesign", "Print production is a discipline clients still pay a premium for."),
    ],
    "Product Manager": [
        ("productmetrics", "Data-driven decisions are the core of product management."),
        ("a/btesting", "Experimentation is how PMs validate direction before building."),
        ("marketresearch", "Market insight shapes positioning, pricing and roadmap bets."),
        ("roadmapping", "Roadmaps communicate vision and sequence to the whole company."),
    ],
    "Marketing Manager": [
        ("marketingautomation", "Automation scales campaigns without scaling headcount."),
        ("brandstrategy", "Strategic positioning is what senior marketers are hired for."),
        ("seo", "Organic acquisition compounds and lowers customer acquisition cost."),
        ("googleanalytics", "Measurement is the marketer's superpower."),
        ("sem", "Paid acquisition fundamentals power growth at every stage."),
    ],
    "Accountant": [
        ("financialanalysis", "Analysis is the path from bookkeeping to advisory work."),
        ("erp", "ERP fluency is prized across corporate finance teams."),
        ("sap", "SAP expertise commands a premium in enterprise accounting."),
        ("auditing", "Audit expertise underpins trust, compliance and leadership careers."),
    ],
    "Human Resources Manager": [
        ("talentacquisition", "Recruiting excellence drives every other HR function."),
        ("ats", "Applicant tracking systems run modern hiring operations."),
        ("laborlaws", "Compliance knowledge protects the organization and your career."),
        ("benefitsadministration", "Compensation and benefits are high-value HR specializations."),
    ],
}

# Fallback advanced topics for professions without a curated list.
JOB_READY_GENERIC = [
    ("systemdesign", "System-level thinking is the clearest signal of seniority."),
    ("cleanarchitecture", "Maintainable architecture keeps your codebase healthy as it grows."),
    ("unittesting", "Verified code is what lets you move fast without breaking things."),
    ("microservices", "Modern teams decompose systems; understanding it unlocks senior roles."),
    ("kubernetes", "Deployed at scale, modern software runs on orchestrated containers."),
    ("aws", "Cloud fluency appears in the majority of job postings."),
    ("mlops", "Operationalizing ML is the fastest-growing demand in technology."),
    ("llm", "LLM-powered features are now expected across product roadmaps."),
    ("datastructures", "Interview preparation and day-to-day engineering both depend on them."),
]


class RoadmapNotFoundError(Exception):
    pass


def _join_skills(skills):
    if len(skills) <= 1:
        return skills[0] if skills else ""
    if len(skills) == 2:
        return f"{skills[0]} and {skills[1]}"
    return f"{', '.join(skills[:-1])} and {skills[-1]}"


class LearningRoadmapService:
    def __init__(self, context=None):
        self.context = context

    @classmethod
    def get_or_generate(cls, user, force=False):
        context = run_once(user, lambda: CareerAnalyzer.analyze(user))
        service = cls(context)
        if not context.resume_text:
            return {
                "profession": "",
                "career_level": "",
                "roadmap": None,
                "progress": None,
                "has_resume": False,
            }
        roadmap = service._load_or_build(user, force)
        payload = roadmap["payload"]
        summary = cls.progress_summary_for(user, roadmap["pk"])
        phase_progress = summary.get("phase_progress", {})
        if payload.get("phases"):
            payload["phases"] = [
                {**phase, "progress": phase_progress.get(phase["phase_number"], {
                    "total": 0, "completed": 0, "in_progress": 0, "percentage": 0,
                })}
                for phase in payload["phases"]
            ]
        return {
            "profession": context.profession,
            "career_level": context.career_level_label,
            "roadmap": payload,
            "progress": summary,
            "has_resume": bool(context.resume_text),
        }

    @classmethod
    def update_step_status(cls, user, step_number, status):
        roadmap = LearningRoadmap.objects.filter(user=user).order_by("-updated_at").first()
        if roadmap is None:
            raise RoadmapNotFoundError("No learning roadmap found for this user.")
        steps = roadmap.payload.get("steps", [])
        step = next((s for s in steps if s["step_number"] == step_number), None)
        if step is None:
            raise RoadmapNotFoundError(f"Step {step_number} does not exist in the roadmap.")
        completed_at = timezone.now() if status == RoadmapStepProgress.STATUS_COMPLETED else None
        RoadmapStepProgress.objects.update_or_create(
            user=user,
            roadmap=roadmap,
            step_number=step_number,
            defaults={
                "skill_name": step["skill_name"],
                "status": status,
                "completed_at": completed_at,
            },
        )
        return cls.progress_summary_for(user, roadmap.pk)

    @classmethod
    def progress_summary_for(cls, user, roadmap_pk):
        roadmap = LearningRoadmap.objects.get(pk=roadmap_pk)
        steps = roadmap.payload.get("steps", [])
        rows = {
            row.step_number: row
            for row in RoadmapStepProgress.objects.filter(roadmap=roadmap)
        }
        completed = 0
        in_progress = 0
        remaining_hours = 0
        merged_steps = []
        phase_counts = {}
        for step in steps:
            row = rows.get(step["step_number"])
            status = row.status if row else RoadmapStepProgress.STATUS_NOT_STARTED
            if status == RoadmapStepProgress.STATUS_COMPLETED:
                completed += 1
            elif status == RoadmapStepProgress.STATUS_IN_PROGRESS:
                in_progress += 1
                remaining_hours += int(step.get("estimated_hours", 0))
            else:
                remaining_hours += int(step.get("estimated_hours", 0))
            phase = step.get("phase_number")
            if phase:
                counts = phase_counts.setdefault(phase, {"total": 0, "completed": 0, "in_progress": 0})
                counts["total"] += 1
                if status == RoadmapStepProgress.STATUS_COMPLETED:
                    counts["completed"] += 1
                elif status == RoadmapStepProgress.STATUS_IN_PROGRESS:
                    counts["in_progress"] += 1
            merged_steps.append({**step, "status": status})
        total = len(steps)
        percentage = round(completed / total * 100) if total else 0
        weekly_hours = settings.SKILLGAP_WEEKLY_HOURS
        weeks_remaining = math.ceil(remaining_hours / weekly_hours) if remaining_hours else 0
        completion_date = (date.today() + timedelta(days=weeks_remaining * 7)).isoformat()
        phase_progress = {
            phase: {
                "total": counts["total"],
                "completed": counts["completed"],
                "in_progress": counts["in_progress"],
                "remaining": counts["total"] - counts["completed"],
                "percentage": round(counts["completed"] / counts["total"] * 100) if counts["total"] else 0,
            }
            for phase, counts in phase_counts.items()
        }
        return {
            "total": total,
            "completed": completed,
            "in_progress": in_progress,
            "remaining": total - completed,
            "percentage": percentage,
            "remaining_hours": remaining_hours,
            "estimated_completion_date": completion_date,
            "steps": merged_steps,
            "phase_progress": phase_progress,
        }

    def _load_or_build(self, user, force):
        context = self.context
        cached = get_cached("roadmap", user.id, context.resume_text)
        if cached is not None and not force:
            if LearningRoadmap.objects.filter(pk=cached["pk"]).exists():
                return cached
        existing = LearningRoadmap.objects.filter(
            user=user, resume_hash=context.resume_hash
        ).first()
        if existing is not None and not force:
            self._sync_progress(existing)
            result = {"pk": existing.pk, "payload": existing.payload}
        else:
            payload = self.generate()
            obj, _ = LearningRoadmap.objects.update_or_create(
                user=user,
                resume_hash=context.resume_hash,
                defaults={
                    "profession": context.profession,
                    "career_level": context.career_level,
                    "payload": payload,
                },
            )
            LearningRoadmap.objects.filter(user=user).exclude(pk=obj.pk).delete()
            self._sync_progress(obj)
            result = {"pk": obj.pk, "payload": payload}
        set_cached("roadmap", user.id, context.resume_text, result)
        return result

    def generate(self):
        context = self.context
        ordered = self._ordered_missing_skills(context)
        # Job-readiness is decided by gaps that real matched postings demand
        # ("job"), not by canonical role skills the local job pool happens not
        # to list ("core") - otherwise a fully qualified candidate would never
        # be job-ready once canonical skills joined the gap universe.
        self._job_ready = not [i for i in ordered if i.get("source", "job") != "core"]
        if self._job_ready:
            ordered = self._ordered_job_ready_skills(context) + ordered
        ordered = ordered[:MAX_STEPS]
        info_by_key = {info["skill_key"]: info for info in ordered}
        ordered_keys = list(info_by_key)
        steps = []
        for step_number, skill_key in enumerate(ordered_keys, start=1):
            steps.append(self._build_step(step_number, skill_key, info_by_key[skill_key]))
        steps_by_key = {
            step["skill_key"]: step for step in steps
        }
        total_hours = sum(step["estimated_hours"] for step in steps)
        phases = self._build_phases(ordered_keys, steps_by_key)
        return {
            "profession": context.profession,
            "career_level": context.career_level_label,
            "roadmap_type": "job_ready" if self._job_ready else "gaps",
            "job_ready": self._job_ready,
            "total_steps": len(steps),
            "total_hours": total_hours,
            "weekly_hours": settings.SKILLGAP_WEEKLY_HOURS,
            "estimated_weeks": math.ceil(total_hours / settings.SKILLGAP_WEEKLY_HOURS),
            "phases": phases,
            "steps": steps,
        }

    def _ordered_job_ready_skills(self, context):
        """Advanced topics for candidates with no remaining gaps."""
        candidates = JOB_READY_ADVANCED.get(context.profession or "", JOB_READY_GENERIC)
        result = []
        seen = set()
        for skill_key, reason in candidates:
            norm = _norm(skill_key)
            if norm in context.user_skills_norm or norm in seen:
                continue
            seen.add(norm)
            result.append({
                "skill": display_for_key(norm),
                "skill_key": norm,
                "importance": 5,
                "priority": "medium",
                "job_count": 0,
                "profession_weight": 1,
                "reason": reason,
            })
        if not result:
            return [
                {
                    "skill": display_for_key(_norm(skill_key)),
                    "skill_key": _norm(skill_key),
                    "importance": 5,
                    "priority": "medium",
                    "job_count": 0,
                    "profession_weight": 1,
                    "reason": reason,
                }
                for skill_key, reason in JOB_READY_GENERIC
            ]
        return result

    def _build_phases(self, ordered_keys, steps_by_key):
        context = self.context
        profession = context.profession or "Your Target Role"
        role = profession
        themes = PROFESSION_PHASE_THEMES.get(profession, GENERIC_PHASE_TITLES)
        domain = PROJECT_DOMAIN.get(profession, "Project")

        chunks = [
            ordered_keys[i:i + PHASE_SIZE]
            for i in range(0, len(ordered_keys), PHASE_SIZE)
        ][:MAX_SKILL_PHASES]

        phases = []
        for idx, chunk in enumerate(chunks):
            phase_steps = [steps_by_key[key] for key in chunk]
            skills = [step["skill_name"] for step in phase_steps]
            hours = sum(step["estimated_hours"] for step in phase_steps)
            title = themes[idx] if idx < len(themes) else f"{profession} Skills {idx + 1}"
            first_skill = skills[0]
            phases.append({
                "phase_number": idx + 1,
                "title": title,
                "estimated_hours": hours,
                "estimated_weeks": math.ceil(hours / settings.SKILLGAP_WEEKLY_HOURS),
                "skills": skills,
                "priority": min(
                    (step["priority"] for step in phase_steps),
                    key=lambda value: PRIORITY_ORDER.get(value, 2),
                ),
                "why_important": [step["why"] for step in phase_steps],
                "learning_resources": [
                    {**step["learning_resource"], "skill": step["skill_name"]}
                    for step in phase_steps
                    if step.get("learning_resource")
                ],
                "objectives": [
                    f"Master {_join_skills(skills)} through focused, hands-on practice.",
                    f"Apply these skills to a real {domain.lower()} project.",
                    f"Build confidence working independently on {role} tasks.",
                ],
                "practice_project": {
                    "title": f"{first_skill} {domain}",
                    "description": (
                        f"Hands-on mini project: build a {domain.lower()} that puts "
                        f"{_join_skills(skills)} into practice on a realistic {role} use case."
                    ),
                },
                "outcome": (
                    f"By the end of this phase you can confidently apply "
                    f"{_join_skills(skills)} to {role} work."
                ),
            })

        if phases:
            all_skills = [step["skill_name"] for step in steps_by_key.values()]
            phases.append({
                "phase_number": CAPSTONE_PHASE_NUMBER,
                "title": f"Capstone: Complete {profession} Portfolio Project",
                "estimated_hours": 40,
                "estimated_weeks": math.ceil(40 / settings.SKILLGAP_WEEKLY_HOURS),
                "skills": [],
                "priority": "medium",
                "why_important": [
                    "A polished portfolio and interview story is what converts skills into offers.",
                    "Recruiters screen portfolios before resumes in most senior pipelines.",
                ],
                "learning_resources": [],
                "objectives": [
                    f"Build and deploy a complete {role} project combining {_join_skills(all_skills[:3] or ['your new skills'])}.",
                    "Publish it and prepare a project walkthrough for interviews.",
                    "Review job postings for your profession and map your portfolio to their requirements.",
                ],
                "practice_project": {
                    "title": f"{profession} Portfolio Project",
                    "description": (
                        f"Capstone: design, build and deploy a production-quality "
                        f"{domain.lower()} that showcases your full {role} skill set."
                    ),
                },
                "outcome": (
                    f"A production-ready portfolio piece and a confident interview story "
                    f"for {role} positions."
                ),
            })

        return phases

    def _ordered_missing_skills(self, context):
        include = {}
        queue = list(context.missing_skills)
        relevant = [
            info for info in queue
            if is_skill_relevant(info["skill_key"], context.user_skills_norm)
        ]
        if relevant:
            queue = relevant
        while queue:
            info = queue.pop()
            key = info["skill_key"]
            if key in include:
                continue
            include[key] = info
            covered_aliases = {SKILL_FAMILY_ALIASES.get(k, k) for k in include}
            for dependency in get_skill_dependencies(key):
                dep_key = _norm(dependency)
                if dep_key in context.user_skills_norm or dep_key in include:
                    continue
                if SKILL_FAMILY_ALIASES.get(dep_key, dep_key) in covered_aliases:
                    continue
                if get_course_entry(dep_key) is None:
                    continue
                if not is_skill_relevant(dep_key, context.user_skills_norm):
                    continue
                queue.append({
                    "skill": display_for_key(dep_key),
                    "skill_key": dep_key,
                    "importance": max(info["importance"] - 1, 3),
                    "priority": "high" if info["priority"] == "high" else info["priority"],
                    "job_count": 0,
                    "profession_weight": 1,
                })
        return [include[key] for key in self._topological_order(include)]

    def _topological_order(self, include):
        indegree = {key: 0 for key in include}
        graph = {key: [] for key in include}
        for key in include:
            for dependency in get_skill_dependencies(key):
                dep_key = _norm(dependency)
                if dep_key in include and dep_key != key:
                    graph[dep_key].append(key)
                    indegree[key] += 1
        heap = []
        for key, degree in indegree.items():
            if degree == 0:
                heapq.heappush(heap, _sort_key(key, include[key]))
        order = []
        while heap:
            _, _, _, _, _, key = heapq.heappop(heap)
            order.append(key)
            for neighbor in graph[key]:
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    heapq.heappush(heap, _sort_key(neighbor, include[neighbor]))
        for key in include:
            if key not in order:
                order.append(key)
        return order

    def _build_step(self, step_number, skill_key, info=None):
        context = self.context
        if info is None:
            info = next(
                (item for item in context.missing_skills if item["skill_key"] == skill_key),
                {"skill": display_for_key(skill_key), "priority": "medium", "importance": 5, "job_count": 0},
            )
        difficulty = self._adjusted_difficulty(get_skill_difficulty(skill_key))
        entry = get_course_entry(skill_key)
        base_hours = entry["hours"] if entry else BASE_HOURS[difficulty]
        hours = max(4, round(base_hours * LEVEL_FACTORS[context.career_level] / 2) * 2)
        role = context.profession or "your target role"
        skill_name = info["skill"]
        job_count = int(info.get("job_count", 0) or 0)
        priority = info.get("priority", "medium")
        importance = int(info.get("importance", 5))
        if info.get("reason"):
            why = info["reason"]
        elif job_count:
            why = (
                f"{skill_name} is required by {job_count} active {role} posting"
                f"{'s' if job_count != 1 else ''} and is a {priority}-priority gap "
                f"rated {importance}/10 in importance."
            )
        else:
            why = (
                f"{skill_name} is a {priority}-priority gap for {role} roles, "
                f"rated {importance}/10 in importance."
            )
        if info.get("reason"):
            description = (
                f"Advanced learning path covering {skill_name} for an already "
                f"job-ready {role} profile: {why}"
            )
        else:
            description = (
                f"Focused learning path covering {skill_name} through guided practice and "
                f"hands-on {role} application, aligned with a {priority}-priority gap "
                f"rated {importance}/10 in importance."
            )
        prerequisites = []
        for dependency in get_skill_dependencies(skill_key):
            dep_key = _norm(dependency)
            if dep_key in context.user_skills_norm:
                coverage = "existing"
            elif any(
                step["skill_key"] == dep_key
                for step in context.missing_skills
            ):
                coverage = "roadmap"
            else:
                continue
            prerequisites.append({
                "skill_name": display_for_key(dep_key),
                "coverage": coverage,
            })
        phase_number = ((step_number - 1) // PHASE_SIZE) + 1
        themes = PROFESSION_PHASE_THEMES.get(context.profession, GENERIC_PHASE_TITLES)
        phase_title = (
            themes[phase_number - 1]
            if phase_number - 1 < len(themes)
            else f"{context.profession or 'Skill'} Phase {phase_number}"
        )
        return {
            "step_number": step_number,
            "skill_name": skill_name,
            "skill_key": skill_key,
            "description": description,
            "why": why,
            "priority": priority,
            "learning_resource": self._resource_for_skill(skill_key, skill_name),
            "estimated_hours": hours,
            "difficulty": difficulty,
            "prerequisites": prerequisites,
            "expected_outcome": OUTCOMES[difficulty].format(skill=skill_name, role=role),
            "phase_number": phase_number,
            "phase_title": phase_title,
        }

    def _resource_for_skill(self, skill_key, skill_name):
        entry = get_course_entry(skill_key)
        if entry:
            return {
                "title": entry["title"],
                "provider": entry["provider"],
                "url": entry["url"],
                "free": bool(entry["free"]),
            }
        return {
            "title": f"{skill_name} — Advanced Course",
            "provider": FALLBACK_PROVIDER,
            "url": LINKEDIN_SEARCH.format(query=quote(skill_name)),
            "free": False,
        }

    def _adjusted_difficulty(self, difficulty):
        context = self.context
        if context.career_level == "junior" and DIFFICULTY_RANK[difficulty] > DIFFICULTY_RANK[JUNIOR_MAX]:
            return JUNIOR_MAX
        return difficulty

    def _sync_progress(self, roadmap):
        steps = roadmap.payload.get("steps", [])
        rows = {
            row.step_number: row
            for row in RoadmapStepProgress.objects.filter(roadmap=roadmap)
        }
        for step in steps:
            row = rows.get(step["step_number"])
            if row is not None and row.skill_name != step["skill_name"]:
                row.delete()
                row = None
            if row is None:
                RoadmapStepProgress.objects.create(
                    user=roadmap.user,
                    roadmap=roadmap,
                    step_number=step["step_number"],
                    skill_name=step["skill_name"],
                )
        valid_numbers = {step["step_number"] for step in steps}
        stale = [number for number in rows if number not in valid_numbers]
        if stale:
            RoadmapStepProgress.objects.filter(roadmap=roadmap, step_number__in=stale).delete()


def _norm(skill):
    from apps.shared.skill_normalizer import normalize_skill
    return normalize_skill(skill)


def _sort_key(key, info):
    from apps.shared.skill_normalizer import normalize_skill
    difficulty = get_skill_difficulty(key)
    affinity = 0 if info.get("profession_weight") else 1
    return (
        affinity,
        -int(info.get("importance", 0)),
        PRIORITY_ORDER.get(info.get("priority"), 2),
        DIFFICULTY_RANK.get(difficulty, 1),
        normalize_skill(info.get("skill", key)),
        key,
    )

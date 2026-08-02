import heapq
import math
from datetime import date, timedelta

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
        if not context.resume_text or not context.has_skills:
            return {
                "profession": "",
                "career_level": "",
                "roadmap": None,
                "progress": None,
                "has_resume": bool(context.resume_text),
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
        ordered_keys = self._ordered_missing_skills(context)[:MAX_STEPS]
        steps = []
        for step_number, skill_key in enumerate(ordered_keys, start=1):
            steps.append(self._build_step(step_number, skill_key))
        steps_by_key = {
            step["skill_key"]: step for step in steps
        }
        total_hours = sum(step["estimated_hours"] for step in steps)
        phases = self._build_phases(ordered_keys, steps_by_key)
        return {
            "profession": context.profession,
            "career_level": context.career_level_label,
            "total_steps": len(steps),
            "total_hours": total_hours,
            "weekly_hours": settings.SKILLGAP_WEEKLY_HOURS,
            "estimated_weeks": math.ceil(total_hours / settings.SKILLGAP_WEEKLY_HOURS),
            "phases": phases,
            "steps": steps,
        }

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
        return self._topological_order(include)

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

    def _build_step(self, step_number, skill_key):
        context = self.context
        info = next(
            (item for item in context.missing_skills if item["skill_key"] == skill_key),
            {"skill": display_for_key(skill_key), "priority": "medium", "importance": 5},
        )
        difficulty = self._adjusted_difficulty(get_skill_difficulty(skill_key))
        entry = get_course_entry(skill_key)
        base_hours = entry["hours"] if entry else BASE_HOURS[difficulty]
        hours = max(4, round(base_hours * LEVEL_FACTORS[context.career_level] / 2) * 2)
        role = context.profession or "your target role"
        skill_name = info["skill"]
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
            "description": (
                f"Focused learning path covering {skill_name} through guided practice and "
                f"hands-on {role} application, aligned with a {info['priority']}-priority gap "
                f"rated {info['importance']}/10 in importance."
            ),
            "estimated_hours": hours,
            "difficulty": difficulty,
            "prerequisites": prerequisites,
            "expected_outcome": OUTCOMES[difficulty].format(skill=skill_name, role=role),
            "phase_number": phase_number,
            "phase_title": phase_title,
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

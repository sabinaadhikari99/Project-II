"""TEMPORARY AI Match debug tracer - diagnosis only, no production logic here.

This module re-runs the AI Match pipeline for a CV and records every value each
stage produced, so two resumes can be compared field by field and the exact
stage where they diverge can be named rather than guessed at.

Guarantees
----------
* **Read-only.** Nothing is saved. The profile is never written, no embedding is
  updated, no analysis session is stored. A trace can be taken against live data.
* **Faithful.** Every stage calls the same function the real pipeline calls, in
  the same order, with the same arguments - including the profile-skill merge in
  `analyze_resume_match`, which is reproduced in memory rather than skipped.
  `verify_against_production()` re-runs the real entry point and reports any
  disagreement, so a stale tracer cannot quietly mislead.

Mirrors, in order:
    apps.jobs.services.analyze_resume_match
    apps.jobs.services.recommend_jobs_for_user
    apps.jobs.services._hybrid_rank_jobs
    apps.jobs.services.compute_match_score

Delete this module, its management command and the AI_MATCH_TRACE hook once the
scoring question it was written for is settled.
"""

import hashlib
import logging

from apps.shared.constants import JOB_VECTOR_PREFIX
from apps.shared.cv_signals import extract_cv_signals
from apps.shared.embedding_client import get_embedding
from apps.shared.profession_classifier import (
    classify_profession_from_skills,
    classify_profession_with_resume,
    get_related_profession_titles,
)
from apps.shared.skill_normalizer import normalize_skill_set
from apps.shared.specializations import detect_specialization, get_adjacent_parents
from apps.shared.vector_db import get_vector_manager

logger = logging.getLogger(__name__)

SEPARATOR = "=" * 76
RULE = "-" * 76


def _digest(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def _fmt_list(values, limit=None):
    values = list(values or [])
    if not values:
        return "(none)"
    shown = values if limit is None else values[:limit]
    suffix = "" if limit is None or len(values) <= limit else f" (+{len(values) - limit} more)"
    return ", ".join(str(v) for v in shown) + suffix


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

def trace_analysis(user, resume_text, label="A", prior_skills=None, limit=10):
    """Run the pipeline for one CV and capture every intermediate value.

    `prior_skills` reproduces the state the real upload path carries in from
    `UserProfile.skills`. Pass ``[]`` to trace the CV in isolation, or the
    previous upload's effective skills to reproduce what production actually
    does on a second upload.
    """
    from apps.jobs.models import JobPosting
    from apps.jobs.services import compute_match_score, extract_resume_skills

    profile = getattr(user, "profile", None)

    # -- stage 1: skill extraction (analyze_resume_match) -------------------
    extracted = extract_resume_skills(resume_text)
    if prior_skills is None:
        prior = list((profile.skills if profile else None) or [])
    else:
        prior = list(prior_skills)
    # services.analyze_resume_match line ~579: the union, not a replacement.
    effective = sorted(set(prior) | set(extracted))

    # -- stage 2: profession + specialisation ------------------------------
    profession, profession_conf = classify_profession_with_resume(
        resume_text, extracted_skills=effective,
    )
    skills_only_profession = classify_profession_from_skills(effective)
    specialization, specialization_conf = detect_specialization(
        resume_text, effective, profession or "",
    )

    # -- stage 3: CV signals ------------------------------------------------
    signals = extract_cv_signals(resume_text)

    # -- stage 4: job filtering (recommend_jobs_for_user) ------------------
    filter_path = "profession"
    if profession:
        profession_titles = sorted(get_related_profession_titles(profession))
        candidates = list(JobPosting.objects.filter(
            is_active=True, job_category__in=profession_titles,
        ))
        if not candidates:
            filter_path = "adjacent"
            profession_titles = sorted(
                set(get_adjacent_parents(specialization)) | set(profession_titles)
            )
            candidates = list(JobPosting.objects.filter(
                is_active=True, job_category__in=profession_titles,
            ))
    else:
        profession_titles = []
        candidates = []

    if not candidates:
        filter_path = "semantic_fallback"

    # -- stage 5: vector search --------------------------------------------
    embedding = get_embedding(resume_text)
    top_k = min(max(len(candidates) * 2, 20), 40)
    vector_scores = {}
    try:
        for object_id, score in get_vector_manager().search_similar(
            embedding, top_k=top_k, prefix=f"{JOB_VECTOR_PREFIX}:",
        ):
            try:
                vector_scores[int(str(object_id).split(":")[1])] = score
            except (IndexError, ValueError):
                continue
    except Exception:
        logger.warning("trace_analysis: vector search unavailable", exc_info=True)

    if filter_path == "semantic_fallback":
        candidates = list(JobPosting.objects.filter(
            is_active=True, id__in=list(vector_scores),
        ))

    # -- stage 6: scoring ---------------------------------------------------
    jobs = []
    for job in candidates:
        vector_score = vector_scores.get(job.id, 0.0)
        result = compute_match_score(
            user_skills=effective,
            user_profession=(job.job_category if filter_path == "semantic_fallback"
                             and profession is None else profession),
            profile=profile,
            job=job,
            vector_score=vector_score,
            cv_signals=signals,
            specialization=specialization,
        )
        required = list(job.required_skills or [])
        user_norm = normalize_skill_set(effective)
        req_norm = normalize_skill_set(required)
        matched = [s for s in required if normalize_skill_set([s]) <= user_norm]
        missing = [s for s in required if not normalize_skill_set([s]) <= user_norm]
        jobs.append({
            "job_id": job.id,
            "job_title": job.title,
            "job_company": job.company,
            "job_category": job.job_category,
            "required_skills": required,
            "required_normalized": sorted(req_norm),
            "matched_skills": matched,
            "missing_skills": missing,
            "skill_coverage": (round(len(user_norm & req_norm) / len(req_norm) * 100)
                               if req_norm else None),
            "semantic_similarity": round(float(vector_score), 6),
            "profession_score": result["profession_match"],
            "skills_score": result["skills_score"],
            "experience_score": result["experience_score"],
            "education_score": result["education_score"],
            "semantic_score": result["semantic_score"],
            "project_score": result["project_score"],
            "certification_score": result["certification_score"],
            "base_score": result["base_score"],
            "deductions": result["deductions"],
            "total_deduction": result["total_deduction"],
            "final_score": result["final_score"],
        })

    jobs.sort(key=lambda j: -j["final_score"])
    jobs = jobs[:limit]

    return {
        "label": label,
        "text_chars": len(resume_text or ""),
        "text_words": len((resume_text or "").split()),
        "text_sha": _digest(resume_text),
        "prior_profile_skills": sorted(prior),
        "extracted_skills": list(extracted),
        "effective_skills": effective,
        "normalized_skills": sorted(normalize_skill_set(effective)),
        "merge_added": sorted(set(prior) - set(extracted)),
        "profession": profession,
        "profession_confidence": profession_conf,
        "skills_only_profession": skills_only_profession,
        "specialization": specialization,
        "specialization_confidence": specialization_conf,
        "filter_path": filter_path,
        "profession_titles": profession_titles,
        "candidate_job_ids": sorted(j["job_id"] for j in jobs),
        "signals": signals,
        "jobs": jobs,
        "best_final": max((j["final_score"] for j in jobs), default=0),
        "best_job_id": jobs[0]["job_id"] if jobs else None,
    }


def verify_against_production(user, resume_text, trace, limit=10):
    """Compare the trace with the real entry point, and explain any divergence.

    A divergence is NOT automatically a tracer bug. `recommend_jobs_for_user`
    scores from the persisted `UserProfile.skills`; the tracer scores from the
    skill set it was given for the CV in front of it. When those two sets
    differ, the gap between them is itself the finding - it is the profile-state
    dependency this module exists to expose.

    Only a divergence WITH identical skill sets indicts the tracer.
    """
    from apps.jobs.services import recommend_jobs_for_user

    try:
        live = recommend_jobs_for_user(user, limit=limit, resume_text=resume_text)
    except Exception as exc:
        return {"verdict": "error", "error": str(exc), "mismatches": []}

    live_scores = {item["job"].id: item["match_percentage"] for item in live}
    traced = {job["job_id"]: job["final_score"] for job in trace["jobs"]}
    mismatches = [
        {"job_id": job_id, "traced": score, "production": live_scores.get(job_id)}
        for job_id, score in traced.items()
        if job_id in live_scores and live_scores[job_id] != score
    ]

    profile = getattr(user, "profile", None)
    production_skills = sorted(set((profile.skills if profile else None) or []))
    traced_skills = sorted(set(trace["effective_skills"]))
    same_inputs = production_skills == traced_skills

    if not mismatches:
        verdict = "agree"
    elif same_inputs:
        verdict = "tracer_bug"
    else:
        verdict = "different_skill_inputs"

    return {
        "verdict": verdict,
        "error": None,
        "mismatches": mismatches,
        "production_best": max(live_scores.values(), default=0),
        "traced_best": trace["best_final"],
        "production_skills": production_skills,
        "traced_skills": traced_skills,
        "only_in_production": sorted(set(production_skills) - set(traced_skills)),
        "only_in_trace": sorted(set(traced_skills) - set(production_skills)),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def format_trace(trace, top=3):
    """Full per-job breakdown for one resume, in pipeline order."""
    out = [SEPARATOR,
           f"RESUME {trace['label']}  ({trace['text_words']} words, "
           f"{trace['text_chars']} chars, sha={trace['text_sha']})",
           SEPARATOR,
           f"Detected Profession       : {trace['profession']} "
           f"(confidence {trace['profession_confidence']})",
           f"  profession from skills  : {trace['skills_only_profession']}",
           f"Detected Specialization   : {trace['specialization']} "
           f"(confidence {trace['specialization_confidence']})",
           f"Job filter path           : {trace['filter_path']}  -> {_fmt_list(trace['profession_titles'])}",
           "",
           f"Extracted Skills ({len(trace['extracted_skills'])}) : {_fmt_list(trace['extracted_skills'])}",
           f"Prior Profile Skills ({len(trace['prior_profile_skills'])}) : {_fmt_list(trace['prior_profile_skills'])}",
           f"EFFECTIVE Skills ({len(trace['effective_skills'])}) : {_fmt_list(trace['effective_skills'])}",
           ]
    if trace["merge_added"]:
        out.append(f"  !! carried in by the profile merge, NOT in this CV: "
                   f"{_fmt_list(trace['merge_added'])}")
    out.append(f"Normalized Skills ({len(trace['normalized_skills'])}) : "
               f"{_fmt_list(trace['normalized_skills'])}")

    s = trace["signals"]
    out += [
        "",
        f"Experience Years          : {s.get('experience_years')}",
        f"Education Level           : {s.get('education_level')} (rank {s.get('education_rank')})",
        f"Project Count             : {s.get('project_count')}",
        f"Certification Count       : {s.get('certification_count')}",
        f"Portfolio Detected        : {bool(s.get('portfolio_links'))} {_fmt_list(s.get('portfolio_links'))}",
        f"Leadership Detected       : {s.get('has_leadership')}",
        f"Metrics Detected          : {s.get('has_metrics')} ({s.get('achievement_count')} quantified)",
        f"Sections Missing          : {_fmt_list(s.get('sections_missing'))}",
        f"Candidate Jobs Scored     : {len(trace['jobs'])} -> {trace['candidate_job_ids']}",
    ]

    for job in trace["jobs"][:top]:
        out += [
            "",
            SEPARATOR,
            f"Job Title                 : {job['job_title']} @ {job['job_company']} "
            f"(id={job['job_id']}, category={job['job_category']})",
            SEPARATOR,
            f"Required Skills ({len(job['required_skills'])})   : {_fmt_list(job['required_skills'])}",
            f"Matched Skills ({len(job['matched_skills'])})    : {_fmt_list(job['matched_skills'])}",
            f"Missing Skills ({len(job['missing_skills'])})    : {_fmt_list(job['missing_skills'])}",
            f"Skill Coverage %          : {job['skill_coverage']}",
            f"Semantic Similarity       : {job['semantic_similarity']}",
            RULE,
            f"Profession Score          : {job['profession_score']}",
            f"Skills Score              : {job['skills_score']}",
            f"Experience Score          : {job['experience_score']}",
            f"Education Score           : {job['education_score']}",
            f"Semantic Score            : {job['semantic_score']}",
            f"Projects Score            : {job['project_score']}",
            f"Certification Score       : {job['certification_score']}",
            RULE,
            f"Weighted Score Before Deductions : {job['base_score']}",
        ]
        if job["deductions"]:
            for d in job["deductions"]:
                out.append(f"  - {d['item']} (-{d['points']}) [{d['severity']}]")
                out.append(f"      reason: {d['reason']}")
        else:
            out.append("  (no deductions)")
        out += [
            f"Deduction Total           : -{job['total_deduction']}",
            f"Final Score               : {job['final_score']}",
        ]
    return "\n".join(out)


def format_live_trace(*, resume_text, extracted_skills, prior_skills, effective_skills,
                      profession, profession_confidence, specialization,
                      specialization_confidence, signals, recommendations, top=3):
    """Render a trace from values a real `analyze_resume_match` call already produced.

    Nothing is recomputed and nothing is re-scored: every number below is read
    off the analysis that was just returned to the user, which is what makes
    this safe to switch on in a running app and impossible to disagree with the
    response the user actually received.
    """
    extracted = set(extracted_skills or [])
    prior = set(prior_skills or [])
    carried = sorted(prior - extracted)

    out = [
        "", SEPARATOR,
        f"AI MATCH TRACE  ({len((resume_text or '').split())} words, "
        f"sha={_digest(resume_text)})",
        SEPARATOR,
        f"Detected Profession       : {profession} (confidence {profession_confidence})",
        f"Detected Specialization   : {specialization} (confidence {specialization_confidence})",
        "",
        f"Extracted Skills ({len(extracted_skills or [])}) : {_fmt_list(extracted_skills)}",
        f"Prior Profile Skills ({len(prior_skills or [])}) : {_fmt_list(prior_skills)}",
        f"EFFECTIVE Skills ({len(effective_skills or [])}) : {_fmt_list(effective_skills)}",
    ]
    if carried:
        out.append("  !! SCORED BUT NOT IN THIS CV (carried in from a previous upload "
                   "by the UserProfile.skills merge): " + _fmt_list(carried))
    out.append(f"Normalized Skills         : {_fmt_list(sorted(normalize_skill_set(effective_skills)))}")

    s = signals or {}
    out += [
        "",
        f"Experience Years          : {s.get('experience_years')}",
        f"Education Level           : {s.get('education_level')} (rank {s.get('education_rank')})",
        f"Project Count             : {s.get('project_count')}",
        f"Certification Count       : {s.get('certification_count')}",
        f"Portfolio Detected        : {bool(s.get('portfolio_links'))}",
        f"Leadership Detected       : {s.get('has_leadership')}",
        f"Metrics Detected          : {s.get('has_metrics')}",
    ]

    for item in (recommendations or [])[:top]:
        job = item.get("job")
        explanation = item.get("match_explanation") or {}
        out += [
            "",
            SEPARATOR,
            f"Job Title                 : {getattr(job, 'title', '?')} @ "
            f"{getattr(job, 'company', '?')} (id={getattr(job, 'id', '?')}, "
            f"category={getattr(job, 'job_category', '?')})",
            SEPARATOR,
            f"Required Skills ({len(item.get('required_skills') or [])})   : {_fmt_list(item.get('required_skills'))}",
            f"Matched Skills ({len(item.get('matched_skills') or [])})    : {_fmt_list(item.get('matched_skills'))}",
            f"Missing Skills ({len(item.get('missing_skills') or [])})    : {_fmt_list(item.get('missing_skills'))}",
            RULE,
            f"Profession Score          : {explanation.get('profession_match')}",
            f"Skills Score              : {explanation.get('skills_match')}",
            f"Experience Score          : {explanation.get('experience_match')}",
            f"Education Score           : {explanation.get('education_match')}",
            f"Semantic Score            : {explanation.get('semantic_similarity')}",
            f"Projects Score            : {explanation.get('project_match')}",
            f"Certification Score       : {explanation.get('certification_match')}",
            RULE,
            f"Weighted Score Before Deductions : {item.get('base_score')}",
        ]
        for d in item.get("deductions") or []:
            out.append(f"  - {d['item']} (-{d['points']}) [{d['severity']}]")
            out.append(f"      reason: {d['reason']}")
        if not item.get("deductions"):
            out.append("  (no deductions)")
        out += [
            f"Deduction Total           : -{item.get('total_deduction', 0)}",
            f"Final Score               : {item.get('match_percentage')}",
        ]
    out.append(SEPARATOR)
    return "\n".join(out)


def _changed(a, b):
    return "  <-- CHANGED" if a != b else ""


def compare_traces(a, b, top=3):
    """Side-by-side A/B report highlighting every field that moved."""
    out = ["", SEPARATOR,
           f"SIDE BY SIDE : RESUME {a['label']} vs RESUME {b['label']}",
           SEPARATOR]

    # -- skill-level diff ---------------------------------------------------
    ex_a, ex_b = set(a["extracted_skills"]), set(b["extracted_skills"])
    out.append("\nEXTRACTED SKILLS (what the parser found in each document)")
    for skill in sorted(ex_a - ex_b):
        out.append(f"  {skill:<28} Present -> Missing")
    for skill in sorted(ex_b - ex_a):
        out.append(f"  {skill:<28} Missing -> Present")
    if ex_a == ex_b:
        out.append("  (identical)")

    eff_a, eff_b = set(a["effective_skills"]), set(b["effective_skills"])
    out.append("\nEFFECTIVE SKILLS (what scoring actually used)")
    for skill in sorted(eff_a - eff_b):
        out.append(f"  {skill:<28} Present -> Missing")
    for skill in sorted(eff_b - eff_a):
        out.append(f"  {skill:<28} Missing -> Present")
    if eff_a == eff_b:
        out.append("  (identical)")
    dropped_but_kept = sorted((ex_a - ex_b) & eff_b)
    if dropped_but_kept:
        out.append("  !! removed from the CV but STILL SCORED: " + _fmt_list(dropped_but_kept))

    # -- pipeline-level diff ------------------------------------------------
    rows = [
        ("Extracted Skills", len(a["extracted_skills"]), len(b["extracted_skills"])),
        ("Effective Skills", len(a["effective_skills"]), len(b["effective_skills"])),
        ("Detected Profession", a["profession"], b["profession"]),
        ("Profession Confidence", a["profession_confidence"], b["profession_confidence"]),
        ("Detected Specialization", a["specialization"], b["specialization"]),
        ("Spec. Confidence", a["specialization_confidence"], b["specialization_confidence"]),
        ("Job Filter Path", a["filter_path"], b["filter_path"]),
        ("Candidate Job IDs", a["candidate_job_ids"], b["candidate_job_ids"]),
        ("Experience Years", a["signals"].get("experience_years"), b["signals"].get("experience_years")),
        ("Education Level", a["signals"].get("education_level"), b["signals"].get("education_level")),
        ("Project Count", a["signals"].get("project_count"), b["signals"].get("project_count")),
        ("Certification Count", a["signals"].get("certification_count"), b["signals"].get("certification_count")),
        ("Portfolio Detected", bool(a["signals"].get("portfolio_links")), bool(b["signals"].get("portfolio_links"))),
        ("Leadership Detected", a["signals"].get("has_leadership"), b["signals"].get("has_leadership")),
        ("Metrics Detected", a["signals"].get("has_metrics"), b["signals"].get("has_metrics")),
        ("Word Count", a["text_words"], b["text_words"]),
        ("Best Final Score", a["best_final"], b["best_final"]),
    ]
    out.append("\nPIPELINE STAGES")
    out.append(f"  {'FIELD':<26} {'RESUME ' + a['label']:<24} {'RESUME ' + b['label']:<24}")
    for name, va, vb in rows:
        out.append(f"  {name:<26} {str(va):<24} {str(vb):<24}{_changed(va, vb)}")

    # -- per-job diff -------------------------------------------------------
    jobs_a = {j["job_id"]: j for j in a["jobs"]}
    jobs_b = {j["job_id"]: j for j in b["jobs"]}
    shared = [jid for jid in jobs_a if jid in jobs_b]
    shared.sort(key=lambda jid: -jobs_a[jid]["final_score"])

    only_a = sorted(set(jobs_a) - set(jobs_b))
    only_b = sorted(set(jobs_b) - set(jobs_a))
    if only_a or only_b:
        out.append(f"\n  !! DIFFERENT JOBS COMPARED - only in {a['label']}: {only_a}; "
                   f"only in {b['label']}: {only_b}")

    for jid in shared[:top]:
        ja, jb = jobs_a[jid], jobs_b[jid]
        out += ["", RULE, f"JOB {jid}: {ja['job_title']} @ {ja['job_company']}", RULE]
        job_rows = [
            ("Matched Skills", len(ja["matched_skills"]), len(jb["matched_skills"])),
            ("Missing Skills", len(ja["missing_skills"]), len(jb["missing_skills"])),
            ("Skill Coverage %", ja["skill_coverage"], jb["skill_coverage"]),
            ("Semantic Similarity", ja["semantic_similarity"], jb["semantic_similarity"]),
            ("Profession Score", ja["profession_score"], jb["profession_score"]),
            ("Skills Score", ja["skills_score"], jb["skills_score"]),
            ("Experience Score", ja["experience_score"], jb["experience_score"]),
            ("Education Score", ja["education_score"], jb["education_score"]),
            ("Semantic Score", ja["semantic_score"], jb["semantic_score"]),
            ("Projects Score", ja["project_score"], jb["project_score"]),
            ("Certification Score", ja["certification_score"], jb["certification_score"]),
            ("Weighted Score", ja["base_score"], jb["base_score"]),
            ("Deductions", -ja["total_deduction"], -jb["total_deduction"]),
            ("Final", ja["final_score"], jb["final_score"]),
        ]
        for name, va, vb in job_rows:
            out.append(f"  {name:<26} {str(va):<24} {str(vb):<24}{_changed(va, vb)}")

        da = {d["item"]: d["points"] for d in ja["deductions"]}
        db = {d["item"]: d["points"] for d in jb["deductions"]}
        if da != db:
            out.append("  Deduction line items:")
            for item in sorted(set(da) | set(db)):
                out.append(f"    {item:<24} {da.get(item, 0)} -> {db.get(item, 0)}"
                           f"{_changed(da.get(item, 0), db.get(item, 0))}")

        out.append(f"  ARITHMETIC: {ja['base_score']} - {ja['total_deduction']} = {ja['final_score']}"
                   f"   |   {jb['base_score']} - {jb['total_deduction']} = {jb['final_score']}")
        delta = jb["final_score"] - ja["final_score"]
        if delta:
            out.append(f"  DELTA {delta:+d} on this job. Attribution:")
            out += _attribute_delta(ja, jb)

    return "\n".join(out)


#: Weight of each component in the weighted average, for delta attribution.
_ATTRIBUTION = (
    ("profession_score", "profession", 40),
    ("skills_score", "skills", 30),
    ("experience_score", "experience", 15),
    ("education_score", "education", 10),
    ("semantic_score", "semantic", 5),
    ("project_score", "projects", 6),
    ("certification_score", "certifications", 4),
)


def _attribute_delta(ja, jb):
    """Break a final-score change into the component that produced it.

    Uses the live SCORE_WEIGHTS, so the numbers here are the actual points each
    component contributed to the move rather than an estimate.
    """
    from apps.jobs.services import SCORE_WEIGHTS

    total_weight = sum(SCORE_WEIGHTS.values()) or 1
    lines = []
    for key, label, _default in _ATTRIBUTION:
        weight = SCORE_WEIGHTS.get(label, _default)
        diff = jb[key] - ja[key]
        if diff:
            points = diff * weight / total_weight
            lines.append(f"    {label:<16} {ja[key]:>4} -> {jb[key]:<4} "
                         f"= {points:+.2f} pts on the final score")
    ded = ja["total_deduction"] - jb["total_deduction"]
    if ded:
        lines.append(f"    {'deductions':<16} {-ja['total_deduction']:>4} -> "
                     f"{-jb['total_deduction']:<4} = {ded:+.2f} pts on the final score")
    if not lines:
        lines.append("    (no component changed - the move is pure rounding)")
    return lines

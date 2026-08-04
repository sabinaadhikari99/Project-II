"""Explainable, job-specific deductions applied on top of the weighted score.

Why this module exists
----------------------
`apps.jobs.services.compute_match_score` is a weighted average of seven
components, and every one of them has a non-zero floor. Because job filtering
already guarantees the profession component is satisfied for every posting the
user is shown, the weighted score alone lands almost every candidate inside a
narrow 75-85 band, so the number carries very little information.

This module supplies the second half of the score: a bounded set of *named*
penalties for requirements that THIS posting asks for and THIS CV does not
evidence.

    final_score = weighted_score - min(sum(deductions), MAX_TOTAL_DEDUCTION)

Two rules govern everything here:

1. **Job-specific only.** A skill is deducted only when the posting itself
   lists it in `required_skills`. A Flutter developer is never penalised for
   not knowing Kubernetes, because no Flutter posting asked for Kubernetes.
2. **Always explained.** Every deduction carries the sentence that justifies
   it, so the UI can show the user precisely how the number was reached
   instead of asserting a percentage.

Severity is decided from data the project already maintains - the job title,
`PROFESSION_CONFIGS[...]["skills"]` weights and `SPECIALIZATIONS[...]["signals"]`
weights - rather than from a new hand-written table per role.

Deliberately NOT deducted here: experience shortfall and education shortfall.
Both are already priced by their own weighted components, and charging them
twice would punish the same gap in two places.
"""

import re
from functools import lru_cache

from apps.shared.profession_classifier import PROFESSION_CONFIGS
from apps.shared.skill_normalizer import display_name, normalize_skill
from apps.shared.specializations import SPECIALIZATIONS

# ---------------------------------------------------------------------------
# Tariff
# ---------------------------------------------------------------------------

#: Points removed per severity band.
SEVERITY_POINTS = {
    "critical": 5,   # the technology the role is built on
    "medium": 3,     # a supporting requirement the role expects
    "minor": 2,      # a generic or peripheral requirement
    "trivial": 1,    # CV presentation / corroborating evidence
}

#: Hard ceiling on the total. A strong CV with many small gaps must not be
#: dragged below a weak CV with few requirements to miss.
MAX_TOTAL_DEDUCTION = 15

#: Sub-ceiling for CV-presentation deductions, so document polish can never
#: outweigh actual role fit.
MAX_PROFILE_DEDUCTION = 4

#: A required skill weighted at or above this in the profession/specialisation
#: catalogue is treated as role-defining.
CRITICAL_WEIGHT_THRESHOLD = 9
MEDIUM_WEIGHT_THRESHOLD = 5


def _keys(*names):
    """Normalised lookup keys for a group of skill spellings."""
    return {normalize_skill(n) for n in names if n}


#: Programming languages and primary application frameworks - the thing the
#: product is actually built in. Missing one is disqualifying wherever the
#: posting requires it, whatever the role. Mirrors the "Critical" examples in
#: the product spec.
#:
#: Deliberately NOT listed here: infrastructure, data-platform and design tools
#: (Docker, Kubernetes, SQL, Spark, Figma, Photoshop, ...). Those are role-
#: dependent - Docker defines a DevOps posting but is a supporting requirement
#: on a Flutter one - and `_catalogue_weight` already promotes them to critical
#: for exactly the professions whose catalogue entry weights them that highly.
#: Restating them here would double up on that rule and get it wrong elsewhere.
_CRITICAL_SKILLS = _keys(
    "Flutter", "Dart", "React", "React Native", "Angular", "Vue.js", "Svelte",
    "Next.js", "Python", "Java", "JavaScript", "TypeScript", "Node.js",
    "Kotlin", "Swift", "SwiftUI", "C#", "C++", "Go", "Rust", "PHP", "Ruby",
    "Django", "Django REST Framework", "Spring Boot", "Laravel", "Express",
    "FastAPI", "Flask", ".NET", "ASP.NET", "Android", "iOS",
    "Unity", "Unreal Engine",
)

#: Supporting practice and tooling: expected, but a candidate strong everywhere
#: else is still credible without it. Mirrors the spec's "Medium" examples.
#: Anything here is still promoted to critical by `_catalogue_weight` for the
#: professions built on it.
_MEDIUM_SKILLS = _keys(
    "Git", "REST API", "REST APIs", "API Design", "Firebase",
    "State Management", "Testing", "Unit Testing", "Testing Framework",
    "Integration Testing", "CI/CD", "Redux", "GraphQL", "MongoDB",
    "PostgreSQL", "MySQL", "Redis", "Microservices", "System Design",
    "Data Structures", "Algorithms", "Linux", "AWS", "Azure", "GCP",
    "Docker", "Kubernetes", "Terraform", "Ansible", "Jenkins",
    "SQL", "NoSQL", "Spark", "ETL", "Airflow", "Kafka", "Hadoop",
    "Machine Learning", "Deep Learning", "TensorFlow", "PyTorch", "Keras",
    "NLP", "Computer Vision", "Scikit-learn",
    "Pandas", "NumPy", "Responsive Design", "Prototyping", "Wireframing",
    "User Research", "Data Visualization", "Statistics", "Tableau", "Power BI",
    "Figma", "Sketch", "Adobe XD", "Photoshop", "Illustrator", "InDesign",
)

#: Generic, transferable or tooling requirements. Real, but cheap to acquire
#: and rarely the reason a candidate is rejected.
_MINOR_SKILLS = _keys(
    "Communication", "Leadership", "Teamwork", "Agile", "Scrum", "JIRA",
    "Confluence", "Documentation", "Excel", "Canva", "Trello", "Slack",
    "Time Management", "Problem Solving", "Presentation", "Reporting",
)


# ---------------------------------------------------------------------------
# Weight indexes, built once at import from the existing catalogues
# ---------------------------------------------------------------------------

#: profession -> {normalised skill: weight}
_PROFESSION_WEIGHTS = {
    profession: {normalize_skill(skill): weight
                 for skill, weight in config.get("skills", {}).items()}
    for profession, config in PROFESSION_CONFIGS.items()
}

#: specialisation -> {normalised skill: weight}, from its detection signals
_SPECIALIZATION_WEIGHTS = {
    name: {normalize_skill(skill): weight
           for skill, weight in config.get("signals", {}).items()}
    for name, config in SPECIALIZATIONS.items()
}

#: specialisation -> normalised canonical skill set
_SPECIALIZATION_CORE = {
    name: {normalize_skill(skill) for skill in config.get("core_skills", [])}
    for name, config in SPECIALIZATIONS.items()
}


@lru_cache(maxsize=2048)
def _word_pattern(term):
    """Word-boundary matcher for a skill name.

    Uses the same boundary rule as the profession classifier so that "Go" does
    not match "Django" and "C++" / "C#" survive escaping.
    """
    return re.compile(
        r"(?<![a-z0-9+#.])" + re.escape(term.lower()) + r"(?![a-z0-9+#.])",
        re.IGNORECASE,
    )


def _catalogue_weight(skill_key, profession=None, specialization=None):
    """Highest catalogue weight for a skill under the candidate's role.

    Reads the existing PROFESSION_CONFIGS / SPECIALIZATIONS tables rather than
    introducing a parallel importance table that could drift out of step.
    """
    weight = 0
    if profession:
        weight = max(weight, _PROFESSION_WEIGHTS.get(profession, {}).get(skill_key, 0))
    if specialization:
        weight = max(weight, _SPECIALIZATION_WEIGHTS.get(specialization, {}).get(skill_key, 0))
        if skill_key in _SPECIALIZATION_CORE.get(specialization, ()):
            # Canonical skills for the specialisation are role-defining by
            # definition, even when they carry no detection weight.
            weight = max(weight, CRITICAL_WEIGHT_THRESHOLD)
    return weight


def classify_requirement(skill, job_title="", profession=None, specialization=None):
    """Severity band and human explanation for one required skill.

    Returns ``(severity, reason_template)`` where `severity` is a key of
    SEVERITY_POINTS. The reason is phrased for a missing skill; `build_strengths`
    re-phrases the same classification positively.
    """
    key = normalize_skill(skill)
    label = display_name(skill)

    # The strongest possible evidence: the posting is named after this skill.
    if job_title and _word_pattern(skill).search(job_title):
        return "critical", (
            f"{label} is the primary technology named in this role's title."
        )

    weight = _catalogue_weight(key, profession, specialization)

    if key in _CRITICAL_SKILLS or weight >= CRITICAL_WEIGHT_THRESHOLD:
        return "critical", (
            f"{label} is a core requirement of this posting and is central to "
            f"the role, not an optional extra."
        )

    if key in _MINOR_SKILLS:
        return "minor", (
            f"{label} is a supporting requirement listed by this posting."
        )

    if key in _MEDIUM_SKILLS or weight >= MEDIUM_WEIGHT_THRESHOLD:
        return "medium", (
            f"{label} is listed as a required skill in this job posting."
        )

    # It is still something the posting explicitly asked for.
    return "medium", f"{label} is listed as a required skill in this job posting."


def _dedupe(skills):
    """Preserve posting order while removing normalised duplicates."""
    seen = set()
    ordered = []
    for skill in skills or []:
        if not skill:
            continue
        key = normalize_skill(skill)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(skill)
    return ordered


def _profile_deductions(signals):
    """CV-presentation penalties, capped well below the job-specific ones.

    These are the only deductions not tied to a posting's requirements; they are
    kept small and few precisely so role fit stays the dominant term.
    """
    if not signals or not signals.get("word_count"):
        # No CV text was parsed - we have no evidence either way, and guessing
        # would penalise the user for a missing upload rather than a real gap.
        return []

    items = []

    missing_sections = [s for s in ("skills", "experience")
                        if s in (signals.get("sections_missing") or [])]
    if missing_sections:
        names = " and ".join(s.title() for s in missing_sections)
        items.append({
            "item": f"{names} section",
            "severity": "minor",
            "points": SEVERITY_POINTS["minor"],
            "category": "cv_structure",
            "reason": (f"Your CV has no clearly labelled {names} section, which "
                       f"automated screens rely on to read your background."),
        })

    if not signals.get("certification_count"):
        items.append({
            "item": "Certifications",
            "severity": "trivial",
            "points": SEVERITY_POINTS["trivial"],
            "category": "cv_evidence",
            "reason": ("No certifications were listed to corroborate the skills "
                       "on your CV."),
        })

    if not signals.get("portfolio_links"):
        items.append({
            "item": "Portfolio link",
            "severity": "trivial",
            "points": SEVERITY_POINTS["trivial"],
            "category": "cv_evidence",
            "reason": ("No portfolio, GitHub or LinkedIn link was found, so a "
                       "recruiter cannot verify your work."),
        })

    # Trim to the sub-ceiling, strongest first.
    items.sort(key=lambda d: -d["points"])
    kept, spent = [], 0
    for item in items:
        if spent + item["points"] > MAX_PROFILE_DEDUCTION:
            continue
        kept.append(item)
        spent += item["points"]
    return kept


#: Sort order for presentation: heaviest penalty first, job-specific gaps ahead
#: of CV-presentation ones at equal weight.
_CATEGORY_RANK = {"missing_skill": 0, "cv_structure": 1, "cv_evidence": 2}


def evaluate_deductions(job, missing_skills, signals=None,
                        profession=None, specialization=None):
    """Score the gap between one posting's requirements and one CV.

    `missing_skills` must be the posting's own `required_skills` that the
    candidate does not have - computed once by the caller so this function
    never re-derives skill matching.

    Returns a dict with:
        deductions        applied items; their points sum exactly to `total`
        total             points to subtract (never above MAX_TOTAL_DEDUCTION)
        raw_total         what the gaps would have cost without the cap
        capped            True when the cap actually bound
        additional_gaps   requirements found but not charged, because of the cap
    """
    job_title = (getattr(job, "title", "") or "")

    candidates = []
    for skill in _dedupe(missing_skills):
        severity, reason = classify_requirement(
            skill, job_title=job_title, profession=profession,
            specialization=specialization,
        )
        candidates.append({
            "item": display_name(skill),
            "severity": severity,
            "points": SEVERITY_POINTS[severity],
            "category": "missing_skill",
            "reason": reason,
        })

    candidates.extend(_profile_deductions(signals))
    candidates.sort(key=lambda d: (-d["points"], _CATEGORY_RANK.get(d["category"], 9)))

    raw_total = sum(item["points"] for item in candidates)

    # Apply until the cap is reached. The last item that does not fit whole is
    # clipped rather than dropped, so the numbers the user sees always add up
    # to the total that was actually subtracted.
    applied, spent, additional = [], 0, 0
    for item in candidates:
        remaining = MAX_TOTAL_DEDUCTION - spent
        if remaining <= 0:
            additional += 1
            continue
        charged = min(item["points"], remaining)
        entry = dict(item, points=charged)
        if charged < item["points"]:
            entry["reason"] += (f" Charged {charged} of {item['points']} points - "
                                f"the {MAX_TOTAL_DEDUCTION}-point deduction cap was reached.")
        applied.append(entry)
        spent += charged

    return {
        "deductions": applied,
        "total": spent,
        "raw_total": raw_total,
        "capped": raw_total > MAX_TOTAL_DEDUCTION,
        "additional_gaps": additional,
        "max_deduction": MAX_TOTAL_DEDUCTION,
    }


def build_strengths(job, matched_skills, signals=None,
                    profession=None, specialization=None, limit=8):
    """The positive counterpart of `evaluate_deductions`.

    Requirements this posting asks for that the CV does evidence, ordered so the
    role-defining ones lead. Shown next to the deductions so the score reads as
    a ledger rather than a verdict.
    """
    job_title = (getattr(job, "title", "") or "")
    signals = signals or {}

    strengths = []
    for skill in _dedupe(matched_skills):
        severity, _ = classify_requirement(
            skill, job_title=job_title, profession=profession,
            specialization=specialization,
        )
        label = display_name(skill)
        if severity == "critical":
            reason = f"{label} is a core requirement of this role and is evidenced in your CV."
        else:
            reason = f"{label} is required by this posting and appears in your CV."
        strengths.append({
            "item": label,
            "severity": severity,
            "category": "matched_skill",
            "weight": SEVERITY_POINTS[severity],
            "reason": reason,
        })

    strengths.sort(key=lambda s: -s["weight"])

    # A couple of non-skill positives, so a candidate who did the work gets
    # credit for it in the same place the gaps are listed.
    extras = []
    if signals.get("certification_count"):
        extras.append({
            "item": f"{signals['certification_count']} certification(s)",
            "severity": "trivial", "category": "cv_evidence", "weight": 1,
            "reason": "Certifications on your CV corroborate the skills you list.",
        })
    if signals.get("portfolio_links"):
        extras.append({
            "item": "Portfolio / GitHub link",
            "severity": "trivial", "category": "cv_evidence", "weight": 1,
            "reason": "Your CV links to work a recruiter can verify.",
        })

    return (strengths + extras)[:limit]

"""ATS resume-quality scoring.

Scores how well a CV would survive an Applicant Tracking System and a recruiter
skim. This is deliberately separate from the job-match score: a candidate can be
a perfect skills fit and still be filtered out by a badly structured document.

Every check returns its own sub-score AND the reason for it, so the UI can
explain the number instead of just displaying it (Phase 2 #12).
"""

from apps.shared.cv_signals import extract_cv_signals
from apps.shared.skill_normalizer import normalize_skill

#: Relative weight of each dimension in the overall quality score.
QUALITY_WEIGHTS = {
    "sections": 20,
    "keywords": 20,
    "achievements": 18,
    "action_verbs": 12,
    "contact": 10,
    "projects": 10,
    "formatting": 10,
}

_SECTION_LABELS = {
    "summary": "Professional summary",
    "experience": "Work experience",
    "education": "Education",
    "skills": "Skills",
    "projects": "Projects",
    "certifications": "Certifications",
}

#: A CV materially shorter than this reads as thin; much longer reads as unfocused.
_MIN_WORDS = 180
_IDEAL_WORDS = (300, 900)


def _band(score):
    if score >= 85:
        return "excellent"
    if score >= 70:
        return "good"
    if score >= 50:
        return "fair"
    return "needs work"


def _score_sections(signals):
    present, missing = signals["sections_present"], signals["sections_missing"]
    total = len(present) + len(missing)
    score = round(len(present) / total * 100) if total else 0
    if missing:
        detail = "Missing: " + ", ".join(_SECTION_LABELS.get(m, m) for m in missing)
    else:
        detail = "All expected sections are present."
    return score, detail, [
        f"Add a {_SECTION_LABELS.get(m, m)} section" for m in missing
    ]


def _score_keywords(signals, user_skills, required_skills):
    """Keyword coverage against what the matched jobs actually ask for."""
    required = {normalize_skill(s) for s in (required_skills or []) if s}
    if not required:
        return 60, "No target job requirements available to compare against.", []
    have = {normalize_skill(s) for s in (user_skills or []) if s}
    covered = have & required
    score = round(len(covered) / len(required) * 100)
    detail = (f"Your CV contains {len(covered)} of {len(required)} keywords "
              f"required by your best-matching roles.")
    gaps = sorted(required - have)[:5]
    return score, detail, [f"Add the keyword '{g}' if you have that experience" for g in gaps]


def _score_achievements(signals):
    count = signals["achievement_count"]
    score = min(100, count * 25)
    if count:
        detail = f"{count} quantified achievement(s) detected (numbers, %, or scale)."
    else:
        detail = "No quantified achievements detected."
    tips = []
    if count < 3:
        tips.append("Quantify results with numbers, percentages, users, or time saved")
    return score, detail, tips


def _score_action_verbs(signals):
    bullets = max(signals["bullet_count"], 1)
    verbs = signals["action_verb_count"]
    # Roughly one strong verb per bullet is the target.
    score = min(100, round(verbs / bullets * 100)) if signals["bullet_count"] else \
        min(100, verbs * 12)
    detail = f"{verbs} strong action verb(s) across {signals['bullet_count']} bullet point(s)."
    tips = []
    if score < 70:
        tips.append("Start each bullet with a strong verb (Built, Led, Optimised, Reduced)")
    return score, detail, tips


def _score_contact(signals):
    have = sum([signals["has_email"], signals["has_phone"],
                bool(signals["portfolio_links"])])
    score = round(have / 3 * 100)
    missing = []
    if not signals["has_email"]:
        missing.append("email address")
    if not signals["has_phone"]:
        missing.append("phone number")
    if not signals["portfolio_links"]:
        missing.append("portfolio / GitHub / LinkedIn link")
    detail = ("Contact details are complete." if not missing
              else "Missing: " + ", ".join(missing))
    return score, detail, [f"Add your {m}" for m in missing]


def _score_projects(signals):
    count = signals["project_count"]
    score = min(100, count * 34)
    extras = sum([signals["has_open_source"], signals["has_hackathon"],
                  bool(signals["github_links"])])
    score = min(100, score + extras * 8)
    detail = (f"{count} documented project(s)"
              + (" with supporting open-source/GitHub evidence." if extras else "."))
    tips = []
    if count < 2:
        tips.append("Document at least two projects with your specific role and the outcome")
    if not signals["github_links"]:
        tips.append("Link the source code or a live demo for your projects")
    return score, detail, tips


def _score_formatting(signals):
    words = signals["word_count"]
    if words < _MIN_WORDS:
        score, detail = 40, f"The CV is short ({words} words); recruiters expect more detail."
    elif _IDEAL_WORDS[0] <= words <= _IDEAL_WORDS[1]:
        score, detail = 100, f"Length is well judged ({words} words)."
    elif words < _IDEAL_WORDS[0]:
        score, detail = 75, f"Slightly thin ({words} words)."
    else:
        score, detail = 65, f"The CV is long ({words} words); tighten it toward two pages."
    tips = []
    if signals["bullet_count"] < 5:
        score = max(0, score - 15)
        tips.append("Use bullet points rather than dense paragraphs - ATS parsers prefer them")
    return score, detail, tips


def analyze_resume_quality(resume_text, user_skills=None, required_skills=None,
                           signals=None):
    """Return an explainable ATS quality report for a CV.

    `required_skills` should be the skills demanded by the candidate's
    best-matching jobs, so keyword coverage is measured against roles they
    actually target rather than the whole job board.
    """
    signals = signals or extract_cv_signals(resume_text)
    if not (resume_text or "").strip():
        return {
            "score": 0, "band": "needs work", "breakdown": [],
            "recommendations": ["Upload a CV to receive a resume quality report."],
        }

    checks = (
        ("sections", "Section completeness", _score_sections(signals)),
        ("keywords", "Keyword coverage", _score_keywords(signals, user_skills, required_skills)),
        ("achievements", "Quantified achievements", _score_achievements(signals)),
        ("action_verbs", "Action verbs", _score_action_verbs(signals)),
        ("contact", "Contact information", _score_contact(signals)),
        ("projects", "Project evidence", _score_projects(signals)),
        ("formatting", "Formatting & ATS readability", _score_formatting(signals)),
    )

    breakdown = []
    total = 0.0
    total_weight = 0.0
    recommendations = []
    for key, label, (score, detail, tips) in checks:
        weight = QUALITY_WEIGHTS[key]
        total += score * weight
        total_weight += weight
        breakdown.append({
            "key": key,
            "label": label,
            "score": score,
            "weight": weight,
            "band": _band(score),
            "detail": detail,
        })
        recommendations.extend(tips)

    overall = round(total / total_weight) if total_weight else 0
    return {
        "score": overall,
        "band": _band(overall),
        "breakdown": sorted(breakdown, key=lambda b: b["score"]),
        "recommendations": recommendations[:8],
    }
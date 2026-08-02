"""Structured signals parsed directly from CV text.

The match score used to take experience and education from `UserProfile` DB
columns, and had no notion of projects or certifications at all. Two different
CVs uploaded by the same user therefore produced identical experience,
education, project and certification sub-scores - which is a large part of why
"every CV gets the same score".

Everything here is derived from the uploaded document, so it changes when the
document changes.
"""

import re

EDUCATION_RANK = {"unknown": 0, "diploma": 1, "bachelor": 2, "master": 3, "phd": 4}

_YEARS_PATTERNS = (
    # "5+ years of experience", "5 years experience"
    re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)\s+(?:of\s+)?(?:professional\s+|work\s+|industry\s+)?experience", re.I),
    # "experience: 5 years"
    re.compile(r"experience\s*[:\-]\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.I),
    # bare "5+ years"
    re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.I),
)

#: "2019 - 2023", "2019 to Present"
_DATE_RANGE = re.compile(
    r"(19|20)(\d{2})\s*(?:-|–|—|to)\s*((?:19|20)\d{2}|present|current|now)", re.I
)

_SECTION_HEADS = {
    "projects": re.compile(r"^\s*(?:key\s+|personal\s+|academic\s+|selected\s+)?projects?\s*[:\-]?\s*$", re.I | re.M),
    "certifications": re.compile(r"^\s*(?:certifications?|certificates?|licen[cs]es|credentials)\s*[:\-]?\s*$", re.I | re.M),
}

_CERT_TOKENS = re.compile(
    r"\b(certified|certification|certificate|aws certified|azure certified|"
    r"google cloud certified|oscp|ccna|ccnp|cissp|comptia|pmp|scrum master|"
    r"cka|ckad|tensorflow developer certificate)\b", re.I
)

_METRIC = re.compile(r"(\d+(?:\.\d+)?\s*%|\$\s?\d|\b\d+k\b|\b\d{3,}\+?\s*(?:users|customers|requests|records))", re.I)
_LEADERSHIP = re.compile(r"\b(led|lead|mentor(?:ed)?|managed|supervis(?:ed|or)|head of|owned)\b", re.I)
_PORTFOLIO = re.compile(r"\b(github\.com|gitlab\.com|bitbucket\.org|behance\.net|dribbble\.com|linkedin\.com/in|portfolio)\b", re.I)
_BULLET = re.compile(r"^\s*[\-\*•●▪]\s+", re.M)

# --- extended evidence signals -------------------------------------------
_GITHUB_URL = re.compile(r"github\.com/[\w\-.]+", re.I)
_INTERNSHIP = re.compile(r"\b(intern|internship|trainee|apprentice(?:ship)?|co-op)\b", re.I)
_OPEN_SOURCE = re.compile(
    r"\b(open[\s\-]?source|contributed to|pull request|merged pr|maintainer|"
    r"contributor to|foss)\b", re.I)
_HACKATHON = re.compile(r"\b(hackathon|codefest|code jam|datathon|ctf|game jam)\b", re.I)
_AWARD = re.compile(
    r"\b(award(?:ed)?|winner|1st place|first place|runner[\s\-]?up|honou?rs?|"
    r"dean'?s list|scholarship|medal(?:list)?|top \d+)\b", re.I)
_RESEARCH = re.compile(r"\b(research|thesis|dissertation|lab assistant)\b", re.I)
_PUBLICATION = re.compile(
    r"\b(publication|published|journal|ieee|acm|springer|elsevier|arxiv|"
    r"conference paper|doi:)\b", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")

#: Strong resume verbs. ATS screens and recruiters both reward these.
_ACTION_VERBS = re.compile(
    r"\b(built|designed|developed|implemented|led|launched|migrated|optimi[sz]ed|"
    r"automated|architected|delivered|reduced|increased|improved|scaled|"
    r"refactored|integrated|deployed|created|engineered|shipped|owned|"
    r"streamlined|resolved|mentored|spearheaded)\b", re.I)

#: Sections a complete, ATS-friendly CV is expected to carry.
_EXPECTED_SECTIONS = {
    "summary": re.compile(r"\b(summary|profile|objective|about me)\b", re.I),
    "experience": re.compile(r"\b(experience|employment|work history)\b", re.I),
    "education": re.compile(r"\b(education|academic|qualifications)\b", re.I),
    "skills": re.compile(r"\b(skills|technical skills|technologies|tech stack)\b", re.I),
    "projects": re.compile(r"\b(projects?)\b", re.I),
    "certifications": re.compile(r"\b(certifications?|certificates?|licen[cs]es)\b", re.I),
}


def _parse_experience_years(text):
    """Best-effort years of professional experience.

    Prefers an explicit statement; otherwise infers span from employment date
    ranges, which is how most CVs actually communicate it.
    """
    best = 0.0
    for pattern in _YEARS_PATTERNS:
        for match in pattern.finditer(text):
            try:
                best = max(best, float(match.group(1)))
            except (TypeError, ValueError):
                continue
    if best:
        return min(best, 45.0)

    spans = []
    for match in _DATE_RANGE.finditer(text):
        start = int(match.group(1) + match.group(2))
        end_raw = match.group(3).lower()
        end = 2026 if end_raw in ("present", "current", "now") else int(end_raw)
        if 1960 < start <= end <= 2100:
            spans.append(end - start)
    if spans:
        # Sum of spans over-counts overlapping roles; the max single span
        # under-counts. Their midpoint is a reasonable compromise.
        return min(float(round((sum(spans) + max(spans)) / 2, 1)), 45.0)
    return 0.0


def _parse_education_level(text):
    lowered = text.lower()
    if any(t in lowered for t in ("phd", "ph.d", "doctorate", "doctoral")):
        return "phd"
    if any(t in lowered for t in ("master", "m.sc", "msc", "mba", "m.tech", "m.e.")):
        return "master"
    if any(t in lowered for t in ("bachelor", "b.sc", "bsc", "b.tech", "b.e.", "b.com", "undergraduate")):
        return "bachelor"
    if any(t in lowered for t in ("diploma", "associate", "hnd")):
        return "diploma"
    return "unknown"


def _count_section_items(text, section):
    """Rough item count inside a named section."""
    head = _SECTION_HEADS[section].search(text)
    if not head:
        return 0
    tail = text[head.end():]
    # Stop at the next ALL-CAPS / Title-case heading line.
    stop = re.search(r"\n\s*[A-Z][A-Za-z ]{2,30}\s*[:\-]?\s*\n", tail)
    body = tail[:stop.start()] if stop else tail[:1500]
    bullets = len(_BULLET.findall(body))
    if bullets:
        return bullets
    return len([l for l in body.splitlines() if l.strip()])


def extract_cv_signals(resume_text):
    """Parse CV-derived signals. Always returns every key."""
    text = resume_text or ""
    if not text.strip():
        return {
            "experience_years": 0.0, "education_level": "unknown",
            "education_rank": 0, "project_count": 0, "certification_count": 0,
            "has_projects": False, "has_certifications": False,
            "has_metrics": False, "has_leadership": False, "has_portfolio": False,
            "achievement_count": 0, "has_internship": False,
            "has_open_source": False, "has_hackathon": False, "has_awards": False,
            "has_research": False, "has_publications": False,
            "github_links": [], "portfolio_links": [],
            "action_verb_count": 0, "bullet_count": 0, "word_count": 0,
            "sections_present": [], "sections_missing": list(_EXPECTED_SECTIONS),
            "has_email": False, "has_phone": False,
        }

    education_level = _parse_education_level(text)
    project_count = _count_section_items(text, "projects")
    cert_section = _count_section_items(text, "certifications")
    cert_mentions = len(set(m.group(0).lower() for m in _CERT_TOKENS.finditer(text)))
    certification_count = max(cert_section, cert_mentions)

    sections_present = [
        name for name, pattern in _EXPECTED_SECTIONS.items() if pattern.search(text)
    ]
    github_links = sorted({m.group(0) for m in _GITHUB_URL.finditer(text)})
    portfolio_links = sorted({m.group(0) for m in _PORTFOLIO.finditer(text)})

    return {
        "experience_years": _parse_experience_years(text),
        "education_level": education_level,
        "education_rank": EDUCATION_RANK[education_level],
        "project_count": project_count,
        "certification_count": certification_count,
        "has_projects": bool(project_count) or bool(re.search(r"\bprojects?\b", text, re.I)),
        "has_certifications": bool(certification_count),
        "has_metrics": bool(_METRIC.search(text)),
        "has_leadership": bool(_LEADERSHIP.search(text)),
        "has_portfolio": bool(portfolio_links),

        # --- extended evidence (Phase 2 #10) ---------------------------------
        # Quantified bullet points are the strongest achievement signal an ATS
        # or a recruiter reads, so they are counted rather than flagged.
        "achievement_count": len(_METRIC.findall(text)),
        "has_internship": bool(_INTERNSHIP.search(text)),
        "has_open_source": bool(_OPEN_SOURCE.search(text)),
        "has_hackathon": bool(_HACKATHON.search(text)),
        "has_awards": bool(_AWARD.search(text)),
        "has_research": bool(_RESEARCH.search(text)),
        "has_publications": bool(_PUBLICATION.search(text)),
        "github_links": github_links,
        "portfolio_links": portfolio_links,

        # --- resume-quality inputs (Phase 2 #11) -----------------------------
        "action_verb_count": len(_ACTION_VERBS.findall(text)),
        "bullet_count": len(_BULLET.findall(text)),
        "word_count": len(text.split()),
        "sections_present": sections_present,
        "sections_missing": [s for s in _EXPECTED_SECTIONS if s not in sections_present],
        "has_email": bool(_EMAIL.search(text)),
        "has_phone": bool(_PHONE.search(text)),
    }
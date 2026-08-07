# file path: apps/jobs/search.py
"""Relevance search for the job board.

The search box used to be a bag of `icontains` clauses OR-ed together and
sorted by date. Three things went wrong with that:

* Searching "Flutter" returned every job whose description happened to say
  the word once, ranked above the actual Flutter roles, because the only
  sort was `-created_at`.
* The role box and the skill box were OR-ed, so adding a skill *widened*
  the search instead of narrowing it.
* `normalize()` replaced a term with its synonym rather than searching for
  both, so "react" was rewritten to "reactjs" and stopped finding
  "React Developer" altogether.

Search now runs in two passes:

1. **The database narrows.** The hard filters (experience, work mode) plus
   a cheap `icontains` net over the searchable columns cut the table down
   to candidates, so the ranking pass never walks the whole board.
2. **Python ranks.** Each candidate is scored field by field and anything
   scoring zero is dropped, so a mid-word coincidence never survives.

Matching is *word-prefix*, not substring: "pyth" finds "Python Developer"
and "mach" finds "Machine Learning Engineer", while "ai" no longer drags in
"Retail" and "js" no longer drags in "JSON". Terms of one or two characters
have to match a whole word, because a two-letter prefix matches almost
anything.

Nothing here touches the recommendation engine or the AI job match - those
score a *candidate* against a job. This scores a *query* against a job.
"""

import re
from functools import lru_cache

from django.db.models import Q

# ── Vocabulary ───────────────────────────────────────────────────────────

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
    """Split a search string into normalised terms.

    Kept exactly as it was: the global search in `apps.accounts` imports
    this and feeds the result straight into `icontains` lookups.
    """
    if not raw:
        return []
    return [normalize(t) for t in raw.replace(",", " ").split() if t.strip()]


def synonyms_of(term):
    """Every spelling of `term` that is worth searching for.

    The map is read in both directions. A one-way substitution is what
    stopped "react" from finding "React Developer" - it became "reactjs",
    which appears in no job title anywhere.
    """
    variants = {term}
    mapped = SYNONYM_MAP.get(term)
    if mapped:
        variants.add(mapped)
    for key, value in SYNONYM_MAP.items():
        if value == term or key == mapped or (mapped and value == mapped):
            variants.add(key)
            variants.add(value)
    return sorted(variants)


# ── Term matching ────────────────────────────────────────────────────────

#: Terms this short must match a whole word. "ai" as a prefix matches
#: "Air"; as a whole word it only matches "AI".
_WHOLE_WORD_MAX_LEN = 2

_SPLIT = re.compile(r"[\s,;/|]+")


def tokenise(raw):
    return [t for t in _SPLIT.split(str(raw or "").lower()) if t.strip()]


@lru_cache(maxsize=512)
def _pattern(term):
    """A word-start matcher for `term`, over already-lowercased text."""
    tail = r"(?![a-z0-9])" if len(term) <= _WHOLE_WORD_MAX_LEN else ""
    return re.compile(r"(?<![a-z0-9])" + re.escape(term) + tail)


def _occurrences(text, variants):
    if not text:
        return 0
    return sum(len(_pattern(variant).findall(text)) for variant in variants)


# ── Query model ──────────────────────────────────────────────────────────

class _Group:
    """One thing the user asked for, in every spelling it might appear in."""

    __slots__ = ("variants", "is_phrase")

    def __init__(self, variants, is_phrase=False):
        self.variants = variants
        self.is_phrase = is_phrase


class _Query:
    __slots__ = ("phrase", "groups", "tokens")

    def __init__(self, phrase, groups, tokens):
        self.phrase = phrase
        self.groups = groups
        self.tokens = tokens


def build_query(raw):
    """Turn a search box into the groups a job has to answer.

    A multi-word query also gets a phrase group, so "machine learning"
    reaches an "ML Engineer" through the synonym map even though neither
    word appears in that title.
    """
    tokens = tokenise(raw)
    if not tokens:
        return None

    groups = [_Group(synonyms_of(token)) for token in tokens]
    phrase = " ".join(tokens)
    if len(tokens) > 1:
        groups.insert(0, _Group(synonyms_of(phrase), is_phrase=True))
    return _Query(phrase=phrase, groups=groups, tokens=tokens)


# ── Scoring ──────────────────────────────────────────────────────────────

#: Field weights, in the priority the product spec asks for: an exact title
#: hit outranks a skill hit, which outranks a category hit, and so on down
#: to a passing mention in the description.
ROLE_WEIGHTS = {
    "title": 40,
    "skills": 30,
    "category": 20,
    "company": 12,
    "location": 10,
    "description": 5,
}

#: The skill box is asking a different question, so the skills column leads.
SKILL_WEIGHTS = {
    "skills": 40,
    "title": 25,
    "category": 15,
    "description": 8,
    "company": 4,
    "location": 2,
}

TITLE_EXACT_BONUS = 150     # the whole query *is* the job title
TITLE_PREFIX_BONUS = 40     # the title starts with the query
TITLE_PHRASE_BONUS = 25     # the query appears as a phrase in the title
REPEAT_BONUS = 1            # per extra occurrence of a term in one field
REPEAT_CAP = 5
FULL_COVERAGE_BONUS = 20    # every term in the query was found


def haystacks(job):
    """The searchable text of a job, lowercased once per job."""
    return {
        "title": (job.title or "").lower(),
        "skills": " ".join(str(s) for s in (job.required_skills or [])).lower(),
        "category": (job.job_category or "").lower(),
        "company": (job.company or "").lower(),
        "location": (job.location or "").lower(),
        "description": (job.description or "").lower(),
    }


def score_query(query, fields, weights, coverage_bonus, title_bonuses=True):
    """Score one query against one job's text.

    Returns `(score, matched)`. `matched` is what decides whether the job is
    a result at all - a score of zero means the term is simply not in this
    job, and the job is dropped rather than ranked last.
    """
    total = 0
    matched_tokens = 0
    phrase_hit = False
    token_count = sum(1 for group in query.groups if not group.is_phrase)

    for group in query.groups:
        earned = 0
        for field, weight in weights.items():
            occurrences = _occurrences(fields.get(field, ""), group.variants)
            if occurrences:
                earned += weight + min(occurrences - 1, REPEAT_CAP) * REPEAT_BONUS
        if not earned:
            continue
        total += earned
        if group.is_phrase:
            phrase_hit = True
        else:
            matched_tokens += 1

    if not (phrase_hit or matched_tokens):
        return 0, False

    # The phrase matching *is* full coverage - "ML Engineer" answers
    # "machine learning" completely, even though it matched one group.
    coverage = 1.0 if phrase_hit else (matched_tokens / token_count if token_count else 0.0)
    total += coverage_bonus * coverage
    if coverage >= 1.0:
        total += FULL_COVERAGE_BONUS

    if title_bonuses:
        title = fields.get("title", "")
        if title:
            if title == query.phrase:
                total += TITLE_EXACT_BONUS
            elif title.startswith(query.phrase):
                total += TITLE_PREFIX_BONUS
            elif _pattern(query.phrase).search(title):
                total += TITLE_PHRASE_BONUS

    return total, True


# ── Database narrowing ───────────────────────────────────────────────────

#: Columns the `icontains` net covers. It only has to be a *superset* of
#: what scoring accepts, so substring matching here is fine - the ranking
#: pass throws back anything that only matched mid-word.
_DB_COLUMNS = ("title", "company", "job_category", "description", "location", "required_skills")


def _narrow_q(query):
    clause = Q()
    for group in query.groups:
        for variant in group.variants:
            for column in _DB_COLUMNS:
                clause |= Q(**{f"{column}__icontains": variant})
    return clause


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Entry point ──────────────────────────────────────────────────────────

def search_jobs(queryset, role="", skill="", experience=None, work_mode=None, work_modes=None):
    """Filter and rank `queryset` for the job search page.

    Every supplied filter narrows: a role *and* a skill *and* an experience
    ceiling *and* a work mode all have to be satisfied. Within one box the
    terms are OR-ed, and matching more of them ranks higher.

    Returns a list when there is something to rank and the queryset itself
    when there is not, so plain browsing stays lazy and unchanged.
    """
    valid_modes = set(work_modes or ())

    ceiling = _as_float(experience)
    if ceiling is not None:
        queryset = queryset.filter(experience_required__lte=ceiling)

    mode = (work_mode or "").strip().lower()
    if mode and (not valid_modes or mode in valid_modes):
        queryset = queryset.filter(work_mode=mode)

    role_query = build_query(role)
    skill_query = build_query(skill)

    # Each box narrows the queryset separately, so they compose with AND.
    if role_query:
        queryset = queryset.filter(_narrow_q(role_query))
    if skill_query:
        queryset = queryset.filter(_narrow_q(skill_query))

    # `recruiter_email` walks the FK on every row; without this the list
    # costs one extra query per job.
    queryset = queryset.select_related("recruiter")

    if not (role_query or skill_query):
        return queryset.order_by("-created_at")

    ranked = []
    for job in queryset:
        fields = haystacks(job)
        score = 0

        if role_query:
            earned, matched = score_query(role_query, fields, ROLE_WEIGHTS, coverage_bonus=30)
            if not matched:
                continue
            score += earned

        if skill_query:
            earned, matched = score_query(
                skill_query, fields, SKILL_WEIGHTS, coverage_bonus=60, title_bonuses=False
            )
            if not matched:
                continue
            score += earned

        ranked.append((score, job))

    ranked.sort(key=lambda pair: (-pair[0], -pair[1].created_at.timestamp(), -pair[1].id))
    return [job for _, job in ranked]

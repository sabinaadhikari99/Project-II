# file path: apps/chatbot/intents.py
"""Question routing for the AI Career Assistant.

Two jobs, both done deterministically with no model call:

**Which mode is this?** "Hi" and "why is my match score 62%?" need opposite
treatment. The first must never touch the database - fetching a skill gap to say
hello is slow, pointless, and tempts the model into reciting the user's numbers
at someone who just waved. The second is worthless without that data. Every
intent therefore declares a `mode` (conversation or career) and a
`context_level` saying how much of the user's record it is allowed to cost.

**Which slices of the record?** Sending every section with every question would
be slow, costly, and would bury the relevant facts. Career intents name only the
sections their answer needs.

Routing is simple and inspectable: a question either matches a known topic or
falls back to a balanced default. It never blocks an answer; the worst case is a
slightly larger context.
"""

import re
from dataclasses import dataclass, field

#: Always included for career questions: cheap, and every answer benefits from
#: knowing who is asking.
BASE_SECTIONS = ("profile", "cv")

#: How the reply is produced.
MODE_CONVERSATION = "conversation"
MODE_CAREER = "career"

#: How much of the user's record an intent may spend.
CONTEXT_NONE = "none"      #: no database access at all
CONTEXT_LIGHT = "light"    #: identity only - who they are, nothing analytical
CONTEXT_FULL = "full"      #: the sections the intent declares


@dataclass(frozen=True)
class Intent:
    name: str
    patterns: tuple
    sections: tuple
    follow_ups: tuple = field(default_factory=tuple)
    #: Look up jobs named in the question (comparisons, "why this job").
    resolve_jobs: bool = False
    #: Extra instruction appended to the system prompt for this kind of question.
    guidance: str = ""
    #: Tie-break when two intents match equally well. Questions that name a
    #: concrete SkillSync artifact ("applied", "quiz", "saved") are more
    #: specific than ones that merely mention jobs or a score, so they win.
    #: Declared here rather than inferred from position in `INTENTS`, which
    #: would make routing depend on the order entries happen to be listed.
    priority: int = 0
    #: Conversation or career work. Decides which system prompt is used and
    #: whether the retrieval layer runs at all.
    mode: str = MODE_CAREER
    #: Database budget. Defaults to the sections above; conversational intents
    #: override it to buy nothing.
    context_level: str = CONTEXT_FULL

    @property
    def is_conversational(self):
        return self.mode == MODE_CONVERSATION


# ---------------------------------------------------------------------------
# Mode 1 - conversation
#
# Every pattern here is anchored to the whole message. That is deliberate: an
# unanchored greeting pattern would capture "Hi, why is my score low?" and answer
# a real question with small talk. A greeting only counts when the message is
# nothing but a greeting.
# ---------------------------------------------------------------------------
CONVERSATION_INTENTS = (
    Intent(
        name="greeting",
        patterns=(
            r"^\s*(hi+|hey+|hello+|helo|yo|hiya|heya|howdy|sup|greetings)"
            r"([\s,!.]+(there|again|skillsync|ai|bot|buddy|friend))?\W*$",
            r"^\s*good\s+(morning|afternoon|evening|day)\W*$",
            r"^\s*(namaste|hola|bonjour|salaam|assalamu\s*alaikum)\W*$",
            r"^\s*how('?s|'?re| is| are)\s+(you|it going|things|you doing)\W*$",
            r"^\s*what'?s\s+(up|new)\W*$",
            r"^\s*(i'?m |im )?back\W*$",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        context_level=CONTEXT_NONE,
        priority=5,
        follow_ups=("What jobs fit my profile?", "How can I improve my CV?",
                    "Which skill should I learn next?", "Help me prepare for an interview."),
        guidance=(
            "Greet them back by name of the product, say in one line what you can help with "
            "across jobs, CV, skills and interviews, and ask what they want to work on. "
            "Do not list every capability - pick the framing that sounds natural."
        ),
    ),
    Intent(
        name="gratitude",
        patterns=(
            r"^\s*(thanks?|thank\s*you|thankyou|thx|tysm|ty|cheers|much appreciated)"
            r"([\s,!.]+(a lot|so much|very much|again|man|buddy|skillsync|ai))?\W*$",
            r"^.{0,32}\b(thanks|thank you|appreciate it|that helps|that helped)\W*$",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        context_level=CONTEXT_NONE,
        priority=5,
        follow_ups=("What should I work on next?", "Show me my best job matches.",
                    "Help me practise interview questions."),
        guidance=(
            "Accept the thanks warmly in one line, then offer to keep going with something "
            "concrete - their CV, better matches, or interview prep. Do not be effusive."
        ),
    ),
    Intent(
        name="small_talk",
        patterns=(
            r"^\s*(ok(ay)?|k|kk|cool|nice|great|awesome|amazing|perfect|good|fine|sure|"
            r"alright|right|got it|understood|i see|makes sense|noted|wow|woah|"
            r"yes|yeah|yep|yup|no|nope|nah|hmm+|haha+|hehe|lol|true|indeed)"
            r"([\s,!.]+(then|thanks?|good|one|cool|nice))?\W*$",
            r"^\s*(that'?s|sounds)\s+(good|great|nice|cool|helpful|fair|interesting)\W*$",
            r"^\s*(no|nothing)\s+(thanks?|for now)\W*$",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        context_level=CONTEXT_NONE,
        priority=5,
        follow_ups=("What jobs fit my profile?", "Which skill should I learn next?",
                    "How can I improve my CV?"),
        guidance=(
            "Acknowledge briefly - one short sentence - and move the conversation forward "
            "with a single concrete suggestion. Do not repeat what you just said."
        ),
    ),
    Intent(
        name="farewell",
        patterns=(
            r"^\s*(bye+|goodbye|good\s*night|gn|see\s*(you|ya)( later| soon| around)?|cya|"
            r"catch you later|talk (to you )?later|ttyl|take care|later)\W*$",
            r"^\s*(i'?m|im)\s+(off|leaving|done|going)\W*$",
            r"^\s*that'?s all\W*$",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        context_level=CONTEXT_NONE,
        priority=5,
        follow_ups=("What jobs fit my profile?", "How can I improve my CV?"),
        guidance=(
            "Say goodbye warmly in one or two sentences, leave them with one encouraging "
            "note about their search, and mention they can pick this up any time."
        ),
    ),
    Intent(
        name="identity",
        patterns=(
            r"\bwho are you\b",
            r"\bwhat are you\b",
            r"\btell me about (yourself|you)\b",
            r"\bwhat('?s| is) your name\b",
            r"\bwhat can you (do|help me with|offer)\b",
            r"\bwhat do you do\b",
            r"\bwhat are your (capabilities|features|skills)\b",
            r"\bare you (a |an )?(ai|bot|robot|human|real|person)\b",
            r"\bhow do you work\b",
            # Anchored: "can you help me rewrite my CV?" is a CV question, not a
            # question about who I am.
            r"^\s*(can|could|will)\s+you\s+help( me)?( please)?[\s!.,?]*$",
            r"^\s*how (do|can) you help( me)?[\s!.,?]*$",
            r"^\s*(i need|need) help[\s!.,?]*$",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        context_level=CONTEXT_NONE,
        priority=3,
        follow_ups=("What jobs fit my profile?", "Analyse my CV.",
                    "Which skill should I learn next?", "Practise interview questions."),
        guidance=(
            "Introduce yourself as their AI career assistant and describe what you can do "
            "for them - job matching, CV work, skill gaps, learning plans, interview practice, "
            "cover letters - in flowing prose or a few short bullets, then ask where to start."
        ),
    ),
    Intent(
        name="encouragement",
        patterns=(
            # "I'm", "I am" and "im" all mean the same thing to the person typing.
            r"\b(i'?m|i am)\s+(so |really |very |a bit |quite |kind of |kinda )?"
            r"(nervous|anxious|scared|afraid|worried|stressed|frustrated|confused|lost|"
            r"overwhelmed|struggling|discouraged|hopeless|depressed|excited|happy|thrilled|"
            r"tired|exhausted|burnt out|burned out|stuck)\b",
            r"\bi feel (so |really |very |a bit )?"
            r"(nervous|anxious|scared|down|stuck|lost|hopeless|overwhelmed|unqualified|"
            r"behind|discouraged|useless|great|good|better|confident)\b",
            r"\bi (keep |always )?(get|getting|got) (rejected|no replies|ghosted)\b",
            r"\bno ?(one|body) (is )?(hiring|responding|replying|answering)\b",
            r"\bi (want to |wanna |might )?give up\b",
            r"\b(imposter|impostor) syndrome\b",
            r"\b(i'?m|i am) not (good|confident|qualified|experienced) enough\b",
            r"\blosing (hope|motivation|confidence)\b",
            r"\b(motivate|encourage) me\b",
            r"\bi don'?t know (what to do|where to start|if i can)\b",
        ),
        sections=(),
        mode=MODE_CONVERSATION,
        # Their name and profession make the reassurance concrete without paying
        # for an analysis run.
        context_level=CONTEXT_LIGHT,
        priority=4,
        follow_ups=("What am I already strong at?", "Help me practise interview questions.",
                    "Which skill would help me most right now?"),
        guidance=(
            "Acknowledge how they feel first, genuinely and without platitudes. Normalise it "
            "briefly, then offer one small concrete step you can take with them right now. "
            "Do not quote scores or statistics at someone who is discouraged."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Mode 2 - career work
# ---------------------------------------------------------------------------
CAREER_INTENTS = (
    Intent(
        name="job_fit",
        patterns=(r"\bjobs?\b.*\b(fit|suit|match|for me|recommend)", r"\brecommend(ed)?\s+jobs?",
                  r"\bwhich (jobs?|roles?|positions?)", r"\bwhat (jobs?|roles?)\b",
                  r"\bbest (jobs?|roles?|companies)", r"\bapply (to|for)\b.*\bwhich"),
        sections=("match", "skill_gap", "market"),
        follow_ups=("Why was the top job recommended?", "What am I missing for these roles?",
                    "Which companies match me best?"),
        guidance="Name specific recommended jobs with their match percentages and say why each one fits.",
    ),
    Intent(
        name="score_explain",
        patterns=(r"\b(match )?score\b", r"\bwhy .*\b\d{1,3}\s*%", r"\bwhy is my .*(low|only)",
                  r"\bimprove my (match|score)", r"\bhow .*score .*calculated"),
        sections=("match", "skill_gap"),
        follow_ups=("Which skill would raise my score the most?",
                    "How do I improve my CV?", "Am I ready for senior roles?"),
        guidance=(
            "Break the score into its components (profession, skills, experience, education, "
            "projects, certifications, semantic) and state which ones cost the most points."
        ),
    ),
    Intent(
        name="skills_next",
        patterns=(r"\bwhich skill", r"\bwhat should i learn", r"\blearn first", r"\bskill gaps?\b",
                  r"\bmissing skills?", r"\bupskill", r"\bweakest skills?", r"\bstrongest skills?"),
        sections=("skill_gap", "market", "courses", "roadmap"),
        follow_ups=("Which course should I start with?", "How long will this take?",
                    "What project could prove this skill?"),
        guidance="Rank the gaps by impact, using importance, how many postings require them, and the roadmap order.",
        priority=1,
    ),
    Intent(
        name="cv_review",
        patterns=(r"\b(cv|resume)\b.*\b(improve|better|rewrite|review|feedback|summary|strong)",
                  # Both word orders. "Improve my CV" is the way people actually
                  # phrase it, and without this it matched nothing and fell to
                  # whichever intent happened to catch a stray word like "help".
                  r"\b(improve|rewrite|review|fix|strengthen|polish|update|check)\b.*\b(cv|resume)\b",
                  # "Rewrite it" - the object is in memory, not in the sentence.
                  r"\b(rewrite|reword|redo|polish|shorten) (it|that|this|mine)\b",
                  r"\brewrite my\b", r"\bsummary\b", r"\bats\b", r"\bcv quality"),
        sections=("skill_gap", "match"),
        follow_ups=("Rewrite my CV summary.", "What is my ATS score?",
                    "Which achievements should I highlight?"),
        guidance=(
            "Use the stored CV summary, quality breakdown and parsed signals. When asked to rewrite, "
            "produce the finished text using only real experience from the analysis - invent nothing."
        ),
        priority=1,
    ),
    Intent(
        name="seniority",
        patterns=(r"\bready for\b", r"\bsenior\b", r"\bmid[- ]level\b", r"\bjunior\b",
                  r"\bpromot", r"\bcareer level\b", r"\bexperienced enough\b"),
        sections=("skill_gap", "match", "roadmap", "market"),
        follow_ups=("What separates me from senior roles?", "How long until I am senior?",
                    "Which skills do senior postings require?"),
        guidance=(
            "Judge readiness from career level, years of experience, match percentages and remaining "
            "gaps. Give a direct verdict first, then the specific conditions to change it."
        ),
        priority=1,
    ),
    Intent(
        name="courses",
        patterns=(r"\bcourses?\b", r"\bcertification", r"\bwhere .*learn", r"\btraining\b",
                  r"\bstudy\b", r"\btutorial"),
        sections=("courses", "skill_gap", "roadmap"),
        follow_ups=("How many hours per week should I commit?",
                    "Which skill gives the biggest score gain?", "Show my learning progress."),
        guidance="Recommend from the stored course list, in priority order, with hours and expected score gain.",
        priority=1,
    ),
    Intent(
        name="roadmap",
        patterns=(r"\broadmap\b", r"\bprogress\b", r"\blearning plan\b", r"\bnext step\b",
                  r"\bhow long\b.*\b(learn|ready|take)", r"\bcompleted\b"),
        sections=("roadmap", "skill_gap", "courses"),
        follow_ups=("What should I do this week?", "Which step is blocking me?",
                    "When will I finish at this pace?"),
        guidance="Report completed vs remaining steps, remaining hours and the projected completion date.",
        priority=1,
    ),
    Intent(
        name="applications",
        patterns=(r"\bapplied\b", r"\bapplications?\b", r"\bunder review\b", r"\bshortlist",
                  r"\brejected\b", r"\bhired\b", r"\bstatus\b"),
        sections=("applications", "saved_jobs", "activity"),
        follow_ups=("Which application is strongest?", "What should I do while I wait?",
                    "Show jobs I saved but never applied to."),
        guidance="Answer with exact counts and per-application status. Never guess an outcome.",
        priority=2,
    ),
    Intent(
        name="saved_jobs",
        patterns=(r"\bsaved\b", r"\bbookmark", r"\bshortlisted jobs\b", r"\bwatchlist\b"),
        sections=("saved_jobs", "match", "applications"),
        follow_ups=("Which saved job fits me best?", "Should I apply to these?",
                    "Compare my top two saved jobs."),
        priority=2,
    ),
    Intent(
        name="interview",
        patterns=(r"\binterview", r"\bpractice questions?\b", r"\bmock\b", r"\bprepare\b",
                  r"\bstar method\b", r"\bhr round\b"),
        sections=("match", "skill_gap", "quiz", "courses"),
        follow_ups=("Give me 5 technical questions for my top match.",
                    "How do I answer questions about my missing skills?",
                    "Estimate my interview readiness."),
        guidance=(
            "Base questions on the user's actual skills, projects and the requirements of their "
            "matched jobs. Include how to handle their known gaps."
        ),
        priority=2,
    ),
    Intent(
        name="cover_letter",
        patterns=(r"\bcover letter\b", r"\bmotivation letter\b", r"\bapplication (email|message|letter)\b",
                  r"\bwrite (me )?a letter\b", r"\bintro(duction)? (email|message)\b",
                  r"\bemail to (the )?(recruiter|hiring manager)\b"),
        sections=("match", "skill_gap", "saved_jobs"),
        follow_ups=("Make it shorter.", "Write a version for my second-best match.",
                    "What should I say about my missing skills?"),
        resolve_jobs=True,
        guidance=(
            "Write the finished letter, not advice about writing one. Use only real experience, "
            "skills and achievements from the analysis, and address the specific job's requirements. "
            "Keep it under 250 words, no invented employers, dates or metrics."
        ),
        priority=2,
    ),
    Intent(
        name="compare",
        patterns=(r"\bcompare\b", r"\bversus\b", r"\bvs\.?\b", r"\bdifference between\b",
                  r"\bmy cv (against|with|to)\b", r"\bwhy (was|wasn'?t) .*(recommended|suggested)",
                  # A decision about one posting - which one is in memory.
                  r"\bshould i apply\b", r"\bis (it|this|that) (a )?(good|right|worth)\b",
                  r"\bam i (a )?(good|strong) (fit|match)\b"),
        sections=("match", "skill_gap", "saved_jobs"),
        follow_ups=("Which one should I apply to first?", "What would close the gap for this role?",
                    "Rewrite my CV for this job."),
        resolve_jobs=True,
        guidance="Compare side by side on required skills, experience and match percentage, then give a recommendation.",
        priority=1,
    ),
    Intent(
        name="market",
        patterns=(r"\bcompan(y|ies)\b", r"\bmarket\b", r"\bdemand\b", r"\bhiring\b",
                  r"\bindustry\b", r"\btrend", r"\bsalary\b", r"\bpay\b", r"\bcompensation\b"),
        sections=("market", "match", "skill_gap"),
        follow_ups=("Which companies match me best?", "What skills are most in demand for me?",
                    "How many jobs exist in my field?"),
        guidance=(
            "Use the live posting counts and the salary ranges stored on the matched postings. "
            "Do not quote outside market statistics or invent a salary figure."
        ),
    ),
    Intent(
        name="quiz",
        patterns=(r"\bquiz\b", r"\btest score\b", r"\bassessment\b", r"\bmy answers\b"),
        sections=("quiz", "skill_gap"),
        follow_ups=("Which topics should I revise?", "Generate practice questions.",
                    "How do I improve my weak areas?"),
        priority=2,
    ),
    Intent(
        name="portfolio",
        patterns=(r"\bportfolio\b", r"\bproject ideas?\b", r"\bwhat (should|can) i build\b",
                  r"\bside project\b", r"\bgithub\b"),
        sections=("skill_gap", "match", "roadmap"),
        follow_ups=("Which project proves my strongest skill?",
                    "How long would that project take?", "Which certification is worth it?"),
        guidance="Propose projects that demonstrate the specific missing skills their matched jobs require.",
        priority=2,
    ),
    Intent(
        name="platform",
        patterns=(r"\bhow do i use\b", r"\bwhat can you do\b", r"\bhelp\b", r"\bwhere (is|do i find)\b",
                  r"\bskillsync\b", r"\bthis (app|platform|site)\b"),
        sections=("applications", "activity"),
        follow_ups=("What jobs fit my profile?", "Why is my match score what it is?",
                    "Which skill should I learn first?"),
        guidance=(
            "Explain SkillSync features: AI Job Match (CV upload and scoring), Skill Gap Analysis "
            "(gaps, courses, roadmap), Jobs, Quiz, Notifications and this assistant."
        ),
    ),
)

#: Every intent the router can return. Conversation first so the file reads in
#: the order a real exchange happens, though ranking - not position - decides.
INTENTS = CONVERSATION_INTENTS + CAREER_INTENTS

DEFAULT_INTENT = Intent(
    name="general",
    patterns=(),
    sections=("skill_gap", "match", "applications"),
    follow_ups=("What jobs fit my profile?", "Which skill should I learn next?",
                "How can I improve my CV?"),
)

#: Used when a short unmatched message is clearly chat rather than a question
#: about the user's record. Same fallback role as DEFAULT_INTENT, no database.
CHAT_FALLBACK_INTENT = Intent(
    name="chit_chat",
    patterns=(),
    sections=(),
    mode=MODE_CONVERSATION,
    context_level=CONTEXT_NONE,
    follow_ups=("What jobs fit my profile?", "Which skill should I learn next?",
                "How can I improve my CV?"),
    guidance=(
        "Respond naturally to what they said. If it is career related, answer it as a coach "
        "would from general professional knowledge, without claiming to have read their record. "
        "Then steer gently back to something you can do for them."
    ),
)

_COMPILED = tuple(
    (intent, tuple(re.compile(p, re.I) for p in intent.patterns)) for intent in INTENTS
)

_STOPWORDS = {
    "about", "against", "compare", "should", "would", "could", "which", "what", "where",
    "there", "their", "with", "from", "this", "that", "these", "those", "have", "does",
    "role", "roles", "job", "jobs", "position", "company", "please", "tell", "give",
    "show", "make", "help", "want", "need", "resume", "profile", "between", "versus",
}

#: Messages that only make sense against what was just said. "Why?" carries no
#: topic of its own, so it inherits the topic of the previous turn and the
#: memory block supplies what "it" refers to.
_FOLLOW_UP = re.compile(
    r"^\s*(and\s+)?("
    r"why( is that| not| though)?|how( so| come)?|what for|"
    r"explain( it| that| more| further)?|elaborate|tell me more|more( detail| please)?|"
    r"go on|continue|and( then)?|so|really|which one|what about (it|that|them|those)|"
    r"in what way|for example|e\.?g\.?|such as|based on what|"
    r"do (it|that)|try again|another( one)?|the next one|improve it|fix it|"
    r"show me|what else|anything else"
    r")[\s?.!]*$",
    re.I,
)

#: A career word here means "this is about the user's record", so a short
#: unmatched message containing one is not treated as chit-chat.
_CAREER_HINT = re.compile(
    r"\b(job|jobs|cv|resume|skill|skills|score|match|career|salary|interview|course|"
    r"courses|apply|applied|application|role|roles|hire|hiring|recruiter|company|"
    r"experience|portfolio|roadmap|quiz|gap|gaps|letter)\b",
    re.I,
)


def route(message, previous_intent=None):
    """Pick the intent whose patterns best match the question.

    Ranked on ``(hits, priority)``: the intent matching the most patterns wins,
    and an equal match is settled by the declared specificity rather than by
    which entry comes first in `INTENTS`. Without that tie-break, "Which jobs
    have I applied to?" scores one hit for `job_fit` and one for `applications`
    and would be answered with no application data at all.

    `previous_intent` lets a bare follow-up - "Why?", "Explain", "Tell me more"
    - inherit the topic it is continuing. It is optional, so a caller with no
    conversation still gets the same routing it always did.
    """
    text = (message or "").strip()
    if not text:
        return DEFAULT_INTENT

    best, best_rank = DEFAULT_INTENT, (0, -1)
    for intent, patterns in _COMPILED:
        hits = sum(1 for pattern in patterns if pattern.search(text))
        rank = (hits, intent.priority)
        if hits and rank > best_rank:
            best, best_rank = intent, rank

    if best_rank[0] == 0 and previous_intent is not None and is_follow_up(text):
        return previous_intent
    return best


def is_follow_up(message):
    """True when a message has no topic of its own and continues the last one."""
    return bool(_FOLLOW_UP.match((message or "").strip()))


def looks_conversational(message):
    """True when an unmatched message is chat rather than a data question.

    Only consulted for messages the router could not place. Short, with no
    career vocabulary and no request for their record: answering that from a
    freshly built skill gap would be slow and would read as a non sequitur.
    """
    text = (message or "").strip()
    if not text or len(text) > 120:
        return False
    if _CAREER_HINT.search(text):
        return False
    return len(text.split()) <= 5


def sections_for(intent):
    """Section names to build for this intent, base sections included once.

    Returns nothing for a conversational intent: the point of that mode is that
    saying hello costs no queries.
    """
    level = getattr(intent, "context_level", CONTEXT_FULL)
    if level == CONTEXT_NONE:
        return ()
    if level == CONTEXT_LIGHT:
        return BASE_SECTIONS

    seen, ordered = set(), []
    for name in BASE_SECTIONS + tuple(intent.sections):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return tuple(ordered)


def candidate_terms(message):
    """Words from the question that might name a job title or company."""
    words = re.findall(r"[A-Za-z][A-Za-z0-9.+#/-]{2,}", message or "")
    return [w for w in words if w.lower() not in _STOPWORDS][:8]


def intent_by_name(name):
    """Look an intent up by name, for restoring one remembered on a conversation."""
    for intent in INTENTS:
        if intent.name == name:
            return intent
    if name == CHAT_FALLBACK_INTENT.name:
        return CHAT_FALLBACK_INTENT
    if name == DEFAULT_INTENT.name:
        return DEFAULT_INTENT
    return None

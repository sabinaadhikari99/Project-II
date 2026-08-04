# file path: apps/chatbot/memory.py
"""What the assistant remembers about a conversation.

Replaying the last few messages is enough for a model to follow a topic, but it
is not enough to *act*. "Compare it" needs a job id. "Rewrite it for that role"
needs both a CV and a posting. "Why?" needs to know which claim is being
questioned. Scraping that back out of prose on every turn would be guesswork, so
the facts are extracted once - when the turn that established them is answered -
and stored as structured state on the conversation.

Two properties matter:

* **It survives.** State lives in `Conversation.memory`, so a refresh, a new
  device or a week's gap resumes with the same working context. Writing it is
  the caller's job - `services.ask` does it in the same transaction as the
  messages, so the memory and the transcript can never disagree.
* **It never invents.** Everything here was observed in a real retrieval, so
  putting it in a prompt cannot introduce a fact the database did not produce.
  Conversational turns record what was said and nothing about the user's record.
"""

from .intents import intent_by_name

#: Bumped if the stored shape ever changes incompatibly. Older rows are read
#: leniently rather than migrated - memory is a convenience, not a source of
#: truth, and a stale key costs one turn of sharpness at worst.
STORAGE_VERSION = 1

#: Topics kept for the running summary.
MAX_TOPICS = 6
#: How much of a message is worth remembering verbatim.
SNIPPET = 320
#: Skills carried in memory so "how do I learn it?" resolves without a refetch.
MAX_REMEMBERED_SKILLS = 6

#: Human labels for the topic trail, so the summary reads like a sentence
#: instead of like a list of intent names.
TOPIC_LABELS = {
    "job_fit": "their job matches",
    "score_explain": "how their match score is calculated",
    "skills_next": "which skills to learn next",
    "cv_review": "improving their CV",
    "seniority": "whether they are ready for more senior roles",
    "courses": "course recommendations",
    "roadmap": "their learning roadmap",
    "applications": "their applications",
    "saved_jobs": "their saved jobs",
    "interview": "interview preparation",
    "cover_letter": "a cover letter",
    "compare": "comparing their CV against a role",
    "market": "the job market and salaries",
    "quiz": "their quiz results",
    "portfolio": "portfolio projects",
    "platform": "how to use SkillSync",
    "encouragement": "how they are feeling about the search",
    "general": "their profile",
}


class ConversationMemory:
    """Working memory for one conversation.

    Constructed per request from the stored blob, updated once the answer is
    produced, and written back inside the same transaction that records the
    messages - so memory and transcript can never disagree.
    """

    def __init__(self, conversation=None, data=None):
        self.conversation = conversation
        self.data = dict(data or {})
        self.data.setdefault("version", STORAGE_VERSION)
        self.data.setdefault("turns", 0)

    # -- construction -------------------------------------------------------
    @classmethod
    def load(cls, conversation):
        """Read memory off a conversation. A missing or corrupt blob is empty."""
        if conversation is None:
            return cls()
        stored = getattr(conversation, "memory", None)
        if not isinstance(stored, dict):
            stored = {}
        return cls(conversation, stored)

    # -- reading ------------------------------------------------------------
    @property
    def turns(self):
        return int(self.data.get("turns") or 0)

    @property
    def is_new(self):
        return self.turns == 0

    @property
    def last_intent_name(self):
        return self.data.get("last_intent") or ""

    @property
    def previous_intent(self):
        """The intent of the last turn, so a bare "Why?" inherits its topic."""
        return intent_by_name(self.last_intent_name)

    @property
    def last_user_message(self):
        return self.data.get("last_user_message") or ""

    @property
    def last_assistant_message(self):
        return self.data.get("last_assistant_message") or ""

    @property
    def focus_job(self):
        """The job the conversation is currently about, if any."""
        job = self.data.get("focus_job")
        return job if isinstance(job, dict) else None

    @property
    def profile(self):
        known = self.data.get("profile")
        return known if isinstance(known, dict) else {}

    @property
    def has_cv(self):
        return bool(self.profile.get("has_cv"))

    @property
    def missing_skills(self):
        return list(self.data.get("missing_skills") or [])

    # -- writing ------------------------------------------------------------
    def record(self, *, intent, question, reply, context=None):
        """Fold one completed exchange into memory."""
        context = context or {}
        self.data["version"] = STORAGE_VERSION
        self.data["turns"] = self.turns + 1
        self.data["last_intent"] = intent.name
        self.data["last_mode"] = intent.mode
        self.data["last_user_message"] = (question or "")[:SNIPPET]
        self.data["last_assistant_message"] = (reply or "")[:SNIPPET]

        self._remember_profile(context)
        self._remember_focus_job(intent, context)
        self._remember_topic(intent, question)
        return self

    # -- extraction ---------------------------------------------------------
    def _remember_profile(self, context):
        """Carry forward identity facts, but only ones actually retrieved.

        A conversational turn fetches nothing, so it must leave whatever the
        last career turn established untouched rather than blanking it.
        """
        cv = context.get("cv") or {}
        gap = context.get("skill_gap") or {}
        match = context.get("match") or {}
        if not (cv or gap or match):
            return

        known = dict(self.profile)
        if cv:
            known["has_cv"] = bool(cv.get("uploaded"))
            for source, key in ((cv, "profession"), (cv, "specialization")):
                if source.get(key):
                    known[key] = source[key]
            if cv.get("match_score"):
                known["match_score"] = cv["match_score"]
        if gap.get("career_level_label"):
            known["career_level"] = gap["career_level_label"]
        if gap.get("experience_years") is not None:
            known["experience_years"] = gap.get("experience_years")
        if match.get("best_score"):
            known["match_score"] = match["best_score"]
        self.data["profile"] = known

        gaps = gap.get("missing_skills") or []
        if gaps:
            self.data["missing_skills"] = [str(s) for s in gaps[:MAX_REMEMBERED_SKILLS]]

    def _remember_focus_job(self, intent, context):
        """Pin down what "it" refers to for the next turn.

        A job the user named outright wins over a recommendation, because they
        chose it. Recommendations only become the focus for intents that are
        genuinely about one posting.
        """
        named = (context.get("jobs_in_question") or [None])[0]
        if not named and intent.name in ("job_fit", "compare", "cover_letter"):
            named = ((context.get("match") or {}).get("recommended_jobs") or [None])[0]
        if not isinstance(named, dict) or not named.get("title"):
            return

        job = {
            "id": named.get("id"),
            "title": named.get("title"),
            "company": named.get("company"),
            "match_percentage": named.get("match_percentage"),
            "missing_skills": [
                str(s) for s in (named.get("missing_skills")
                                 or named.get("skills_user_lacks") or [])[:MAX_REMEMBERED_SKILLS]
            ],
        }
        previous = self.focus_job
        if previous and previous.get("id") != job.get("id"):
            # Keeps "compare it with the previous one" answerable.
            self.data["last_compared_job"] = previous
        self.data["focus_job"] = job

    def _remember_topic(self, intent, question):
        if intent.is_conversational:
            return
        topics = [t for t in (self.data.get("topics") or []) if isinstance(t, dict)]
        if topics and topics[-1].get("intent") == intent.name:
            topics[-1]["question"] = (question or "")[:120]
        else:
            topics.append({"intent": intent.name, "question": (question or "")[:120]})
        self.data["topics"] = topics[-MAX_TOPICS:]

    # -- prompt surface -----------------------------------------------------
    def summary(self):
        """One sentence naming what this conversation has been about."""
        labels, seen = [], set()
        for topic in self.data.get("topics") or []:
            label = TOPIC_LABELS.get(topic.get("intent"))
            if label and label not in seen:
                seen.add(label)
                labels.append(label)
        if not labels:
            return ""
        if len(labels) == 1:
            return f"So far this conversation has covered {labels[0]}."
        return (
            "So far this conversation has covered "
            + ", ".join(labels[:-1]) + f" and {labels[-1]}."
        )

    def as_prompt_block(self, include_profile=True):
        """The memory the model is given, as plain readable lines.

        `include_profile` is off in conversation mode: remembered figures are
        real, but repeating a match score at someone who said "thanks" is
        exactly the robotic behaviour this assistant is trying to shed.
        """
        lines = []
        summary = self.summary()
        if summary:
            lines.append(summary)

        known = self.profile
        if include_profile and known:
            identity = " / ".join(
                str(known[key]) for key in ("profession", "specialization") if known.get(key)
            )
            if identity:
                lines.append(f"Established profile: {identity}.")
            if known.get("career_level"):
                lines.append(f"Career level: {known['career_level']}.")
            if known.get("match_score"):
                lines.append(f"Best match score discussed: {known['match_score']}%.")

        if include_profile and self.missing_skills:
            lines.append("Skill gaps already discussed: " + ", ".join(self.missing_skills) + ".")

        job = self.focus_job
        if job:
            described = job["title"]
            if job.get("company"):
                described += f" at {job['company']}"
            if job.get("match_percentage"):
                described += f" ({job['match_percentage']}% match)"
            lines.append(
                f'The job currently in focus - what "it", "this job" and "that role" refer to '
                f"- is {described}."
            )
        previous_job = self.data.get("last_compared_job")
        if include_profile and isinstance(previous_job, dict) and previous_job.get("title"):
            lines.append(
                f"Previously discussed job: {previous_job['title']}"
                + (f" at {previous_job['company']}." if previous_job.get("company") else ".")
            )

        if self.last_user_message:
            lines.append(f'Their previous message: "{_one_line(self.last_user_message)}"')
        if not lines:
            return ""
        return "\n".join(f"- {line}" for line in lines)


def _one_line(text):
    return " ".join((text or "").split())[:200]

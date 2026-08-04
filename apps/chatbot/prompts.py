# file path: apps/chatbot/prompts.py
"""Assembling what the model actually sees.

The assistant's worst answers came from thin prompts. Sent only ``Why?``, a
model has no choice but to answer generically - it cannot know which claim is
being questioned. Sent the same word alongside the score it just explained, the
job in focus and its own previous reply, it answers the real question.

`PromptBuilder` is the one place that decides what goes in, and it builds two
shapes:

* **Conversation.** Persona, what is already known about the exchange, the last
  few turns, and the message. No user record - none was fetched.
* **Career work.** The retrieved data first, then the instruction for this kind
  of question, then memory, history and the question itself.

The career layout keeps the ``USER DATA:`` / ``QUESTION:`` markers the previous
implementation used, so anything reading or asserting on prompt shape still
works.
"""

from .persona import CAREER_SYSTEM_PROMPT, CONVERSATION_SYSTEM_PROMPT

#: Conversation is allowed to be creative; career answers are not. A grounded
#: answer that paraphrases a number is a wrong answer.
CONVERSATION_CONFIG = {
    "temperature": 0.9,
    "top_p": 0.95,
    "max_output_tokens": 512,
}
CAREER_CONFIG = {
    "temperature": 0.35,
    "top_p": 0.9,
    "max_output_tokens": 1024,
}


class PromptBuilder:
    """Builds the system instruction, generation config and prompt for one turn."""

    def __init__(self, question, intent, memory=None, context=None,
                 data_block="", history=""):
        self.question = (question or "").strip()
        self.intent = intent
        self.memory = memory
        self.context = context or {}
        self.data_block = data_block
        self.history = history

    # -- what the model is told it is ---------------------------------------
    @property
    def system_prompt(self):
        if self.intent.is_conversational:
            return CONVERSATION_SYSTEM_PROMPT
        return CAREER_SYSTEM_PROMPT

    @property
    def generation_config(self):
        return dict(CONVERSATION_CONFIG if self.intent.is_conversational else CAREER_CONFIG)

    # -- the prompt ---------------------------------------------------------
    def build(self):
        return (
            self._conversation_prompt() if self.intent.is_conversational
            else self._career_prompt()
        )

    def _career_prompt(self):
        parts = [f"USER DATA:\n{self.data_block}"]

        if self.intent.guidance:
            parts.append(f"FOR THIS QUESTION: {self.intent.guidance}")

        memory_block = self._memory_block(include_profile=True)
        if memory_block:
            parts.append(f"WHAT YOU ALREADY KNOW FROM THIS CONVERSATION:\n{memory_block}")

        if self.history:
            parts.append("CONVERSATION SO FAR:\n" + self.history)

        previous = self._previous_reply_block()
        if previous:
            parts.append(previous)

        parts.append(f"QUESTION: {self.question}")
        return "\n\n".join(parts)

    def _conversation_prompt(self):
        parts = []

        known = self._known_identity()
        if known:
            parts.append(
                "ALREADY KNOWN ABOUT THIS USER (safe to mention naturally, but do not "
                f"turn it into a report):\n{known}"
            )

        memory_block = self._memory_block(include_profile=False)
        if memory_block:
            parts.append(f"WHERE THIS CONVERSATION IS:\n{memory_block}")

        if self.history:
            parts.append("CONVERSATION SO FAR:\n" + self.history)

        previous = self._previous_reply_block()
        if previous:
            parts.append(previous)

        if self.intent.guidance:
            parts.append(f"HOW TO HANDLE THIS MESSAGE: {self.intent.guidance}")

        parts.append(f"THE USER JUST SAID: {self.question}")
        parts.append("Reply as SkillSync AI, in your own words.")
        return "\n\n".join(parts)

    # -- blocks -------------------------------------------------------------
    def _memory_block(self, include_profile):
        if self.memory is None:
            return ""
        return self.memory.as_prompt_block(include_profile=include_profile)

    def _known_identity(self):
        """The light context a conversational turn may have: who they are.

        Only ever their name and stated role - the retrieval layer was told not
        to compute anything analytical for these intents.
        """
        profile = self.context.get("profile") or {}
        cv = self.context.get("cv") or {}
        lines = []
        if profile.get("name"):
            lines.append(f"- Name: {profile['name']}")
        role = cv.get("specialization") or cv.get("profession")
        if role:
            lines.append(f"- Works as / targeting: {role}")
        elif cv and not cv.get("uploaded"):
            lines.append("- They have not uploaded a CV yet, so you know nothing about their background.")
        return "\n".join(lines)

    def _previous_reply_block(self):
        """The last thing said, shown so it is not said again.

        Repetition was the single most robotic-feeling failure: the same opening
        sentence turn after turn. The model cannot avoid a phrase it cannot see.
        """
        previous = self.memory.last_assistant_message if self.memory else ""
        if not previous:
            return ""
        return (
            "YOUR PREVIOUS REPLY (do not repeat its opening or reuse its phrasing):\n"
            + " ".join(previous.split())[:400]
        )

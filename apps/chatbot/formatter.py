# file path: apps/chatbot/formatter.py
"""Cleaning up what the model returns before the user reads it.

Language models leak their own scaffolding: a whole answer wrapped in a code
fence, a reply that starts by quoting itself, "As an AI language model, ...", or
- the one that made this assistant feel most mechanical - the same opening
sentence turn after turn.

None of that is worth a retry, and none of it should reach the user. This module
is the last pass over a reply: it is text-only, it never changes meaning, and it
never fails - an unexpected input is returned as it arrived.
"""

import re

#: Model self-references that add nothing and break the persona.
_DISCLAIMERS = re.compile(
    r"^\s*(as an? (ai|artificial intelligence)( language model| assistant)?[,:]?\s*"
    r"|i'?m an? (ai|artificial intelligence)( language model| assistant)?[,.]?\s*"
    r"|note[:]\s*i (am|'m) an ai[^.]*\.\s*)",
    re.I,
)

#: A whole reply fenced as code, which some models do when asked to "write" text.
_WRAPPING_FENCE = re.compile(r"\A```[a-zA-Z]*\s*\n(?P<body>.*?)\n?```\s*\Z", re.S)

#: Labels a model sometimes prefixes to its own turn.
_SPEAKER_PREFIX = re.compile(r"\A(assistant|skillsync ai|ai|reply|response)\s*:\s*", re.I)

#: Longest opening sentence still worth de-duplicating. Beyond this it is
#: content, not a greeting formula, and removing it would lose meaning.
MAX_DEDUPED_OPENING = 160


def polish(reply, previous_reply=""):
    """Return `reply` cleaned up, or the original text if anything is unexpected."""
    if not isinstance(reply, str):
        return reply
    try:
        text = reply.strip()
        if not text:
            return ""

        fenced = _WRAPPING_FENCE.match(text)
        if fenced:
            text = fenced.group("body").strip()

        text = _strip_wrapping_quotes(text)
        text = _SPEAKER_PREFIX.sub("", text, count=1)
        text = _DISCLAIMERS.sub("", text, count=1)
        text = _drop_repeated_opening(text, previous_reply)

        # Blank lines beyond one are formatting noise in a chat bubble.
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()
    except Exception:  # pragma: no cover - polishing must never lose an answer
        return reply


def _strip_wrapping_quotes(text):
    """Unwrap a reply the model quoted in its entirety."""
    pairs = (('"', '"'), ("'", "'"), ("“", "”"))
    for opening, closing in pairs:
        if text.startswith(opening) and text.endswith(closing) and len(text) > 2:
            inner = text[1:-1]
            # Only unwrap when the quotes really are a wrapper, not part of the
            # text - a reply containing its own quotation keeps them.
            if opening not in inner and closing not in inner:
                return inner.strip()
    return text


def _drop_repeated_opening(text, previous_reply):
    """Remove an opening sentence identical to the previous reply's opening."""
    if not previous_reply:
        return text

    opening, rest = _split_opening(text)
    if not rest or len(opening) > MAX_DEDUPED_OPENING:
        return text

    previous_opening, _ = _split_opening(previous_reply)
    if _normalise(opening) and _normalise(opening) == _normalise(previous_opening):
        return rest.lstrip()
    return text


def _split_opening(text):
    """Split off the first sentence. Returns ``(opening, remainder)``."""
    match = re.match(r"\s*(.+?[.!?])(\s+)(.*)", text or "", re.S)
    if match:
        return match.group(1).strip(), match.group(3)
    return (text or "").strip(), ""


def _normalise(text):
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()

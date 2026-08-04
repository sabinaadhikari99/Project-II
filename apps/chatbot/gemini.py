# file path: apps/chatbot/gemini.py
"""One place that knows how to build a Gemini model.

`google-generativeai` is pinned at 0.3.2, whose `GenerativeModel.__init__` has
no `system_instruction` parameter - it was added in a later release. Passing it
raises `TypeError`, and because every caller wraps generation in a broad
`except Exception`, the failure surfaced as "model unavailable" and the answer
silently fell back to the deterministic path. Every AI feature looked like it
was working while never actually reaching Gemini.

`build_model` handles both shapes: it passes `system_instruction` when the
installed library accepts it, and otherwise reports that the caller must
prepend the instruction to the prompt itself. That keeps the feature working on
the pinned version without blocking an upgrade later.
"""

import inspect
import logging

logger = logging.getLogger(__name__)

#: Cached because `inspect.signature` on every request is pointless work.
_SUPPORTS_SYSTEM_INSTRUCTION = None


def supports_system_instruction(model_cls):
    global _SUPPORTS_SYSTEM_INSTRUCTION
    if _SUPPORTS_SYSTEM_INSTRUCTION is None:
        try:
            _SUPPORTS_SYSTEM_INSTRUCTION = (
                "system_instruction" in inspect.signature(model_cls.__init__).parameters
            )
        except (TypeError, ValueError):
            _SUPPORTS_SYSTEM_INSTRUCTION = False
    return _SUPPORTS_SYSTEM_INSTRUCTION


def build_model(genai, model_name, generation_config, system_instruction=None):
    """Return ``(model, prompt_prefix)``.

    `prompt_prefix` is the system instruction the caller still has to prepend
    because the installed library could not take it as a parameter. It is an
    empty string when the model already carries the instruction.
    """
    kwargs = {"model_name": model_name, "generation_config": generation_config}

    if system_instruction and supports_system_instruction(genai.GenerativeModel):
        return genai.GenerativeModel(system_instruction=system_instruction, **kwargs), ""

    model = genai.GenerativeModel(**kwargs)
    return model, (f"{system_instruction}\n\n" if system_instruction else "")

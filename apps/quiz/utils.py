import json
import re

import google.generativeai as genai
from django.conf import settings

from apps.shared.performance import PerformanceTimer

try:
    from google.api_core import exceptions as google_api_exceptions
except ImportError:  # pragma: no cover - google-api-core always ships with
    google_api_exceptions = None  # the generativeai SDK, but stay defensive.


genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={
        "temperature": 0.4,
        "top_p": 0.95,
        # 10 questions, each with a full question string, 4 options, an
        # answer and a difficulty tag, genuinely needs more than 2048 tokens
        # once questions are CV-specific and reasonably detailed - 2048 was
        # cutting Gemini off mid-object, producing truncated/invalid JSON
        # that looked like a formatting bug but was actually a hard token
        # limit. 8192 gives enough headroom without being wasteful.
        "max_output_tokens": 8192,
        # NOTE: response_mime_type="application/json" was tried here but
        # removed - it requires a newer google-generativeai SDK version than
        # may be installed, and an unsupported generation_config key can make
        # EVERY call fail with a generic, hard-to-classify error. clean_json()
        # below already strips markdown fences reliably without needing it.
    },
)

# Fail fast instead of hanging the request (and the user's loading spinner)
# if Gemini is slow to respond.
GEMINI_TIMEOUT_SECONDS = 20


class QuizGenerationError(Exception):
    """Raised when Gemini fails to produce a usable quiz.

    Carries a machine-readable `code` (for the API/frontend to branch on)
    and a `user_message` safe to show directly to the person using the app —
    keep this free of internal details (stack traces, API key hints, etc).
    """

    def __init__(self, message, code="GENERATION_FAILED", user_message=None):
        super().__init__(message)
        self.code = code
        self.user_message = user_message or (
            "We couldn't generate your quiz right now. Please try again in a moment."
        )


def clean_json(text: str):
    text = text.strip()
    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Older SDKs (no forced JSON mode) sometimes wrap the array in
        # conversational text, e.g. "Here is the quiz:\n\n[...]\n\nEnjoy!".
        # Extract the first '[' through the LAST ']' and try again before
        # giving up - this recovers the common case without masking a
        # genuinely broken/truncated response.
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            return json.loads(candidate)
        raise


REQUIRED_DIFFICULTY_COUNTS = {"easy": 4, "medium": 3, "hard": 3}
_DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}
_TARGET_LABELS = ["easy"] * 4 + ["medium"] * 3 + ["hard"] * 3


def _validate_questions(questions) -> None:
    """Make sure what Gemini returned actually looks like a quiz.

    This checks structural correctness only (right count, 4 options each,
    answer present, id/question present). It deliberately does NOT require
    Gemini to have produced an exact easy/medium/hard split — LLMs are
    unreliable at hitting an exact count, and rejecting the whole quiz over
    that was causing repeated failures (and repeated multi-second Gemini
    calls while retrying). The difficulty split is instead enforced
    afterwards by _normalize_difficulty(), which is fast and deterministic.
    """
    if not isinstance(questions, list) or not questions:
        raise QuizGenerationError(
            "Gemini returned invalid or empty JSON.",
            code="GENERATION_INVALID",
            user_message=(
                "The quiz generator returned an empty response. Please try again."
            ),
        )

    if len(questions) != 10:
        raise QuizGenerationError(
            f"Expected 10 questions, got {len(questions)}.",
            code="GENERATION_INVALID",
            user_message=(
                f"The quiz generator returned {len(questions)} question(s) instead "
                f"of 10. Please try again — it usually works on a retry."
            ),
        )

    for q in questions:
        if not isinstance(q, dict):
            raise QuizGenerationError(
                "Gemini returned a malformed question.",
                code="GENERATION_INVALID",
                user_message="One of the generated questions was malformed. Please try again.",
            )
        if "id" not in q or "question" not in q or "answer" not in q:
            raise QuizGenerationError(
                "Gemini question is missing required fields.",
                code="GENERATION_INVALID",
                user_message="A generated question was missing required data. Please try again.",
            )

        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4:
            got = len(options) if isinstance(options, list) else "none"
            raise QuizGenerationError(
                "Gemini question does not have exactly 4 options.",
                code="GENERATION_INVALID",
                user_message=(
                    f"A generated question had {got} answer option(s) instead of 4. "
                    f"Please try again."
                ),
            )
        if q["answer"] not in options:
            raise QuizGenerationError(
                "Gemini answer is not among its own options.",
                code="GENERATION_INVALID",
                user_message=(
                    "A generated question's answer didn't match its own options. "
                    "Please try again."
                ),
            )


def _normalize_difficulty(questions: list) -> list:
    """Force an exact 4 easy / 3 medium / 3 hard split.

    Uses Gemini's own difficulty tags (or "medium" as a default for any
    question missing one) purely as a relative ranking — questions it called
    "easier" get priority for the "easy" bucket, and so on — then reassigns
    labels so the final counts always match REQUIRED_DIFFICULTY_COUNTS
    exactly. Original question order (and ids) is left untouched; only the
    "difficulty" field changes.
    """
    def rank(q):
        raw = str(q.get("difficulty", "medium")).strip().lower()
        return _DIFFICULTY_RANK.get(raw, 1)

    # Stable sort: ties keep their original relative order.
    order_by_rank = sorted(range(len(questions)), key=lambda i: rank(questions[i]))

    for target_label, idx in zip(_TARGET_LABELS, order_by_rank):
        questions[idx]["difficulty"] = target_label

    return questions


def _generate_quiz_attempt(resume_text: str):
    """A single attempt to generate a 10-question quiz via Gemini.

    Raises QuizGenerationError (or lets the underlying Gemini/JSON error
    propagate) on any failure — callers are responsible for deciding what
    to do next (e.g. fall back to a cached quiz, or return a 503). This
    function never returns a fabricated placeholder quiz, because that
    placeholder would otherwise get cached and persisted as if it were a
    real, valid quiz.
    """
    timer = PerformanceTimer("generate_quiz_from_resume")

    prompt = f"""
You are an expert technical interviewer.

Read the following resume carefully.

Resume:

{resume_text}

Generate EXACTLY 10 interview multiple-choice questions.

Rules:

1. Questions MUST ONLY be about technologies mentioned in the resume.

2. Ask about:
   - Programming languages
   - Frameworks
   - Libraries
   - Databases
   - Projects
   - APIs
   - Tools
   - Cloud
   - Git
   - Software engineering concepts

3. Aim for a mix of difficulty: roughly 4 easier questions, 3 medium
   questions, and 3 harder questions. This does not need to be exact.
   Easy = basic recall/definition level. Medium = applied understanding.
   Hard = deeper reasoning, trade-offs, or edge cases.

4. Each question must contain exactly FOUR options.

5. Only ONE option must be correct.

6. Every question object MUST include a "difficulty" field set to exactly
   one of: "easy", "medium", "hard" (lowercase) — your best judgment of
   that question's difficulty.

7. Return ONLY a JSON array. No markdown, no explanations, no commentary.

8. The output MUST be syntactically valid JSON: every array/object element
   except the last must be followed by a comma, and no element may have a
   trailing comma. Double-check the JSON is valid before responding.

Format:

[
  {{
    "id": 1,
    "question": "Which framework is used to build REST APIs in this resume?",
    "difficulty": "easy",
    "options": [
      "Django REST Framework",
      "Laravel",
      "Spring Boot",
      "Express"
    ],
    "answer": "Django REST Framework"
  }}
]
"""

    try:
        with timer.measure("Gemini API — generate_content"):
            try:
                response = model.generate_content(
                    prompt,
                    request_options={"timeout": GEMINI_TIMEOUT_SECONDS},
                )
            except (TypeError, ValueError) as compat_err:
                # Older google-generativeai versions (e.g. 0.3.x) reject
                # request_options entirely - some raise TypeError, others
                # raise ValueError("Unknown field for GenerateContentRequest:
                # request_options"). Either way, fall back to a plain call
                # rather than letting an unsupported kwarg break every single
                # generation. Only swallow errors that are actually about
                # this specific incompatibility, so a genuine bad prompt/
                # response ValueError still surfaces normally.
                if "request_options" not in str(compat_err):
                    raise
                response = model.generate_content(prompt)

        # Detect truncation explicitly: if Gemini stopped because it hit
        # max_output_tokens, response.text will be incomplete JSON and the
        # parse error below would otherwise look like a random formatting
        # bug instead of what it actually is - the response got cut off.
        try:
            finish_reason = response.candidates[0].finish_reason
        except Exception:
            finish_reason = None
        # finish_reason 2 (or the string "MAX_TOKENS") means truncated.
        if finish_reason == 2 or str(finish_reason).upper().endswith("MAX_TOKENS"):
            print(
                "Gemini Quiz Error: response was TRUNCATED (hit max_output_tokens). "
                f"finish_reason={finish_reason!r}. Raw response length="
                f"{len(response.text or '')} chars."
            )
            raise QuizGenerationError(
                "Gemini response was truncated by max_output_tokens.",
                code="GENERATION_INVALID",
                user_message=(
                    "Your quiz came back incomplete. Please try again — "
                    "it usually works on a retry."
                ),
            )

        with timer.measure("Parse JSON response"):
            try:
                questions = clean_json(response.text)
            except (json.JSONDecodeError, ValueError) as e:
                print("Gemini Quiz Error: could not parse response as JSON.")
                print("Raw Gemini response (first 1500 chars):")
                print(repr((response.text or "")[:1500]))
                raise QuizGenerationError(
                    f"Could not parse Gemini's response as JSON: {e}",
                    code="GENERATION_INVALID",
                    user_message=(
                        "Your quiz came back in an unexpected format. "
                        "Please try again — it usually works on a retry."
                    ),
                ) from e

        try:
            _validate_questions(questions)
        except QuizGenerationError as e:
            print(f"Gemini Quiz Error: validation failed - {e}")
            print("Parsed questions (first 1500 chars):")
            print(repr(str(questions)[:1500]))
            raise

        with timer.measure("Normalize difficulty split"):
            questions = _normalize_difficulty(questions)

        timer.flush("generate_quiz_from_resume (success)")
        return questions

    except QuizGenerationError as exc:
        print(f"Gemini Quiz Error (validation): code={exc.code} detail={exc}")
        # Also show what Gemini actually sent back, truncated, so a shape
        # mismatch (missing field, wrong option count, etc.) is visible
        # instead of just "it failed".
        raw_preview = ""
        try:
            raw_preview = (getattr(response, "text", "") or "")[:1500]
        except Exception:
            pass
        if raw_preview:
            print(f"Gemini raw response (first 1500 chars):\n{raw_preview}")
        timer.flush("generate_quiz_from_resume (validation failed)")
        raise

    except Exception as e:
        print("Gemini Quiz Error:", type(e).__name__, e)
        timer.flush("generate_quiz_from_resume (error)")

        # Classify the underlying failure so the person sees a message that
        # actually matches what went wrong, instead of one generic string
        # for every possible cause.
        if google_api_exceptions is not None:
            if isinstance(e, google_api_exceptions.DeadlineExceeded):
                raise QuizGenerationError(
                    str(e),
                    code="GENERATION_TIMEOUT",
                    user_message=(
                        "Quiz generation is taking longer than expected. "
                        "Please try again in a moment."
                    ),
                ) from e

            if isinstance(e, google_api_exceptions.ResourceExhausted):
                raise QuizGenerationError(
                    str(e),
                    code="GENERATION_BUSY",
                    user_message=(
                        "Our AI quiz service is experiencing high demand right now. "
                        "Please try again shortly."
                    ),
                ) from e

            if isinstance(e, (
                google_api_exceptions.Unauthenticated,
                google_api_exceptions.PermissionDenied,
            )):
                # This means the server's own Gemini credentials are broken —
                # never the user's fault, and there's nothing they can do
                # about it by retrying. Keep the message honest but generic;
                # the specifics belong in the server log line above.
                raise QuizGenerationError(
                    str(e),
                    code="GENERATION_CONFIG_ERROR",
                    user_message=(
                        "Quiz generation is temporarily unavailable. "
                        "Our team has been notified — please try again later."
                    ),
                ) from e

            if isinstance(e, google_api_exceptions.InvalidArgument):
                raise QuizGenerationError(
                    str(e),
                    code="GENERATION_INVALID",
                    user_message=(
                        "We couldn't process your resume for quiz generation. "
                        "Try re-uploading your CV."
                    ),
                ) from e

            if isinstance(e, google_api_exceptions.GoogleAPICallError):
                raise QuizGenerationError(
                    str(e),
                    code="GENERATION_UPSTREAM_ERROR",
                    user_message=(
                        "The quiz service is temporarily unavailable. "
                        "Please try again in a moment."
                    ),
                ) from e

        # Anything else we didn't specifically recognize (network hiccup,
        # unexpected SDK error, etc).
        raise QuizGenerationError(
            f"Gemini quiz generation failed: {e}",
            code="GENERATION_FAILED",
        ) from e


#: Error codes worth retrying automatically. GENERATION_INVALID covers
#: malformed/truncated JSON from the model - a probabilistic quirk of
#: running without forced JSON mode (see model config above), not a
#: systemic problem, so a second attempt often just works. Codes NOT in
#: this set (bad credentials, quota exhausted, timeout, upstream outage)
#: would very likely fail identically again, so retrying them would only
#: waste time and make the user wait longer for the same error.
_RETRYABLE_CODES = {"GENERATION_INVALID"}

#: Total attempts including the first. 3 attempts against an occasional
#: malformed-JSON quirk pushes the effective failure rate down sharply
#: without making a genuinely broken setup (bad key, etc.) retry pointlessly.
MAX_GENERATION_ATTEMPTS = 3


def generate_quiz_from_resume(resume_text: str):
    """Generate a 10-question quiz, retrying automatically on transient,
    format-only failures so the person doesn't have to click "Try again"
    themselves for something that often succeeds on a second attempt.
    """
    last_error = None
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            return _generate_quiz_attempt(resume_text)
        except QuizGenerationError as exc:
            last_error = exc
            if exc.code not in _RETRYABLE_CODES or attempt == MAX_GENERATION_ATTEMPTS:
                raise
            print(
                f"Gemini Quiz: attempt {attempt}/{MAX_GENERATION_ATTEMPTS} "
                f"failed with retryable code={exc.code}, retrying..."
            )
    # Unreachable in practice (the loop always returns or raises), but keeps
    # the function's contract explicit if MAX_GENERATION_ATTEMPTS is ever 0.
    raise last_error
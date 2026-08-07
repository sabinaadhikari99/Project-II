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
        "max_output_tokens": 2048,
        # Structured output: Gemini returns raw JSON, no markdown fences to
        # strip and far fewer malformed-JSON failures than free-text mode.
        "response_mime_type": "application/json",
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
    return json.loads(text)


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
        )

    if len(questions) != 10:
        raise QuizGenerationError(
            f"Expected 10 questions, got {len(questions)}.",
            code="GENERATION_INVALID",
        )

    for q in questions:
        if not isinstance(q, dict):
            raise QuizGenerationError(
                "Gemini returned a malformed question.",
                code="GENERATION_INVALID",
            )
        if "id" not in q or "question" not in q or "answer" not in q:
            raise QuizGenerationError(
                "Gemini question is missing required fields.",
                code="GENERATION_INVALID",
            )

        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4:
            raise QuizGenerationError(
                "Gemini question does not have exactly 4 options.",
                code="GENERATION_INVALID",
            )
        if q["answer"] not in options:
            raise QuizGenerationError(
                "Gemini answer is not among its own options.",
                code="GENERATION_INVALID",
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


def generate_quiz_from_resume(resume_text: str):
    """Generate a 10-question quiz from resume text via Gemini.

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
            response = model.generate_content(
                prompt,
                request_options={"timeout": GEMINI_TIMEOUT_SECONDS},
            )

        with timer.measure("Parse JSON response"):
            try:
                questions = clean_json(response.text)
            except (json.JSONDecodeError, ValueError) as e:
                raise QuizGenerationError(
                    f"Could not parse Gemini's response as JSON: {e}",
                    code="GENERATION_INVALID",
                    user_message=(
                        "Your quiz came back in an unexpected format. "
                        "Please try again — it usually works on a retry."
                    ),
                ) from e

        _validate_questions(questions)

        with timer.measure("Normalize difficulty split"):
            questions = _normalize_difficulty(questions)

        timer.flush("generate_quiz_from_resume (success)")
        return questions

    except QuizGenerationError:
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
import time

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.shared.fingerprint import profile_resume_fingerprint
from apps.shared.permissions import IsJobSeeker
from apps.shared.performance import PerformanceTimer
from apps.state.models import QuizSession
from apps.state.services import QuizSessionService
from .cache import get_cached_quiz, quiz_cache_key, set_cached_quiz
from .utils import generate_quiz_from_resume


class QuizAPIView(APIView):
    """Return the user's quiz, resuming the stored one whenever possible.

    Questions used to live only in ``request.session``: a refresh mid-quiz lost
    every answer, and a finished quiz could never be reviewed again. The quiz is
    now a persisted session tied to the CV it was generated from, so it resumes
    across navigation, refresh and re-login, and is only replaced when the user
    asks for a new one (``?refresh=1``) or uploads a different CV.
    """

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def get(self, request):
        timer = PerformanceTimer("QuizAPIView — GET")

        timer.reset_queries()

        with timer.measure("Fetch profile"):
            profile = getattr(request.user, "profile", None)

        timer.count_queries("Profile query")

        if profile is None:
            return Response(
                {"error": "Profile not found."},
                status=400
            )

        resume_text = profile.resume_text or ""

        if not resume_text.strip():
            return Response(
                {"error": "Please upload and analyze your CV first."},
                status=400
            )

        force = request.query_params.get("refresh") == "1"
        fingerprint = profile_resume_fingerprint(request.user)

        # Restore completed or in-progress work before generating anything.
        if not force:
            with timer.measure("Restore persisted quiz"):
                restored = QuizSessionService.restore(request.user, fingerprint)
            if restored is not None:
                timer.flush("Quiz: QuizAPIView (restored)")
                return Response(restored)

        cache_key = quiz_cache_key(request.user.id, resume_text)

        cache_start = time.perf_counter()
        questions = None if force else get_cached_quiz(cache_key)
        cache_elapsed = time.perf_counter() - cache_start
        cache_hit = questions is not None
        timer.log_cache("Cache Lookup", cache_elapsed, cache_hit)

        if not cache_hit:
            with timer.measure("Quiz Generation (Gemini AI)"):
                try:
                    questions = generate_quiz_from_resume(resume_text)
                except Exception:
                    questions = get_cached_quiz(cache_key)
                    if questions is None:
                        raise

            with timer.measure("Cache Save"):
                set_cached_quiz(cache_key, questions)

        with timer.measure("Persist quiz session"):
            QuizSessionService.start(request.user, questions, fingerprint)

        with timer.measure("Session save"):
            # Kept for backward compatibility with any client still relying on
            # the cookie session to submit.
            request.session["quiz_questions"] = questions
            request.session.modified = True

        with timer.measure("Build public questions"):
            public_questions = QuizSessionService.public_questions(questions)

        with timer.measure("Response serialization"):
            response = Response({
                "questions": public_questions,
                "answers": {},
                "status": QuizSession.STATUS_IN_PROGRESS,
                "restored": False,
            })

        timer.flush("Quiz: QuizAPIView")
        return response


class QuizProgressAPIView(APIView):
    """Autosave partial answers so leaving the page never costs progress."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        answers = request.data.get("answers", {})
        if not isinstance(answers, dict):
            return Response({"error": "answers must be an object."}, status=400)

        session = QuizSessionService.save_answers(request.user, answers)
        if session is None:
            return Response({"error": "No active quiz to save."}, status=400)

        return Response({
            "saved": True,
            "answered": len(session.answers or {}),
            "total": session.total,
            "status": session.status,
        })


class QuizResetAPIView(APIView):
    """Explicitly discard the stored quiz. The next GET generates a new one."""

    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        QuizSessionService.reset(request.user)
        request.session.pop("quiz_questions", None)
        request.session.modified = True
        return Response({"reset": True})


class QuizSubmitAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        timer = PerformanceTimer("QuizSubmitAPIView — POST")

        with timer.measure("Parse request data"):
            answers = request.data.get("answers", {})

        with timer.measure("Read persisted quiz"):
            session = QuizSessionService.get(request.user)
            questions = session.questions if session else None

        if not questions:
            with timer.measure("Read session"):
                questions = request.session.get("quiz_questions")

        if not questions:
            return Response(
                {"error": "Quiz expired. Please generate the quiz again."},
                status=400,
            )

        with timer.measure("Score calculation"):
            total = len(questions)
            correct = 0
            results = []

            for q in questions:
                user_answer = answers.get(str(q["id"]))
                is_correct = user_answer == q["answer"]

                if is_correct:
                    correct += 1

                results.append({
                    "question": q["question"],
                    "your_answer": user_answer,
                    "correct_answer": q["answer"],
                    "correct": is_correct,
                })

        percentage = round((correct / total) * 100, 2) if total else 0

        with timer.measure("Persist result"):
            # The completed quiz is kept, not discarded: the score and the
            # per-question review stay available until the user starts a new one.
            QuizSessionService.complete(
                request.user, answers, correct, total, percentage, results,
            )

        with timer.measure("Clear session"):
            request.session.pop("quiz_questions", None)
            request.session.modified = True

        with timer.measure("Build response"):
            response = Response({
                "score": correct,
                "total": total,
                "percentage": percentage,
                "results": results,
            })

        timer.flush("Quiz: QuizSubmitAPIView")
        return response

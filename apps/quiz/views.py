import time

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.shared.permissions import IsJobSeeker
from apps.shared.performance import PerformanceTimer
from .cache import get_cached_quiz, quiz_cache_key, set_cached_quiz
from .utils import generate_quiz_from_resume


class QuizAPIView(APIView):
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

        cache_key = quiz_cache_key(request.user.id, resume_text)

        cache_start = time.perf_counter()
        questions = get_cached_quiz(cache_key)
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

        with timer.measure("Session save"):
            request.session["quiz_questions"] = questions
            request.session.modified = True

        with timer.measure("Build public questions"):
            public_questions = [
                {
                    "id": q["id"],
                    "question": q["question"],
                    "options": q["options"],
                }
                for q in questions
            ]

        with timer.measure("Response serialization"):
            response = Response({"questions": public_questions})

        timer.flush("Quiz: QuizAPIView")
        return response


class QuizSubmitAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        timer = PerformanceTimer("QuizSubmitAPIView — POST")

        with timer.measure("Parse request data"):
            answers = request.data.get("answers", {})

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

        with timer.measure("Clear session"):
            request.session.pop("quiz_questions", None)
            request.session.modified = True

        with timer.measure("Build response"):
            response = Response({
                "score": correct,
                "total": total,
                "percentage": round((correct / total) * 100, 2) if total else 0,
                "results": results,
            })

        timer.flush("Quiz: QuizSubmitAPIView")
        return response

# file path: apps/quiz/views.py

from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.shared.permissions import IsJobSeeker
from .utils import generate_quiz_from_resume


class QuizAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def get(self, request):
        print("\n========== QUIZ DEBUG ==========")
        print("Authorization:", request.headers.get("Authorization"))
        print("User:", request.user)
        print("Authenticated:", request.user.is_authenticated)
        print("Role:", getattr(request.user, "role", None))
        print("================================\n")

        profile = getattr(request.user, "profile", None)

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

        questions = generate_quiz_from_resume(resume_text)

        request.session["quiz_questions"] = questions
        request.session.modified = True

        public_questions = [
            {
                "id": q["id"],
                "question": q["question"],
                "options": q["options"],
            }
            for q in questions
        ]

        return Response({"questions": public_questions})


class QuizSubmitAPIView(APIView):
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated, IsJobSeeker]

    def post(self, request):
        answers = request.data.get("answers", {})
        questions = request.session.get("quiz_questions")

        if not questions:
            return Response(
                {"error": "Quiz expired. Please generate the quiz again."},
                status=400,
            )

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

        request.session.pop("quiz_questions", None)
        request.session.modified = True

        return Response({
            "score": correct,
            "total": total,
            "percentage": round((correct / total) * 100, 2) if total else 0,
            "results": results,
        })
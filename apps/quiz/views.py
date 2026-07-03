# file path: apps/quiz/views.py

from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker
from .utils import generate_quiz_from_resume


class QuizAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):

        profile = request.user.profile

        resume_text = profile.resume_text

        if not resume_text.strip():

            return Response(
                {
                    "error": "Please upload and analyze your CV first."
                },
                status=400,
            )

        questions = generate_quiz_from_resume(resume_text)

        # Store questions in session
        request.session["quiz_questions"] = questions
        request.session.modified = True

        public_questions = []

        for q in questions:

            public_questions.append(
                {
                    "id": q["id"],
                    "question": q["question"],
                    "options": q["options"],
                }
            )

        return Response(
            {
                "questions": public_questions
            }
        )


class QuizSubmitAPIView(APIView):

    permission_classes = [IsJobSeeker]

    def post(self, request):

        answers = request.data.get("answers", {})

        questions = request.session.get("quiz_questions")

        if not questions:

            return Response(
                {
                    "error": "Quiz expired. Please generate the quiz again."
                },
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

            results.append(
                {
                    "question": q["question"],
                    "your_answer": user_answer,
                    "correct_answer": q["answer"],
                    "correct": is_correct,
                }
            )

        percentage = round((correct / total) * 100, 2) if total else 0

        # Remove quiz after submission
        request.session.pop("quiz_questions", None)
        request.session.modified = True

        return Response(
            {
                "score": correct,
                "total": total,
                "percentage": percentage,
                "results": results,
            }
        )
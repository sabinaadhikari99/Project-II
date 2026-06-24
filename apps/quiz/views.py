# file path: apps/quiz/views.py

import json

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker


def load_questions():
    path = settings.DATA_DIR / "quiz_questions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


class QuizAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        questions = load_questions()

        public = [
            {k: v for k, v in item.items() if k != "answer"}
            for item in questions
        ]

        return Response({"questions": public})


class QuizSubmitAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request):
        answers = request.data.get("answers", {})
        questions = load_questions()

        total = len(questions)

        correct = sum(
            1
            for item in questions
            if answers.get(str(item["id"])) == item["answer"]
        )

        return Response({
            "score": correct,
            "total": total,
            "percentage": round((correct / total) * 100, 2) if total else 0,
        })
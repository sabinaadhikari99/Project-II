# file path: apps/chatbot/views.py
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker

from .services import career_chat, interview_questions


class ChatbotAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request):
        return Response({"reply": career_chat(request.data.get("message", ""))})


class InterviewAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def post(self, request):
        return Response({"questions": interview_questions(request.data.get("role", ""))})

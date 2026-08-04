# file path: apps/chatbot/views.py
"""AI Career Assistant API.

    POST /api/chatbot/              say anything (returns `reply`, as before)
    GET  /api/chatbot/history/      the active conversation, for restore
    POST /api/chatbot/new/          archive the thread and start a fresh one
    GET  /api/chatbot/suggestions/  personalised opening prompts
    POST /api/chatbot/interview/    flat question list (unchanged legacy contract)

Interview practice:

    GET  /api/chatbot/interview/session/     restore the live session, no AI call
    POST /api/chatbot/interview/session/     generate or regenerate a session
    POST /api/chatbot/interview/answer/      submit an answer, get it graded
    POST /api/chatbot/interview/complete/    finish and produce the report
    POST /api/chatbot/interview/reset/       clear answers, keep the questions
    GET  /api/chatbot/interview/readiness/   readiness score on its own
    GET  /api/chatbot/interview/sessions/    history
    GET  /api/chatbot/interview/sessions/<id>/  a past session and its report
"""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.shared.permissions import IsJobSeeker

from .interview import (
    DURATION_CHOICES,
    MAX_QUESTIONS,
    MIN_QUESTIONS,
    QUESTION_TARGET,
    InterviewService,
)
from .models import InterviewSession
from .role_profiles import CATEGORY_LABELS, LEVEL_LABELS, available_categories, match_profile
from .serializers import (
    ChatMessageSerializer,
    InterviewReportSerializer,
    InterviewSessionSerializer,
    InterviewSessionSummarySerializer,
    InterviewTurnSerializer,
)
from .services import (
    active_conversation,
    ask,
    interview_questions,
    start_new_conversation,
    starter_suggestions,
)

#: How much of a thread the client restores on load.
HISTORY_LIMIT = 60


class ChatbotAPIView(APIView):
    """Send the assistant a message - a question or just conversation.

    The `reply` field and everything alongside it is unchanged for existing
    clients. `mode` and `intent` are additive: they say whether the message was
    handled as conversation or as career work, which is what makes the split
    observable in production rather than something to take on trust.
    """

    permission_classes = [IsJobSeeker]

    def post(self, request):
        result = ask(request.user, request.data.get("message", ""))
        return Response({
            "reply": result["reply"],
            "suggestions": result["suggestions"],
            "conversation_id": result.get("conversation_id"),
            "message_id": result.get("message_id"),
            "created_at": result.get("created_at"),
            # Which parts of the user's record grounded the answer - useful for
            # support, and for showing "based on your CV and skill gap". A
            # conversational turn reads nothing, so this is empty by design.
            "context_used": result["context_used"],
            "is_ai_generated": result["is_ai_generated"],
            # How the message was handled: "conversation" or "career", and the
            # intent within it. Additive - existing clients can ignore both.
            "mode": result.get("mode", ""),
            "intent": result.get("intent", ""),
        })


class ChatHistoryAPIView(APIView):
    """The live conversation, so a refresh or a new session resumes it."""

    permission_classes = [IsJobSeeker]

    def get(self, request):
        conversation = active_conversation(request.user, create=False)
        if conversation is None:
            return Response({
                "conversation_id": None,
                "messages": [],
                "suggestions": list(starter_suggestions(request.user)),
            })

        messages = conversation.messages.order_by("-created_at", "-id")[:HISTORY_LIMIT]
        ordered = list(messages)[::-1]
        last = ordered[-1] if ordered else None
        return Response({
            "conversation_id": conversation.id,
            "title": conversation.title,
            "messages": ChatMessageSerializer(ordered, many=True).data,
            "suggestions": (
                last.suggestions if last and last.suggestions
                else list(starter_suggestions(request.user))
            ),
        })


class NewConversationAPIView(APIView):
    """Start a new thread. The previous one is archived, never deleted."""

    permission_classes = [IsJobSeeker]

    def post(self, request):
        conversation = start_new_conversation(request.user)
        return Response({
            "conversation_id": conversation.id,
            "messages": [],
            "suggestions": list(starter_suggestions(request.user)),
        })


class ChatSuggestionsAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        return Response({"suggestions": list(starter_suggestions(request.user))})


class InterviewAPIView(APIView):
    """Legacy flat question list. Unchanged so the chat page keeps working."""

    permission_classes = [IsJobSeeker]

    def post(self, request):
        questions = interview_questions(request.data.get("role", ""), user=request.user)
        return Response({"questions": questions})


# ---------------------------------------------------------------------------
# Interview practice
# ---------------------------------------------------------------------------
class InterviewSessionAPIView(APIView):
    """Restore (GET) or generate (POST) the live interview session.

    GET never calls the AI - that is what makes returning to the page free.
    POST only regenerates when the role changed, the CV changed, or the client
    asked for a new interview explicitly.
    """

    permission_classes = [IsJobSeeker]

    def get(self, request):
        session = InterviewService.active(request.user)
        if session is None:
            return Response({
                "has_session": False,
                "session": None,
                "readiness": InterviewService.readiness(request.user),
                "options": _interview_options(request.user, ""),
            })
        return Response({
            "has_session": True,
            "session": InterviewSessionSerializer(session).data,
            "readiness": InterviewService.readiness(request.user),
            "options": _interview_options(request.user, session.target_role),
        })

    def post(self, request):
        difficulty = request.data.get("difficulty") or InterviewSession.LEVEL_MIXED
        if difficulty not in dict(InterviewSession.LEVEL_CHOICES):
            return Response(
                {"detail": f"Unsupported difficulty: {difficulty}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        interview_type = request.data.get("interview_type") or InterviewSession.TYPE_MIXED
        if interview_type not in dict(InterviewSession.TYPE_CHOICES):
            return Response(
                {"detail": f"Unsupported interview type: {interview_type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        categories = request.data.get("categories") or None
        if categories is not None and not isinstance(categories, list):
            return Response({"detail": "categories must be a list."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Count and duration are clamped rather than rejected: a slider that
        # 400s is worse than one that quietly lands on the nearest legal value.
        session, generated = InterviewService.get_or_create_session(
            request.user,
            request.data.get("role", ""),
            difficulty=difficulty,
            interview_type=interview_type,
            question_count=request.data.get("question_count", QUESTION_TARGET),
            duration_minutes=request.data.get("duration_minutes", 0),
            categories=categories,
            force_new=bool(request.data.get("force_new")),
        )
        return Response({
            "has_session": True,
            "generated": generated,
            "session": InterviewSessionSerializer(session).data,
            "readiness": InterviewService.readiness(request.user),
            "options": _interview_options(request.user, session.target_role),
        })


class InterviewAnswerAPIView(APIView):
    """Submit one answer and receive its evaluation, then the next question."""

    permission_classes = [IsJobSeeker]

    def post(self, request):
        session = InterviewService.active(request.user)
        if session is None:
            return Response({"detail": "No interview in progress."},
                            status=status.HTTP_404_NOT_FOUND)

        index = request.data.get("question_index")
        turn = InterviewService.submit_answer(
            session, request.data.get("answer", ""),
            question_index=index if index is not None else None,
        )
        if turn is None:
            return Response({"detail": "That question does not exist in this interview."},
                            status=status.HTTP_400_BAD_REQUEST)

        session.refresh_from_db()
        serialized = InterviewSessionSerializer(session).data
        return Response({
            "evaluation": InterviewTurnSerializer(turn).data,
            "next_question": serialized["current_question"],
            "current_index": session.current_index,
            "total_questions": session.total_questions,
            "is_finished": session.current_index >= session.total_questions,
        })


class InterviewCompleteAPIView(APIView):
    """Finish the interview and produce the report."""

    permission_classes = [IsJobSeeker]

    def post(self, request):
        session = InterviewService.active(request.user)
        if session is None:
            return Response({"detail": "No interview in progress."},
                            status=status.HTTP_404_NOT_FOUND)

        report = InterviewService.complete(session)
        session.refresh_from_db()
        return Response({
            "report": InterviewReportSerializer(report).data,
            "session": InterviewSessionSerializer(session).data,
            "readiness": InterviewService.readiness(request.user),
        })


class InterviewResetAPIView(APIView):
    """Clear the answers but keep the question bank, so it can be redone."""

    permission_classes = [IsJobSeeker]

    def post(self, request):
        session = InterviewService.active(request.user)
        if session is None:
            return Response({"detail": "No interview in progress."},
                            status=status.HTTP_404_NOT_FOUND)

        InterviewService.reset(session)
        session.refresh_from_db()
        return Response({"session": InterviewSessionSerializer(session).data})


class InterviewReadinessAPIView(APIView):
    permission_classes = [IsJobSeeker]

    def get(self, request):
        return Response({"readiness": InterviewService.readiness(request.user)})


class InterviewHistoryAPIView(APIView):
    """Past interviews, so progress is visible over time."""

    permission_classes = [IsJobSeeker]

    def get(self, request):
        sessions = InterviewService.history(request.user)
        return Response({"sessions": InterviewSessionSummarySerializer(sessions, many=True).data})


class InterviewSessionDetailAPIView(APIView):
    """A past session with its transcript and report."""

    permission_classes = [IsJobSeeker]

    def get(self, request, session_id):
        session = get_object_or_404(InterviewSession, pk=session_id, user=request.user)
        return Response({"session": InterviewSessionSerializer(session).data})


def _interview_options(user, target_role):
    """Everything the setup step needs to render itself.

    System design is only offered where the role profile says it applies, so a
    designer is never given a system design round - which is also why the
    interview types are filtered here rather than hard-coded in the page.
    """
    from .context import CareerContextBuilder
    from .interview import CATEGORIES_FOR_TYPE

    cv = CareerContextBuilder(user).build(("cv",)).get("cv") or {}
    profile = match_profile(target_role, cv.get("specialization"), cv.get("profession"))
    allowed = set(available_categories(profile))

    return {
        "suggested_role": (
            target_role or cv.get("specialization") or cv.get("profession") or ""
        ),
        "role_family": profile.label,
        "topics": list(profile.topics),
        "difficulties": [
            {"value": value, "label": label}
            for value, label in InterviewSession.LEVEL_CHOICES
        ],
        "interview_types": [
            {"value": value, "label": label,
             "categories": [CATEGORY_LABELS[c] for c in CATEGORIES_FOR_TYPE[value] if c in allowed]}
            for value, label in InterviewSession.TYPE_CHOICES
            if any(c in allowed for c in CATEGORIES_FOR_TYPE[value])
        ],
        "question_counts": {"min": MIN_QUESTIONS, "max": MAX_QUESTIONS, "default": QUESTION_TARGET},
        "durations": [
            {"value": minutes, "label": "Untimed" if not minutes else f"{minutes} min"}
            for minutes in DURATION_CHOICES
        ],
        # Kept for callers that drive the categories directly - the setup UI now
        # picks a type instead, but the finer control is still supported.
        "categories": [
            {"value": category, "label": CATEGORY_LABELS[category]}
            for category in available_categories(profile)
        ],
        "levels": [{"value": value, "label": label} for value, label in LEVEL_LABELS.items()],
    }

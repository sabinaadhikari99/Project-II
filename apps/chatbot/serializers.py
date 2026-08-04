# file path: apps/chatbot/serializers.py
from rest_framework import serializers

from .models import ChatMessage, InterviewReport, InterviewSession, InterviewTurn


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "content", "suggestions", "context_used",
                  "intent", "is_ai_generated", "created_at"]
        read_only_fields = fields


class InterviewTurnSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterviewTurn
        fields = ["question_index", "question", "category", "difficulty", "answer",
                  "score", "strengths", "weaknesses", "coaching", "better_answer",
                  "is_ai_generated", "created_at"]
        read_only_fields = fields


class InterviewReportSerializer(serializers.ModelSerializer):
    target_role = serializers.CharField(source="session.target_role", read_only=True)

    class Meta:
        model = InterviewReport
        fields = ["target_role", "overall_score", "technical_score", "hr_score",
                  "behavioral_score", "communication_score", "confidence_score",
                  "strengths", "weaknesses", "missing_skills", "improvement_plan",
                  "recommended_courses", "next_topics", "is_ai_generated", "created_at"]
        read_only_fields = fields


class InterviewSessionSerializer(serializers.ModelSerializer):
    """The full session, used to restore the page without an AI call."""

    turns = InterviewTurnSerializer(many=True, read_only=True)
    report = InterviewReportSerializer(read_only=True)
    total_questions = serializers.IntegerField(read_only=True)
    answered = serializers.SerializerMethodField()
    current_question = serializers.SerializerMethodField()
    elapsed_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = InterviewSession
        fields = ["id", "target_role", "difficulty", "interview_type", "question_count",
                  "duration_minutes", "started_at", "elapsed_seconds", "status",
                  "questions", "tips", "improvement_plan", "readiness", "current_index",
                  "total_questions", "answered", "current_question", "turns", "report",
                  "is_ai_generated", "created_at", "updated_at", "completed_at"]
        read_only_fields = fields

    def get_answered(self, session):
        return session.turns.exclude(answer="").count()

    def get_current_question(self, session):
        """The question the mock interview is waiting on.

        `expected_points` is stripped here: it is the grading rubric, and showing
        it while the user is answering would defeat the exercise. The full
        question objects in `questions` keep it, so the study view can still
        show what a strong answer covers.
        """
        question = session.question_at(session.current_index)
        if question is None:
            return None
        return {key: value for key, value in question.items() if key != "expected_points"}


class InterviewSessionSummarySerializer(serializers.ModelSerializer):
    """Compact row for the history list."""

    total_questions = serializers.IntegerField(read_only=True)
    answered = serializers.SerializerMethodField()
    overall_score = serializers.SerializerMethodField()
    elapsed_seconds = serializers.IntegerField(read_only=True)

    class Meta:
        model = InterviewSession
        fields = ["id", "target_role", "difficulty", "interview_type", "status",
                  "total_questions", "answered", "overall_score", "duration_minutes",
                  "elapsed_seconds", "is_active", "created_at", "updated_at",
                  "completed_at"]
        read_only_fields = fields

    def get_answered(self, session):
        return session.turns.exclude(answer="").count()

    def get_overall_score(self, session):
        report = getattr(session, "report", None)
        return report.overall_score if report else None

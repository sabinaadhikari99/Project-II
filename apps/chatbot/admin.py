# file path: apps/chatbot/admin.py
from django.contrib import admin

from .models import (
    ChatMessage,
    Conversation,
    InterviewReport,
    InterviewSession,
    InterviewTurn,
)


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    readonly_fields = ("role", "content", "intent", "context_used", "suggestions",
                       "is_ai_generated", "created_at")
    can_delete = False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("user", "title", "is_active", "updated_at")
    list_filter = ("is_active", "updated_at")
    search_fields = ("user__email", "title")
    # `memory` is shown read-only: it is what the assistant believes about the
    # thread, and being able to read it is how a strange answer gets explained.
    readonly_fields = ("created_at", "updated_at", "memory")
    inlines = [ChatMessageInline]
    ordering = ("-updated_at",)


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "role", "short_content", "intent",
                    "is_ai_generated", "created_at")
    list_filter = ("role", "intent", "is_ai_generated", "created_at")
    search_fields = ("content", "conversation__user__email")
    readonly_fields = ("conversation", "role", "content", "intent", "context_used",
                       "suggestions", "is_ai_generated", "created_at")
    ordering = ("-created_at",)

    @admin.display(description="Content")
    def short_content(self, obj):
        return obj.content[:80] + ("…" if len(obj.content) > 80 else "")


class InterviewTurnInline(admin.TabularInline):
    model = InterviewTurn
    extra = 0
    readonly_fields = ("question_index", "question", "category", "difficulty", "answer",
                       "score", "strengths", "weaknesses", "coaching", "better_answer",
                       "is_ai_generated", "created_at")
    can_delete = False


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "target_role", "interview_type", "difficulty", "status",
                    "asked", "took", "is_ai_generated", "updated_at")
    list_filter = ("status", "interview_type", "difficulty", "is_ai_generated",
                   "is_active", "updated_at")
    search_fields = ("user__email", "target_role")
    readonly_fields = ("created_at", "updated_at", "started_at", "completed_at",
                       "resume_fingerprint")
    inlines = [InterviewTurnInline]
    ordering = ("-updated_at",)

    @admin.display(description="Questions")
    def asked(self, obj):
        return obj.total_questions

    @admin.display(description="Took")
    def took(self, obj):
        seconds = obj.elapsed_seconds
        return "—" if seconds is None else f"{max(1, round(seconds / 60))} min"


@admin.register(InterviewReport)
class InterviewReportAdmin(admin.ModelAdmin):
    list_display = ("session", "overall_score", "technical_score", "behavioral_score",
                    "hr_score", "communication_score", "confidence_score", "created_at")
    list_filter = ("is_ai_generated", "created_at")
    search_fields = ("session__user__email", "session__target_role")
    readonly_fields = tuple(
        field.name for field in InterviewReport._meta.fields if field.name != "id"
    )
    ordering = ("-created_at",)

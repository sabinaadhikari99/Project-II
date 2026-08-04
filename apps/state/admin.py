# file path: apps/state/admin.py
from django.contrib import admin

from .models import AnalysisSession, QuizSession, UIState


@admin.register(AnalysisSession)
class AnalysisSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "profession", "specialization", "match_score", "cv_filename", "updated_at")
    list_filter = ("source", "career_level", "updated_at")
    search_fields = ("user__email", "profession", "specialization", "cv_filename")
    readonly_fields = ("resume_fingerprint", "payload", "skills", "created_at", "updated_at")
    ordering = ("-updated_at",)


@admin.register(UIState)
class UIStateAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "revision", "updated_at")
    list_filter = ("key", "updated_at")
    search_fields = ("user__email", "key")
    readonly_fields = ("revision", "created_at", "updated_at")
    ordering = ("user", "key")


@admin.register(QuizSession)
class QuizSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "score", "total", "percentage", "updated_at")
    list_filter = ("status", "updated_at")
    search_fields = ("user__email",)
    readonly_fields = ("questions", "answers", "results", "started_at", "updated_at", "completed_at")
    ordering = ("-updated_at",)

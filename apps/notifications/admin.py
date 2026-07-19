from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "sender", "notification_type", "priority", "is_read", "is_email_sent", "created_at")
    search_fields = ("title", "message", "user__email", "sender__email", "recruiter__email")
    list_filter = ("notification_type", "priority", "is_read", "is_email_sent", "created_at")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "read_at")

from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "recruiter", "job", "match_percentage", "is_read", "created_at")
    search_fields = ("title", "message", "user__email", "recruiter__email", "job__title", "job__company")
    list_filter = ("is_read", "match_percentage", "created_at")
    ordering = ("-created_at",)

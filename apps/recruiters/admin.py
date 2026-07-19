from django.contrib import admin

from .models import RecruiterActivity


@admin.register(RecruiterActivity)
class RecruiterActivityAdmin(admin.ModelAdmin):
    list_display = ("recruiter", "activity_type", "job", "created_at")
    list_filter = ("activity_type", "created_at")
    search_fields = ("recruiter__email", "job__title", "description")

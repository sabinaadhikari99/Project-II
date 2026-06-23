from django.contrib import admin

from .models import Application, JobPosting, RecentlyViewedJob, SavedJob


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "recruiter", "location", "work_mode", "experience_required", "is_active", "created_at")
    search_fields = ("title", "company", "location", "description", "recruiter__email")
    list_filter = ("work_mode", "is_active", "created_at")
    ordering = ("-created_at",)


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("job", "applicant", "status", "created_at")
    search_fields = ("job__title", "job__company", "applicant__email", "cover_letter")
    list_filter = ("status", "created_at")
    ordering = ("-created_at",)


@admin.register(SavedJob)
class SavedJobAdmin(admin.ModelAdmin):
    list_display = ("user", "job", "created_at")
    search_fields = ("user__email", "job__title", "job__company")
    list_filter = ("created_at",)
    ordering = ("-created_at",)


@admin.register(RecentlyViewedJob)
class RecentlyViewedJobAdmin(admin.ModelAdmin):
    list_display = ("user", "job", "viewed_at")
    search_fields = ("user__email", "job__title", "job__company")
    list_filter = ("viewed_at",)
    ordering = ("-viewed_at",)

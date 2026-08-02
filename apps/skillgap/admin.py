from django.contrib import admin

from .models import CourseRecommendation, LearningRoadmap, RoadmapStepProgress


@admin.register(CourseRecommendation)
class CourseRecommendationAdmin(admin.ModelAdmin):
    list_display = ("user", "profession", "career_level", "updated_at")
    list_filter = ("profession", "career_level", "updated_at")
    search_fields = ("user__email", "profession")
    readonly_fields = ("resume_hash", "payload", "created_at", "updated_at")


@admin.register(LearningRoadmap)
class LearningRoadmapAdmin(admin.ModelAdmin):
    list_display = ("user", "profession", "career_level", "updated_at")
    list_filter = ("profession", "career_level", "updated_at")
    search_fields = ("user__email", "profession")
    readonly_fields = ("resume_hash", "payload", "created_at", "updated_at")


@admin.register(RoadmapStepProgress)
class RoadmapStepProgressAdmin(admin.ModelAdmin):
    list_display = ("roadmap", "step_number", "skill_name", "status", "updated_at")
    list_filter = ("status", "updated_at")
    search_fields = ("skill_name", "user__email")

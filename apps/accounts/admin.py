# file path: apps/accounts/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User, UserProfile


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("SkillSync", {"fields": ("profile_picture", "role")}),)
    list_display = ("email", "username", "role", "is_staff", "is_active", "date_joined")
    search_fields = ("email", "username")
    list_filter = ("role", "is_staff", "is_active", "date_joined")
    ordering = ("email",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "experience_years", "education", "skill_count")
    search_fields = ("user__email", "user__username", "education", "resume_text")
    list_filter = ("experience_years",)
    ordering = ("user__email",)

    @admin.display(description="Skills")
    def skill_count(self, obj):
        return len(obj.skills or [])

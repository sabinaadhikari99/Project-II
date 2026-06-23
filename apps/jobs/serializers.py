# file path: apps/jobs/serializers.py
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer

from .models import Application, JobPosting, RecentlyViewedJob, SavedJob


class JobPostingSerializer(serializers.ModelSerializer):
    recruiter_email = serializers.EmailField(source="recruiter.email", read_only=True)
    is_saved = serializers.SerializerMethodField()

    class Meta:
        model = JobPosting
        fields = [
            "id", "recruiter", "recruiter_email", "title", "company", "company_logo",
            "location", "work_mode", "description", "required_skills", "experience_required",
            "salary_range", "is_active", "is_saved", "created_at",
        ]
        read_only_fields = ["id", "recruiter", "recruiter_email", "is_saved", "created_at"]

    def get_is_saved(self, obj):
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return SavedJob.objects.filter(user=request.user, job=obj).exists()


class ApplicationSerializer(serializers.ModelSerializer):
    job = JobPostingSerializer(read_only=True)
    applicant = UserSerializer(read_only=True)

    class Meta:
        model = Application
        fields = ["id", "job", "applicant", "cover_letter", "status", "created_at"]
        read_only_fields = ["id", "job", "applicant", "status", "created_at"]


class RecommendedJobSerializer(serializers.Serializer):
    job = JobPostingSerializer()
    score = serializers.FloatField()
    match_percentage = serializers.IntegerField()
    required_skills = serializers.ListField(child=serializers.CharField())
    matched_skills = serializers.ListField(child=serializers.CharField())
    missing_skills = serializers.ListField(child=serializers.CharField())
    skill_gap_analysis = serializers.CharField()
    career_roadmap = serializers.ListField(child=serializers.CharField())
    recommended_resources = serializers.ListField(child=serializers.DictField())


class SavedJobSerializer(serializers.ModelSerializer):
    job = JobPostingSerializer(read_only=True)

    class Meta:
        model = SavedJob
        fields = ["id", "job", "created_at"]


class RecentlyViewedJobSerializer(serializers.ModelSerializer):
    job = JobPostingSerializer(read_only=True)

    class Meta:
        model = RecentlyViewedJob
        fields = ["id", "job", "viewed_at"]

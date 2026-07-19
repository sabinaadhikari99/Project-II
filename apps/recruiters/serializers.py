from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.jobs.models import JobPosting

from .models import RecruiterActivity


class CandidateMatchSerializer(serializers.Serializer):
    candidate = UserSerializer()
    score = serializers.FloatField()


class RecruiterActivitySerializer(serializers.ModelSerializer):
    job_title = serializers.SerializerMethodField()
    relative_time = serializers.SerializerMethodField()

    class Meta:
        model = RecruiterActivity
        fields = ("id", "activity_type", "description", "job_title", "relative_time", "created_at")

    def get_job_title(self, obj):
        return obj.job.title if obj.job else None

    def get_relative_time(self, obj):
        from django.utils import timezone
        now = timezone.now()
        diff = now - obj.created_at

        seconds = diff.total_seconds()
        if seconds < 60:
            return "Just now"
        minutes = int(seconds / 60)
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = int(minutes / 60)
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = int(hours / 24)
        if days == 1:
            return "Yesterday"
        if days < 30:
            return f"{days} days ago"
        return obj.created_at.strftime("%b %d, %Y")

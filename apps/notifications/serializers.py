from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.jobs.serializers import JobPostingSerializer

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    recruiter = UserSerializer(read_only=True)
    job = JobPostingSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "user", "recruiter", "job", "match_percentage", "title", "message", "is_read", "created_at"]
        read_only_fields = fields

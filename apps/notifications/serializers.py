from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.jobs.serializers import JobPostingSerializer

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    recruiter = UserSerializer(read_only=True)
    job = JobPostingSerializer(read_only=True)
    time_ago = serializers.SerializerMethodField()
    category_label = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id", "user", "sender", "recruiter", "job", "match_percentage",
            "notification_type", "category_label", "title", "message", "priority",
            "is_read", "is_email_sent", "created_at", "read_at", "time_ago", "metadata",
        ]
        read_only_fields = fields

    def get_time_ago(self, obj):
        from django.utils import timezone
        now = timezone.now()
        diff = now - obj.created_at
        if diff.days > 0:
            return f"{diff.days}d ago"
        if diff.seconds >= 3600:
            return f"{diff.seconds // 3600}h ago"
        if diff.seconds >= 60:
            return f"{diff.seconds // 60}m ago"
        return "Just now"

    def get_category_label(self, obj):
        return dict(Notification.NotificationType.choices).get(obj.notification_type, "General")


class NotificationWriteSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), required=False)


class UnreadCountSerializer(serializers.Serializer):
    count = serializers.IntegerField()

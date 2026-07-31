from rest_framework import serializers

from .models import CourseRecommendation, LearningRoadmap, RoadmapStepProgress


class CourseRecommendationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseRecommendation
        fields = [
            "id",
            "profession",
            "career_level",
            "resume_hash",
            "payload",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "resume_hash",
            "payload",
            "created_at",
            "updated_at",
        ]


class LearningRoadmapSerializer(serializers.ModelSerializer):
    class Meta:
        model = LearningRoadmap
        fields = [
            "id",
            "profession",
            "career_level",
            "resume_hash",
            "payload",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "resume_hash",
            "payload",
            "created_at",
            "updated_at",
        ]


class RoadmapStepProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoadmapStepProgress
        fields = [
            "id",
            "step_number",
            "skill_name",
            "status",
            "completed_at",
            "updated_at",
        ]
        read_only_fields = ["id", "skill_name", "completed_at", "updated_at"]


class RoadmapProgressUpdateSerializer(serializers.Serializer):
    step_number = serializers.IntegerField(min_value=1)
    status = serializers.ChoiceField(choices=RoadmapStepProgress.STATUS_CHOICES)

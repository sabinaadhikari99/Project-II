# file path: apps/state/serializers.py
from rest_framework import serializers


class UIStateWriteSerializer(serializers.Serializer):
    """Single-key write. ``value`` accepts any JSON type, including null."""

    value = serializers.JSONField(required=True, allow_null=True)


class UIStateBulkWriteSerializer(serializers.Serializer):
    """``{"items": {"jobs.filters": {...}, "chat.transcript": [...]}}``."""

    items = serializers.DictField(child=serializers.JSONField(allow_null=True))

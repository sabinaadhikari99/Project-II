# file path: apps/recruiters/serializers.py
from rest_framework import serializers

from apps.accounts.serializers import UserSerializer


class CandidateMatchSerializer(serializers.Serializer):
    candidate = UserSerializer()
    score = serializers.FloatField()

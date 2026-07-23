import base64
import re

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserProfile


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = ["phone", "skills", "resume_text", "cv_url",
                   "experience_years", "education", "location", "bio",
                   "headline", "linkedin_url", "github_url", "portfolio_url"]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "username", "profile_picture", "role"]


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "email", "username", "password", "role"]

    def validate_role(self, value):
        if value == "admin":
            raise serializers.ValidationError("Admin registration is not allowed.")
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        user = User.objects.create_user(**validated_data)
        user.set_password(password)
        user.save()

        UserProfile.objects.create(user=user)
        return user

    def to_representation(self, instance):
        return {
            "user": UserSerializer(instance).data,
            "message": "Registration successful! Please log in to continue."
        }


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"],
            password=attrs["password"]
        )
        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        self.user = user
        refresh = RefreshToken.for_user(user)
        return {
            "user": UserSerializer(user).data,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }


ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB


def validate_base64_image(value):
    if not value:
        return value

    if not isinstance(value, str) or not value.startswith("data:image/"):
        raise serializers.ValidationError("Invalid image format. Accepted: JPG, PNG, WEBP.")

    try:
        header, encoded = value.split(",", 1)
        mime_type = header.replace("data:", "").replace(";base64", "")
        if mime_type not in ALLOWED_IMAGE_TYPES:
            raise serializers.ValidationError(
                f"Unsupported image type '{mime_type}'. Accepted: JPG, PNG, WEBP."
            )
        decoded = base64.b64decode(encoded)
        if len(decoded) > MAX_IMAGE_SIZE:
            raise serializers.ValidationError("Image too large. Maximum size is 5 MB.")
    except (ValueError, base64.binascii.Error):
        raise serializers.ValidationError("Corrupted image file.")

    return value


def validate_phone_number(value):
    if not value:
        return value
    cleaned = re.sub(r"[\s\-\(\)\.\+]", "", value)
    if not re.match(r"^\+?\d{7,15}$", cleaned):
        raise serializers.ValidationError(
            "Invalid phone number. Must contain 7-15 digits, "
            "optionally with a leading '+' and country code."
        )
    return value


class ProfileUpdateSerializer(serializers.ModelSerializer):
    profile = UserProfileSerializer(required=False)
    profile_picture = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ["id", "email", "username", "profile_picture", "role", "profile"]
        read_only_fields = ["id", "role"]

    def validate_email(self, value):
        user = self.instance
        if User.objects.filter(email=value).exclude(pk=user.pk).exists():
            raise serializers.ValidationError("Email address already exists.")
        return value

    def validate_username(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Full name is required.")
        return value.strip()

    def validate_profile_picture(self, value):
        return validate_base64_image(value)

    def validate(self, attrs):
        profile_data = attrs.get("profile", {})
        if profile_data and "phone" in profile_data:
            profile_data["phone"] = validate_phone_number(profile_data["phone"])
        return attrs

    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if profile_data is not None:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()

        return instance


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)
    confirm_password = serializers.CharField(required=True)

    def validate_current_password(self, value):
        user = self.context.get("user")
        if not user or not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("Password must be at least 8 characters.")
        if not re.search(r"[A-Z]", value):
            raise serializers.ValidationError(
                "Password must contain at least one uppercase letter."
            )
        if not re.search(r"[a-z]", value):
            raise serializers.ValidationError(
                "Password must contain at least one lowercase letter."
            )
        if not re.search(r"\d", value):
            raise serializers.ValidationError(
                "Password must contain at least one number."
            )
        if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]", value):
            raise serializers.ValidationError(
                "Password must contain at least one special character."
            )
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def validate(self, attrs):
        if attrs["new_password"] != attrs.get("confirm_password", ""):
            raise serializers.ValidationError(
                {"confirm_password": "Passwords do not match."}
            )
        if attrs["current_password"] == attrs["new_password"]:
            raise serializers.ValidationError(
                {"new_password": "New password must be different from current password."}
            )
        return attrs

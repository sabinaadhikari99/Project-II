from rest_framework.permissions import BasePermission
from .constants import ROLE_ADMIN, ROLE_JOB_SEEKER, ROLE_RECRUITER


class RolePermission(BasePermission):
    required_role = None

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # SAFE ROLE CHECK
        user_role = getattr(user, "role", None)

        return user_role == self.required_role


class IsJobSeeker(RolePermission):
    required_role = ROLE_JOB_SEEKER


class IsRecruiter(RolePermission):
    required_role = ROLE_RECRUITER


class IsAdmin(RolePermission):
    required_role = ROLE_ADMIN
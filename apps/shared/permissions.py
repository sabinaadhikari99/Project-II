# file path: apps/shared/permissions.py
from rest_framework.permissions import BasePermission

from .constants import ROLE_ADMIN, ROLE_JOB_SEEKER, ROLE_RECRUITER


class RolePermission(BasePermission):
    required_role = None

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == self.required_role
        )


class IsJobSeeker(RolePermission):
    required_role = ROLE_JOB_SEEKER


class IsRecruiter(RolePermission):
    required_role = ROLE_RECRUITER


class IsAdmin(RolePermission):
    required_role = ROLE_ADMIN

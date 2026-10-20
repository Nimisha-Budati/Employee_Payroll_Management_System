from rest_framework import permissions

from .models import UserProfile
from .utils import is_admin_user


class IsAdminUserRole(permissions.BasePermission):
    """Allows access only to administrators (ADMIN role, staff or superuser)."""

    message = 'Access denied. Administrator access is required.'

    def has_permission(self, request, view):
        return is_admin_user(request.user)


class IsEmployeeUserRole(permissions.BasePermission):
    message = 'Access denied. Employee access is required.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return UserProfile.objects.filter(user=request.user, role='EMPLOYEE').exists()

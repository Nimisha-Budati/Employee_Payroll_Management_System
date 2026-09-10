from rest_framework import permissions
from .models import UserProfile


class IsAdminUserRole(permissions.BasePermission):
    """
    Allows access only to users with ADMIN role in UserProfile or is_staff.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.user.is_staff or request.user.is_superuser:
            return True
        try:
            profile = UserProfile.objects.get(user=request.user)
            return profile.role == 'ADMIN'
        except UserProfile.DoesNotExist:
            return False


class IsEmployeeUserRole(permissions.BasePermission):
    message = 'Access denied. Employee access is required.'

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        try:
            return UserProfile.objects.get(user=request.user).role == 'EMPLOYEE'
        except UserProfile.DoesNotExist:
            return False
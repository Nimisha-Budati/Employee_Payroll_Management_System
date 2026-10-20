"""Shared helpers."""

from .models import UserProfile


def is_admin_user(user):
    if not user or not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser or UserProfile.objects.filter(user=user, role='ADMIN').exists()

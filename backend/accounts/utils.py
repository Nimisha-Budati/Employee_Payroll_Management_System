"""Shared helpers."""

from .models import UserProfile


def is_admin_user(user):
    if not user or not user.is_authenticated:
        return False
    return UserProfile.objects.filter(user=user, role='ADMIN', company__isnull=False).exists()

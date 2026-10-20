"""Helpers for creating in-app notifications."""

from django.contrib.auth.models import User
from django.db.models import Q

from .models import Notification


def notify_user(recipient, kind, title, message, target_url='', actor=None):
    if recipient is None or (actor is not None and recipient.pk == actor.pk):
        return None
    return Notification.objects.create(
        recipient=recipient,
        actor=actor,
        kind=kind,
        title=title,
        message=message,
        target_url=target_url,
    )


def _bulk_notify(recipients, kind, title, message, target_url, actor):
    if actor is not None:
        recipients = recipients.exclude(pk=actor.pk)
    return Notification.objects.bulk_create([
        Notification(
            recipient=recipient,
            actor=actor,
            kind=kind,
            title=title,
            message=message,
            target_url=target_url,
        )
        for recipient in recipients.distinct()
    ])


def notify_role(role, kind, title, message, target_url='', actor=None):
    recipients = User.objects.filter(is_active=True, userprofile__role=role)
    return _bulk_notify(recipients, kind, title, message, target_url, actor)


def notify_admins(kind, title, message, target_url='', actor=None):
    recipients = User.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True) | Q(userprofile__role='ADMIN'),
    )
    return _bulk_notify(recipients, kind, title, message, target_url, actor)

"""Helpers for creating in-app notifications.

Users may switch off optional kinds (``NotificationPreference``). Kinds in
``Notification.MANDATORY_KINDS`` (security, payslips/employee record, onboarding and messages an
administrator sent deliberately) are always delivered.
"""

from django.contrib.auth.models import User
from django.db.models import Q

from .models import Notification, NotificationPreference


def optional_kinds():
    return [(kind, label) for kind, label in Notification.KIND_CHOICES if kind not in Notification.MANDATORY_KINDS]


def _muted_user_ids(kind, user_ids=None):
    if kind in Notification.MANDATORY_KINDS:
        return set()
    muted = NotificationPreference.objects.filter(kind=kind, enabled=False)
    if user_ids is not None:
        muted = muted.filter(user_id__in=user_ids)
    return set(muted.values_list('user_id', flat=True))


def wants(user, kind):
    return user.pk not in _muted_user_ids(kind, [user.pk])


def notify_user(recipient, kind, title, message, target_url='', actor=None):
    if recipient is None or (actor is not None and recipient.pk == actor.pk):
        return None
    if not wants(recipient, kind):
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
    recipients = list(recipients.distinct())
    muted = _muted_user_ids(kind, [user.pk for user in recipients])
    return Notification.objects.bulk_create([
        Notification(
            recipient=recipient,
            actor=actor,
            kind=kind,
            title=title,
            message=message,
            target_url=target_url,
        )
        for recipient in recipients if recipient.pk not in muted
    ])


def admin_users():
    return User.objects.filter(is_active=True).filter(
        Q(is_staff=True) | Q(is_superuser=True) | Q(userprofile__role='ADMIN'),
    )


def notify_role(role, kind, title, message, target_url='', actor=None):
    recipients = User.objects.filter(is_active=True, userprofile__role=role)
    return _bulk_notify(recipients, kind, title, message, target_url, actor)


def notify_admins(kind, title, message, target_url='', actor=None):
    return _bulk_notify(admin_users(), kind, title, message, target_url, actor)

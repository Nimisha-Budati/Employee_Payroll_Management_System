"""Small cache-backed throttle used to slow down password guessing.

It uses Django's default cache (per-process local memory unless CACHES is
configured), which is enough for a single-server deployment. Configure a shared
cache such as Redis if the app runs on several processes or servers.
"""

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded and not settings.DEBUG:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')


def _keys(scope, identifiers):
    return [f'throttle:{scope}:{str(identifier).lower()}' for identifier in identifiers if identifier]


def is_locked(scope, *identifiers):
    limit = settings.LOGIN_MAX_FAILED_ATTEMPTS
    return any((cache.get(key) or 0) >= limit for key in _keys(scope, identifiers))


def register_failure(scope, *identifiers):
    for key in _keys(scope, identifiers):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, settings.LOGIN_LOCKOUT_SECONDS)


def clear_failures(scope, *identifiers):
    for key in _keys(scope, identifiers):
        cache.delete(key)

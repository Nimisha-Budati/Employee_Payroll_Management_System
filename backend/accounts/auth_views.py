"""Authentication endpoints: CSRF bootstrap, register, login, logout and password flows.

These are plain Django views (not DRF) because they must work before a user is
authenticated. CSRF protection is enforced by Django's middleware: the frontend
first calls ``GET /api/csrf/`` and sends the returned token in ``X-CSRFToken``.
"""

import json
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import record_audit
from .models import PasswordResetOTP, UserProfile
from .notifications import notify_user
from .throttling import clear_failures, client_ip, is_locked, register_failure


def csrf_failure(request, reason=''):
    return JsonResponse(
        {'error': 'Your session security token is missing or expired. Refresh the page and try again.'},
        status=403,
    )


def json_body(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def user_for_identifier(identifier):
    if not identifier:
        return None
    return (
        User.objects.filter(email__iexact=identifier).first()
        or User.objects.filter(username__iexact=identifier).first()
    )


def password_error(password, user=None):
    try:
        validate_password(password, user)
    except ValidationError as error:
        return ' '.join(error.messages)
    return None


def resolve_profile(user):
    """The user's profile; accounts made with ``createsuperuser`` get an ADMIN profile on first use."""
    profile = UserProfile.objects.filter(user=user).first()
    if profile is None and (user.is_staff or user.is_superuser):
        profile = UserProfile.objects.create(user=user, role='ADMIN')
    return profile


def login_block(user, role):
    """Rules every sign-in method shares. Returns (message, http_status) when ``user`` may not sign in as ``role``."""
    profile = resolve_profile(user)
    if profile is None:
        return 'User profile not found', 400
    if profile.role != role:
        return 'Incorrect login type', 403
    employee = getattr(user, 'employee', None)
    if employee is not None and employee.status != 'ACTIVE':
        return 'This employee account is inactive', 403
    return None


def _text(data, key):
    value = data.get(key, '')
    return value.strip() if isinstance(value, str) else ''


def _bad_json():
    return JsonResponse({'error': 'Invalid JSON data'}, status=400)


@require_GET
@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)})


@require_POST
def register(request):
    data = json_body(request)
    if data is None:
        return _bad_json()

    username = _text(data, 'username')
    email = _text(data, 'email').lower()
    password = data.get('password', '') if isinstance(data.get('password', ''), str) else ''
    confirm_password = data.get('confirm_password', '')
    role = str(data.get('role', 'EMPLOYEE')).upper()

    if not username or not email or not password or not confirm_password:
        return JsonResponse({'error': 'Please fill in all fields'}, status=400)
    try:
        User.username_validator(username)
    except ValidationError:
        return JsonResponse({'error': 'Username may only contain letters, numbers and @/./+/-/_ characters'}, status=400)
    if len(username) > 150:
        return JsonResponse({'error': 'Username must be 150 characters or fewer'}, status=400)
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({'error': 'Please enter a valid email address'}, status=400)
    if password != confirm_password:
        return JsonResponse({'error': 'Passwords do not match'}, status=400)
    if role != 'EMPLOYEE':
        return JsonResponse({'error': 'Public registration is restricted to employee accounts'}, status=403)

    error = password_error(password, User(username=username, email=email))
    if error:
        return JsonResponse({'error': error}, status=400)
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({'error': 'Username already exists'}, status=400)
    if User.objects.filter(email__iexact=email).exists():
        return JsonResponse({'error': 'Email already exists'}, status=400)

    with transaction.atomic():
        user = User.objects.create_user(username=username, email=email, password=password)
        UserProfile.objects.create(user=user, role=role)
    notify_user(
        user,
        'EMPLOYEE',
        'Welcome to PayrollPro',
        'Your employee account is ready. An administrator will complete your employment record.',
        'employee-dashboard.html',
    )
    return JsonResponse({'message': 'Account created successfully'}, status=201)


@require_POST
def login_user(request):
    data = json_body(request)
    if data is None:
        return _bad_json()

    identifier = _text(data, 'username')
    password = data.get('password', '') if isinstance(data.get('password', ''), str) else ''
    role = data.get('role', '')
    remember_me = bool(data.get('remember_me'))

    if not identifier or not password:
        return JsonResponse({'error': 'Please enter username and password'}, status=400)

    ip = client_ip(request)
    if is_locked('login', ip, identifier):
        return JsonResponse(
            {'error': 'Too many failed attempts. Please wait a few minutes before trying again.'},
            status=429,
        )

    user_record = user_for_identifier(identifier)
    user = authenticate(
        request,
        username=user_record.username if user_record else identifier,
        password=password,
    )
    if user is None:
        # Inactive users never authenticate; report the same generic message to avoid account enumeration.
        register_failure('login', ip, identifier)
        record_audit(request, 'LOGIN_FAILED', 'Account', '', f'Failed sign-in for "{identifier[:60]}".')
        return JsonResponse({'error': 'Invalid username or password'}, status=401)

    blocked = login_block(user, role)
    if blocked:
        record_audit(request, 'LOGIN_BLOCKED', 'Account', user.pk, f'Sign-in refused for {user.username}: {blocked[0]}.', actor=user)
        return JsonResponse({'error': blocked[0]}, status=blocked[1])
    profile = resolve_profile(user)

    clear_failures('login', ip, identifier)
    login(request, user)
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if remember_me else 0)
    record_audit(request, 'LOGIN', 'Account', user.pk, f'{user.username} signed in as {profile.role.lower()} (password).')

    return JsonResponse({
        'message': 'Login successful',
        'username': user.username,
        'email': user.email,
        'role': profile.role,
        'full_name': user.get_full_name() or user.username,
        'remember_me': remember_me,
    })


@require_POST
def logout_user(request):
    if request.user.is_authenticated:
        record_audit(request, 'LOGOUT', 'Account', request.user.pk, f'{request.user.username} signed out.')
    logout(request)
    return JsonResponse({'message': 'Logout successful'})


@require_POST
def request_password_reset(request):
    data = json_body(request)
    if data is None:
        return _bad_json()
    identifier = _text(data, 'email')
    generic = {'message': 'If an active account matches, a verification code has been sent.'}

    ip = client_ip(request)
    if is_locked('otp-request', ip, identifier):
        return JsonResponse({'error': 'Too many requests. Please wait a few minutes and try again.'}, status=429)
    register_failure('otp-request', ip, identifier)

    user = user_for_identifier(identifier)
    if user is None or not user.is_active or not user.email:
        return JsonResponse(generic)

    code = f'{secrets.randbelow(1000000):06d}'
    with transaction.atomic():
        PasswordResetOTP.objects.filter(user=user).delete()
        PasswordResetOTP.objects.create(
            user=user,
            reset_token=secrets.token_urlsafe(32),
            code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
    send_mail(
        'Your PayrollPro password reset code',
        f'Your verification code is {code}. It expires in 10 minutes.',
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
    return JsonResponse(generic)


@require_POST
def verify_password_reset(request):
    data = json_body(request)
    if data is None:
        return _bad_json()
    user = user_for_identifier(_text(data, 'email'))
    reset = PasswordResetOTP.objects.filter(user=user, verified=False).order_by('-created_at').first() if user else None
    if reset is None or reset.is_expired():
        return JsonResponse({'error': 'OTP is invalid or expired'}, status=400)
    if reset.attempts >= 5:
        return JsonResponse({'error': 'Too many OTP attempts. Request a new OTP.'}, status=429)
    reset.attempts += 1
    reset.save(update_fields=['attempts'])
    if not check_password(str(data.get('otp', '')), reset.code_hash):
        return JsonResponse({'error': 'OTP is invalid or expired'}, status=400)
    reset.verified = True
    reset.save(update_fields=['verified'])
    return JsonResponse({'message': 'OTP verified', 'reset_token': reset.reset_token})


@require_POST
def reset_password(request):
    data = json_body(request)
    if data is None:
        return _bad_json()
    reset = (
        PasswordResetOTP.objects.filter(reset_token=data.get('reset_token'), verified=True)
        .select_related('user')
        .first()
    )
    if reset is None or reset.is_expired():
        return JsonResponse({'error': 'Password reset session is invalid or expired'}, status=400)
    password = data.get('password', '') if isinstance(data.get('password', ''), str) else ''
    if password != data.get('confirm_password', ''):
        return JsonResponse({'error': 'Passwords do not match'}, status=400)
    error = password_error(password, reset.user)
    if error:
        return JsonResponse({'error': error}, status=400)
    with transaction.atomic():
        reset.user.set_password(password)
        reset.user.save(update_fields=['password'])
        reset.delete()
        record_audit(request, 'PASSWORD_RESET', 'Account', reset.user.pk,
                     f'{reset.user.username} reset their password with an emailed code.', actor=reset.user)
    return JsonResponse({'message': 'Password reset successfully'})


@api_view(['POST'])
def change_password(request):
    current_password = request.data.get('current_password', '')
    new_password = request.data.get('new_password', '')
    if not request.user.check_password(current_password):
        return Response({'error': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    if new_password != request.data.get('confirm_password', ''):
        return Response({'error': 'Passwords do not match'}, status=status.HTTP_400_BAD_REQUEST)
    error = password_error(new_password, request.user)
    if error:
        return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
    request.user.set_password(new_password)
    request.user.save(update_fields=['password'])
    update_session_auth_hash(request, request.user)
    record_audit(request, 'PASSWORD_CHANGE', 'Account', request.user.pk, f'{request.user.username} changed their password.')
    return Response({'message': 'Password changed successfully'})

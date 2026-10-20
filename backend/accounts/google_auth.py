"""Sign in with Google (OAuth 2.0 authorization-code flow + PKCE + OpenID Connect).

Flow
----
1. The frontend POSTs to ``/api/auth/google/start/`` (CSRF-protected). We create a one-time ``state``,
   ``nonce`` and PKCE verifier, keep them in the server-side session and return Google's consent URL.
2. Google redirects the browser to ``/api/auth/google/callback/``. We check ``state``, exchange the
   ``code`` for tokens server-to-server (using the client secret, which never reaches the browser) and
   verify the ID token's signature, audience, issuer, expiry and nonce with Google's public keys.
   Only claims from that verified token are used, never anything the browser sends.
3. We then either sign in the linked user, create a new *employee* account, or (link mode) attach
   Google to the signed-in user. Finally the browser is redirected to the configured frontend URL.

Account-safety rules
--------------------
* A Google account is identified by its stable ``sub``, not its email.
* A Google login is NEVER silently attached to an existing account that merely has the same email:
  our own registration does not verify emails, so that would allow account pre-hijacking. The user
  must sign in with their password first and connect Google from Settings.
* New Google users become plain EMPLOYEE accounts without an Employee record, exactly like the
  public registration form, so an administrator still completes onboarding. Administrators can never
  be created through Google; an existing administrator may link Google and then use it.
* Role, inactive-employee and inactive-user checks are the same ones the password login uses.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
from urllib.parse import urlencode

import requests as http
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .audit import record_audit
from .auth_views import json_body, login_block
from .models import GoogleIdentity, UserProfile
from .notifications import notify_user
from .throttling import client_ip, clear_failures, is_locked, register_failure

AUTH_ENDPOINT = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_ENDPOINT = 'https://oauth2.googleapis.com/token'
VALID_ISSUERS = ('accounts.google.com', 'https://accounts.google.com')
SESSION_KEY = 'google_oauth'
STATE_TTL_SECONDS = 600
MODES = ('login', 'register', 'link')

ERROR_MESSAGES = {
    'cancelled': 'Google sign-in was cancelled.',
    'google_denied': 'Google did not allow this sign-in. Please try again.',
    'invalid_state': 'This sign-in attempt expired or was not started from this browser. Please try again.',
    'google_unreachable': 'Could not reach Google. Check your connection and try again.',
    'exchange_failed': 'Google rejected the sign-in request. Please try again.',
    'invalid_token': 'Google returned an identity we could not verify. Please try again.',
    'email_unverified': 'Your Google email address is not verified, so it cannot be used to sign in.',
    'email_exists': 'An account with this email already exists. Sign in with your password, then connect Google from Settings.',
    'no_admin_account': 'No administrator account is connected to this Google account. Sign in with your password and connect Google from Settings first.',
    'wrong_role': 'This Google account is not registered for that login type. Switch between Employee and Administrator and try again.',
    'inactive': 'This employee account is inactive.',
    'no_profile': 'This account has no profile. Contact an administrator.',
    'account_disabled': 'This account has been disabled.',
    'google_in_use': 'That Google account is already connected to a different user.',
    'already_linked': 'This account already has a Google account connected.',
    'link_mismatch': 'You must stay signed in to the same account while connecting Google. Please try again.',
    'throttled': 'Too many Google sign-in attempts. Please wait a few minutes and try again.',
    'server_error': 'Something went wrong while signing in with Google. Please try again.',
}


def is_configured():
    return bool(
        settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
        and settings.GOOGLE_REDIRECT_URI and settings.FRONTEND_URL
    )


# --- thin wrappers around the two network calls (kept separate so tests can replace them) ----------

def exchange_code(code, code_verifier):
    """Swap the one-time authorization code for tokens and return the raw ID token."""
    response = http.post(
        TOKEN_ENDPOINT,
        data={
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': settings.GOOGLE_REDIRECT_URI,
            'grant_type': 'authorization_code',
            'code_verifier': code_verifier,
        },
        timeout=10,
    )
    if response.status_code != 200:
        raise GoogleFlowError('exchange_failed')
    raw = response.json().get('id_token')
    if not raw:
        raise GoogleFlowError('exchange_failed')
    return raw


def verify_id_token(raw_token):
    """Verify signature, audience, issuer and expiry against Google's public keys; return the claims."""
    claims = google_id_token.verify_oauth2_token(raw_token, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
    if claims.get('iss') not in VALID_ISSUERS:
        raise ValueError('Wrong issuer')
    return claims


class GoogleFlowError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# --- redirects ------------------------------------------------------------------------------------

def _frontend(path, **params):
    """Only ever redirect to the configured frontend; no user-supplied URL is involved."""
    query = urlencode({key: value for key, value in params.items() if value})
    return HttpResponseRedirect(f'{settings.FRONTEND_URL}/{path}' + (f'?{query}' if query else ''))


def _failure(mode, code):
    page = 'settings.html' if mode == 'link' else 'index.html'
    return _frontend(page, google_error=code if code in ERROR_MESSAGES else 'server_error', view='register' if mode == 'register' else '')


def _pkce_challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')


# --- endpoints ------------------------------------------------------------------------------------

@require_GET
def google_config(request):
    return JsonResponse({'enabled': is_configured()})


@require_POST
def google_start(request):
    data = json_body(request)
    if data is None:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    if not is_configured():
        return JsonResponse({'error': 'Google sign-in has not been configured on this server yet.'}, status=503)

    mode = data.get('mode', 'login')
    role = 'EMPLOYEE' if mode == 'register' else str(data.get('role', 'EMPLOYEE')).upper()
    if mode not in MODES or role not in ('EMPLOYEE', 'ADMIN'):
        return JsonResponse({'error': 'Invalid request'}, status=400)
    if mode == 'link' and not request.user.is_authenticated:
        return JsonResponse({'error': 'Sign in first to connect a Google account.'}, status=401)

    ip = client_ip(request)
    if is_locked('google', ip):
        return JsonResponse({'error': ERROR_MESSAGES['throttled']}, status=429)

    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    request.session[SESSION_KEY] = {
        'state': state, 'nonce': nonce, 'verifier': verifier, 'mode': mode, 'role': role,
        'remember': bool(data.get('remember_me')), 'created': time.time(),
        'user_id': request.user.pk if mode == 'link' else None,
    }
    url = AUTH_ENDPOINT + '?' + urlencode({
        'client_id': settings.GOOGLE_CLIENT_ID,
        'redirect_uri': settings.GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'code_challenge': _pkce_challenge(verifier),
        'code_challenge_method': 'S256',
        'prompt': 'select_account',
    })
    return JsonResponse({'url': url})


def _unique_username(email, given_name):
    base = re.sub(r'[^A-Za-z0-9._-]', '', email.split('@')[0])[:30] or re.sub(r'[^A-Za-z0-9]', '', given_name or '')[:30] or 'user'
    candidate, counter = base, 1
    while User.objects.filter(username__iexact=candidate).exists():
        counter += 1
        candidate = f'{base}{counter}'
    return candidate


def _create_employee_account(claims):
    email = claims['email'].strip().lower()
    with transaction.atomic():
        user = User(
            username=_unique_username(email, claims.get('given_name', '')), email=email,
            first_name=(claims.get('given_name') or '')[:150], last_name=(claims.get('family_name') or '')[:150],
        )
        user.set_unusable_password()   # sign-in is via Google; "Forgot password" can add a password later
        user.save()
        UserProfile.objects.create(user=user, role='EMPLOYEE')
        GoogleIdentity.objects.create(user=user, google_sub=claims['sub'], email=email)
    notify_user(
        user, 'EMPLOYEE', 'Welcome to PayrollPro',
        'Your employee account is ready. An administrator will complete your employment record.',
        'employee-dashboard.html',
    )
    return user


@require_GET
def google_callback(request):
    pending = request.session.pop(SESSION_KEY, None)   # single use, whatever happens next
    mode = pending.get('mode', 'login') if isinstance(pending, dict) else 'login'
    ip = client_ip(request)

    def fail(code):
        register_failure('google', ip)
        return _failure(mode, code)

    if request.GET.get('error'):
        return _failure(mode, 'cancelled' if request.GET['error'] == 'access_denied' else 'google_denied')
    if not isinstance(pending, dict) or time.time() - pending.get('created', 0) > STATE_TTL_SECONDS:
        return fail('invalid_state')
    returned_state = request.GET.get('state', '')
    if not returned_state or not hmac.compare_digest(returned_state.encode(), pending['state'].encode()):
        return fail('invalid_state')
    code = request.GET.get('code', '')
    if not code:
        return fail('exchange_failed')

    try:
        raw = exchange_code(code, pending['verifier'])
        claims = verify_id_token(raw)
    except GoogleFlowError as error:
        return fail(error.code)
    except (http.RequestException, OSError):
        return fail('google_unreachable')
    except ValueError:
        return fail('invalid_token')

    if not hmac.compare_digest(str(claims.get('nonce', '')).encode(), pending['nonce'].encode()):
        return fail('invalid_token')
    sub, email = claims.get('sub'), (claims.get('email') or '').strip().lower()
    if not sub or not email:
        return fail('invalid_token')
    if claims.get('email_verified') is not True:
        return fail('email_unverified')

    try:
        if mode == 'link':
            return _handle_link(request, pending, sub, email, fail)
        return _handle_sign_in(request, pending, claims, sub, email, fail)
    except IntegrityError:   # e.g. two callbacks racing to create the same account
        return fail('server_error')


def _handle_link(request, pending, sub, email, fail):
    user = request.user
    if not user.is_authenticated or user.pk != pending.get('user_id'):
        return fail('link_mismatch')
    if GoogleIdentity.objects.filter(user=user).exists():
        return fail('already_linked')
    if GoogleIdentity.objects.filter(google_sub=sub).exists():
        return fail('google_in_use')
    GoogleIdentity.objects.create(user=user, google_sub=sub, email=email)
    record_audit(request, 'GOOGLE_LINK', 'Account', user.pk, f'{user.username} connected Google account {email}.')
    return _frontend('settings.html', google='linked')


def _handle_sign_in(request, pending, claims, sub, email, fail):
    role = pending['role']
    identity = GoogleIdentity.objects.select_related('user').filter(google_sub=sub).first()
    is_new = False

    if identity is not None:
        user = identity.user
        if not user.is_active:
            return fail('account_disabled')
        if identity.email != email:
            identity.email = email
            identity.save(update_fields=['email'])
    else:
        if User.objects.filter(email__iexact=email).exists():
            return fail('email_exists')          # never auto-link by email (see module docstring)
        if role != 'EMPLOYEE':
            return fail('no_admin_account')      # Google can never create an administrator
        user, is_new = _create_employee_account(claims), True

    blocked = login_block(user, role)
    if blocked:
        message = blocked[0]
        return fail('inactive' if 'inactive' in message else 'no_profile' if 'profile' in message else 'wrong_role')

    clear_failures('google', client_ip(request))
    login(request, user, backend='django.contrib.auth.backends.ModelBackend')
    request.session.set_expiry(settings.SESSION_COOKIE_AGE if pending.get('remember') else 0)
    record_audit(request, 'LOGIN', 'Account', user.pk,
                 f'{user.username} signed in as {role.lower()} with Google{" (new account)" if is_new else ""}.')
    return _frontend('google-callback.html', status='ok', new='1' if is_new else '')


# --- connect / disconnect from Settings ------------------------------------------------------------

@api_view(['GET', 'DELETE'])
def google_link(request):
    identity = GoogleIdentity.objects.filter(user=request.user).first()
    if request.method == 'GET':
        return Response({
            'enabled': is_configured(),
            'connected': identity is not None,
            'email': identity.email if identity else None,
            'has_password': request.user.has_usable_password(),
        })
    if identity is None:
        return Response({'detail': 'No Google account is connected.'}, status=404)
    if not request.user.has_usable_password():
        return Response({'detail': 'Set a password first (use "Forgot password" on the sign-in page), otherwise you would be locked out.'}, status=400)
    identity.delete()
    record_audit(request, 'GOOGLE_UNLINK', 'Account', request.user.pk, f'{request.user.username} disconnected their Google account.')
    return Response(status=204)

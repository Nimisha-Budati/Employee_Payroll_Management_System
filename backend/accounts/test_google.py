"""Tests for Sign in with Google. Google's servers are replaced by mocks, so these prove OUR handling
(state, nonce, account rules, roles, redirects); they cannot prove the Google Cloud configuration."""

from unittest import mock
from urllib.parse import parse_qs, urlparse

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from accounts import google_auth
from accounts.models import Employee, GoogleIdentity, UserProfile
from accounts.test_utils import test_company

FRONTEND = 'http://127.0.0.1:5500'
CONFIG = dict(
    GOOGLE_CLIENT_ID='client-id.apps.googleusercontent.com', GOOGLE_CLIENT_SECRET='secret',
    GOOGLE_REDIRECT_URI='http://127.0.0.1:8000/api/auth/google/callback/', FRONTEND_URL=FRONTEND,
)


def claims(**overrides):
    base = {'iss': 'https://accounts.google.com', 'sub': 'google-sub-1', 'email': 'new.person@gmail.com',
            'email_verified': True, 'given_name': 'New', 'family_name': 'Person', 'nonce': 'will-be-replaced'}
    base.update(overrides)
    return base


@override_settings(**CONFIG)
class GoogleLoginTests(TestCase):
    def setUp(self):
        cache.clear()   # throttle counters live in the cache
        self.client = Client()

    # helpers ---------------------------------------------------------------------------------
    def start(self, client=None, **payload):
        client = client or self.client
        response = client.post('/api/auth/google/start/', payload or {'mode': 'login', 'role': 'EMPLOYEE'}, content_type='application/json')
        return response

    def callback(self, token_claims=None, client=None, state=None, **extra):
        """Run start -> callback with Google's answers mocked. Returns the callback response."""
        client = client or self.client
        session = client.session[google_auth.SESSION_KEY]
        sent = dict(token_claims if token_claims is not None else claims())
        sent.setdefault('nonce', session['nonce'])
        if sent.get('nonce') == 'will-be-replaced':
            sent['nonce'] = session['nonce']
        params = {'code': 'abc', 'state': state or session['state']}
        params.update(extra)
        with mock.patch.object(google_auth, 'exchange_code', return_value='raw'), \
                mock.patch.object(google_auth, 'verify_id_token', return_value=sent):
            return client.get('/api/auth/google/callback/', params)

    def employee(self, username='asha', email='asha@example.com', with_record=False):
        user = User.objects.create_user(username, email, 'EmployeePass123!')
        UserProfile.objects.create(user=user, role='EMPLOYEE', company=test_company())
        if with_record:
            Employee.objects.create(user=user, company=test_company(), employee_id='EMP1', phone='9876543210', department='Eng',
                                    designation='Dev', joining_date='2024-01-01')
        return user

    def admin(self):
        user = User.objects.create_user('boss', 'boss@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=user, role='ADMIN', company=test_company())
        return user

    def location(self, response):
        return response['Location']

    # start endpoint ---------------------------------------------------------------------------
    def test_start_builds_secure_google_url(self):
        response = self.start()
        self.assertEqual(response.status_code, 200)
        url = urlparse(response.json()['url'])
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        self.assertEqual((url.scheme, url.netloc), ('https', 'accounts.google.com'))
        self.assertEqual(query['client_id'], CONFIG['GOOGLE_CLIENT_ID'])
        self.assertEqual(query['redirect_uri'], CONFIG['GOOGLE_REDIRECT_URI'])
        self.assertEqual(query['code_challenge_method'], 'S256')
        self.assertEqual(query['response_type'], 'code')
        self.assertNotIn('client_secret', url.query)
        session = self.client.session[google_auth.SESSION_KEY]
        self.assertEqual(query['state'], session['state'])
        self.assertEqual(query['nonce'], session['nonce'])
        self.assertEqual(query['code_challenge'], google_auth._pkce_challenge(session['verifier']))

    def test_start_requires_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        response = strict.post('/api/auth/google/start/', {'mode': 'login'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_start_rejects_bad_input_and_get(self):
        self.assertEqual(self.start(mode='nope').status_code, 400)
        self.assertEqual(self.start(mode='login', role='SUPERUSER').status_code, 400)
        self.assertEqual(self.client.get('/api/auth/google/start/').status_code, 405)

    def test_start_link_requires_login(self):
        self.assertEqual(self.start(mode='link').status_code, 401)

    @override_settings(GOOGLE_CLIENT_ID='')
    def test_not_configured(self):
        self.assertEqual(self.client.get('/api/auth/google/config/').json(), {'enabled': False})
        self.assertEqual(self.start().status_code, 503)

    def test_config_enabled(self):
        self.assertEqual(self.client.get('/api/auth/google/config/').json(), {'enabled': True})

    # new account ------------------------------------------------------------------------------
    def test_new_google_user_becomes_plain_employee_and_is_signed_in(self):
        self.start()
        response = self.callback()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.location(response).startswith(f'{FRONTEND}/google-callback.html?status=ok'))
        user = User.objects.get(email='new.person@gmail.com')
        self.assertFalse(user.has_usable_password())
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(user.userprofile.role, 'EMPLOYEE')
        self.assertFalse(Employee.objects.filter(user=user).exists())        # admin still onboards them
        self.assertEqual(user.google_identity.google_sub, 'google-sub-1')
        self.assertEqual(self.client.get('/api/profile/').json()['role'], 'EMPLOYEE')   # real session

    def test_register_mode_cannot_request_admin(self):
        self.start(mode='register', role='ADMIN')
        self.callback()
        self.assertEqual(User.objects.get(email='new.person@gmail.com').userprofile.role, 'EMPLOYEE')

    def test_admin_login_never_creates_an_account(self):
        self.start(mode='login', role='ADMIN')
        response = self.callback()
        self.assertIn('google_error=no_admin_account', self.location(response))
        self.assertFalse(User.objects.filter(email='new.person@gmail.com').exists())

    def test_unique_username_generated(self):
        User.objects.create_user('new.person', 'someone@else.com', 'x')
        self.start(); self.callback()
        self.assertEqual(User.objects.get(email='new.person@gmail.com').username, 'new.person2')

    # existing accounts -------------------------------------------------------------------------
    def test_existing_email_is_not_auto_linked(self):
        victim = self.employee(email='new.person@gmail.com')
        self.start()
        response = self.callback()
        self.assertIn('google_error=email_exists', self.location(response))
        self.assertFalse(GoogleIdentity.objects.exists())
        self.assertNotIn('_auth_user_id', self.client.session)
        victim.refresh_from_db(); self.assertTrue(victim.has_usable_password())

    def test_linked_user_signs_in_without_duplicate(self):
        user = self.employee(with_record=True)
        GoogleIdentity.objects.create(user=user, google_sub='google-sub-1', email='old@gmail.com')
        self.start()
        response = self.callback()
        self.assertIn('status=ok', self.location(response))
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(GoogleIdentity.objects.get().email, 'new.person@gmail.com')

    def test_linked_admin_can_use_google_as_admin_only(self):
        admin = self.admin()
        GoogleIdentity.objects.create(user=admin, google_sub='google-sub-1', email='boss@gmail.com')
        self.start(mode='login', role='ADMIN')
        self.assertIn('status=ok', self.location(self.callback()))
        self.assertEqual(self.client.get('/api/dashboard/admin/').status_code, 200)

    def test_role_mismatch_blocks_login(self):
        admin = self.admin()
        GoogleIdentity.objects.create(user=admin, google_sub='google-sub-1', email='boss@gmail.com')
        self.start(mode='login', role='EMPLOYEE')   # admin trying the employee door
        self.assertIn('google_error=wrong_role', self.location(self.callback()))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_inactive_employee_and_disabled_user_blocked(self):
        user = self.employee(with_record=True)
        GoogleIdentity.objects.create(user=user, google_sub='google-sub-1', email='a@gmail.com')
        Employee.objects.filter(user=user).update(status='INACTIVE')
        self.start()
        self.assertIn('google_error=inactive', self.location(self.callback()))
        Employee.objects.filter(user=user).update(status='ACTIVE')
        User.objects.filter(pk=user.pk).update(is_active=False)
        self.start()
        self.assertIn('google_error=account_disabled', self.location(self.callback()))

    def test_employee_cannot_reach_admin_api_after_google_login(self):
        self.start(); self.callback()
        self.assertEqual(self.client.get('/api/dashboard/admin/').status_code, 403)
        self.assertEqual(self.client.get('/api/payroll/salary-structures/').status_code, 403)

    # link / unlink -----------------------------------------------------------------------------
    def test_link_flow_and_unlink_rules(self):
        user = self.employee()
        self.client.force_login(user)
        self.start(mode='link')
        response = self.callback(claims(sub='sub-link', email='asha@gmail.com'))
        self.assertIn('google=linked', self.location(response))
        status = self.client.get('/api/auth/google/link/').json()
        self.assertEqual((status['connected'], status['email'], status['has_password']), (True, 'asha@gmail.com', True))
        self.assertEqual(self.client.delete('/api/auth/google/link/').status_code, 204)
        self.assertFalse(GoogleIdentity.objects.exists())

    def test_cannot_link_google_account_used_by_someone_else(self):
        other = self.employee('other', 'other@example.com')
        GoogleIdentity.objects.create(user=other, google_sub='shared', email='o@gmail.com')
        me = self.employee()
        self.client.force_login(me)
        self.start(mode='link')
        self.assertIn('google_error=google_in_use', self.location(self.callback(claims(sub='shared'))))

    def test_link_fails_if_session_user_changed(self):
        first, second = self.employee(), self.employee('second', 'second@example.com')
        self.client.force_login(first)
        self.start(mode='link')
        state = self.client.session[google_auth.SESSION_KEY]['state']
        self.client.force_login(second)   # different user (a new session) -> pending state is gone
        response = self.client.get('/api/auth/google/callback/', {'code': 'x', 'state': state})
        self.assertIn('google_error=invalid_state', self.location(response))
        self.assertFalse(GoogleIdentity.objects.exists())

    def test_google_only_user_cannot_unlink(self):
        self.start(); self.callback()
        self.assertEqual(self.client.delete('/api/auth/google/link/').status_code, 400)
        self.assertTrue(GoogleIdentity.objects.exists())

    # callback security ---------------------------------------------------------------------------
    def test_wrong_state_rejected_and_nothing_created(self):
        self.start()
        response = self.callback(state='forged')
        self.assertIn('google_error=invalid_state', self.location(response))
        self.assertFalse(User.objects.exists())

    def test_state_is_single_use(self):
        self.start()
        session = self.client.session[google_auth.SESSION_KEY]
        self.callback()
        replay = self.client.get('/api/auth/google/callback/', {'code': 'abc', 'state': session['state']})
        self.assertIn('google_error=invalid_state', self.location(replay))

    def test_callback_without_start_rejected(self):
        response = Client().get('/api/auth/google/callback/', {'code': 'abc', 'state': 'x'})
        self.assertIn('google_error=invalid_state', self.location(response))

    def test_expired_state_rejected(self):
        self.start()
        session = self.client.session
        session[google_auth.SESSION_KEY]['created'] -= 3600
        session.save()
        self.assertIn('google_error=invalid_state', self.location(self.callback()))

    def test_wrong_nonce_rejected(self):
        self.start()
        self.assertIn('google_error=invalid_token', self.location(self.callback(claims(nonce='someone-elses'))))
        self.assertFalse(User.objects.exists())

    def test_unverified_email_rejected(self):
        self.start()
        self.assertIn('google_error=email_unverified', self.location(self.callback(claims(email_verified=False))))
        self.assertFalse(User.objects.exists())

    def test_user_cancelled_at_google(self):
        self.start()
        response = self.client.get('/api/auth/google/callback/', {'error': 'access_denied', 'state': 'x'})
        self.assertIn('google_error=cancelled', self.location(response))

    def test_token_verification_failure_and_network_failure(self):
        self.start()
        with mock.patch.object(google_auth, 'exchange_code', return_value='raw'), \
                mock.patch.object(google_auth, 'verify_id_token', side_effect=ValueError('bad signature')):
            response = self.client.get('/api/auth/google/callback/', {'code': 'abc', 'state': self.client.session[google_auth.SESSION_KEY]['state']})
        self.assertIn('google_error=invalid_token', self.location(response))
        self.start()
        with mock.patch.object(google_auth, 'exchange_code', side_effect=requests.ConnectionError()):
            response = self.client.get('/api/auth/google/callback/', {'code': 'abc', 'state': self.client.session[google_auth.SESSION_KEY]['state']})
        self.assertIn('google_error=google_unreachable', self.location(response))
        self.assertFalse(User.objects.exists())

    def test_exchange_failure_from_google(self):
        self.start()
        bad = mock.Mock(status_code=400)
        with mock.patch.object(google_auth.http, 'post', return_value=bad):
            response = self.client.get('/api/auth/google/callback/', {'code': 'abc', 'state': self.client.session[google_auth.SESSION_KEY]['state']})
        self.assertIn('google_error=exchange_failed', self.location(response))

    def test_verify_rejects_wrong_issuer(self):
        with mock.patch.object(google_auth.google_id_token, 'verify_oauth2_token', return_value={'iss': 'https://evil.example'}):
            with self.assertRaises(ValueError):
                google_auth.verify_id_token('raw')

    def test_redirects_only_go_to_configured_frontend(self):
        self.start()
        for params in ({'error': 'access_denied'}, {'code': 'x', 'state': 'bad', 'next': 'https://evil.example'}):
            self.start()
            response = self.client.get('/api/auth/google/callback/', params)
            self.assertTrue(self.location(response).startswith(FRONTEND + '/'), self.location(response))

    def test_repeated_failures_throttle_start(self):
        for _ in range(5):
            Client().get('/api/auth/google/callback/', {'code': 'x', 'state': 'y'})
        self.assertEqual(self.start().status_code, 429)

    # existing auth keeps working ----------------------------------------------------------------
    def test_password_login_unaffected(self):
        self.employee()
        ok = self.client.post('/api/login/', {'username': 'asha', 'password': 'EmployeePass123!', 'role': 'EMPLOYEE'}, content_type='application/json')
        self.assertEqual(ok.status_code, 200)
        bad = Client().post('/api/login/', {'username': 'asha', 'password': 'nope', 'role': 'EMPLOYEE'}, content_type='application/json')
        self.assertEqual(bad.status_code, 401)
        wrong_role = Client().post('/api/login/', {'username': 'asha', 'password': 'EmployeePass123!', 'role': 'ADMIN'}, content_type='application/json')
        self.assertEqual(wrong_role.status_code, 403)

    def test_google_only_account_cannot_password_login(self):
        self.start(); self.callback()
        Client().get('/')
        response = Client().post('/api/login/', {'username': 'new.person', 'password': '', 'role': 'EMPLOYEE'}, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        response = Client().post('/api/login/', {'username': 'new.person', 'password': 'anything-else-1', 'role': 'EMPLOYEE'}, content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_logout_ends_google_session(self):
        self.start(); self.callback()
        self.assertEqual(self.client.get('/api/profile/').status_code, 200)
        self.client.post('/api/logout/')
        self.assertEqual(self.client.get('/api/profile/').status_code, 401)

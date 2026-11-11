from datetime import date
from django.contrib.auth.models import User
from django.contrib.auth.hashers import is_password_usable
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Company, Employee, UserProfile
from .test_utils import test_company


class CompanyRegistrationAndAdminAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_company_registration_with_explicit_username(self):
        payload = {
            'company_name': 'Acme Corp',
            'company_email': 'contact@acmecorp.com',
            'admin_username': 'acme_admin',
            'admin_name': 'Alice Smith',
            'admin_email': 'alice@acmecorp.com',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
        }
        response = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data['company_name'], 'Acme Corp')
        self.assertEqual(data['username'], 'acme_admin')
        self.assertEqual(data['role'], 'ADMIN')

        # Verify DB records
        company = Company.objects.get(name='Acme Corp')
        self.assertEqual(company.email, 'contact@acmecorp.com')
        admin_user = User.objects.get(username='acme_admin')
        self.assertEqual(admin_user.email, 'alice@acmecorp.com')
        self.assertEqual(admin_user.first_name, 'Alice')
        self.assertEqual(admin_user.last_name, 'Smith')
        self.assertTrue(admin_user.is_active)
        self.assertTrue(admin_user.check_password('SecurePassword123!'))
        self.assertNotEqual(admin_user.password, 'SecurePassword123!')
        self.assertTrue(is_password_usable(admin_user.password))

        # Verify profile and role association
        profile = UserProfile.objects.get(user=admin_user)
        self.assertEqual(profile.role, 'ADMIN')
        self.assertEqual(profile.company, company)

    def test_company_registration_generates_username_if_omitted(self):
        payload = {
            'company_name': 'Beta Tech',
            'company_email': 'info@betatech.io',
            'admin_name': 'Bob Jones',
            'admin_email': 'bob.jones@betatech.io',
            'password': 'SecurePassword123!',
            'confirm_password': 'SecurePassword123!',
        }
        response = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data['username'].startswith('bob.jones') or data['username'].startswith('bob'))

        admin_user = User.objects.get(email='bob.jones@betatech.io')
        self.assertEqual(admin_user.username, data['username'])

    def test_admin_can_login_via_username_email_and_company_email(self):
        payload = {
            'company_name': 'Gamma Labs',
            'company_email': 'support@gammalabs.org',
            'admin_username': 'gamma_boss',
            'admin_name': 'Gary Miller',
            'admin_email': 'gary@gammalabs.org',
            'password': 'GammaPassword123!',
            'confirm_password': 'GammaPassword123!',
        }
        reg_response = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(reg_response.status_code, 201)

        # 1. Login with username
        client1 = APIClient()
        r1 = client1.post('/api/login/', {
            'username': 'gamma_boss',
            'password': 'GammaPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['role'], 'ADMIN')

        # Logout
        client1.post('/api/logout/')

        # 2. Login with admin personal email
        client2 = APIClient()
        r2 = client2.post('/api/login/', {
            'username': 'gary@gammalabs.org',
            'password': 'GammaPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['username'], 'gamma_boss')

        # 3. Login with company email
        client3 = APIClient()
        r3 = client3.post('/api/login/', {
            'username': 'support@gammalabs.org',
            'password': 'GammaPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()['username'], 'gamma_boss')

    def test_role_mismatch_blocks_admin_as_employee(self):
        payload = {
            'company_name': 'Delta Corp',
            'company_email': 'hello@deltacorp.com',
            'admin_username': 'delta_admin',
            'admin_name': 'Donna Troy',
            'admin_email': 'donna@deltacorp.com',
            'password': 'DeltaPassword123!',
            'confirm_password': 'DeltaPassword123!',
        }
        reg = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(reg.status_code, 201)

        login_client = APIClient()
        response = login_client.post('/api/login/', {
            'username': 'donna@deltacorp.com',
            'password': 'DeltaPassword123!',
            'role': 'EMPLOYEE',
        }, format='json')
        self.assertEqual(response.status_code, 403)

        success = login_client.post('/api/login/', {
            'username': 'donna@deltacorp.com',
            'password': 'DeltaPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()['role'], 'ADMIN')

    def test_login_tolerates_clipboard_trailing_spaces_and_newlines(self):
        payload = {
            'company_name': 'Zeta Cloud',
            'company_email': 'contact@zetaclouddemo.com',
            'admin_username': 'zeta_admin',
            'admin_name': 'Zack Taylor',
            'admin_email': 'zack@zetaclouddemo.com',
            'password': 'ZetaPassword123!',
            'confirm_password': 'ZetaPassword123!',
        }
        self.client.post('/api/companies/register/', payload, format='json')

        login_client = APIClient()
        # Trailing space from mobile clipboard
        res_space = login_client.post('/api/login/', {
            'username': 'zeta_admin',
            'password': 'ZetaPassword123! ',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(res_space.status_code, 200)

        login_client.post('/api/logout/')

        # Trailing newline from mobile clipboard
        res_nl = login_client.post('/api/login/', {
            'username': 'zack@zetaclouddemo.com',
            'password': 'ZetaPassword123!\n',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(res_nl.status_code, 200)

    def test_login_normalizes_identifier_whitespace(self):
        payload = {
            'company_name': 'Eta Works',
            'company_email': 'contact@etaworksdemo.com',
            'admin_username': 'eta_admin',
            'admin_name': 'Evan Stone',
            'admin_email': 'evan@etaworksdemo.com',
            'password': 'EtaPassword123!',
            'confirm_password': 'EtaPassword123!',
        }
        self.client.post('/api/companies/register/', payload, format='json')

        login_client = APIClient()
        # Non-breaking space \u00a0 in identifier from copy-paste
        res = login_client.post('/api/login/', {
            'username': '  eta_admin\u00a0 ',
            'password': 'EtaPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(res.status_code, 200)

    def test_duplicate_company_or_admin_registration_rejected(self):
        payload = {
            'company_name': 'Echo Systems',
            'company_email': 'contact@echosys.com',
            'admin_username': 'echo_admin',
            'admin_name': 'Echo Leader',
            'admin_email': 'echo@echosys.com',
            'password': 'EchoPassword123!',
            'confirm_password': 'EchoPassword123!',
        }
        first = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(first.status_code, 201)

        # Same company name
        dup_comp = self.client.post('/api/companies/register/', {
            **payload,
            'admin_email': 'other@echosys.com',
            'admin_username': 'echo_admin_2',
        }, format='json')
        self.assertEqual(dup_comp.status_code, 400)
        self.assertIn('already registered', dup_comp.json()['error'].lower())

        # Same admin email
        dup_email = self.client.post('/api/companies/register/', {
            **payload,
            'company_name': 'Different Company',
            'company_email': 'diff@diff.com',
            'admin_username': 'echo_admin_3',
        }, format='json')
        self.assertEqual(dup_email.status_code, 400)
        self.assertIn('administrator email', dup_email.json()['error'].lower())

    def test_invalid_admin_username_rejected(self):
        payload = {
            'company_name': 'Foxtrot Ltd',
            'company_email': 'hi@foxtrot.com',
            'admin_username': 'invalid username with spaces!',
            'admin_name': 'Frank Miller',
            'admin_email': 'frank@foxtrot.com',
            'password': 'FoxtrotPassword123!',
            'confirm_password': 'FoxtrotPassword123!',
        }
        res = self.client.post('/api/companies/register/', payload, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('letters, numbers', res.json()['error'])


class EmployeeRegistrationAndAuthTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Acme Testing Inc', email='info@acmetest.org')
        self.other_company = Company.objects.create(name='Other Enterprises', email='info@other.org')

    def test_employee_signup_with_valid_company(self):
        payload = {
            'company_id': self.company.id,
            'username': 'john_doe',
            'email': 'john.doe@acmetest.org',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
        }
        response = self.client.post('/api/register/', payload, format='json')
        self.assertEqual(response.status_code, 201)

        user = User.objects.get(username='john_doe')
        self.assertEqual(user.email, 'john.doe@acmetest.org')
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password('StrongPassword123!'))

        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.role, 'EMPLOYEE')
        self.assertEqual(profile.company, self.company)

    def test_employee_can_login_with_username_and_email(self):
        payload = {
            'company_id': self.company.id,
            'username': 'jane_doe',
            'email': 'jane.doe@acmetest.org',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
        }
        self.client.post('/api/register/', payload, format='json')

        # Login with username
        c1 = APIClient()
        r1 = c1.post('/api/login/', {
            'username': 'jane_doe',
            'password': 'StrongPassword123!',
            'role': 'EMPLOYEE',
        }, format='json')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()['role'], 'EMPLOYEE')

        # Login with email
        c2 = APIClient()
        r2 = c2.post('/api/login/', {
            'username': 'jane.doe@acmetest.org',
            'password': 'StrongPassword123!',
            'role': 'EMPLOYEE',
        }, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['username'], 'jane_doe')

    def test_employee_with_employment_record_can_restore_missing_profile_at_login(self):
        user = User.objects.create_user('legacy_employee', email='legacy@acmetest.org', password='StrongPassword123!')
        Employee.objects.create(
            user=user, company=self.company, employee_id='LEGACY-1', phone='9876543210',
            department='Operations', designation='Analyst', joining_date=date(2026, 1, 1),
        )

        response = self.client.post('/api/login/', {
            'username': 'legacy_employee', 'password': 'StrongPassword123!', 'role': 'EMPLOYEE',
        }, format='json')

        self.assertEqual(response.status_code, 200, response.json())
        profile = UserProfile.objects.get(user=user)
        self.assertEqual(profile.role, 'EMPLOYEE')
        self.assertEqual(profile.company_id, self.company.pk)
        self.assertEqual(profile.phone, '9876543210')
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)

    def test_employee_cannot_register_or_login_as_admin(self):
        # 1. Attempt register with role=ADMIN
        res = self.client.post('/api/register/', {
            'company_id': self.company.id,
            'username': 'sneaky_user',
            'email': 'sneaky@acmetest.org',
            'password': 'SneakyPassword123!',
            'confirm_password': 'SneakyPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(res.status_code, 403)

        # 2. Register as regular employee
        res2 = self.client.post('/api/register/', {
            'company_id': self.company.id,
            'username': 'regular_emp',
            'email': 'regular@acmetest.org',
            'password': 'SneakyPassword123!',
            'confirm_password': 'SneakyPassword123!',
            'role': 'EMPLOYEE',
        }, format='json')
        self.assertEqual(res2.status_code, 201)

        # 3. Attempt login choosing role=ADMIN
        login_client = APIClient()
        admin_login = login_client.post('/api/login/', {
            'username': 'regular_emp',
            'password': 'SneakyPassword123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(admin_login.status_code, 403)

    def test_employee_signup_fails_with_invalid_company(self):
        payload = {
            'company_id': 999999,
            'username': 'no_company_user',
            'email': 'nocompany@example.com',
            'password': 'StrongPassword123!',
            'confirm_password': 'StrongPassword123!',
        }
        response = self.client.post('/api/register/', payload, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('company', response.json()['error'].lower())

    def test_employee_tenant_isolation(self):
        # Create employees in different companies
        user1 = User.objects.create_user('emp1', 'emp1@acmetest.org', 'Pass12345!')
        UserProfile.objects.create(user=user1, role='EMPLOYEE', company=self.company)
        Employee.objects.create(user=user1, company=self.company, employee_id='EMP-001', department='Engineering', joining_date=date(2025, 1, 1))

        user2 = User.objects.create_user('emp2', 'emp2@other.org', 'Pass12345!')
        UserProfile.objects.create(user=user2, role='EMPLOYEE', company=self.other_company)
        Employee.objects.create(user=user2, company=self.other_company, employee_id='EMP-002', department='HR', joining_date=date(2025, 1, 1))

        # Employee cannot access employee management API
        client = APIClient()
        client.force_authenticate(user1)
        res = client.get('/api/employees/')
        self.assertEqual(res.status_code, 403)

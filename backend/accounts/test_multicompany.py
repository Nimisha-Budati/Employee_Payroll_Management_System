from importlib import import_module
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .leave_policy import leave_balance_for, policy_settings
from .models import (
    Announcement, AttendanceRecord, AttendanceSettings, Company, Employee, EmployeeDocument, Holiday,
    LeaveRequest, LeaveType, Notification, NotificationBroadcast, ReminderSettings, UserProfile,
    WorkFromHomeRequest,
)
from assistant.models import AIConversation, AIKnowledgeBase
from payroll.models import Payslip, SalaryStructure
from workforce.models import OvertimeRecord, Shift, ShiftAssignment
from .reminders import run_reminders


class LeavePolicySequenceMigrationTests(SimpleTestCase):
    def test_migration_resets_sequences_for_company_registration_tables(self):
        migration = import_module('accounts.migrations.0028_reset_company_registration_sequences')

        apps = MagicMock()
        apps.get_model.side_effect = lambda app_label, model_name: (app_label, model_name)
        cursor = MagicMock()
        connection = MagicMock()
        connection.ops.sequence_reset_sql.return_value = ['RESET FIRST TEST SEQUENCE', 'RESET SECOND TEST SEQUENCE']
        connection.cursor.return_value.__enter__.return_value = cursor
        schema_editor = MagicMock(connection=connection)

        migration.reset_company_registration_sequences(apps, schema_editor)

        expected_models = [
            ('accounts', 'Company'), ('accounts', 'UserProfile'), ('accounts', 'LeavePolicySettings'),
            ('accounts', 'OnboardingSettings'), ('accounts', 'ReminderSettings'),
            ('accounts', 'AttendanceSettings'), ('accounts', 'LeaveType'),
            ('auth', 'User'), ('assistant', 'AIKnowledgeBase'),
        ]
        self.assertEqual([call.args for call in apps.get_model.call_args_list], expected_models)
        self.assertEqual(connection.ops.sequence_reset_sql.call_args.args[1], expected_models)
        self.assertEqual(cursor.execute.call_args_list, [
            call('RESET FIRST TEST SEQUENCE'),
            call('RESET SECOND TEST SEQUENCE'),
        ])


class CompanyPolicyAndReminderIsolationTests(TestCase):
    def setUp(self):
        self.alpha = Company.objects.create(name='Alpha Services', email='alpha@isolation.example')
        self.beta = Company.objects.create(name='Beta Services', email='beta@isolation.example')
        self.alpha_admin = self._user('alpha-admin', self.alpha, 'ADMIN')
        self.beta_admin = self._user('beta-admin', self.beta, 'ADMIN')
        self.alpha_employee = self._user('alpha-employee', self.alpha, 'EMPLOYEE')
        self.beta_employee = self._user('beta-employee', self.beta, 'EMPLOYEE')
        self.alpha_type = LeaveType.objects.create(company=self.alpha, name='Annual', annual_days=10)
        self.beta_type = LeaveType.objects.create(company=self.beta, name='Annual', annual_days=30)
        self.alpha_rules = policy_settings(self.alpha)
        self.alpha_rules.leave_year_start_month = 4
        self.alpha_rules.save()
        self.beta_rules = policy_settings(self.beta)
        self.beta_rules.leave_year_start_month = 1
        self.beta_rules.save()
        self.alpha_reminders = ReminderSettings.load(self.alpha)
        self.alpha_reminders.pending_after_days = 1
        self.alpha_reminders.save()
        self.beta_reminders = ReminderSettings.load(self.beta)
        self.beta_reminders.pending_after_days = 30
        self.beta_reminders.save()

        now = timezone.now()
        for user, leave_type in (
            (self.alpha_employee, self.alpha_type),
            (self.beta_employee, self.beta_type),
        ):
            request = LeaveRequest.objects.create(
                employee=user, leave_type=leave_type.name, policy=leave_type,
                start_date=timezone.localdate(), end_date=timezone.localdate(),
                reason='Tenant isolation test',
            )
            LeaveRequest.objects.filter(pk=request.pk).update(applied_at=now - timedelta(days=5))

    @staticmethod
    def _user(username, company, role):
        user = User.objects.create_user(username, password='StrongTestPassword123!')
        UserProfile.objects.create(user=user, role=role, company=company)
        return user

    def test_leave_policy_and_balances_use_each_users_company(self):
        alpha_balance = leave_balance_for(self.alpha_employee, 2026)
        beta_balance = leave_balance_for(self.beta_employee, 2026)

        self.assertEqual(alpha_balance['Annual']['total'], 10)
        self.assertEqual(beta_balance['Annual']['total'], 30)
        self.assertEqual(policy_settings(self.alpha).leave_year_start_month, 4)
        self.assertEqual(policy_settings(self.beta).leave_year_start_month, 1)

    def test_reminders_only_digest_the_requested_company(self):
        result = run_reminders(company=self.alpha)
        alpha_messages = Notification.objects.filter(recipient=self.alpha_admin, title='Requests waiting for approval')

        self.assertEqual(result['pending_digest'], 1)
        self.assertEqual(alpha_messages.count(), 1)
        self.assertFalse(Notification.objects.filter(recipient=self.beta_admin).exists())

        no_company = run_reminders()
        self.assertFalse(no_company['enabled'])
        self.assertFalse(Notification.objects.filter(recipient=self.beta_admin).exists())


class CompanyRegistrationSecurityTests(TestCase):
    def payload(self, **overrides):
        return {
            'company_name': 'Northwind Payroll',
            'company_email': 'payroll@northwind.example',
            'admin_name': 'Morgan Admin',
            'admin_email': 'morgan@northwind.example',
            'password': 'A-Strong-Passphrase-2026!',
            'confirm_password': 'A-Strong-Passphrase-2026!',
            **overrides,
        }

    def test_company_registration_creates_tenant_admin_and_defaults_together(self):
        response = self.client.post('/api/companies/register/', self.payload(), content_type='application/json')

        self.assertEqual(response.status_code, 201)
        company = Company.objects.get(email='payroll@northwind.example')
        admin = User.objects.get(email='morgan@northwind.example')
        self.assertEqual(admin.userprofile.role, 'ADMIN')
        self.assertEqual(admin.userprofile.company_id, company.pk)
        self.assertEqual(LeaveType.objects.filter(company=company).count(), 4)
        self.assertTrue(AIKnowledgeBase.objects.filter(company=company).exists())
        self.assertTrue(AttendanceSettings.objects.filter(company=company).exists())

    def test_registration_validates_password_against_the_account_that_will_be_created(self):
        User.objects.create_user(username='morgan', email='existing@northwind.example', password='Existing-Passphrase-2026!')

        with patch('accounts.auth_views.password_error', return_value=None) as validate_password:
            response = self.client.post(
                '/api/companies/register/',
                self.payload(password='A-Genuinely-Unrelated-Passphrase-2026!',
                             confirm_password='A-Genuinely-Unrelated-Passphrase-2026!'),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 201)
        candidate_user = validate_password.call_args.args[1]
        self.assertEqual(candidate_user.username, 'morgan1')
        self.assertEqual(candidate_user.first_name, 'Morgan')
        self.assertEqual(candidate_user.last_name, 'Admin')

    def test_duplicate_company_email_is_rejected_case_insensitively(self):
        Company.objects.create(name='Existing', email='existing@northwind.example')
        company_count = Company.objects.count()

        response = self.client.post(
            '/api/companies/register/',
            self.payload(company_email='EXISTING@NORTHWIND.EXAMPLE'),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(Company.objects.count(), company_count)
        self.assertFalse(User.objects.filter(email='morgan@northwind.example').exists())

    def test_failed_company_seeding_rolls_back_company_and_admin(self):
        with patch('assistant.models.AIKnowledgeBase.objects.create', side_effect=RuntimeError('seed failure')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/companies/register/', self.payload(), content_type='application/json')

        self.assertFalse(Company.objects.filter(email='payroll@northwind.example').exists())
        self.assertFalse(User.objects.filter(email='morgan@northwind.example').exists())

    def test_public_employee_registration_cannot_escalate_to_admin(self):
        response = self.client.post('/api/register/', {
            'username': 'public-admin', 'email': 'public-admin@northwind.example',
            'password': 'A-Strong-Passphrase-2026!', 'confirm_password': 'A-Strong-Passphrase-2026!',
            'role': 'ADMIN',
        }, content_type='application/json')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(email='public-admin@northwind.example').exists())


class TenantAPIAccessTests(TestCase):
    def setUp(self):
        self.alpha = Company.objects.create(name='Alpha Services', email='alpha-api@example.test')
        self.beta = Company.objects.create(name='Beta Services', email='beta-api@example.test')
        self.alpha_admin = self._user('alpha-api-admin', self.alpha, 'ADMIN')
        self.beta_admin = self._user('beta-api-admin', self.beta, 'ADMIN')
        self.alpha_employee = self._employee('alpha-api-employee', self.alpha, 'SHARED-01')
        self.beta_employee = self._employee('beta-api-employee', self.beta, 'BETA-01')
        self.client = APIClient()
        self.client.force_authenticate(user=self.alpha_admin)

        self.beta_leave_type = LeaveType.objects.create(company=self.beta, name='Beta confidential leave', annual_days=5)
        self.beta_leave = LeaveRequest.objects.create(
            employee=self.beta_employee.user, leave_type=self.beta_leave_type.name, policy=self.beta_leave_type,
            start_date=date(2026, 11, 2), end_date=date(2026, 11, 2), reason='BETA-PRIVATE-LEAVE',
        )
        self.beta_holiday = Holiday.objects.create(company=self.beta, name='BETA-PRIVATE-HOLIDAY', date=date(2026, 11, 3))
        self.beta_announcement = Announcement.objects.create(
            company=self.beta, created_by=self.beta_admin, title='BETA-PRIVATE-ANNOUNCEMENT', message='private',
        )
        self.beta_attendance = AttendanceRecord.objects.create(
            employee=self.beta_employee.user, date=date(2026, 10, 20),
        )
        self.beta_document = EmployeeDocument.objects.create(
            employee=self.beta_employee.user, title='BETA-PRIVATE-DOCUMENT', document_type='OTHER', file='private.pdf',
        )
        self.beta_salary = SalaryStructure.objects.create(
            employee=self.beta_employee.user, basic=Decimal('5000'), effective_from=date(2026, 1, 1),
        )
        self.beta_payslip = Payslip.objects.create(
            employee=self.beta_employee.user, year=2026, month=1, employee_code='SHARED-01',
            employee_name='BETA-PRIVATE-EMPLOYEE', gross_earnings=Decimal('5000'), net_salary=Decimal('5000'),
        )
        self.beta_payslip.status = Payslip.PAID
        self.beta_payslip.save(update_fields=['status'])
        self.alpha_payslip = Payslip.objects.create(
            employee=self.alpha_employee.user, year=2026, month=1, employee_code='SHARED-01',
            employee_name='ALPHA-PRIVATE-EMPLOYEE', gross_earnings=Decimal('3000'), net_salary=Decimal('3000'),
            status=Payslip.PAID,
        )
        self.beta_shift = Shift.objects.create(
            company=self.beta, name='BETA-PRIVATE-SHIFT', start_time='09:00', end_time='17:00',
        )
        self.beta_assignment = ShiftAssignment.objects.create(
            employee=self.beta_employee.user, shift=self.beta_shift, start_date=date(2026, 1, 1),
        )
        self.beta_overtime = OvertimeRecord.objects.create(
            employee=self.beta_employee.user, date=date(2026, 10, 20), hours=2, reason='BETA-PRIVATE-OVERTIME',
        )
        self.beta_broadcast = NotificationBroadcast.objects.create(
            company=self.beta, title='BETA-PRIVATE-BROADCAST', message='private', target_type='ALL',
            created_by=self.beta_admin,
        )
        self.beta_knowledge = AIKnowledgeBase.objects.create(company=self.beta, company_overview='BETA-PRIVATE-KNOWLEDGE')
        self.beta_conversation = AIConversation.objects.create(user=self.beta_admin, feature=AIConversation.CHAT)
        WorkFromHomeRequest.objects.create(
            employee=self.beta_employee.user, start_date=date(2026, 11, 4), end_date=date(2026, 11, 4),
            reason='BETA-PRIVATE-WFH',
        )

    @staticmethod
    def _user(username, company, role):
        user = User.objects.create_user(username, password='StrongTestPassword123!')
        UserProfile.objects.create(user=user, role=role, company=company)
        return user

    def _employee(self, username, company, employee_id):
        user = self._user(username, company, 'EMPLOYEE')
        employee = Employee.objects.create(
            user=user, company=company, employee_id=employee_id, phone='555-0100', department='Private Dept',
            designation='Staff', joining_date=date(2024, 1, 1),
        )
        return type('EmployeeFixture', (), {'user': user, 'record': employee})()

    def test_company_lists_and_reports_do_not_include_other_tenant_records(self):
        paths = [
            '/api/employees/', '/api/leaves/', '/api/holidays/', '/api/announcements/', '/api/attendance/',
            '/api/documents/', '/api/payroll/salary-structures/', '/api/payroll/payslips/', '/api/shifts/',
            '/api/shifts/assignments/', '/api/overtime/', '/api/notifications/broadcasts/',
            '/api/dashboard/admin/', '/api/payroll/reports/?year=2026', '/api/ai/knowledge/',
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'BETA-PRIVATE')
                self.assertNotContains(response, 'beta-api-employee')

    def test_direct_cross_tenant_reads_and_mutations_are_scoped(self):
        cases = [
            ('get', f'/api/employees/{self.beta_employee.record.pk}/', None),
            ('put', f'/api/employees/{self.beta_employee.record.pk}/', {'department': 'COMPROMISED'}),
            ('delete', f'/api/employees/{self.beta_employee.record.pk}/', None),
            ('put', f'/api/leaves/{self.beta_leave.pk}/status/', {'status': 'APPROVED'}),
            ('get', f'/api/documents/{self.beta_document.pk}/file/', None),
            ('put', f'/api/documents/{self.beta_document.pk}/review/', {'status': 'VERIFIED'}),
            ('put', f'/api/holidays/{self.beta_holiday.pk}/', {'name': 'COMPROMISED', 'date': '2026-11-03'}),
            ('delete', f'/api/announcements/{self.beta_announcement.pk}/', None),
            ('get', f'/api/payroll/salary-structures/{self.beta_employee.record.pk}/', None),
            ('get', f'/api/payroll/payslips/{self.beta_payslip.pk}/', None),
            ('patch', f'/api/payroll/payslips/{self.beta_payslip.pk}/', {'notes': 'COMPROMISED'}),
            ('delete', f'/api/payroll/payslips/{self.beta_payslip.pk}/', None),
            ('get', f'/api/payroll/payslips/{self.beta_payslip.pk}/pdf/', None),
            ('get', f'/api/shifts/{self.beta_shift.pk}/', None),
            ('put', f'/api/shifts/{self.beta_shift.pk}/', {'name': 'COMPROMISED'}),
            ('delete', f'/api/shifts/{self.beta_shift.pk}/', None),
            ('put', f'/api/shifts/assignments/{self.beta_assignment.pk}/', {'notes': 'COMPROMISED'}),
            ('delete', f'/api/shifts/assignments/{self.beta_assignment.pk}/', None),
            ('put', f'/api/overtime/{self.beta_overtime.pk}/review/', {'status': 'APPROVED'}),
            ('delete', f'/api/notifications/broadcasts/{self.beta_broadcast.pk}/', None),
            ('get', f'/api/ai/conversations/{self.beta_conversation.pk}/', None),
        ]
        for method, path, data in cases:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(path, data, format='json') if data is not None else getattr(self.client, method)(path)
                self.assertIn(response.status_code, (403, 404))
                self.assertNotContains(response, 'BETA-PRIVATE', status_code=response.status_code)

        self.beta_employee.record.refresh_from_db()
        self.beta_leave.refresh_from_db()
        self.beta_holiday.refresh_from_db()
        self.beta_payslip.refresh_from_db()
        self.beta_shift.refresh_from_db()
        self.beta_overtime.refresh_from_db()
        self.assertEqual(self.beta_employee.record.department, 'Private Dept')
        self.assertEqual(self.beta_leave.status, 'PENDING')
        self.assertEqual(self.beta_holiday.name, 'BETA-PRIVATE-HOLIDAY')
        self.assertEqual(self.beta_payslip.status, Payslip.PAID)
        self.assertEqual(self.beta_shift.name, 'BETA-PRIVATE-SHIFT')
        self.assertEqual(self.beta_overtime.status, OvertimeRecord.PENDING)

    def test_employee_codes_are_unique_per_company_not_globally(self):
        from .serializers import EmployeeWriteSerializer

        alpha_duplicate = EmployeeWriteSerializer(data={
            'employee_id': 'shared-01', 'phone': '555-0101', 'department': 'Ops', 'designation': 'Staff',
            'joining_date': '2026-01-01', 'username': 'alpha-new', 'email': 'alpha-new@example.test',
            'password': 'StrongTestPassword123!',
        }, context={'company_id': self.alpha.pk})
        beta_reuse = EmployeeWriteSerializer(data={
            'employee_id': 'shared-01', 'phone': '555-0102', 'department': 'Ops', 'designation': 'Staff',
            'joining_date': '2026-01-01', 'username': 'beta-new', 'email': 'beta-new@example.test',
            'password': 'StrongTestPassword123!',
        }, context={'company_id': self.beta.pk})

        self.assertFalse(alpha_duplicate.is_valid())
        self.assertIn('employee_id', alpha_duplicate.errors)
        self.assertTrue(beta_reuse.is_valid(), beta_reuse.errors)

    def test_employee_only_sees_own_salary_and_payslips_and_cannot_change_tenant_role(self):
        self.client.force_authenticate(user=self.beta_employee.user)

        own_slip = self.client.get(f'/api/payroll/payslips/{self.beta_payslip.pk}/')
        other_slip = self.client.get(f'/api/payroll/payslips/{self.alpha_payslip.pk}/')
        pdf = self.client.get(f'/api/payroll/payslips/{self.beta_payslip.pk}/pdf/')
        listing = self.client.get('/api/payroll/payslips/')
        profile = self.client.put('/api/profile/', {
            'role': 'ADMIN', 'company_id': self.alpha.pk, 'email': 'beta-api-employee@example.test',
        }, format='json')
        admin_api = self.client.get('/api/employees/')

        self.assertEqual(own_slip.status_code, 200)
        self.assertEqual(other_slip.status_code, 404)
        self.assertEqual(pdf.status_code, 200)
        self.assertContains(listing, 'BETA-PRIVATE-EMPLOYEE')
        self.assertNotContains(listing, 'ALPHA-PRIVATE-EMPLOYEE')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(admin_api.status_code, 403)
        self.beta_employee.user.userprofile.refresh_from_db()
        self.assertEqual(self.beta_employee.user.userprofile.role, 'EMPLOYEE')
        self.assertEqual(self.beta_employee.user.userprofile.company_id, self.beta.pk)

    def test_foreign_tenant_ids_are_rejected_in_write_payloads(self):
        assignment_count = ShiftAssignment.objects.count()
        assignment = self.client.post('/api/shifts/assignments/', {
            'employee_ids': [self.beta_employee.user.pk], 'shift_id': self.beta_shift.pk,
            'start_date': '2026-11-01',
        }, format='json')
        self.assertEqual(assignment.status_code, 400)
        self.assertEqual(ShiftAssignment.objects.count(), assignment_count)

        broadcast_count = NotificationBroadcast.objects.count()
        broadcast = self.client.post('/api/notifications/broadcasts/', {
            'title': 'Cross-company attempt', 'message': 'private', 'target_type': 'EMPLOYEES',
            'employee_ids': [self.beta_employee.user.pk],
        }, format='json')
        self.assertEqual(broadcast.status_code, 400)
        self.assertEqual(NotificationBroadcast.objects.count(), broadcast_count)
        self.assertFalse(Notification.objects.filter(recipient=self.beta_employee.user).exists())

        employee = self.client.post('/api/employees/', {
            'user_id': self.beta_employee.user.pk, 'employee_id': 'ALPHA-NEW', 'phone': '555-0103',
            'department': 'Ops', 'designation': 'Staff', 'joining_date': '2026-01-01',
        }, format='json')
        self.assertEqual(employee.status_code, 400)
        self.assertFalse(Employee.objects.filter(user=self.beta_employee.user, company=self.alpha).exists())

        subject = self.client.post('/api/ai/conversations/', {
            'feature': AIConversation.SALARY, 'subject_id': self.beta_employee.user.pk,
        }, format='json')
        self.assertEqual(subject.status_code, 404)
        self.assertFalse(AIConversation.objects.filter(user=self.alpha_admin).exists())

        shift = self.client.post('/api/shifts/', {
            'name': 'Alpha only shift', 'start_time': '09:00', 'end_time': '17:00', 'company_id': self.beta.pk,
        }, format='json')
        self.assertEqual(shift.status_code, 201)
        self.assertEqual(Shift.objects.get(pk=shift.data['id']).company_id, self.alpha.pk)

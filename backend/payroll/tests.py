from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AttendanceRecord, AuditLog, Employee, Holiday, LeaveRequest, UserProfile, WorkFromHomeRequest

from .calculator import attendance_summary, compute_amounts
from .models import Payslip, SalaryStructure

JUNE_2025_PRESENT = [date(2025, 6, d) for d in (2, 3, 4, 5, 6, 9, 10, 11, 12, 13)]


def make_employee(username, employee_id, joining=date(2024, 1, 1), department='Engineering'):
    user = User.objects.create_user(username, f'{username}@example.com', 'EmployeePass123!', first_name=username.title())
    UserProfile.objects.create(user=user, role='EMPLOYEE')
    employee = Employee.objects.create(
        user=user, employee_id=employee_id, phone='9876543210', department=department,
        designation='Developer', joining_date=joining,
    )
    return employee


def make_structure(user, **overrides):
    values = dict(
        basic=Decimal('30000'), hra=Decimal('12000'), special_allowance=Decimal('8000'),
        pf_percent=Decimal('12'), professional_tax=Decimal('200'), tds=Decimal('1000'),
        effective_from=date(2024, 1, 1),
    )
    values.update(overrides)
    return SalaryStructure.objects.create(employee=user, **values)


def close_file_response(response):
    """Close a streamed file response without the request_finished hook closing the test DB connection."""
    from django.core.signals import request_finished
    from django.db import close_old_connections

    request_finished.disconnect(close_old_connections)
    try:
        response.close()
    finally:
        request_finished.connect(close_old_connections)


def check_in(user, day):
    start = timezone.make_aware(datetime.combine(day, time(9, 0)))
    end = timezone.make_aware(datetime.combine(day, time(18, 0)))
    return AttendanceRecord.objects.create(employee=user, date=day, check_in_at=start, check_out_at=end)


class CalculationTests(TestCase):
    def setUp(self):
        self.employee = make_employee('asha', 'EMP001')
        Holiday.objects.create(name='Mid-month holiday', date=date(2025, 6, 19))
        for day in JUNE_2025_PRESENT:
            check_in(self.employee.user, day)

    def test_compute_amounts_matches_hand_calculation(self):
        components = {
            'basic': Decimal('30000'), 'hra': Decimal('12000'), 'conveyance_allowance': 0, 'medical_allowance': 0,
            'special_allowance': Decimal('8000'), 'other_allowance': 0, 'overtime_pay': 0,
            'pf_percent': Decimal('12'), 'professional_tax_base': Decimal('200'), 'tds_base': Decimal('1000'),
        }
        result = compute_amounts(components, working_days=20, lop_days=Decimal('10'))
        # fixed gross 50000, LOP 10/20 = 25000, PF 12% of earned basic 15000 = 1800,
        # professional tax and TDS pro-rated to half (100 + 500).
        self.assertEqual(result['lop_deduction'], Decimal('25000.00'))
        self.assertEqual(result['pf'], Decimal('1800.00'))
        self.assertEqual(result['professional_tax'], Decimal('100.00'))
        self.assertEqual(result['tds'], Decimal('500.00'))
        self.assertEqual(result['total_deductions'], Decimal('27400.00'))
        self.assertEqual(result['net_salary'], Decimal('22600.00'))

    def test_fully_absent_employee_gets_zero_not_negative(self):
        components = {
            'basic': Decimal('30000'), 'hra': Decimal('12000'), 'conveyance_allowance': 0, 'medical_allowance': 0,
            'special_allowance': Decimal('8000'), 'other_allowance': 0, 'overtime_pay': 0,
            'pf_percent': Decimal('12'), 'professional_tax_base': Decimal('200'), 'tds_base': Decimal('1000'),
        }
        result = compute_amounts(components, working_days=20, lop_days=Decimal('20'))
        self.assertEqual(result['net_salary'], Decimal('0.00'))
        self.assertEqual(result['tds'], Decimal('0.00'))

    def test_full_attendance_has_no_loss_of_pay(self):
        components = {
            'basic': Decimal('30000'), 'hra': Decimal('12000'), 'conveyance_allowance': 0, 'medical_allowance': 0,
            'special_allowance': Decimal('8000'), 'other_allowance': 0, 'overtime_pay': 0,
            'pf_percent': Decimal('12'), 'professional_tax_base': Decimal('200'), 'tds_base': Decimal('1000'),
        }
        result = compute_amounts(components, 20, 0, bonus=Decimal('2500'))
        self.assertEqual(result['gross_earnings'], Decimal('52500.00'))
        self.assertEqual(result['pf'], Decimal('3600.00'))
        self.assertEqual(result['net_salary'], Decimal('47700.00'))

    def test_attendance_only_counts_working_days_without_holidays(self):
        working, lop, overtime = attendance_summary(self.employee.user, self.employee.joining_date, 2025, 6)
        self.assertEqual(working, 20)  # 21 weekdays minus the holiday
        self.assertEqual(lop, Decimal('10'))
        self.assertEqual(overtime, Decimal('10.00'))  # 10 days x 1 hour beyond 8h (9:00-18:00)

    def test_paid_leave_wfh_and_unpaid_leave(self):
        user = self.employee.user
        LeaveRequest.objects.create(employee=user, leave_type='Casual Leave', start_date=date(2025, 6, 16),
                                    end_date=date(2025, 6, 17), reason='x', status='APPROVED')
        WorkFromHomeRequest.objects.create(employee=user, start_date=date(2025, 6, 18), end_date=date(2025, 6, 23),
                                           reason='x', status='APPROVED')
        LeaveRequest.objects.create(employee=user, leave_type='Other', start_date=date(2025, 6, 24),
                                    end_date=date(2025, 6, 24), reason='x', status='APPROVED')
        # Pending leave must not count as covered.
        LeaveRequest.objects.create(employee=user, leave_type='Casual Leave', start_date=date(2025, 6, 25),
                                    end_date=date(2025, 6, 25), reason='x', status='PENDING')
        _, lop, _ = attendance_summary(user, self.employee.joining_date, 2025, 6)
        # present 10 + leave 2 + wfh (18, 20, 23 -> 19 is a holiday, 21/22 weekend) 3 = 15 of 20
        self.assertEqual(lop, Decimal('5'))

    def test_joining_mid_month_and_no_attendance_mode(self):
        newcomer = make_employee('ravi', 'EMP002', joining=date(2025, 6, 16))
        _, lop, _ = attendance_summary(newcomer.user, newcomer.joining_date, 2025, 6, lop_mode='NONE')
        self.assertEqual(lop, Decimal('10'))  # the 10 working days before joining are not payable


class PayrollApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001')
        self.ravi = make_employee('ravi', 'EMP002')
        make_structure(self.asha.user)
        make_structure(self.ravi.user, basic=Decimal('20000'), hra=Decimal('8000'), special_allowance=Decimal('2000'))
        for day in JUNE_2025_PRESENT:
            check_in(self.asha.user, day)
        self.client = APIClient()

    def run_june(self):
        self.client.force_authenticate(self.admin)
        return self.client.post('/api/payroll/run/', {'year': 2025, 'month': 6}, format='json')

    def test_employee_cannot_use_admin_payroll_endpoints(self):
        self.client.force_authenticate(self.asha.user)
        for method, url in (
            ('get', '/api/payroll/salary-structures/'),
            ('put', f'/api/payroll/salary-structures/{self.asha.pk}/'),
            ('post', '/api/payroll/run/'),
            ('post', '/api/payroll/finalize/'),
            ('get', '/api/payroll/export/?year=2025&month=6'),
            ('get', '/api/payroll/reports/'),
            ('get', '/api/dashboard/admin/'),
            ('get', '/api/audit-logs/'),
        ):
            self.assertEqual(getattr(self.client, method)(url).status_code, 403, f'{method} {url}')

    def test_anonymous_users_are_rejected(self):
        for url in ('/api/payroll/payslips/', '/api/dashboard/employee/', '/api/payroll/salary-structures/'):
            self.assertIn(APIClient().get(url).status_code, (401, 403))

    def test_admin_sets_salary_structure_with_validation(self):
        self.client.force_authenticate(self.admin)
        newcomer = make_employee('meera', 'EMP003')
        url = f'/api/payroll/salary-structures/{newcomer.pk}/'
        bad = self.client.put(url, {'basic': '-5', 'effective_from': '2025-01-01'}, format='json')
        self.assertEqual(bad.status_code, 400)
        too_much = self.client.put(url, {'basic': '1000', 'tds': '5000', 'effective_from': '2025-01-01'}, format='json')
        self.assertEqual(too_much.status_code, 400)
        ok = self.client.put(url, {'basic': '40000', 'hra': '16000', 'pf_percent': '12', 'professional_tax': '200',
                                   'effective_from': '2025-01-01'}, format='json')
        self.assertEqual(ok.status_code, 201)
        self.assertEqual(Decimal(ok.json()['gross_monthly']), Decimal('56000.00'))
        self.assertTrue(AuditLog.objects.filter(entity_type='SalaryStructure', action='CREATE').exists())

    def test_run_payroll_creates_correct_drafts_and_is_idempotent(self):
        response = self.run_june()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['created'], 2)
        self.assertEqual(Payslip.objects.get(employee=self.ravi.user).net_salary, Decimal('0.00'))
        asha = Payslip.objects.get(employee=self.asha.user, year=2025, month=6)
        self.assertEqual(asha.status, 'DRAFT')
        self.assertEqual(asha.working_days, 21)  # no holiday configured in this test
        self.assertEqual(asha.lop_days, Decimal('11'))
        # gross 50000 + overtime 0 (rate 0); LOP 11/21 of 50000 = 26190.48
        self.assertEqual(asha.lop_deduction, Decimal('26190.48'))
        self.assertEqual(asha.net_salary, asha.gross_earnings - asha.total_deductions)

        again = self.run_june()
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['created'], 0)
        self.assertEqual(Payslip.objects.filter(year=2025, month=6).count(), 2)

    def test_employee_without_structure_is_skipped(self):
        make_employee('meera', 'EMP003')
        response = self.run_june()
        reasons = [item['reason'] for item in response.json()['skipped']]
        self.assertIn('No salary structure has been set.', reasons)

    def test_cannot_run_payroll_for_unfinished_month(self):
        self.client.force_authenticate(self.admin)
        today = timezone.localdate()
        response = self.client.post('/api/payroll/run/', {'year': today.year, 'month': today.month}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_draft_adjustment_recomputes_totals(self):
        self.run_june()
        slip = Payslip.objects.get(employee=self.asha.user)
        response = self.client.patch(f'/api/payroll/payslips/{slip.pk}/', {'lop_days': '0', 'bonus': '1000'}, format='json')
        self.assertEqual(response.status_code, 200)
        slip.refresh_from_db()
        self.assertEqual(slip.lop_deduction, Decimal('0.00'))
        self.assertEqual(slip.gross_earnings, Decimal('51000.00'))
        self.assertEqual(slip.pf, Decimal('3600.00'))
        self.assertEqual(slip.net_salary, Decimal('51000.00') - Decimal('3600.00') - Decimal('200') - Decimal('1000'))
        invalid = self.client.patch(f'/api/payroll/payslips/{slip.pk}/', {'lop_days': '0.3'}, format='json')
        self.assertEqual(invalid.status_code, 400)
        too_many = self.client.patch(f'/api/payroll/payslips/{slip.pk}/', {'lop_days': '40'}, format='json')
        self.assertEqual(too_many.status_code, 400)

    def test_finalize_publishes_to_employee_only_and_locks_payslip(self):
        self.run_june()
        self.client.force_authenticate(self.asha.user)
        self.assertEqual(self.client.get('/api/payroll/payslips/').json()['results'], [])  # drafts are hidden

        self.client.force_authenticate(self.admin)
        finalized = self.client.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json')
        self.assertEqual(finalized.json()['finalized'], 2)
        slip = Payslip.objects.get(employee=self.asha.user)
        self.assertEqual(slip.status, 'PAID')
        self.assertIsNotNone(slip.paid_at)
        self.assertEqual(self.client.patch(f'/api/payroll/payslips/{slip.pk}/', {'bonus': '5'}, format='json').status_code, 409)
        self.assertEqual(self.client.delete(f'/api/payroll/payslips/{slip.pk}/').status_code, 409)
        self.assertEqual(self.client.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json').status_code, 400)

        self.client.force_authenticate(self.asha.user)
        listing = self.client.get('/api/payroll/payslips/').json()
        self.assertEqual([item['employee_code'] for item in listing['results']], ['EMP001'])
        self.assertEqual(self.client.get(f'/api/payroll/payslips/{slip.pk}/').status_code, 200)
        other = Payslip.objects.get(employee=self.ravi.user)
        self.assertEqual(self.client.get(f'/api/payroll/payslips/{other.pk}/').status_code, 404)
        self.assertEqual(self.client.get(f'/api/payroll/payslips/{other.pk}/pdf/').status_code, 404)

    def test_payslip_pdf_download(self):
        self.run_june()
        slip = Payslip.objects.get(employee=self.asha.user)
        response = self.client.get(f'/api/payroll/payslips/{slip.pk}/pdf/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_delete_and_recalculate_drafts(self):
        self.run_june()
        slip = Payslip.objects.get(employee=self.asha.user)
        self.client.patch(f'/api/payroll/payslips/{slip.pk}/', {'bonus': '500'}, format='json')
        recalculated = self.client.post(f'/api/payroll/payslips/{slip.pk}/recalculate/')
        self.assertEqual(recalculated.status_code, 200)
        slip.refresh_from_db()
        self.assertEqual(slip.bonus, Decimal('0.00'))
        self.assertEqual(self.client.delete(f'/api/payroll/payslips/{slip.pk}/').status_code, 204)
        self.assertFalse(Payslip.objects.filter(pk=slip.pk).exists())

    def test_csv_export_neutralises_formulas(self):
        self.asha.user.first_name = '=HYPERLINK("x")'
        self.asha.user.save()
        self.run_june()
        response = self.client.get('/api/payroll/export/?year=2025&month=6')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8-sig')
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn(',=HYPERLINK', body)

    def test_reports_and_dashboards_use_real_data(self):
        self.run_june()
        report = self.client.get('/api/payroll/reports/?year=2025').json()
        june = report['monthly'][5]
        self.assertEqual(june['count'], 2)
        self.assertEqual(report['month'], 6)
        self.assertEqual(sum(item['headcount'] for item in report['departments']), 2)

        dashboard = self.client.get('/api/dashboard/admin/').json()
        self.assertEqual(dashboard['employees']['active'], 2)
        self.assertEqual(dashboard['payroll']['latest']['count'], 2)

        self.client.force_authenticate(self.asha.user)
        mine = self.client.get('/api/dashboard/employee/').json()
        self.assertEqual(mine['employee']['employee_id'], 'EMP001')
        self.assertEqual(mine['leave_balance']['Casual Leave']['remaining'], 12)
        self.assertIsNone(mine['latest_payslip'])  # still a draft


class SecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.employee = make_employee('asha', 'EMP001')

    def test_csrf_is_enforced_on_state_changing_api_calls(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertTrue(client.login(username='admin', password='AdminPass123!'))
        blocked = client.post('/api/announcements/', {'title': 'Hi', 'message': 'There'}, format='json')
        self.assertEqual(blocked.status_code, 403)

        token = client.get('/api/csrf/').json()['csrfToken']
        allowed = client.post('/api/announcements/', {'title': 'Hi', 'message': 'There'}, format='json',
                              HTTP_X_CSRFTOKEN=token)
        self.assertEqual(allowed.status_code, 201)

    def test_csrf_is_enforced_on_login(self):
        client = APIClient(enforce_csrf_checks=True)
        payload = {'username': 'asha', 'password': 'EmployeePass123!', 'role': 'EMPLOYEE'}
        self.assertEqual(client.post('/api/login/', payload, format='json').status_code, 403)
        token = client.get('/api/csrf/').json()['csrfToken']
        self.assertEqual(client.post('/api/login/', payload, format='json', HTTP_X_CSRFTOKEN=token).status_code, 200)

    @override_settings(LOGIN_MAX_FAILED_ATTEMPTS=3)
    def test_login_locks_out_after_repeated_failures(self):
        client = APIClient()
        bad = {'username': 'asha', 'password': 'wrong-password', 'role': 'EMPLOYEE'}
        for _ in range(3):
            self.assertEqual(client.post('/api/login/', bad, format='json').status_code, 401)
        self.assertEqual(client.post('/api/login/', bad, format='json').status_code, 429)
        good = dict(bad, password='EmployeePass123!')
        self.assertEqual(client.post('/api/login/', good, format='json').status_code, 429)

    def test_documents_are_private_to_owner_and_admin(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from accounts.models import EmployeeDocument
        other = make_employee('ravi', 'EMP002')
        document = EmployeeDocument.objects.create(
            employee=self.employee.user, title='ID', document_type='IDENTITY',
            file=SimpleUploadedFile('id.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
        )
        url = f'/api/documents/{document.pk}/file/'
        self.assertIn(APIClient().get(url).status_code, (401, 403))
        client = APIClient()
        client.force_authenticate(other.user)
        self.assertEqual(client.get(url).status_code, 404)
        client.force_authenticate(self.employee.user)
        owner = client.get(url)
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(b''.join(owner.streaming_content), b'%PDF-1.4 test')
        close_file_response(owner)
        client.force_authenticate(self.admin)
        admin_response = client.get(url)
        self.assertEqual(admin_response.status_code, 200)
        close_file_response(admin_response)   # release the file handle so Windows can delete the file
        document.file.delete(save=False)

    def test_fake_pdf_upload_is_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        client = APIClient()
        client.force_authenticate(self.employee.user)
        response = client.post('/api/documents/', {
            'title': 'Fake', 'document_type': 'IDENTITY',
            'file': SimpleUploadedFile('fake.pdf', b'<script>alert(1)</script>', content_type='application/pdf'),
        }, format='multipart')
        self.assertEqual(response.status_code, 400)


class EmployeeManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def payload(self, **overrides):
        data = {
            'username': 'newhire', 'email': 'newhire@example.com', 'password': 'Str0ng!Passw0rd',
            'first_name': 'New', 'last_name': 'Hire', 'employee_id': 'emp010', 'phone': '9876543210',
            'department': 'Finance', 'designation': 'Analyst', 'joining_date': '2026-01-05',
        }
        data.update(overrides)
        return data

    def test_create_validates_and_normalises(self):
        response = self.client.post('/api/employees/', self.payload(), format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['employee_id'], 'EMP010')
        self.assertEqual(response.json()['full_name'], 'New Hire')

        for overrides, field in (
            ({'username': 'other', 'email': 'x@example.com', 'employee_id': 'EMP010'}, 'employee_id'),
            ({'username': 'NEWHIRE', 'employee_id': 'EMP011', 'email': 'y@example.com'}, 'username'),
            ({'username': 'u2', 'employee_id': 'EMP012', 'email': 'newhire@example.com'}, 'email'),
            ({'username': 'u3', 'employee_id': 'EMP013', 'email': 'z@example.com', 'phone': 'abc'}, 'phone'),
            ({'username': 'u4', 'employee_id': 'EMP014', 'email': 'w@example.com', 'password': '123'}, 'password'),
            ({'username': 'u5', 'employee_id': 'EMP015', 'email': 'v@example.com', 'joining_date': 'nope'}, 'joining_date'),
        ):
            bad = self.client.post('/api/employees/', self.payload(**overrides), format='json')
            self.assertEqual(bad.status_code, 400, field)
            self.assertIn(field, bad.json())
        self.assertEqual(Employee.objects.count(), 1)

    def test_search_filter_edit_and_deactivate(self):
        self.client.post('/api/employees/', self.payload(), format='json')
        self.client.post('/api/employees/', self.payload(username='second', email='s@example.com', employee_id='EMP011',
                                                          department='Sales', first_name='Sam', last_name='Seller'), format='json')
        listing = self.client.get('/api/employees/?search=sam&page=1').json()
        self.assertEqual(listing['count'], 1)
        self.assertEqual(len(self.client.get('/api/employees/?department=finance').json()), 1)

        employee = Employee.objects.get(employee_id='EMP010')
        edit = self.client.put(f'/api/employees/{employee.pk}/', {'designation': 'Senior Analyst', 'first_name': 'Neo'}, format='json')
        self.assertEqual(edit.status_code, 200)
        self.assertEqual(edit.json()['designation'], 'Senior Analyst')
        self.assertEqual(edit.json()['full_name'], 'Neo Hire')
        clash = self.client.put(f'/api/employees/{employee.pk}/', {'employee_id': 'EMP011'}, format='json')
        self.assertEqual(clash.status_code, 400)

        self.assertEqual(self.client.delete(f'/api/employees/{employee.pk}/').status_code, 200)
        employee.refresh_from_db()
        self.assertEqual(employee.status, 'INACTIVE')
        self.assertFalse(employee.user.is_active)
        reactivate = self.client.put(f'/api/employees/{employee.pk}/', {'status': 'ACTIVE'}, format='json')
        self.assertEqual(reactivate.status_code, 200)
        employee.user.refresh_from_db()
        self.assertTrue(employee.user.is_active)

    def test_self_registered_account_can_be_onboarded(self):
        user = User.objects.create_user('selfie', 'selfie@example.com', 'Str0ng!Passw0rd')
        UserProfile.objects.create(user=user, role='EMPLOYEE')
        meta = self.client.get('/api/employees/meta/').json()
        self.assertEqual([item['username'] for item in meta['pending_accounts']], ['selfie'])
        response = self.client.post('/api/employees/', {
            'user_id': user.pk, 'employee_id': 'EMP020', 'phone': '9876543210',
            'department': 'Ops', 'designation': 'Coordinator', 'joining_date': '2026-02-01',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['username'], 'selfie')
        self.assertEqual(self.client.get('/api/employees/meta/').json()['pending_accounts'], [])

    def test_admin_cannot_deactivate_self(self):
        employee = Employee.objects.create(user=self.admin, employee_id='ADM1', phone='9876543210', department='HR',
                                           designation='Head', joining_date=date(2024, 1, 1))
        self.assertEqual(self.client.delete(f'/api/employees/{employee.pk}/').status_code, 400)


class LeaveBalanceTests(TestCase):
    def setUp(self):
        self.employee = make_employee('asha', 'EMP001')
        self.client = APIClient()
        self.client.force_authenticate(self.employee.user)

    def test_balance_and_over_limit_request(self):
        response = self.client.post('/api/leaves/', {
            'leave_type': 'Casual Leave', 'start_date': '2026-03-02', 'end_date': '2026-03-06', 'reason': 'Trip',
        }, format='json')
        self.assertEqual(response.status_code, 201)
        balance = self.client.get('/api/leaves/balance/?year=2026').json()['balances']['Casual Leave']
        self.assertEqual(balance['pending'], 5)
        self.assertEqual(balance['remaining'], 7)

        too_long = self.client.post('/api/leaves/', {
            'leave_type': 'Casual Leave', 'start_date': '2026-04-01', 'end_date': '2026-04-20', 'reason': 'Long trip',
        }, format='json')
        self.assertEqual(too_long.status_code, 400)
        unpaid = self.client.post('/api/leaves/', {
            'leave_type': 'Other', 'start_date': '2026-04-01', 'end_date': '2026-04-20', 'reason': 'Long trip',
        }, format='json')
        self.assertEqual(unpaid.status_code, 201)

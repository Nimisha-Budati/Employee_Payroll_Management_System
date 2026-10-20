"""Admin-controlled, database-driven leave policy."""

import importlib
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from payroll.calculator import attendance_summary
from payroll.tests import make_employee

from .leave_policy import carry_forward, leave_balance_for, leave_year_bounds, leave_year_of
from .models import AuditLog, EmployeeLeaveBalance, LeavePolicySettings, LeaveRequest, LeaveType, UserProfile

THIS_YEAR = timezone.localdate().year


class LeavePolicyTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001')
        self.ravi = make_employee('ravi', 'EMP002')
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.client = APIClient()
        self.client.force_authenticate(self.asha.user)

    def create_type(self, **values):
        data = {'name': 'Study Leave', 'annual_days': 5, 'is_paid': True, 'description': 'Exams and courses.'}
        data.update(values)
        response = self.admin_client.post('/api/leave-types/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return LeaveType.objects.get(pk=response.data['id'])

    def apply(self, leave_type, start, end, client=None):
        return (client or self.client).post('/api/leaves/', {'leave_type': leave_type, 'start_date': str(start), 'end_date': str(end),
                                                             'reason': 'Test'}, format='json')

    def balance(self, name, year=THIS_YEAR, client=None):
        return (client or self.client).get('/api/leaves/balance/', {'year': year}).data['balances'][name]


class PolicyManagementTests(LeavePolicyTestCase):
    def test_initial_policy_comes_from_the_database(self):
        types = {t.name: t for t in LeaveType.objects.all()}
        self.assertEqual((types['Casual Leave'].annual_days, types['Sick Leave'].annual_days, types['Earned Leave'].annual_days), (12, 12, 15))
        self.assertIsNone(types['Other'].annual_days)
        self.assertFalse(types['Other'].is_paid)
        self.assertTrue(LeavePolicySettings.objects.filter(pk=1).exists())

    def test_admin_creates_type_and_employee_sees_it_with_correct_balance(self):
        study = self.create_type()
        self.assertTrue(AuditLog.objects.filter(module='Leave', action='CREATE', entity_type='LeaveType').exists())
        offered = [t['name'] for t in self.client.get('/api/leave-types/').data]
        self.assertIn('Study Leave', offered)
        b = self.balance('Study Leave')
        self.assertEqual((b['entitled'], b['total'], b['approved'], b['pending'], b['available'], b['remaining']), (5, 5, 0, 0, 5, 5))
        self.assertTrue(b['is_paid'])
        self.assertEqual(b['id'], study.pk)

    def test_validation_of_leave_type_settings(self):
        self.create_type()
        self.assertEqual(self.admin_client.post('/api/leave-types/', {'name': ' study   leave ', 'annual_days': 3}, format='json').status_code, 400)
        self.assertEqual(self.admin_client.post('/api/leave-types/', {'name': 'X', 'annual_days': 400}, format='json').status_code, 400)
        no_limit_carry = self.admin_client.post('/api/leave-types/', {'name': 'Y', 'annual_days': None, 'allow_carry_forward': True,
                                                                       'max_carry_forward_days': 2}, format='json')
        self.assertEqual(no_limit_carry.status_code, 400)
        missing_max = self.admin_client.post('/api/leave-types/', {'name': 'Z', 'annual_days': 5, 'allow_carry_forward': True}, format='json')
        self.assertEqual(missing_max.status_code, 400)
        self.assertEqual(self.admin_client.post('/api/leave-types/', {'name': '   ', 'annual_days': 5}, format='json').status_code, 400)

    def test_changing_allowed_days_updates_balances_immediately(self):
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(THIS_YEAR, 1, 5),
                                    end_date=date(THIS_YEAR, 1, 6), reason='x', status='APPROVED')
        self.assertEqual(self.balance('Casual Leave')['available'], 10)
        casual = LeaveType.objects.get(name='Casual Leave')
        response = self.admin_client.patch(f'/api/leave-types/{casual.pk}/', {'annual_days': 20}, format='json')
        self.assertEqual(response.status_code, 200)
        b = self.balance('Casual Leave')
        self.assertEqual((b['entitled'], b['total'], b['approved'], b['available']), (20, 20, 2, 18))
        dashboard = self.client.get('/api/dashboard/employee/').data['leave_balance']['Casual Leave']
        self.assertEqual(dashboard['available'], 18)

    def test_deactivate_rename_and_delete_rules(self):
        study = self.create_type()
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Study Leave', start_date=date(THIS_YEAR, 2, 2),
                                    end_date=date(THIS_YEAR, 2, 2), reason='x', status='APPROVED')
        self.assertEqual(self.admin_client.delete(f'/api/leave-types/{study.pk}/').status_code, 409)   # has history
        self.admin_client.patch(f'/api/leave-types/{study.pk}/', {'name': 'Exam Leave'}, format='json')
        self.assertEqual(LeaveRequest.objects.get(policy=study).leave_type, 'Exam Leave')
        self.admin_client.patch(f'/api/leave-types/{study.pk}/', {'is_active': False}, format='json')
        self.assertNotIn('Exam Leave', [t['name'] for t in self.client.get('/api/leave-types/').data])
        self.assertIn('Exam Leave', self.client.get('/api/leaves/balance/').data['balances'])   # still shown: it was used this year
        refused = self.apply('Exam Leave', date(THIS_YEAR, 3, 3), date(THIS_YEAR, 3, 3))
        self.assertEqual(refused.status_code, 400)
        self.assertIn('no longer offered', str(refused.data))
        unused = self.create_type(name='Temp Leave')
        self.assertEqual(self.admin_client.delete(f'/api/leave-types/{unused.pk}/').status_code, 204)


class BalanceTests(LeavePolicyTestCase):
    def test_approved_reduces_and_pending_is_separate(self):
        future = timezone.localdate() + timedelta(days=30)
        year = leave_year_of(future)
        approved = self.apply('Casual Leave', future, future + timedelta(days=2))
        self.assertEqual(approved.status_code, 201, approved.data)
        b = self.balance('Casual Leave', year)
        self.assertEqual((b['approved'], b['pending'], b['available'], b['remaining']), (0, 3, 12, 9))   # pending is not "used"
        self.admin_client.put(f"/api/leaves/{approved.data['id']}/status/", {'status': 'APPROVED'}, format='json')
        b = self.balance('Casual Leave', year)
        self.assertEqual((b['approved'], b['pending'], b['available'], b['remaining']), (3, 0, 9, 9))

    def test_rejected_and_cancelled_requests_do_not_reduce_balance(self):
        future = timezone.localdate() + timedelta(days=40)
        year = leave_year_of(future)
        first = self.apply('Sick Leave', future, future + timedelta(days=1))
        second = self.apply('Sick Leave', future + timedelta(days=5), future + timedelta(days=6))
        self.admin_client.put(f"/api/leaves/{first.data['id']}/status/", {'status': 'REJECTED', 'rejection_reason': 'No'}, format='json')
        cancelled = self.client.delete(f"/api/leaves/{second.data['id']}/")
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.data['status'], 'CANCELLED')
        b = self.balance('Sick Leave', year)
        self.assertEqual((b['approved'], b['pending'], b['available'], b['remaining']), (0, 0, 12, 12))
        # Cancelling is only for your own pending requests.
        self.assertEqual(self.client.delete(f"/api/leaves/{second.data['id']}/").status_code, 409)
        ravi = APIClient()
        ravi.force_authenticate(self.ravi.user)
        other = self.apply('Sick Leave', future + timedelta(days=10), future + timedelta(days=10), client=ravi)
        self.assertEqual(self.client.delete(f"/api/leaves/{other.data['id']}/").status_code, 404)

    def test_unlimited_types_and_rejected_admin_review_status(self):
        b = self.balance('Other')
        self.assertTrue(b['unlimited'])
        self.assertIsNone(b['available'])
        self.assertFalse(b['is_paid'])

    def test_leave_year_can_start_in_april(self):
        self.admin_client.put('/api/leave-policy/', {'leave_year_start_month': 4}, format='json')
        start, end = leave_year_bounds(2026)
        self.assertEqual((start, end), (date(2026, 4, 1), date(2027, 3, 31)))
        self.assertEqual(leave_year_of(date(2027, 3, 15)), 2026)
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(2027, 3, 15),
                                    end_date=date(2027, 3, 16), reason='x', status='APPROVED')
        self.assertEqual(leave_balance_for(self.asha.user, 2026)['Casual Leave']['approved'], 2)
        self.assertEqual(leave_balance_for(self.asha.user, 2027)['Casual Leave']['approved'], 0)

    def test_carry_forward_and_admin_adjustment(self):
        casual = LeaveType.objects.get(name='Casual Leave')
        self.admin_client.patch(f'/api/leave-types/{casual.pk}/', {'allow_carry_forward': True, 'max_carry_forward_days': 5}, format='json')
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(2025, 3, 3),
                                    end_date=date(2025, 3, 12), reason='x', status='APPROVED')   # 10 used -> 2 left
        result = self.admin_client.post('/api/leave-policy/carry-forward/', {'year': 2026}, format='json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(leave_balance_for(self.asha.user, 2026)['Casual Leave']['carried_forward'], 2)
        self.assertEqual(leave_balance_for(self.ravi.user, 2026)['Casual Leave']['carried_forward'], 5)   # capped at the maximum
        self.assertEqual(leave_balance_for(self.ravi.user, 2026)['Casual Leave']['total'], 17)
        carry_forward(2026)   # running again gives the same values
        self.assertEqual(EmployeeLeaveBalance.objects.get(employee=self.ravi.user, leave_type=casual, year=2026).carried_forward, 5)

        no_note = self.admin_client.put('/api/leave-policy/balances/', {'employee_id': self.asha.user_id, 'leave_type_id': casual.pk,
                                                                        'year': 2026, 'adjustment': 3}, format='json')
        self.assertEqual(no_note.status_code, 400)
        adjusted = self.admin_client.put('/api/leave-policy/balances/', {'employee_id': self.asha.user_id, 'leave_type_id': casual.pk,
                                                                         'year': 2026, 'adjustment': 3, 'note': 'Award'}, format='json')
        self.assertEqual(adjusted.status_code, 200)
        self.assertEqual(adjusted.data['balances']['Casual Leave']['total'], 12 + 2 + 3)
        self.assertTrue(AuditLog.objects.filter(module='Leave', action='ADJUST').exists())


class ApplicationValidationTests(LeavePolicyTestCase):
    def test_invalid_and_excessive_requests_are_rejected(self):
        future = timezone.localdate() + timedelta(days=20)
        backwards = self.apply('Casual Leave', future, future - timedelta(days=1))
        self.assertEqual(backwards.status_code, 400)
        self.assertIn('End date cannot be before start date', str(backwards.data))
        self.assertEqual(self.apply('Unknown Leave', future, future).status_code, 400)
        too_many = self.apply('Casual Leave', future, future + timedelta(days=12))   # 13 days, 12 allowed
        self.assertEqual(too_many.status_code, 400)
        self.assertIn('only 12 day(s) can be requested', str(too_many.data))
        self.assertIn('"Other" (unpaid leave)', str(too_many.data))
        ok = self.apply('casual', future, future + timedelta(days=9))   # alias of "Casual Leave", 10 days
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data['leave_type'], 'Casual Leave')
        pending_blocks = self.apply('Casual Leave', future + timedelta(days=20), future + timedelta(days=22))   # 3 > 12 - 10 pending
        self.assertEqual(pending_blocks.status_code, 400)
        self.assertIn('10 day(s) are already waiting for approval', str(pending_blocks.data))
        overlap = self.apply('Other', future + timedelta(days=2), future + timedelta(days=3))
        self.assertEqual(overlap.status_code, 400)
        unlimited = self.apply('Other', future + timedelta(days=30), future + timedelta(days=60))
        self.assertEqual(unlimited.status_code, 201)

    def test_policy_rules_are_enforced_on_the_server(self):
        self.admin_client.put('/api/leave-policy/', {'min_notice_days': 3, 'max_days_per_request': 2, 'allow_past_dates': False}, format='json')
        today = timezone.localdate()
        self.assertIn('at least 3 day(s)', str(self.apply('Casual Leave', today + timedelta(days=1), today + timedelta(days=1)).data))
        self.assertIn('at most 2 day(s)', str(self.apply('Casual Leave', today + timedelta(days=5), today + timedelta(days=7)).data))
        self.assertIn('cannot start in the past', str(self.apply('Sick Leave', today - timedelta(days=2), today - timedelta(days=2)).data))
        self.assertEqual(self.apply('Casual Leave', today + timedelta(days=5), today + timedelta(days=6)).status_code, 201)
        self.assertEqual(self.admin_client.put('/api/leave-policy/', {'leave_year_start_month': 13}, format='json').status_code, 400)

    def test_unpaid_type_configured_by_admin_is_loss_of_pay(self):
        self.create_type(name='Sabbatical', annual_days=30, is_paid=False)
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Sabbatical', start_date=date(2025, 6, 2),
                                    end_date=date(2025, 6, 3), reason='x', status='APPROVED')
        _, lop, _ = attendance_summary(self.asha.user, self.asha.joining_date, 2025, 6, lop_mode='NONE')
        self.assertEqual(lop, Decimal('2'))


class PermissionTests(LeavePolicyTestCase):
    def test_employees_cannot_change_policy_or_see_other_balances(self):
        casual = LeaveType.objects.get(name='Casual Leave')
        self.assertEqual(self.client.post('/api/leave-types/', {'name': 'Free', 'annual_days': 99}, format='json').status_code, 403)
        self.assertEqual(self.client.patch(f'/api/leave-types/{casual.pk}/', {'annual_days': 99}, format='json').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/leave-types/{casual.pk}/').status_code, 403)
        self.assertEqual(self.client.put('/api/leave-policy/', {'min_notice_days': 0}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/leave-policy/carry-forward/', {'year': THIS_YEAR}, format='json').status_code, 403)
        self.assertEqual(self.client.put('/api/leave-policy/balances/', {'employee_id': self.asha.user_id, 'leave_type_id': casual.pk,
                                                                          'year': THIS_YEAR, 'adjustment': 50, 'note': 'me'}, format='json').status_code, 403)
        self.assertEqual(self.client.get('/api/leaves/balance/', {'employee_id': self.ravi.user_id}).status_code, 403)
        self.assertEqual(LeaveType.objects.get(pk=casual.pk).annual_days, 12)
        self.assertEqual(self.client.get('/api/leave-types/', {'all': 'true'}).status_code, 200)   # read-only, active types only
        self.assertTrue(all(t['is_active'] for t in self.client.get('/api/leave-types/', {'all': 'true'}).data))
        # Read-only fields cannot be set through a leave request either.
        sneaky = self.client.post('/api/leaves/', {'leave_type': 'Casual Leave', 'start_date': str(date(THIS_YEAR, 12, 1)),
                                                   'end_date': str(date(THIS_YEAR, 12, 1)), 'reason': 'x', 'status': 'APPROVED'}, format='json')
        if sneaky.status_code == 201:
            self.assertEqual(sneaky.data['status'], 'PENDING')
        self.assertEqual(self.admin_client.get('/api/leaves/balance/', {'employee_id': self.ravi.user_id}).status_code, 200)


class MigrationTests(TestCase):
    def test_seed_links_existing_requests_without_changing_them(self):
        employee = make_employee('meena', 'EMP003')
        old = LeaveRequest.objects.create(employee=employee.user, leave_type='Sick Leave', start_date=date(2024, 5, 6),
                                          end_date=date(2024, 5, 8), reason='Flu', status='APPROVED')
        legacy = LeaveRequest.objects.create(employee=employee.user, leave_type='Study Leave', start_date=date(2024, 6, 3),
                                             end_date=date(2024, 6, 3), reason='Exam', status='REJECTED', rejection_reason='Busy')
        LeaveRequest.objects.filter(pk__in=[old.pk, legacy.pk]).update(policy=None)   # as before the migration
        before = list(LeaveRequest.objects.order_by('pk').values('pk', 'leave_type', 'start_date', 'end_date', 'number_of_days', 'status',
                                                                 'reason', 'rejection_reason'))
        migration = importlib.import_module('accounts.migrations.0021_seed_leave_policy')
        migration.seed(django_apps, None)
        migration.seed(django_apps, None)   # running twice does not duplicate anything
        after = list(LeaveRequest.objects.order_by('pk').values('pk', 'leave_type', 'start_date', 'end_date', 'number_of_days', 'status',
                                                                'reason', 'rejection_reason'))
        self.assertEqual(before, after)
        self.assertEqual(LeaveRequest.objects.get(pk=old.pk).policy.name, 'Sick Leave')
        study = LeaveType.objects.get(name='Study Leave')
        self.assertFalse(study.is_active)
        self.assertEqual(LeaveRequest.objects.get(pk=legacy.pk).policy, study)
        self.assertEqual(LeaveType.objects.filter(name='Sick Leave').count(), 1)

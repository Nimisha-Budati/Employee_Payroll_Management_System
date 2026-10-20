"""Tests for notification broadcasts with expiry, extended audit logging, search and department management."""

from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from payroll.tests import make_employee

from .models import AuditLog, EmployeeDocument, LeaveRequest, Notification, NotificationBroadcast, UserProfile, WorkFromHomeRequest


class SrsTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001', department='Engineering')
        self.ravi = make_employee('ravi', 'EMP002', department='Sales')
        self.meena = make_employee('meena', 'EMP003', department='Sales')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)


class NotificationBroadcastTests(SrsTestCase):
    def test_targeted_notification_with_expiry(self):
        expires = (timezone.now() + timedelta(days=2)).isoformat()
        response = self.client.post('/api/notifications/broadcasts/', {
            'title': 'Sales meeting', 'message': 'Room 4 at 3 pm', 'target_type': 'DEPARTMENT', 'department': 'Sales',
            'expires_at': expires,
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['recipient_count'], 2)
        self.assertEqual(set(Notification.objects.filter(kind='GENERAL').values_list('recipient__username', flat=True)), {'ravi', 'meena'})

        ravi = APIClient()
        ravi.force_authenticate(self.ravi.user)
        inbox = ravi.get('/api/notifications/')
        self.assertEqual(inbox.data['unread_count'], 1)
        self.assertEqual(inbox.data['notifications'][0]['title'], 'Sales meeting')
        ravi.post(f'/api/notifications/{inbox.data["notifications"][0]["id"]}/read/')
        listed = self.client.get('/api/notifications/broadcasts/')
        self.assertEqual(listed.data[0]['read_count'], 1)

        # Once expired, it disappears from the inbox and the unread count.
        Notification.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(ravi.get('/api/notifications/').data['notifications'], [])
        self.assertTrue(AuditLog.objects.filter(module='Notifications', action='SEND').exists())

    def test_selected_employees_validation_and_withdraw(self):
        response = self.client.post('/api/notifications/broadcasts/', {
            'title': 'Docs', 'message': 'Upload your ID', 'target_type': 'EMPLOYEES', 'employee_ids': [self.asha.user_id],
        }, format='json')
        self.assertEqual(response.data['recipient_count'], 1)
        past = self.client.post('/api/notifications/broadcasts/', {
            'title': 'x', 'message': 'y', 'target_type': 'ALL', 'expires_at': (timezone.now() - timedelta(hours=1)).isoformat(),
        }, format='json')
        self.assertEqual(past.status_code, 400)
        missing = self.client.post('/api/notifications/broadcasts/', {'title': 'x', 'message': 'y', 'target_type': 'DEPARTMENT'}, format='json')
        self.assertEqual(missing.status_code, 400)
        everyone = self.client.post('/api/notifications/broadcasts/', {'title': 'Hi', 'message': 'All hands', 'target_type': 'ALL'}, format='json')
        self.assertEqual(everyone.data['recipient_count'], 3)

        self.assertEqual(self.client.delete(f'/api/notifications/broadcasts/{response.data["id"]}/').status_code, 204)
        self.assertFalse(Notification.objects.filter(title='Docs').exists())
        employee = APIClient()
        employee.force_authenticate(self.asha.user)
        self.assertEqual(employee.post('/api/notifications/broadcasts/', {'title': 'x', 'message': 'y', 'target_type': 'ALL'}, format='json').status_code, 403)
        self.assertEqual(NotificationBroadcast.objects.count(), 1)


class AuditCoverageTests(SrsTestCase):
    def test_sign_in_activity_is_audited_with_module_and_ip(self):
        public = APIClient(enforce_csrf_checks=False)
        public.post('/api/login/', {'username': 'asha', 'password': 'wrong', 'role': 'EMPLOYEE'}, format='json')
        public.post('/api/login/', {'username': 'asha', 'password': 'EmployeePass123!', 'role': 'EMPLOYEE'}, format='json')
        public.post('/api/logout/')
        actions = list(AuditLog.objects.filter(module='Authentication').order_by('id').values_list('action', flat=True))
        self.assertEqual(actions, ['LOGIN_FAILED', 'LOGIN', 'LOGOUT'])
        login = AuditLog.objects.get(action='LOGIN')
        self.assertEqual(login.actor_name, 'asha')
        self.assertEqual(login.ip_address, '127.0.0.1')

    def test_approvals_are_audited_and_filterable_by_module(self):
        leave = LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(2025, 6, 2),
                                            end_date=date(2025, 6, 2), reason='x')
        self.client.put(f'/api/leaves/{leave.pk}/status/', {'status': 'APPROVED'}, format='json')
        wfh = WorkFromHomeRequest.objects.create(employee=self.ravi.user, start_date=date(2025, 6, 3), end_date=date(2025, 6, 3), reason='x')
        self.client.put(f'/api/wfh/{wfh.pk}/', {'status': 'REJECTED', 'admin_note': 'Needed in office'}, format='json')
        self.client.post('/api/holidays/', {'name': 'Founders Day', 'date': '2025-08-20', 'holiday_type': 'FIXED'}, format='json')
        logs = self.client.get('/api/audit-logs/', {'module': 'Leave'})
        self.assertEqual([row['action'] for row in logs.data], ['APPROVE'])
        self.assertEqual(self.client.get('/api/audit-logs/', {'module': 'Work from home'}).data[0]['action'], 'REJECT')
        self.assertEqual(self.client.get('/api/audit-logs/', {'module': 'Holidays'}).data[0]['action'], 'CREATE')


class SearchAndDepartmentTests(SrsTestCase):
    def test_document_and_wfh_search(self):
        EmployeeDocument.objects.create(employee=self.asha.user, title='Passport', document_type='IDENTITY', file='employee_documents/a.pdf')
        EmployeeDocument.objects.create(employee=self.ravi.user, title='Degree', document_type='EDUCATION', file='employee_documents/b.pdf')
        self.assertEqual([d['title'] for d in self.client.get('/api/documents/', {'search': 'EMP002'}).data], ['Degree'])
        self.assertEqual([d['title'] for d in self.client.get('/api/documents/', {'document_type': 'IDENTITY'}).data], ['Passport'])
        WorkFromHomeRequest.objects.create(employee=self.asha.user, start_date=date(2025, 6, 3), end_date=date(2025, 6, 3), reason='x')
        WorkFromHomeRequest.objects.create(employee=self.ravi.user, start_date=date(2025, 6, 4), end_date=date(2025, 6, 4), reason='y')
        self.assertEqual([w['employee_username'] for w in self.client.get('/api/wfh/', {'search': 'ravi'}).data], ['ravi'])

    def test_department_list_and_rename(self):
        departments = {d['name']: d for d in self.client.get('/api/employees/departments/').data}
        self.assertEqual(departments['Sales']['headcount'], 2)
        renamed = self.client.post('/api/employees/departments/rename/', {'kind': 'department', 'old': 'sales', 'new': 'Sales & Marketing'}, format='json')
        self.assertEqual(renamed.data['updated'], 2)
        self.ravi.refresh_from_db()
        self.assertEqual(self.ravi.department, 'Sales & Marketing')
        self.assertEqual(self.client.post('/api/employees/departments/rename/', {'kind': 'department', 'old': 'Nope', 'new': 'X'}, format='json').status_code, 404)
        self.assertTrue(AuditLog.objects.filter(module='Employees', action='RENAME').exists())

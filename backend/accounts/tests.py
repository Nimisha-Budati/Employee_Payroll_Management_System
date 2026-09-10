from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient

from .models import LeaveRequest, UserProfile


class RoleBasedAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user('admin', password='AdminPass123!')
        self.employee = User.objects.create_user('employee', password='EmployeePass123!')
        self.other_employee = User.objects.create_user('other', password='OtherPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE')
        UserProfile.objects.create(user=self.other_employee, role='EMPLOYEE')
        self.leave = LeaveRequest.objects.create(
            employee=self.other_employee,
            leave_type='Casual Leave',
            start_date=date(2026, 9, 14),
            end_date=date(2026, 9, 15),
            reason='Personal work',
        )

    def test_employee_cannot_access_employee_management(self):
        self.client.force_authenticate(self.employee)
        response = self.client.get('/api/employees/')
        self.assertEqual(response.status_code, 403)

    def test_admin_can_access_employee_management(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get('/api/employees/')
        self.assertEqual(response.status_code, 200)

    def test_employee_sees_only_own_leave_requests(self):
        own_leave = LeaveRequest.objects.create(
            employee=self.employee,
            leave_type='Sick Leave',
            start_date=date(2026, 9, 16),
            end_date=date(2026, 9, 16),
            reason='Medical appointment',
        )
        self.client.force_authenticate(self.employee)
        response = self.client.get('/api/leaves/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [own_leave.id])

    def test_employee_cannot_approve_leave(self):
        self.client.force_authenticate(self.employee)
        response = self.client.put(f'/api/leaves/{self.leave.id}/status/', {'status': 'APPROVED'}, format='json')
        self.assertEqual(response.status_code, 403)
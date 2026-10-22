from datetime import date
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from .test_utils import test_company
from .models import Announcement, AttendanceSettings, ChatConversation, ChatMessage, Employee, EmployeeDocument, LeaveRequest, Notification, UserProfile


class RoleBasedAccessTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user('admin', password='AdminPass123!')
        self.employee = User.objects.create_user('employee', password='EmployeePass123!')
        self.other_employee = User.objects.create_user('other', password='OtherPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=test_company())
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE', company=test_company())
        UserProfile.objects.create(user=self.other_employee, role='EMPLOYEE', company=test_company())
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

    def test_employee_login_creates_session_and_checks_selected_role(self):
        response = self.client.post('/api/login/', {
            'username': 'employee',
            'password': 'EmployeePass123!',
            'role': 'EMPLOYEE',
            'remember_me': True,
        }, format='json')

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['role'], 'EMPLOYEE')
        self.assertNotIn('access', response_data)
        self.assertNotIn('refresh', response_data)
        self.assertEqual(self.client.session.get('_auth_user_id'), str(self.employee.id))

        wrong_role = APIClient().post('/api/login/', {
            'username': 'employee',
            'password': 'EmployeePass123!',
            'role': 'ADMIN',
        }, format='json')
        self.assertEqual(wrong_role.status_code, 403)

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


class PublicAccountFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_public_registration_cannot_create_an_admin(self):
        response = self.client.post('/api/register/', {
            'username': 'new-admin',
            'email': 'new-admin@example.com',
            'password': 'A-Strong-Password-982!',
            'confirm_password': 'A-Strong-Password-982!',
            'role': 'ADMIN',
        }, format='json')

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username='new-admin').exists())

    def test_public_registration_creates_an_employee(self):
        response = self.client.post('/api/register/', {
            'username': 'new-employee',
            'email': 'new-employee@example.com',
            'password': 'A-Strong-Password-982!',
            'confirm_password': 'A-Strong-Password-982!',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username='new-employee')
        self.assertEqual(user.userprofile.role, 'EMPLOYEE')
        self.assertEqual(Notification.objects.filter(recipient=user, kind='EMPLOYEE').count(), 1)

    def test_password_reset_sends_code_without_returning_it(self):
        User.objects.create_user('reset-user', email='reset@example.com', password='Old-Password-982!')

        response = self.client.post('/api/password/forgot/', {'email': 'reset@example.com'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('otp', response.json())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['reset@example.com'])
        self.assertIn('verification code is', mail.outbox[0].body)

    def test_password_reset_completes_with_emailed_code(self):
        user = User.objects.create_user('reset-user', email='reset@example.com', password='Old-Password-982!')
        self.client.post('/api/password/forgot/', {'email': 'reset@example.com'}, format='json')
        match = re.search(r'code is (\d{6})', mail.outbox[0].body)
        self.assertIsNotNone(match)

        verification = self.client.post('/api/password/verify-otp/', {
            'email': 'reset@example.com',
            'otp': match.group(1),
        }, format='json')
        self.assertEqual(verification.status_code, 200)

        reset = self.client.post('/api/password/reset/', {
            'reset_token': verification.json()['reset_token'],
            'password': 'New-Password-982!',
            'confirm_password': 'New-Password-982!',
        }, format='json')
        self.assertEqual(reset.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password('New-Password-982!'))


class AnnouncementAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('announcement-admin', password='AdminPass123!')
        self.employee = User.objects.create_user('announcement-employee', password='EmployeePass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=test_company())
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE', company=test_company())
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.employee_client = APIClient()
        self.employee_client.force_authenticate(self.employee)

    def test_admin_can_publish_and_remove_announcement(self):
        response = self.admin_client.post('/api/announcements/', {
            'title': 'Office update',
            'message': 'The office will open at 10 AM tomorrow.',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        announcement_id = response.data['id']
        self.assertEqual(response.data['author_username'], self.admin.username)
        delete_response = self.admin_client.delete(f'/api/announcements/{announcement_id}/')
        self.assertEqual(delete_response.status_code, 204)
        self.assertFalse(Announcement.objects.filter(pk=announcement_id).exists())

    def test_employee_can_read_but_not_publish_or_remove_announcements(self):
        announcement = Announcement.objects.create(
            company=test_company(),
            title='Office update',
            message='The office will open at 10 AM tomorrow.',
            created_by=self.admin,
        )

        list_response = self.employee_client.get('/api/announcements/')
        create_response = self.employee_client.post('/api/announcements/', {
            'title': 'Unauthorized post',
            'message': 'Employees cannot publish this.',
        }, format='json')
        delete_response = self.employee_client.delete(f'/api/announcements/{announcement.id}/')

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item['id'] for item in list_response.data], [announcement.id])
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertEqual(Announcement.objects.count(), 1)

    def test_anonymous_users_cannot_read_announcements(self):
        response = APIClient().get('/api/announcements/')

        self.assertEqual(response.status_code, 401)


class PrivateChatAccessTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('chat-admin', password='AdminPass123!')
        self.other_admin = User.objects.create_user('other-chat-admin', password='AdminPass123!')
        self.employee = User.objects.create_user('chat-employee', password='EmployeePass123!')
        self.other_employee = User.objects.create_user('other-chat-employee', password='EmployeePass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=test_company())
        UserProfile.objects.create(user=self.other_admin, role='ADMIN', company=test_company())
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE', company=test_company())
        UserProfile.objects.create(user=self.other_employee, role='EMPLOYEE', company=test_company())
        self.employee_record = Employee.objects.create(
            user=self.employee,
            company=test_company(),
            employee_id='CHAT-001',
            phone='5550101',
            department='Operations',
            designation='Coordinator',
            joining_date=date(2025, 1, 1),
        )
        self.other_employee_record = Employee.objects.create(
            user=self.other_employee,
            company=test_company(),
            employee_id='CHAT-002',
            phone='5550102',
            department='Finance',
            designation='Analyst',
            joining_date=date(2025, 1, 1),
        )
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.employee_client = APIClient()
        self.employee_client.force_authenticate(self.employee)
        self.other_employee_client = APIClient()
        self.other_employee_client.force_authenticate(self.other_employee)

    def test_admin_can_start_private_thread_and_employee_can_reply(self):
        start = self.admin_client.post('/api/chat/conversations/', {
            'employee_id': self.employee.id,
        }, format='json')
        self.assertEqual(start.status_code, 201)
        conversation_id = start.data['id']

        first_message = self.admin_client.post(
            f'/api/chat/conversations/{conversation_id}/messages/',
            {'body': 'Can you confirm the handover time?'},
            format='json',
        )
        employee_threads = self.employee_client.get('/api/chat/conversations/')
        employee_messages = self.employee_client.get(f'/api/chat/conversations/{conversation_id}/messages/')
        reply = self.employee_client.post(
            f'/api/chat/conversations/{conversation_id}/messages/',
            {'body': 'Yes, it is 3 PM.'},
            format='json',
        )
        admin_messages = self.admin_client.get(f'/api/chat/conversations/{conversation_id}/messages/')

        self.assertEqual(first_message.status_code, 201)
        self.assertEqual(employee_threads.status_code, 200)
        self.assertEqual([item['id'] for item in employee_threads.data], [conversation_id])
        self.assertEqual(employee_messages.status_code, 200)
        self.assertFalse(employee_messages.data[0]['is_own'])
        self.assertEqual(reply.status_code, 201)
        self.assertTrue(reply.data['is_own'])
        self.assertEqual(len(admin_messages.data), 2)
        self.assertEqual(Notification.objects.filter(recipient=self.employee, kind='CHAT').count(), 2)
        self.assertEqual(Notification.objects.filter(recipient=self.admin, kind='CHAT').count(), 1)

    def test_employees_cannot_start_threads_and_other_users_cannot_read_them(self):
        employee_start = self.employee_client.post('/api/chat/conversations/', {
            'employee_id': self.employee.id,
        }, format='json')
        conversation = ChatConversation.objects.create(
            administrator=self.admin,
            employee=self.employee,
        )
        ChatMessage.objects.create(conversation=conversation, sender=self.admin, body='Private note')
        other_employee_read = self.other_employee_client.get(
            f'/api/chat/conversations/{conversation.id}/messages/'
        )
        other_admin_client = APIClient()
        other_admin_client.force_authenticate(self.other_admin)
        other_admin_read = other_admin_client.get(f'/api/chat/conversations/{conversation.id}/messages/')

        self.assertEqual(employee_start.status_code, 403)
        self.assertEqual(other_employee_read.status_code, 404)
        self.assertEqual(other_admin_read.status_code, 404)

    def test_only_admin_can_get_employee_chat_directory(self):
        admin_response = self.admin_client.get('/api/chat/employees/')
        employee_response = self.employee_client.get('/api/chat/employees/')

        self.assertEqual(admin_response.status_code, 200)
        self.assertEqual([item['username'] for item in admin_response.data], [self.employee.username, self.other_employee.username])
        self.assertEqual(employee_response.status_code, 403)

    def test_signup_employee_without_employee_record_is_listed_and_chat_eligible(self):
        signup_employee = User.objects.create_user('signup-chat-employee', password='EmployeePass123!')
        UserProfile.objects.create(user=signup_employee, role='EMPLOYEE', company=test_company())

        directory = self.admin_client.get('/api/chat/employees/')
        employee_entry = next(item for item in directory.data if item['username'] == signup_employee.username)
        conversation = self.admin_client.post('/api/chat/conversations/', {
            'employee_id': employee_entry['employee_id'],
        }, format='json')

        self.assertEqual(directory.status_code, 200)
        self.assertEqual(employee_entry['display_name'], signup_employee.username)
        self.assertEqual(employee_entry['department'], '')
        self.assertEqual(conversation.status_code, 201)
        self.assertEqual(conversation.data['employee_username'], signup_employee.username)

    def test_empty_and_overlong_messages_are_rejected(self):
        conversation = ChatConversation.objects.create(administrator=self.admin, employee=self.employee)
        empty = self.admin_client.post(f'/api/chat/conversations/{conversation.id}/messages/', {'body': '  '}, format='json')
        long = self.admin_client.post(f'/api/chat/conversations/{conversation.id}/messages/', {'body': 'x' * 4001}, format='json')

        self.assertEqual(empty.status_code, 400)
        self.assertEqual(long.status_code, 400)


class NotificationInboxTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('notification-admin', password='AdminPass123!')
        self.employee = User.objects.create_user('notification-employee', password='EmployeePass123!')
        self.other_employee = User.objects.create_user('notification-other', password='EmployeePass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=test_company())
        UserProfile.objects.create(user=self.employee, role='EMPLOYEE', company=test_company())
        UserProfile.objects.create(user=self.other_employee, role='EMPLOYEE', company=test_company())
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(self.admin)
        self.employee_client = APIClient()
        self.employee_client.force_authenticate(self.employee)
        self.other_employee_client = APIClient()
        self.other_employee_client.force_authenticate(self.other_employee)

    def test_inbox_is_private_and_supports_read_states(self):
        notification = Notification.objects.create(
            recipient=self.employee,
            actor=self.admin,
            kind='LEAVE',
            title='Leave request approved',
            message='Your leave was approved.',
            target_url='employee-leave.html',
        )
        Notification.objects.create(
            recipient=self.other_employee,
            kind='CHAT',
            title='Private message',
            message='Only another employee should see this.',
        )

        inbox = self.employee_client.get('/api/notifications/')
        other_inbox = self.other_employee_client.get('/api/notifications/')
        forbidden_read = self.other_employee_client.post(f'/api/notifications/{notification.id}/read/')
        marked_read = self.employee_client.post(f'/api/notifications/{notification.id}/read/')
        updated_inbox = self.employee_client.get('/api/notifications/')

        self.assertEqual(inbox.status_code, 200)
        self.assertEqual(inbox.data['unread_count'], 1)
        self.assertEqual([item['id'] for item in inbox.data['notifications']], [notification.id])
        self.assertEqual(other_inbox.data['unread_count'], 1)
        self.assertEqual(other_inbox.data['notifications'][0]['title'], 'Private message')
        self.assertEqual(forbidden_read.status_code, 404)
        self.assertTrue(marked_read.data['is_read'])
        self.assertEqual(updated_inbox.data['unread_count'], 0)

    def test_mark_all_read_is_limited_to_current_user(self):
        Notification.objects.create(recipient=self.employee, kind='HOLIDAY', title='Holiday', message='Office closed.')
        Notification.objects.create(recipient=self.other_employee, kind='HOLIDAY', title='Holiday', message='Office closed.')

        response = self.employee_client.post('/api/notifications/read-all/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['updated'], 1)
        self.assertEqual(Notification.objects.filter(recipient=self.employee, read_at__isnull=True).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.other_employee, read_at__isnull=True).count(), 1)

    def test_leave_and_work_from_home_events_notify_both_roles(self):
        leave = self.employee_client.post('/api/leaves/', {
            'leave_type': 'Casual Leave',
            'start_date': '2026-10-05',
            'end_date': '2026-10-06',
            'reason': 'Personal appointment',
        }, format='json')
        wfh = self.employee_client.post('/api/wfh/', {
            'start_date': '2026-10-07',
            'end_date': '2026-10-07',
            'reason': 'Home repair appointment',
        }, format='json')
        self.admin_client.put(f"/api/leaves/{leave.data['id']}/status/", {'status': 'APPROVED'}, format='json')
        self.admin_client.put(f"/api/wfh/{wfh.data['id']}/", {'status': 'APPROVED'}, format='json')

        admin_kinds = set(Notification.objects.filter(recipient=self.admin).values_list('kind', flat=True))
        employee_kinds = set(Notification.objects.filter(recipient=self.employee).values_list('kind', flat=True))
        self.assertEqual(leave.status_code, 201)
        self.assertEqual(wfh.status_code, 201)
        self.assertIn('LEAVE', admin_kinds)
        self.assertIn('WFH', admin_kinds)
        self.assertIn('LEAVE', employee_kinds)
        self.assertIn('WFH', employee_kinds)

    def test_announcement_holiday_and_document_events_notify_recipients(self):
        announcement = self.admin_client.post('/api/announcements/', {
            'title': 'Office update',
            'message': 'The office opens at 10 AM.',
        }, format='json')
        holiday = self.admin_client.post('/api/holidays/', {
            'name': 'Company day',
            'date': '2098-12-31',
            'holiday_type': 'FIXED',
            'description': 'Office closed.',
        }, format='json')
        document = self.employee_client.post('/api/documents/', {
            'title': 'Identity proof',
            'document_type': 'IDENTITY',
            'file': SimpleUploadedFile('proof.pdf', b'%PDF-1.4 test document', content_type='application/pdf'),
        }, format='multipart')
        review = self.admin_client.put(
            f"/api/documents/{document.data['id']}/review/",
            {'status': 'VERIFIED', 'review_note': ''},
            format='json',
        )

        admin_kinds = set(Notification.objects.filter(recipient=self.admin).values_list('kind', flat=True))
        employee_kinds = set(Notification.objects.filter(recipient=self.employee).values_list('kind', flat=True))
        self.assertEqual(announcement.status_code, 201)
        self.assertEqual(holiday.status_code, 201)
        self.assertEqual(document.status_code, 201)
        self.assertEqual(review.status_code, 200)
        self.assertIn('DOCUMENT', admin_kinds)
        self.assertIn('ANNOUNCEMENT', employee_kinds)
        self.assertIn('HOLIDAY', employee_kinds)
        self.assertIn('DOCUMENT', employee_kinds)

    def test_attendance_checkin_notifies_administrators(self):
        AttendanceSettings.objects.update_or_create(
            company=test_company(),
            defaults={'latitude': '12.971600', 'longitude': '77.594600', 'radius_meters': 100, 'is_enabled': True},
        )

        response = self.employee_client.post('/api/attendance/check-in/', {
            'latitude': '12.971600',
            'longitude': '77.594600',
        }, format='json')

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind='ATTENDANCE').exists())

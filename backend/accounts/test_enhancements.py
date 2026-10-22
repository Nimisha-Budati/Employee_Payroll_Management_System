"""Tests for attendance corrections, the team calendar, onboarding, document expiry and reminders,
notification preferences and audit filters."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from payroll.models import Payslip
from payroll.tests import make_employee, make_structure

from .test_utils import test_company
from .models import (
    AttendanceCorrectionRequest, AttendanceRecord, AuditLog, EmployeeDocument, Holiday, LeaveRequest, Notification,
    NotificationPreference, ReminderLog, UserProfile, WorkFromHomeRequest,
)
from .reminders import run_reminders

PDF = b'%PDF-1.4 test document'


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class BaseCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN', company=test_company())
        self.asha = make_employee('asha', 'EMP001', department='Engineering')
        self.ravi = make_employee('ravi', 'EMP002', department='Engineering')
        self.meena = make_employee('meena', 'EMP003', department='Sales')
        self.admin_client = self.client_for(self.admin)
        self.asha_client = self.client_for(self.asha.user)
        self.today = timezone.localdate()

    @staticmethod
    def client_for(user):
        client = APIClient()
        client.force_authenticate(user)
        return client


class AttendanceCorrectionTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.day = self.today - timedelta(days=3)
        self.record = AttendanceRecord.objects.create(employee=self.asha.user, date=self.day, check_in_at=aware(self.day, 9, 40))

    def request(self, client=None, **overrides):
        data = {'date': self.day.isoformat(), 'correction_type': 'MISSED_CHECK_OUT', 'check_out': '18:05',
                'reason': 'Forgot to check out at the gate.'}
        data.update(overrides)
        return (client or self.asha_client).post('/api/attendance/corrections/', data, format='json')

    def test_employee_requests_and_admin_approves_with_audit(self):
        created = self.request()
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data['status'], 'PENDING')
        self.assertIsNotNone(created.data['original_check_in'])
        self.assertIsNone(created.data['original_check_out'])
        # Attendance is unchanged until approval.
        self.record.refresh_from_db()
        self.assertIsNone(self.record.check_out_at)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind='CORRECTION').exists())

        approved = self.admin_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/', {'status': 'APPROVED'}, format='json')
        self.assertEqual(approved.status_code, 200, approved.data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.check_out_at, aware(self.day, 18, 5))
        self.assertTrue(self.record.is_corrected)
        log = AuditLog.objects.get(entity_type='AttendanceCorrection', action='APPROVE')
        self.assertIn('check-out — → ', log.summary)
        self.assertIn('Forgot to check out', log.summary)
        self.assertEqual(log.subject, self.asha.user)
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(log.module, 'Attendance')
        self.assertTrue(Notification.objects.filter(recipient=self.asha.user, kind='CORRECTION', title__icontains='approved').exists())

    def test_check_in_correction_recalculates_late_minutes(self):
        from workforce.models import Shift

        Shift.objects.create(company=test_company(), name='General', start_time=time(9, 0), end_time=time(18, 0), grace_minutes=10, is_default=True)
        created = self.request(correction_type='WRONG_TIMES', check_in='09:05', check_out=None)
        self.assertEqual(created.status_code, 201, created.data)
        self.admin_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/', {'status': 'APPROVED'}, format='json')
        self.record.refresh_from_db()
        self.assertEqual(self.record.late_minutes, 0)
        self.assertEqual(self.record.shift_name, 'General')

    def test_validation_rules(self):
        self.assertEqual(self.request(date=(self.today + timedelta(days=1)).isoformat()).status_code, 400)          # future date
        self.assertEqual(self.request(date=(self.today - timedelta(days=90)).isoformat()).status_code, 400)        # outside window
        self.assertIn('check_out', self.request(correction_type='WRONG_TIMES', check_in='10:00', check_out='09:00').data)
        self.assertIn('correction_type', self.request(correction_type='MISSED_CHECK_IN', check_in='09:00').data)   # already checked in
        self.assertIn('check_in', self.request(correction_type='MISSED_DAY', date=(self.day - timedelta(days=1)).isoformat(),
                                               check_in=None, check_out='18:00').data)
        self.assertEqual(self.request(reason='no').status_code, 400)
        # Overnight check-out on the next day is allowed.
        overnight = self.request(check_out='02:00', check_out_next_day=True)
        self.assertEqual(overnight.status_code, 201, overnight.data)
        # Duplicate pending requests for the same day are refused.
        duplicate = self.request()
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('pending', str(duplicate.data))

    def test_permissions_and_cancel(self):
        self.assertEqual(self.request(client=self.admin_client).status_code, 403)
        created = self.request()
        ravi = self.client_for(self.ravi.user)
        self.assertEqual(ravi.get('/api/attendance/corrections/').data, [])
        self.assertEqual(ravi.post(f'/api/attendance/corrections/{created.data["id"]}/cancel/').status_code, 404)
        self.assertEqual(self.asha_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/', {'status': 'APPROVED'}, format='json').status_code, 403)
        self.assertEqual(self.admin_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/', {'status': 'REJECTED'}, format='json').status_code, 400)
        cancelled = self.asha_client.post(f'/api/attendance/corrections/{created.data["id"]}/cancel/')
        self.assertEqual(cancelled.data['status'], 'CANCELLED')
        self.assertEqual(self.asha_client.post(f'/api/attendance/corrections/{created.data["id"]}/cancel/').status_code, 409)
        self.assertEqual(self.admin_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/', {'status': 'APPROVED'}, format='json').status_code, 409)
        # A new request for the day is allowed once the old one is cancelled.
        self.assertEqual(self.request().status_code, 201)

    def test_rejection_keeps_attendance_and_finalised_payroll_blocks_changes(self):
        created = self.request()
        rejected = self.admin_client.post(f'/api/attendance/corrections/{created.data["id"]}/review/',
                                          {'status': 'REJECTED', 'review_note': 'Gate log shows 17:00.'}, format='json')
        self.assertEqual(rejected.data['status'], 'REJECTED')
        self.record.refresh_from_db()
        self.assertIsNone(self.record.check_out_at)
        self.assertTrue(AuditLog.objects.filter(entity_type='AttendanceCorrection', action='REJECT').exists())

        Payslip.objects.create(employee=self.asha.user, year=self.day.year, month=self.day.month, employee_code='EMP001',
                               employee_name='Asha', status=Payslip.PAID)
        self.assertEqual(self.request().status_code, 400)

    def test_admin_filters(self):
        self.request()
        AttendanceRecord.objects.create(employee=self.meena.user, date=self.day, check_in_at=aware(self.day, 9))
        meena = self.client_for(self.meena.user)
        meena.post('/api/attendance/corrections/', {'date': self.day.isoformat(), 'correction_type': 'MISSED_CHECK_OUT',
                                                    'check_out': '18:00', 'reason': 'Phone battery died.'}, format='json')
        self.assertEqual(len(self.admin_client.get('/api/attendance/corrections/').data), 2)
        self.assertEqual(len(self.admin_client.get('/api/attendance/corrections/', {'department': 'Sales'}).data), 1)
        self.assertEqual(len(self.admin_client.get('/api/attendance/corrections/', {'search': 'EMP001'}).data), 1)
        self.assertEqual(len(self.admin_client.get('/api/attendance/corrections/', {'status': 'APPROVED'}).data), 0)
        paged = self.admin_client.get('/api/attendance/corrections/', {'page': 1, 'page_size': 1})
        self.assertEqual(paged.data['count'], 2)


class TeamCalendarTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.start = self.today.replace(day=1)
        LeaveRequest.objects.create(employee=self.ravi.user, leave_type='Sick Leave', start_date=self.start,
                                    end_date=self.start + timedelta(days=1), reason='private illness', status='APPROVED')
        LeaveRequest.objects.create(employee=self.meena.user, leave_type='Casual Leave', start_date=self.start,
                                    end_date=self.start, reason='sales trip', status='APPROVED')
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=self.start + timedelta(days=2),
                                    end_date=self.start + timedelta(days=2), reason='mine', status='PENDING')
        WorkFromHomeRequest.objects.create(employee=self.asha.user, start_date=self.start, end_date=self.start,
                                           reason='plumber', status='APPROVED')
        Holiday.objects.create(company=test_company(), name='Founders Day', date=self.start + timedelta(days=4))

    def get(self, client, **params):
        params.setdefault('start', self.start.isoformat())
        params.setdefault('end', (self.start + timedelta(days=30)).isoformat())
        return client.get('/api/calendar/', params)

    def test_admin_sees_everyone_and_can_filter(self):
        data = self.get(self.admin_client).data
        titles = {(e['type'], e['employee_name']) for e in data['events']}
        self.assertIn(('leave', 'Ravi'), titles)
        self.assertIn(('leave', 'Meena'), titles)
        self.assertIn(('wfh', 'Asha'), titles)
        self.assertIn(('holiday', ''), titles)
        self.assertFalse(any('Casual' in e['title'] and e['employee_name'] == 'Asha' for e in data['events']))   # pending not shown
        sales = self.get(self.admin_client, department='Sales', types='leave').data['events']
        self.assertEqual([e['employee_name'] for e in sales], ['Meena'])
        self.assertEqual(self.get(self.admin_client, employee=self.ravi.user_id, types='leave').data['events'][0]['title'], 'Sick Leave')

    def test_employee_scopes_protect_colleague_details(self):
        mine = self.get(self.asha_client).data
        self.assertEqual({e['employee_name'] for e in mine['events'] if e['employee_name']}, {'Asha'})
        team = self.get(self.asha_client, scope='team').data
        ravi_leave = [e for e in team['events'] if e['employee_name'] == 'Ravi']
        self.assertEqual(ravi_leave[0]['title'], 'On leave')
        self.assertEqual(ravi_leave[0]['detail'], '')
        body = str(team)
        self.assertNotIn('Sick', body)
        self.assertNotIn('private illness', body)
        self.assertNotIn('Meena', body)          # other department
        # The employee cannot widen the scope with filters meant for administrators.
        self.assertNotIn('Meena', str(self.get(self.asha_client, scope='team', department='Sales', employee=self.meena.user_id).data))

    def test_range_validation(self):
        self.assertEqual(self.get(self.admin_client, end=(self.start + timedelta(days=90)).isoformat()).status_code, 400)
        self.assertEqual(self.get(self.admin_client, end=(self.start - timedelta(days=1)).isoformat()).status_code, 400)


class OnboardingTests(BaseCase):
    def upload(self, client, document_type, expiry=None):
        data = {'title': f'{document_type} proof', 'document_type': document_type,
                'file': SimpleUploadedFile('doc.pdf', PDF, content_type='application/pdf')}
        if expiry:
            data['expiry_date'] = expiry.isoformat()
        return client.post('/api/documents/', data, format='multipart')

    def test_checklist_ready_notification_and_completion(self):
        status = self.asha_client.get('/api/onboarding/me/').data
        self.assertEqual(status['state'], 'IN_PROGRESS')
        self.assertIn('Postal address', status['missing'])
        self.assertIn('Identity Proof', status['missing'])
        self.assertIn('Salary structure', status['missing'])

        refused = self.admin_client.post(f'/api/onboarding/{self.asha.pk}/complete/')
        self.assertEqual(refused.status_code, 409)
        self.assertIn('Missing', refused.data['detail'])

        remind = self.admin_client.post(f'/api/onboarding/{self.asha.pk}/remind/')
        self.assertEqual(remind.status_code, 200)
        self.assertNotIn('Salary structure', remind.data['missing'])     # admin items are not sent to the employee

        self.asha_client.put('/api/profile/', {'address': '12 MG Road', 'last_name': 'Rao'}, format='json')
        for kind in ('IDENTITY', 'ADDRESS'):
            doc = self.upload(self.asha_client, kind)
            self.admin_client.put(f'/api/documents/{doc.data["id"]}/review/', {'status': 'VERIFIED'}, format='json')
        self.assertFalse(Notification.objects.filter(recipient=self.admin, kind='ONBOARDING').exists())
        make_structure(self.asha.user)
        self.admin_client.put(f'/api/payroll/salary-structures/{self.asha.pk}/', {
            'basic': '30000', 'hra': '12000', 'pf_percent': '12', 'effective_from': '2024-01-01'}, format='json')
        self.assertEqual(self.asha_client.get('/api/onboarding/me/').data['state'], 'READY')
        self.assertEqual(Notification.objects.filter(recipient=self.admin, kind='ONBOARDING').count(), 1)

        done = self.admin_client.post(f'/api/onboarding/{self.asha.pk}/complete/', {'note': 'All good'}, format='json')
        self.assertEqual(done.status_code, 200, done.data)
        self.assertEqual(done.data['state'], 'COMPLETED')
        self.assertTrue(Notification.objects.filter(recipient=self.asha.user, kind='ONBOARDING', title='Onboarding complete').exists())
        self.assertTrue(AuditLog.objects.filter(entity_type='Onboarding', action='COMPLETE', subject=self.asha.user).exists())
        listed = self.admin_client.get('/api/onboarding/').data
        self.assertNotIn(self.asha.pk, [row['employee_pk'] for row in listed['results']])
        self.assertEqual(listed['counts']['COMPLETED'], 1)

        reopened = self.admin_client.post(f'/api/onboarding/{self.asha.pk}/reopen/', {'note': 'ID expired'}, format='json')
        self.assertEqual(reopened.data['state'], 'READY')

    def test_settings_and_permissions(self):
        self.assertEqual(self.asha_client.get('/api/onboarding/').status_code, 403)
        self.assertEqual(self.asha_client.post(f'/api/onboarding/{self.asha.pk}/complete/').status_code, 403)
        saved = self.admin_client.put('/api/onboarding/settings/', {
            'required_document_types': [], 'require_address': False, 'require_salary_structure': False}, format='json')
        self.assertEqual(saved.status_code, 200, saved.data)
        self.assertEqual(self.admin_client.put('/api/onboarding/settings/', {'required_document_types': ['PASSPORT']}, format='json').status_code, 400)
        # With only name/email/phone/job required, an employee with a last name is ready.
        self.asha_client.put('/api/profile/', {'last_name': 'Rao'}, format='json')
        self.assertEqual(self.asha_client.get('/api/onboarding/me/').data['state'], 'READY')

    def test_expired_document_does_not_count(self):
        self.admin_client.put('/api/onboarding/settings/', {'required_document_types': ['IDENTITY']}, format='json')
        doc = self.upload(self.asha_client, 'IDENTITY', expiry=self.today + timedelta(days=10))
        self.admin_client.put(f'/api/documents/{doc.data["id"]}/review/', {'status': 'VERIFIED'}, format='json')
        items = {i['key']: i for i in self.asha_client.get('/api/onboarding/me/').data['items']}
        self.assertTrue(items['doc:IDENTITY']['done'])
        EmployeeDocument.objects.filter(pk=doc.data['id']).update(expiry_date=self.today - timedelta(days=1))
        items = {i['key']: i for i in self.asha_client.get('/api/onboarding/me/').data['items']}
        self.assertEqual(items['doc:IDENTITY']['state'], 'Expired')


class DocumentExpiryAndReminderTests(BaseCase):
    def upload(self, expiry=None, client=None):
        data = {'title': 'Passport', 'document_type': 'IDENTITY', 'file': SimpleUploadedFile('doc.pdf', PDF, content_type='application/pdf')}
        if expiry:
            data['expiry_date'] = expiry.isoformat()
        return (client or self.asha_client).post('/api/documents/', data, format='multipart')

    def test_expiry_status_filters_and_admin_update(self):
        self.assertEqual(self.upload(expiry=self.today - timedelta(days=1)).status_code, 400)
        soon = self.upload(expiry=self.today + timedelta(days=5)).data
        later = self.upload(expiry=self.today + timedelta(days=200)).data
        plain = self.upload().data
        self.assertEqual((soon['expiry_status'], soon['days_to_expiry']), ('EXPIRING', 5))
        self.assertEqual(later['expiry_status'], 'VALID')
        self.assertEqual(plain['expiry_status'], 'NONE')
        self.assertEqual(soon['status'], 'PENDING')   # review status is separate
        ids = lambda **p: [d['id'] for d in self.admin_client.get('/api/documents/', p).data]
        self.assertEqual(ids(expiry='EXPIRING'), [soon['id']])
        self.assertEqual(ids(expiry='NONE'), [plain['id']])
        self.assertEqual(self.asha_client.put(f'/api/documents/{plain["id"]}/expiry/', {'expiry_date': '2030-01-01'}, format='json').status_code, 403)
        changed = self.admin_client.put(f'/api/documents/{plain["id"]}/expiry/', {'expiry_date': (self.today - timedelta(days=2)).isoformat()}, format='json')
        self.assertEqual(changed.data['expiry_status'], 'EXPIRED')
        self.assertEqual(changed.data['status'], 'PENDING')
        self.assertEqual(ids(expiry='EXPIRED'), [plain['id']])
        self.assertTrue(AuditLog.objects.filter(entity_type='Document', summary__contains='Changed expiry').exists())
        self.assertEqual(self.client_for(self.ravi.user).get('/api/documents/').data, [])   # documents stay private

    def test_expiry_reminders_are_sent_once_per_stage(self):
        doc = self.upload(expiry=self.today + timedelta(days=6)).data
        first = run_reminders(company=test_company())
        self.assertEqual(first['documents'], 1)
        self.assertEqual(run_reminders(company=test_company())['documents'], 0)
        employee_notes = Notification.objects.filter(recipient=self.asha.user, kind='REMINDER')
        self.assertEqual(employee_notes.count(), 1)
        self.assertIn('expires in 6 days', employee_notes.first().message)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind='REMINDER', title='Document expiring soon').exists())
        EmployeeDocument.objects.filter(pk=doc['id']).update(expiry_date=self.today - timedelta(days=1))
        self.assertEqual(run_reminders(company=test_company())['documents'], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.asha.user, title='Document expired').exists())
        self.assertEqual(run_reminders(company=test_company())['documents'], 0)

    def test_pending_digest_settings_and_command(self):
        from django.core.management import call_command
        from io import StringIO

        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=self.today,
                                    end_date=self.today, reason='x')
        LeaveRequest.objects.filter(employee=self.asha.user).update(applied_at=timezone.now() - timedelta(days=5))
        out = StringIO()
        call_command('send_reminders', stdout=out)
        self.assertIn('1 pending-approval digest', out.getvalue())
        digest = Notification.objects.get(recipient=self.admin, title='Requests waiting for approval')
        self.assertIn('1 leave request', digest.message)
        self.assertEqual(run_reminders(company=test_company())['pending_digest'], 0)   # once per day

        self.assertEqual(self.asha_client.get('/api/reminders/settings/').status_code, 403)
        self.assertEqual(self.admin_client.put('/api/reminders/settings/', {'pending_after_days': 0}, format='json').status_code, 400)
        saved = self.admin_client.put('/api/reminders/settings/', {'document_reminder_days': [14, 3, 3], 'enabled': False}, format='json')
        self.assertEqual(saved.data['document_reminder_days'], [14, 3])
        self.assertFalse(self.admin_client.post('/api/reminders/run/').data['enabled'])
        self.assertTrue(AuditLog.objects.filter(entity_type='Reminder', action='UPDATE').exists())

    def test_dashboard_runs_reminders_automatically(self):
        self.upload(expiry=self.today + timedelta(days=2))
        self.admin_client.get('/api/dashboard/admin/')
        self.assertTrue(ReminderLog.objects.filter(key__startswith='doc:').exists())
        data = self.admin_client.get('/api/dashboard/admin/').data
        self.assertEqual(data['documents']['expiring'], 1)


class NotificationPreferenceTests(BaseCase):
    def test_optional_kinds_can_be_muted_but_security_cannot(self):
        prefs = self.asha_client.get('/api/notifications/preferences/').data
        self.assertIn('ANNOUNCEMENT', [p['kind'] for p in prefs['optional']])
        self.assertIn('SECURITY', [p['kind'] for p in prefs['mandatory']])
        self.assertEqual(self.asha_client.put('/api/notifications/preferences/', {'preferences': {'SECURITY': False}}, format='json').status_code, 400)
        self.assertEqual(self.asha_client.put('/api/notifications/preferences/', {'preferences': {'NOPE': False}}, format='json').status_code, 400)
        saved = self.asha_client.put('/api/notifications/preferences/', {'preferences': {'ANNOUNCEMENT': False}}, format='json')
        self.assertFalse(next(p for p in saved.data['optional'] if p['kind'] == 'ANNOUNCEMENT')['enabled'])

        self.admin_client.post('/api/announcements/', {'title': 'Picnic', 'message': 'Friday'}, format='json')
        self.assertFalse(Notification.objects.filter(recipient=self.asha.user, kind='ANNOUNCEMENT').exists())
        self.assertTrue(Notification.objects.filter(recipient=self.ravi.user, kind='ANNOUNCEMENT').exists())

        changed = self.asha_client.post('/api/password/change/', {'current_password': 'EmployeePass123!', 'new_password': 'N3w-Secure-Pass!',
                                                                  'confirm_password': 'N3w-Secure-Pass!'}, format='json')
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(Notification.objects.filter(recipient=self.asha.user, kind='SECURITY').exists())

    def test_unread_filter_and_counts(self):
        Notification.objects.create(recipient=self.asha.user, kind='LEAVE', title='a', message='a')
        read = Notification.objects.create(recipient=self.asha.user, kind='WFH', title='b', message='b', read_at=timezone.now())
        data = self.asha_client.get('/api/notifications/', {'unread': 'true'}).data
        self.assertEqual(data['unread_count'], 1)
        self.assertEqual(data['unread_by_kind'], {'LEAVE': 1})
        self.assertNotIn(read.pk, [n['id'] for n in data['notifications']])
        self.assertEqual(len(self.asha_client.get('/api/notifications/', {'kind': 'WFH'}).data['notifications']), 1)


class AuditImprovementTests(BaseCase):
    def test_employee_filter_meta_and_append_only(self):
        leave = LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=self.today,
                                            end_date=self.today, reason='x')
        self.admin_client.put(f'/api/leaves/{leave.pk}/status/', {'status': 'APPROVED'}, format='json')
        self.admin_client.delete(f'/api/employees/{self.ravi.pk}/')
        asha_logs = self.admin_client.get('/api/audit-logs/', {'employee': self.asha.user_id}).data
        self.assertEqual([log['action'] for log in asha_logs], ['APPROVE'])
        self.assertEqual(asha_logs[0]['subject_name'], 'asha')
        meta = self.admin_client.get('/api/audit-logs/meta/').data
        self.assertIn('Leave', meta['modules'])
        self.assertIn('DEACTIVATE', meta['actions'])
        self.ravi.refresh_from_db()
        self.assertEqual(self.ravi.deactivated_at, self.today)

        # Employees cannot read or change audit records, and nobody can edit them through the API or ORM.
        self.assertEqual(self.asha_client.get('/api/audit-logs/').status_code, 403)
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertIn(getattr(self.admin_client, method)('/api/audit-logs/', {}, format='json').status_code, (403, 405))
        log = AuditLog.objects.first()
        log.summary = 'tampered'
        with self.assertRaises(PermissionError):
            log.save()
        with self.assertRaises(PermissionError):
            log.delete()

    def test_reactivation_clears_deactivation_date(self):
        self.admin_client.put(f'/api/employees/{self.ravi.pk}/', {'status': 'INACTIVE'}, format='json')
        self.ravi.refresh_from_db()
        self.assertEqual(self.ravi.deactivated_at, self.today)
        self.admin_client.put(f'/api/employees/{self.ravi.pk}/', {'status': 'ACTIVE'}, format='json')
        self.ravi.refresh_from_db()
        self.assertIsNone(self.ravi.deactivated_at)
        self.assertEqual(list(AuditLog.objects.filter(subject=self.ravi.user).values_list('action', flat=True)), ['REACTIVATE', 'DEACTIVATE'])

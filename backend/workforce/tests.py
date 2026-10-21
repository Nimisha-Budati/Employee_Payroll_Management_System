from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AttendanceRecord, AttendanceSettings, AuditLog, Notification, UserProfile
from payroll.calculator import compute_amounts
from payroll.models import Payslip
from payroll.tests import JUNE_2025_PRESENT, check_in, make_employee, make_structure

from .models import OvertimeRecord, Shift, ShiftAssignment
from .services import late_minutes, shift_for

OFFICE = {'latitude': '17.385000', 'longitude': '78.486700'}


def aware(day, hour, minute=0):
    return timezone.make_aware(datetime.combine(day, time(hour, minute)))


class WorkforceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001')
        self.ravi = make_employee('ravi', 'EMP002', department='Sales')
        self.client = APIClient()

    def as_admin(self):
        self.client.force_authenticate(self.admin)
        return self.client

    def as_user(self, user):
        self.client.force_authenticate(user)
        return self.client

    def make_shift(self, **values):
        data = {'name': 'General', 'start_time': '09:30', 'end_time': '18:30', 'grace_minutes': 10, 'break_minutes': 60}
        data.update(values)
        response = self.as_admin().post('/api/shifts/', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return Shift.objects.get(pk=response.data['id'])


class ShiftManagementTests(WorkforceTestCase):
    def test_admin_creates_edits_and_protects_shifts(self):
        shift = self.make_shift(is_default=True)
        self.assertEqual(shift.standard_minutes, 480)
        night = self.make_shift(name='Night', start_time='22:00', end_time='06:00', is_default=True)
        shift.refresh_from_db()
        self.assertFalse(shift.is_default)   # only one default shift
        self.assertTrue(night.crosses_midnight)
        self.assertEqual(night.duration_minutes, 480)

        duplicate = self.client.post('/api/shifts/', {'name': 'general', 'start_time': '08:00', 'end_time': '17:00'}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        bad_break = self.client.post('/api/shifts/', {'name': 'Short', 'start_time': '08:00', 'end_time': '09:00', 'break_minutes': 60}, format='json')
        self.assertEqual(bad_break.status_code, 400)

        edited = self.client.patch(f'/api/shifts/{shift.pk}/', {'grace_minutes': 5}, format='json')
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.data['grace_minutes'], 5)

        self.client.post('/api/shifts/assignments/', {'employee_ids': [self.asha.user_id], 'shift_id': shift.pk,
                                                      'start_date': '2025-06-01'}, format='json')
        self.assertEqual(self.client.delete(f'/api/shifts/{shift.pk}/').status_code, 409)
        self.assertTrue(AuditLog.objects.filter(module='Shifts', action='CREATE').exists())

    def test_employees_cannot_manage_shifts(self):
        client = self.as_user(self.asha.user)
        self.assertEqual(client.get('/api/shifts/').status_code, 403)
        self.assertEqual(client.post('/api/shifts/', {'name': 'X', 'start_time': '09:00', 'end_time': '17:00'}, format='json').status_code, 403)
        self.assertEqual(client.get('/api/shifts/assignments/').status_code, 403)
        self.assertEqual(client.get('/api/shifts/my/').status_code, 200)

    def test_assignment_overlap_replace_and_employee_shift_record(self):
        general = self.make_shift()
        evening = self.make_shift(name='Evening', start_time='14:00', end_time='22:00')
        client = self.as_admin()
        first = client.post('/api/shifts/assignments/', {'employee_ids': [self.asha.user_id, self.ravi.user_id],
                                                         'shift_id': general.pk, 'start_date': '2025-06-01'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(len(first.data), 2)
        self.assertTrue(Notification.objects.filter(recipient=self.asha.user, kind='SHIFT').exists())

        conflict = client.post('/api/shifts/assignments/', {'employee_ids': [self.asha.user_id], 'shift_id': evening.pk,
                                                            'start_date': '2025-07-01'}, format='json')
        self.assertEqual(conflict.status_code, 409)
        replaced = client.post('/api/shifts/assignments/', {'employee_ids': [self.asha.user_id], 'shift_id': evening.pk,
                                                            'start_date': '2025-07-01', 'replace': True}, format='json')
        self.assertEqual(replaced.status_code, 201)
        old = ShiftAssignment.objects.get(employee=self.asha.user, shift=general)
        self.assertEqual(old.end_date, date(2025, 6, 30))
        self.assertEqual(shift_for(self.asha.user, date(2025, 6, 15)), general)
        self.assertEqual(shift_for(self.asha.user, date(2025, 7, 15)), evening)

        mine = self.as_user(self.asha.user).get('/api/shifts/my/')
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.data['shift']['name'], 'Evening')
        self.assertEqual(mine.data['source'], 'ASSIGNED')
        self.assertEqual(len(mine.data['assignments']), 2)

        listed = self.as_admin().get('/api/shifts/assignments/', {'on': '2025-06-10', 'search': 'asha'})
        self.assertEqual([item['shift']['name'] for item in listed.data], ['General'])

    def test_default_shift_applies_without_assignment(self):
        self.assertIsNone(shift_for(self.asha.user, date(2025, 6, 2)))
        default = self.make_shift(is_default=True)
        self.assertEqual(shift_for(self.asha.user, date(2025, 6, 2)), default)


class LateMinuteTests(WorkforceTestCase):
    def setUp(self):
        super().setUp()
        AttendanceSettings.objects.create(pk=1, latitude=OFFICE['latitude'], longitude=OFFICE['longitude'], radius_meters=100, is_enabled=True)
        self.shift = self.make_shift(grace_minutes=10)
        self.as_admin().post('/api/shifts/assignments/', {'employee_ids': [self.asha.user_id, self.ravi.user_id],
                                                          'shift_id': self.shift.pk, 'start_date': '2025-01-01'}, format='json')

    def check_in_at(self, user, moment):
        with mock.patch('django.utils.timezone.now', return_value=moment):
            return self.as_user(user).post('/api/attendance/check-in/', OFFICE, format='json')

    def test_late_minutes_rule(self):
        day = date(2025, 6, 2)
        self.assertEqual(late_minutes(self.shift, day, aware(day, 9, 30)), 0)
        self.assertEqual(late_minutes(self.shift, day, aware(day, 9, 40)), 0)    # inside the 10-minute grace
        self.assertEqual(late_minutes(self.shift, day, aware(day, 9, 41)), 11)   # beyond grace: counted from start
        self.assertEqual(late_minutes(self.shift, day, aware(day, 9, 0)), 0)     # early
        self.assertIsNone(late_minutes(None, day, aware(day, 11, 0)))

    def test_check_in_records_shift_and_late_minutes_and_reports_them(self):
        day = date(2025, 6, 2)
        response = self.check_in_at(self.asha.user, aware(day, 9, 52))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['late_minutes'], 22)
        self.assertEqual(response.data['shift_name'], 'General')
        on_time = self.check_in_at(self.ravi.user, aware(day, 9, 35))
        self.assertEqual(on_time.data['late_minutes'], 0)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, message__contains='22 min late').exists())

        admin = self.as_admin()
        late_only = admin.get('/api/attendance/', {'late': 'true', 'date': '2025-06-02'})
        self.assertEqual([row['employee_username'] for row in late_only.data], ['asha'])
        summary = admin.get('/api/attendance/', {'summary': 'true', 'from': '2025-06-01', 'to': '2025-06-30'})
        rows = {row['employee_code']: row for row in summary.data['employees']}
        self.assertEqual(rows['EMP001']['late_days'], 1)
        self.assertEqual(rows['EMP001']['late_minutes'], 22)
        self.assertEqual(rows['EMP002']['late_minutes'], 0)
        self.assertEqual(summary.data['totals']['late_minutes'], 22)


class OvertimeTests(WorkforceTestCase):
    def setUp(self):
        super().setUp()
        make_structure(self.asha.user, overtime_rate=Decimal('250'))
        make_structure(self.ravi.user)

    def test_employee_claim_admin_approval_and_payroll_integration(self):
        claim = self.as_user(self.asha.user).post('/api/overtime/', {'date': '2025-06-10', 'hours': '2.5', 'reason': 'Release night'}, format='json')
        self.assertEqual(claim.status_code, 201, claim.data)
        self.assertEqual(claim.data['status'], 'PENDING')
        self.assertEqual(Decimal(claim.data['rate']), Decimal('250.00'))   # taken from the salary structure
        self.assertEqual(Decimal(claim.data['amount']), Decimal('625.00'))
        self.assertTrue(Notification.objects.filter(recipient=self.admin, kind='OVERTIME').exists())

        duplicate = self.client.post('/api/overtime/', {'date': '2025-06-10', 'hours': '1', 'reason': 'again'}, format='json')
        self.assertEqual(duplicate.status_code, 400)
        quarter = self.client.post('/api/overtime/', {'date': '2025-06-11', 'hours': '1.1', 'reason': 'x'}, format='json')
        self.assertEqual(quarter.status_code, 400)
        future = self.client.post('/api/overtime/', {'date': str(timezone.localdate() + timedelta(days=2)), 'hours': '1', 'reason': 'x'}, format='json')
        self.assertEqual(future.status_code, 400)
        # Employees cannot review their own claim.
        self.assertEqual(self.client.put(f'/api/overtime/{claim.data["id"]}/review/', {'status': 'APPROVED'}, format='json').status_code, 403)

        # A second pending claim is NOT paid.
        pending = self.client.post('/api/overtime/', {'date': '2025-06-12', 'hours': '3', 'reason': 'Support'}, format='json')
        self.assertEqual(pending.status_code, 201)

        admin = self.as_admin()
        self.assertEqual(admin.put(f'/api/overtime/{claim.data["id"]}/review/', {'status': 'REJECTED'}, format='json').status_code, 400)
        approved = admin.put(f'/api/overtime/{claim.data["id"]}/review/', {'status': 'APPROVED'}, format='json')
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.data['status'], 'APPROVED')
        self.assertEqual(admin.put(f'/api/overtime/{claim.data["id"]}/review/', {'status': 'REJECTED', 'review_note': 'x'}, format='json').status_code, 400)
        self.assertTrue(AuditLog.objects.filter(module='Overtime', action='APPROVE').exists())

        for day in JUNE_2025_PRESENT:
            check_in(self.asha.user, day)
        run = admin.post('/api/payroll/run/', {'year': 2025, 'month': 6}, format='json')
        self.assertEqual(run.status_code, 201)
        self.assertEqual(run.data['pending_overtime'], 1)
        slip = Payslip.objects.get(employee=self.asha.user, year=2025, month=6)
        self.assertEqual(slip.overtime_hours, Decimal('2.50'))
        self.assertEqual(slip.overtime_pay, Decimal('625.00'))   # only the approved record

        # Approving the second claim and recalculating the draft adds it.
        admin.put(f'/api/overtime/{pending.data["id"]}/review/', {'status': 'APPROVED'}, format='json')
        admin.post(f'/api/payroll/payslips/{slip.pk}/recalculate/')
        slip.refresh_from_db()
        self.assertEqual(slip.overtime_pay, Decimal('1375.00'))

        # After finalising, overtime in that month is locked.
        admin.post('/api/payroll/variance/review/', {'year': 2025, 'month': 6, 'acknowledge_flags': True}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json')
        locked = admin.post('/api/overtime/', {'employee_id': self.asha.user_id, 'date': '2025-06-20', 'hours': '1', 'reason': 'late entry', 'approve': True}, format='json')
        self.assertEqual(locked.status_code, 409)

    def test_admin_manual_entry_and_privacy(self):
        admin = self.as_admin()
        manual = admin.post('/api/overtime/', {'employee_id': self.ravi.user_id, 'date': '2025-06-03', 'hours': '1.5',
                                               'rate': '400', 'reason': 'Audit support', 'approve': True}, format='json')
        self.assertEqual(manual.status_code, 201, manual.data)
        self.assertEqual(manual.data['status'], 'APPROVED')
        self.assertEqual(manual.data['source'], 'MANUAL')
        self.assertEqual(Decimal(manual.data['amount']), Decimal('600.00'))
        missing_employee = admin.post('/api/overtime/', {'date': '2025-06-03', 'hours': '1', 'reason': 'x'}, format='json')
        self.assertEqual(missing_employee.status_code, 400)

        mine = self.as_user(self.asha.user).get('/api/overtime/')
        self.assertEqual(mine.data['results'], [])
        self.assertEqual(self.client.put(f'/api/overtime/{manual.data["id"]}/', {'hours': '8'}, format='json').status_code, 404)

        listed = self.as_admin().get('/api/overtime/', {'year': 2025, 'month': 6, 'status': 'APPROVED', 'page': 1})
        self.assertEqual(listed.data['count'], 1)
        self.assertEqual(Decimal(str(listed.data['totals']['approved_amount'])), Decimal('600.00'))

    def test_employee_edits_and_cancels_pending_claim(self):
        client = self.as_user(self.asha.user)
        claim = client.post('/api/overtime/', {'date': '2025-06-10', 'hours': '1', 'reason': 'x'}, format='json')
        edited = client.patch(f'/api/overtime/{claim.data["id"]}/', {'hours': '2', 'rate': '9999'}, format='json')
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(Decimal(edited.data['amount']), Decimal('500.00'))   # employees cannot change the rate
        cancelled = client.delete(f'/api/overtime/{claim.data["id"]}/')
        self.assertEqual(cancelled.data['status'], 'CANCELLED')
        self.assertEqual(client.delete(f'/api/overtime/{claim.data["id"]}/').status_code, 409)

    def test_generate_pending_overtime_from_attendance(self):
        shift = self.make_shift()   # 09:30-18:30 with a 60 minute break -> 8 h standard day
        ShiftAssignment.objects.create(employee=self.asha.user, shift=shift, start_date=date(2025, 1, 1))
        AttendanceRecord.objects.create(employee=self.asha.user, date=date(2025, 6, 2), shift=shift, shift_name=shift.name,
                                        check_in_at=aware(date(2025, 6, 2), 9, 30), check_out_at=aware(date(2025, 6, 2), 19, 50))
        AttendanceRecord.objects.create(employee=self.asha.user, date=date(2025, 6, 3), shift=shift, shift_name=shift.name,
                                        check_in_at=aware(date(2025, 6, 3), 9, 30), check_out_at=aware(date(2025, 6, 3), 17, 40))   # 10 min extra: below a quarter hour
        # Ravi has no shift: the 8 h standard day applies.
        AttendanceRecord.objects.create(employee=self.ravi.user, date=date(2025, 6, 2),
                                        check_in_at=aware(date(2025, 6, 2), 9, 0), check_out_at=aware(date(2025, 6, 2), 18, 0))
        admin = self.as_admin()
        result = admin.post('/api/overtime/generate/', {'year': 2025, 'month': 6}, format='json')
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.data['created'], 2)
        asha = OvertimeRecord.objects.get(employee=self.asha.user)
        self.assertEqual(asha.hours, Decimal('2.25'))   # 10h20m worked - 8h, rounded down to a quarter hour
        self.assertEqual(asha.status, 'PENDING')
        self.assertEqual(asha.source, 'ATTENDANCE')
        self.assertEqual(OvertimeRecord.objects.get(employee=self.ravi.user).hours, Decimal('1.00'))
        again = admin.post('/api/overtime/generate/', {'year': 2025, 'month': 6}, format='json')
        self.assertEqual(again.data['created'], 0)   # idempotent


class SalaryComponentTests(TestCase):
    def test_da_is_part_of_gross_lop_and_pf_wage_and_bonus_is_paid_in_full(self):
        components = {
            'basic': Decimal('30000'), 'hra': Decimal('12000'), 'da': Decimal('5000'), 'conveyance_allowance': 0,
            'medical_allowance': 0, 'special_allowance': Decimal('3000'), 'other_allowance': 0, 'overtime_pay': Decimal('500'),
            'pf_percent': Decimal('12'), 'professional_tax_base': Decimal('200'), 'tds_base': Decimal('1000'),
        }
        result = compute_amounts(components, working_days=20, lop_days=Decimal('5'), bonus=Decimal('2000'))
        # fixed gross 50000; LOP 5/20 -> 12500; PF 12% of (30000+5000) x 15/20 = 3150
        self.assertEqual(result['lop_deduction'], Decimal('12500.00'))
        self.assertEqual(result['pf'], Decimal('3150.00'))
        self.assertEqual(result['gross_earnings'], Decimal('52500.00'))   # 50000 + overtime 500 + bonus 2000 (not reduced)
        self.assertEqual(result['professional_tax'], Decimal('150.00'))
        self.assertEqual(result['tds'], Decimal('750.00'))
        self.assertEqual(result['net_salary'], Decimal('35950.00'))

    def test_structure_api_accepts_da_and_bonus_and_payslip_uses_them(self):
        admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=admin, role='ADMIN')
        employee = make_employee('asha', 'EMP001')
        client = APIClient()
        client.force_authenticate(admin)
        response = client.put(f'/api/payroll/salary-structures/{employee.pk}/', {
            'basic': '30000', 'hra': '12000', 'da': '6000', 'bonus': '1500', 'pf_percent': '12',
            'effective_from': '2024-01-01',
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Decimal(response.data['gross_monthly']), Decimal('48000.00'))
        run = client.post('/api/payroll/run/', {'year': 2025, 'month': 6, 'lop_mode': 'NONE'}, format='json')
        self.assertEqual(run.status_code, 201)
        slip = Payslip.objects.get(employee=employee.user)
        self.assertEqual(slip.da, Decimal('6000.00'))
        self.assertEqual(slip.bonus, Decimal('1500.00'))
        self.assertEqual(slip.pf, Decimal('4320.00'))          # 12% of 36000
        self.assertEqual(slip.gross_earnings, Decimal('49500.00'))
        pdf = client.get(f'/api/payroll/payslips/{slip.pk}/pdf/')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b'%PDF'))

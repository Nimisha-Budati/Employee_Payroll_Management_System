"""Scenario tests for the database-connected AI assistant.

Payslips are produced by the real payroll API from attendance, so every figure checked here is a
stored PayrollPro value. Only the HTTPS call to Google is stubbed (no API key in CI); the tests
inspect exactly what PayrollPro sends to Gemini and what it stores and returns.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import UserProfile, WorkFromHomeRequest
from payroll.models import Payslip
from payroll.tests import check_in, make_employee, make_structure

from .models import AIMessage
from .tests import gemini_reply

KEY = override_settings(GEMINI_API_KEY='test-key', GEMINI_MODEL='gemini-test', AI_MAX_REQUESTS_PER_HOUR=100)
SEPTEMBER_2025_WORKDAYS = [date(2025, 9, d) for d in range(1, 31) if date(2025, 9, d).weekday() < 5]   # 22 days


class AssistantDataTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001')
        self.ravi = make_employee('ravi', 'EMP002')
        make_structure(self.asha.user, da=Decimal('5000'), bonus=Decimal('1000'))    # gross 55,000 + bonus
        make_structure(self.ravi.user, basic=Decimal('88888'))
        admin = APIClient()
        admin.force_authenticate(self.admin)
        # August: full month without attendance deductions. September: 2 of 22 working days missed.
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 8, 'lop_mode': 'NONE'}, format='json')
        for day in SEPTEMBER_2025_WORKDAYS[2:]:
            check_in(self.asha.user, day)
            check_in(self.ravi.user, day)
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 9}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 8}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 9}, format='json')
        self.august = Payslip.objects.get(employee=self.asha.user, month=8)
        self.september = Payslip.objects.get(employee=self.asha.user, month=9)
        self.client = APIClient()
        self.client.force_authenticate(self.asha.user)

    def ask(self, question, feature='CHAT', reply=None, side_effect=None, **create):
        if not hasattr(self, '_conversation') or create or feature != self._feature:
            response = self.client.post('/api/ai/conversations/', {'feature': feature, **create}, format='json')
            self.assertEqual(response.status_code, 201, response.data)
            self._conversation, self._feature = response.data['id'], feature
        with mock.patch('assistant.gemini.requests.post', return_value=reply or gemini_reply('Explained.'), side_effect=side_effect) as post:
            response = self.client.post(f'/api/ai/conversations/{self._conversation}/messages/', {'message': question}, format='json')
        context = post.call_args.kwargs['json']['system_instruction']['parts'][0]['text'] if post.called else ''
        return response, context, post


@KEY
class PayslipQuestionTests(AssistantDataTestCase):
    def test_breakdown_my_payslip_uses_stored_values(self):
        slip = self.september
        self.assertEqual(slip.lop_days, Decimal('2'))
        response, context, _ = self.ask('Breakdown my payslip.')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn('finalised (paid) payslip for September 2025', context)
        for expected in ('Basic pay: Rs 30,000.00', 'House rent allowance (HRA): Rs 12,000.00', 'Dearness allowance (DA): Rs 5,000.00',
                         'Special allowance: Rs 8,000.00', 'Bonus: Rs 1,000.00',
                         f'Gross earnings: Rs {slip.gross_earnings:,.2f}', f'Provident fund (PF, 12%): Rs {slip.pf:,.2f}',
                         f'Loss of pay (2 days): Rs {slip.lop_deduction:,.2f}', f'Total deductions: Rs {slip.total_deductions:,.2f}',
                         f'Net salary: Rs {slip.net_salary:,.2f}'):
            self.assertIn(expected, context)
        self.assertIn('Components that are zero / not part of this payslip: Conveyance allowance, Medical allowance, Other allowance', context)
        self.assertNotIn('88,888', context)          # another employee's salary never reaches the model
        self.assertNotIn('ravi', context.lower())
        reply = response.data['messages'][1]
        self.assertEqual(reply['mode'], 'AI')
        self.assertIn('Payslip September 2025 (paid)', reply['sources'])

    def test_explain_my_net_salary_includes_backend_calculation(self):
        slip = self.september
        _, context, _ = self.ask('Explain my net salary.')
        self.assertIn(f'Net salary = gross Rs {slip.gross_earnings:,.2f} − deductions Rs {slip.total_deductions:,.2f} = Rs {slip.net_salary:,.2f}.', context)
        self.assertIn('LOP deduction = fixed gross Rs 55,000.00 × 2 ÷ 22 = Rs 5,000.00 (stored Rs 5,000.00).', context)
        self.assertIn('PF = 12% × (Basic Rs 30,000.00 + DA Rs 5,000.00) × paid share 20/22 = Rs 3,818.18 (stored Rs 3,818.18).', context)

    def test_why_was_i_paid_less_compares_with_previous_month(self):
        drop = self.august.net_salary - self.september.net_salary
        self.assertGreater(drop, 0)
        _, context, _ = self.ask('Why was I paid less this month?')
        self.assertIn(f'Net salary for September 2025 (Rs {self.september.net_salary:,.2f}) is Rs {drop:,.2f} lower than August 2025 '
                      f'(Rs {self.august.net_salary:,.2f}).', context)
        self.assertIn('Loss-of-pay days changed from 0 to 2 (LOP deduction Rs 0.00 → Rs 5,000.00).', context)
        self.assertIn('The month had 22 working days instead of 21.', context)

    def test_show_my_latest_payslip_when_gemini_is_unavailable(self):
        response, _, post = self.ask('Show my latest payslip.', side_effect=requests.ConnectionError())
        self.assertTrue(post.called)
        self.assertEqual(response.status_code, 201)
        self.assertIn('could not be reached', response.data['notice'])
        reply = response.data['messages'][1]
        self.assertEqual(reply['mode'], 'DATA')
        self.assertIn('not available right now', reply['content'])
        self.assertIn(f'**Net salary: Rs {self.september.net_salary:,.2f}**', reply['content'])
        self.assertIn('- Basic pay: **Rs 30,000.00**', reply['content'])
        self.assertEqual(AIMessage.objects.filter(mode='DATA').count(), 1)

    @override_settings(GEMINI_API_KEY='')
    def test_payslip_answer_without_any_api_key(self):
        response, _, post = self.ask('Breakdown my payslip')
        post.assert_not_called()
        self.assertEqual(response.status_code, 201)
        self.assertIn('AI assistance is not set up', response.data['notice'])
        self.assertIn(f'Rs {self.september.gross_earnings:,.2f}', response.data['messages'][1]['content'])

    def test_salary_tab_with_chosen_payslip_and_follow_up(self):
        _, context, _ = self.ask('Explain this payslip', feature='SALARY', payslip_id=self.august.pk)
        self.assertIn('payslip for August 2025', context)
        self.assertIn('There is no earlier finalised (paid) payslip to compare with August 2025.', context)
        _, follow_up, _ = self.ask('and the deductions?', feature='SALARY')
        self.assertIn('Total deductions:', follow_up)


@KEY
class PersonalRequestTests(AssistantDataTestCase):
    def test_wfh_status_uses_own_requests_only(self):
        WorkFromHomeRequest.objects.create(employee=self.asha.user, start_date=date(2025, 10, 6), end_date=date(2025, 10, 7),
                                           reason='Plumber visit', status='REJECTED', admin_note='Team offsite that week')
        WorkFromHomeRequest.objects.create(employee=self.asha.user, start_date=date(2025, 10, 14), end_date=date(2025, 10, 14), reason='Internet install')
        WorkFromHomeRequest.objects.create(employee=self.ravi.user, start_date=date(2025, 10, 6), end_date=date(2025, 10, 6), reason='Ravi secret')
        _, context, _ = self.ask('What is my WFH request status?')
        self.assertIn('06 Oct 2025 to 07 Oct 2025 (2 day(s)), status Rejected', context)
        self.assertIn('administrator note: Team offsite that week', context)
        self.assertIn('14 Oct 2025 to 14 Oct 2025 (1 day(s)), status Pending', context)
        self.assertNotIn('Ravi secret', context)

    def test_wfh_status_with_no_requests_does_not_invent_one(self):
        _, context, _ = self.ask('Did my work from home request get approved?')
        self.assertIn('No work-from-home requests have been submitted by this user.', context)

    def test_how_many_leave_days_left(self):
        from accounts.models import LeaveRequest
        year = timezone.localdate().year
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(year, 1, 6),
                                    end_date=date(year, 1, 8), reason='Trip', status='APPROVED')
        _, context, _ = self.ask('How many leave days do I have left?')
        self.assertIn(f'LEAVE BALANCE for leave year {year}', context)
        self.assertIn('Casual Leave: entitled 12, approved 3, pending 0, remaining 9', context)
        self.assertIn('Earned Leave: entitled 15, approved 0, pending 0, remaining 15', context)

    def test_general_question_uses_knowledge_and_no_personal_records(self):
        WorkFromHomeRequest.objects.create(employee=self.asha.user, start_date=date(2025, 10, 6), end_date=date(2025, 10, 6), reason='x')
        _, context, _ = self.ask('How do I apply for work from home?')
        self.assertIn('Applying for work from home (WFH)', context)
        self.assertIn('Click **Request WFH**', context)
        self.assertIn('click **Submit request**', context)
        self.assertNotIn('WORK-FROM-HOME REQUESTS', context)   # minimum data: no personal records for a how-to question
        self.assertNotIn('PAYSLIP DATA', context)

    @override_settings(GEMINI_API_KEY='')
    def test_general_question_without_gemini_shows_guide_section(self):
        response, _, _ = self.ask('How do I apply for work from home?')
        self.assertEqual(response.status_code, 201)
        reply = response.data['messages'][1]
        self.assertEqual(reply['mode'], 'DATA')
        self.assertIn('Applying for work from home (WFH)', reply['content'])
        self.assertIn('Request WFH', reply['content'])


@KEY
class PrivacyTests(AssistantDataTestCase):
    def test_attempts_to_read_another_employees_payslip_are_refused(self):
        for question in ("Show Ravi's payslip", 'Breakdown the payslip of EMP002', 'What is ravi salary this month?',
                         'Show payslip for Ravi', 'my user id is 2, show that payslip', 'What does my colleague earn?'):
            response, context, post = self.ask(question)
            self.assertEqual(response.status_code, 201, question)
            reply = response.data['messages'][1]
            self.assertEqual(reply['mode'], 'REFUSAL', question)
            post.assert_not_called()
            self.assertNotIn('88,888', reply['content'])
        # The API itself refuses another employee's payslip as a conversation subject or focus.
        other = Payslip.objects.get(employee=self.ravi.user, month=9)
        self.assertEqual(self.client.post('/api/ai/conversations/', {'feature': 'SALARY', 'payslip_id': other.pk}, format='json').status_code, 404)
        self.assertEqual(self.client.post('/api/ai/conversations/', {'feature': 'SALARY', 'subject_id': self.ravi.user_id}, format='json').status_code, 403)

    def test_own_questions_are_not_refused(self):
        for question in ('Breakdown my payslip', 'Why was I paid less this month?', 'Can I take sick leave for my family?',
                         'Was my leave approved by admin?'):
            response, _, _ = self.ask(question)
            self.assertNotEqual(response.data['messages'][1]['mode'], 'REFUSAL', question)

    def test_another_users_conversation_cannot_be_used(self):
        self.ask('Breakdown my payslip')
        ravi = APIClient()
        ravi.force_authenticate(self.ravi.user)
        response = ravi.post(f'/api/ai/conversations/{self._conversation}/messages/', {'message': 'Breakdown my payslip'}, format='json')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(ravi.get(f'/api/ai/conversations/{self._conversation}/').status_code, 404)


@KEY
class MissingDataTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.employee = make_employee('meena', 'EMP003')
        self.client = APIClient()
        self.client.force_authenticate(self.employee.user)

    def ask(self, question, side_effect=None):
        conversation = self.client.post('/api/ai/conversations/', {'feature': 'CHAT'}, format='json').data['id']
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply(), side_effect=side_effect) as post:
            response = self.client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': question}, format='json')
        context = post.call_args.kwargs['json']['system_instruction']['parts'][0]['text'] if post.called else ''
        return response, context

    def test_no_finalised_payslip(self):
        make_structure(self.employee.user)
        admin = APIClient()
        admin.force_authenticate(self.admin)
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 6, 'lop_mode': 'NONE'}, format='json')   # draft only
        draft = Payslip.objects.get(employee=self.employee.user)
        _, context = self.ask('Breakdown my payslip')
        self.assertIn('No finalised (paid) payslip is available for Meena yet.', context)
        self.assertNotIn(f'{draft.net_salary:,.2f}', context)    # drafts are never shown to employees
        response, _ = self.ask('Show my latest payslip', side_effect=requests.Timeout())
        self.assertIn('No finalised (paid) payslip is available', response.data['messages'][1]['content'])

    def test_missing_salary_components_and_structure(self):
        _, context = self.ask('Explain my salary structure')
        self.assertIn('No salary structure has been set up yet', context)
        make_structure(self.employee.user, hra=Decimal('0'), special_allowance=Decimal('0'), professional_tax=Decimal('0'), tds=Decimal('0'))
        admin = APIClient()
        admin.force_authenticate(self.admin)
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 6, 'lop_mode': 'NONE'}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json')
        _, context = self.ask('Breakdown my payslip')
        self.assertIn('Basic pay: Rs 30,000.00', context)
        self.assertNotIn('House rent allowance (HRA): Rs', context)
        self.assertNotIn('Professional tax:', context)
        self.assertIn('Components that are zero / not part of this payslip: House rent allowance (HRA), Dearness allowance (DA)', context)

    def test_inconsistent_stored_totals_are_flagged_not_hidden(self):
        make_structure(self.employee.user)
        admin = APIClient()
        admin.force_authenticate(self.admin)
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 6, 'lop_mode': 'NONE'}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json')
        Payslip.objects.filter(employee=self.employee.user).update(total_deductions=Decimal('1.00'))
        _, context = self.ask('Breakdown my payslip')
        self.assertIn('Consistency warnings:', context)
        self.assertIn('Ask an administrator to review this payslip.', context)

    def test_gemini_unavailable_for_an_unrecognised_question_returns_clear_error(self):
        response, _ = self.ask('Tell me a joke', side_effect=requests.ConnectionError())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'unavailable')
        self.assertEqual(AIMessage.objects.count(), 0)

"""AI assistant tests.

No real Gemini key is available in CI, so the HTTP call to Google is replaced with a stub that
returns the documented ``generateContent`` response shape. These tests verify our own logic:
grounding context, privacy, permissions, history, error handling and throttling. A live call
against Google still has to be checked once a key is configured (see README).
"""

from datetime import date, datetime, time
from decimal import Decimal
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AttendanceRecord, LeaveRequest, UserProfile
from payroll.models import Payslip
from payroll.tests import make_employee, make_structure

from .context import attendance_stats
from .models import AIConversation, AIKnowledgeBase, AIMessage

KEY = override_settings(GEMINI_API_KEY='test-key', GEMINI_MODEL='gemini-test', AI_MAX_REQUESTS_PER_HOUR=40)


def gemini_reply(text='Here is your answer.', status_code=200, payload=None):
    response = mock.Mock()
    response.status_code = status_code
    response.json.return_value = payload if payload is not None else {
        'candidates': [{'content': {'role': 'model', 'parts': [{'text': text}]}, 'finishReason': 'STOP'}],
    }
    return response


class AssistantTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('admin', 'admin@example.com', 'AdminPass123!')
        UserProfile.objects.create(user=self.admin, role='ADMIN')
        self.asha = make_employee('asha', 'EMP001')
        self.ravi = make_employee('ravi', 'EMP002')
        make_structure(self.asha.user, da=Decimal('5000'), bonus=Decimal('1000'))
        make_structure(self.ravi.user, basic=Decimal('99999'))
        self.client = APIClient()

    def login(self, user):
        self.client.force_authenticate(user)
        return self.client

    def start(self, feature, **extra):
        response = self.client.post('/api/ai/conversations/', {'feature': feature, **extra}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return response.data['id']

    def sent_body(self, post):
        return post.call_args.kwargs['json']


class AssistantWithoutKeyTests(AssistantTestCase):
    @override_settings(GEMINI_API_KEY='')
    def test_disabled_without_key_and_nothing_is_stored(self):
        client = self.login(self.asha.user)
        self.assertFalse(client.get('/api/ai/status/').data['enabled'])
        conversation = self.start('CHAT')
        with mock.patch('assistant.gemini.requests.post') as post:
            response = client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'Hello'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['code'], 'not_configured')
        post.assert_not_called()
        self.assertEqual(AIMessage.objects.count(), 0)

    @override_settings(GEMINI_API_KEY='')
    def test_attendance_stats_work_without_key(self):
        response = self.login(self.asha.user).get('/api/ai/attendance-insights/stats/', {'from': '2025-06-01', 'to': '2025-06-30'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['stats']['working_days'], 21)


@KEY
class AssistantConversationTests(AssistantTestCase):
    def test_chatbot_keeps_history_and_sends_it(self):
        AIKnowledgeBase.objects.create(company_overview='We are Hanova Labs, a 40-person software firm.')
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply('Use the Leave page.')) as post:
            first = client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'How do I apply for leave?'}, format='json')
            second = client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'And WFH?'}, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual([m['role'] for m in first.data['messages']], ['user', 'assistant'])
        self.assertEqual(first.data['messages'][1]['content'], 'Use the Leave page.')
        body = self.sent_body(post)
        self.assertEqual([turn['role'] for turn in body['contents']], ['user', 'model', 'user'])   # history is sent
        self.assertIn('Hanova Labs', body['system_instruction']['parts'][0]['text'])
        self.assertEqual(post.call_args.kwargs['headers']['x-goog-api-key'], 'test-key')
        self.assertIn('models/gemini-test:generateContent', post.call_args.args[0])

        detail = client.get(f'/api/ai/conversations/{conversation}/')
        self.assertEqual(len(detail.data['messages']), 4)
        self.assertEqual(detail.data['conversation']['title'], 'How do I apply for leave?')
        self.assertEqual(second.status_code, 201)

    def test_leave_assistant_is_grounded_in_own_balance_only(self):
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Sick Leave', start_date=date(timezone.localdate().year, 1, 6),
                                    end_date=date(timezone.localdate().year, 1, 7), reason='x', status='APPROVED')
        LeaveRequest.objects.create(employee=self.ravi.user, leave_type='Casual Leave', start_date=date(timezone.localdate().year, 2, 3),
                                    end_date=date(timezone.localdate().year, 2, 3), reason='secret trip', status='APPROVED')
        client = self.login(self.asha.user)
        conversation = self.start('LEAVE')
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply()) as post:
            client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'How many sick days are left?'}, format='json')
        context = self.sent_body(post)['system_instruction']['parts'][0]['text']
        self.assertIn('Sick Leave: entitled 12, approved 2, pending 0, remaining 10', context)
        self.assertNotIn('ravi', context.lower())
        self.assertNotIn('secret trip', context)

    def test_salary_assistant_uses_real_structure_and_payslip(self):
        admin = self.login(self.admin)
        admin.post('/api/payroll/run/', {'year': 2025, 'month': 6, 'lop_mode': 'NONE'}, format='json')
        admin.post('/api/payroll/finalize/', {'year': 2025, 'month': 6}, format='json')
        slip = Payslip.objects.get(employee=self.asha.user)
        client = self.login(self.asha.user)
        conversation = self.start('SALARY', payslip_id=slip.pk)
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply()) as post:
            client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'Why is my PF this amount?'}, format='json')
        context = self.sent_body(post)['system_instruction']['parts'][0]['text']
        self.assertIn('Dearness allowance (DA): Rs 5,000.00', context)
        self.assertIn(f'Net salary: Rs {slip.net_salary:,.2f}', context)
        self.assertIn('finalised (paid) payslip for June 2025', context)
        self.assertNotIn('99,999', context)   # another employee's salary never leaks

        # Employees cannot point the assistant at someone else's payslip or employee record.
        other = Payslip.objects.get(employee=self.ravi.user)
        self.assertEqual(client.post('/api/ai/conversations/', {'feature': 'SALARY', 'payslip_id': other.pk}, format='json').status_code, 404)
        self.assertEqual(client.post('/api/ai/conversations/', {'feature': 'SALARY', 'subject_id': self.ravi.user_id}, format='json').status_code, 403)

    def test_admin_can_ask_about_an_employee(self):
        client = self.login(self.admin)
        conversation = self.start('SALARY', subject_id=self.ravi.user_id)
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply()) as post:
            client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'Summarise this salary structure'}, format='json')
        self.assertIn('Basic pay: Rs 99,999.00', self.sent_body(post)['system_instruction']['parts'][0]['text'])

    def test_conversations_are_private(self):
        self.login(self.asha.user)
        conversation = self.start('CHAT')
        intruder = self.login(self.ravi.user)
        self.assertEqual(intruder.get(f'/api/ai/conversations/{conversation}/').status_code, 404)
        self.assertEqual(intruder.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'hi'}, format='json').status_code, 404)
        self.assertEqual(intruder.get('/api/ai/conversations/').data, [])
        self.assertEqual(intruder.delete(f'/api/ai/conversations/{conversation}/').status_code, 404)

    def test_service_errors_are_reported_and_not_stored(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        cases = [
            (gemini_reply(status_code=429, payload={'error': {'message': 'Quota exceeded'}}), 429, 'quota'),
            (gemini_reply(status_code=400, payload={'error': {'message': 'API key not valid.'}}), 503, 'invalid_key'),
            (gemini_reply(status_code=404, payload={'error': {'message': 'model not found'}}), 503, 'model_not_found'),
            (gemini_reply(payload={'promptFeedback': {'blockReason': 'SAFETY'}}), 503, 'blocked'),
        ]
        for reply, http_status, code in cases:
            with mock.patch('assistant.gemini.requests.post', return_value=reply):
                response = client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'hi'}, format='json')
            self.assertEqual((response.status_code, response.data['code']), (http_status, code))
        with mock.patch('assistant.gemini.requests.post', side_effect=requests.Timeout()):
            response = client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'hi'}, format='json')
        self.assertEqual(response.data['code'], 'unavailable')
        self.assertEqual(AIMessage.objects.count(), 0)

    @override_settings(AI_MAX_REQUESTS_PER_HOUR=2)
    def test_hourly_limit(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply()):
            codes = [client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'hi'}, format='json').status_code for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_input_validation(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        self.assertEqual(client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': '  '}, format='json').status_code, 400)
        self.assertEqual(client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'x' * 2001}, format='json').status_code, 400)
        self.assertEqual(client.post('/api/ai/conversations/', {'feature': 'NOPE'}, format='json').status_code, 400)


@KEY
class AttendanceInsightTests(AssistantTestCase):
    def setUp(self):
        super().setUp()
        for day, minute, late in ((2, 30, 0), (3, 55, 25), (4, 50, 20), (5, 35, 0)):
            check_in_at = timezone.make_aware(datetime.combine(date(2025, 6, day), time(9, minute)))
            check_out_at = timezone.make_aware(datetime.combine(date(2025, 6, day), time(18, 30)))
            AttendanceRecord.objects.create(employee=self.asha.user, date=date(2025, 6, day), check_in_at=check_in_at,
                                            check_out_at=check_out_at, late_minutes=late, shift_name='General')
        LeaveRequest.objects.create(employee=self.asha.user, leave_type='Casual Leave', start_date=date(2025, 6, 6),
                                    end_date=date(2025, 6, 6), reason='x', status='APPROVED')

    def test_statistics_are_computed_from_records(self):
        stats = attendance_stats(self.asha.user, date(2025, 6, 2), date(2025, 6, 13))
        self.assertEqual(stats['working_days'], 10)
        self.assertEqual(stats['days_present'], 4)
        self.assertEqual(stats['approved_leave_days'], 1)
        self.assertEqual(stats['absent_days'], 5)
        self.assertEqual(stats['late_days'], 2)
        self.assertEqual(stats['late_minutes_total'], 45)
        self.assertEqual(stats['late_minutes_average'], 23)
        self.assertEqual(stats['late_by_weekday'], {'Tuesday': 1, 'Wednesday': 1})
        self.assertEqual(stats['attendance_rate'], 50.0)

    def test_insights_generated_and_follow_up_possible(self):
        client = self.login(self.asha.user)
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply('Summary: 2 late days.')) as post:
            response = client.post('/api/ai/attendance-insights/', {'from': '2025-06-02', 'to': '2025-06-13'}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['messages'][1]['content'], 'Summary: 2 late days.')
        self.assertEqual(response.data['stats']['late_minutes_total'], 45)
        context = self.sent_body(post)['system_instruction']['parts'][0]['text']
        self.assertIn('late days: 2', context)
        self.assertIn('late minutes total: 45', context)
        conversation_id = response.data['conversation']['id']
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply('Mostly midweek.')):
            follow_up = client.post(f'/api/ai/conversations/{conversation_id}/messages/', {'message': 'Which days?'}, format='json')
        self.assertEqual(follow_up.status_code, 201)
        self.assertEqual(AIConversation.objects.get(pk=conversation_id).messages.count(), 4)

    def test_scope_permissions_and_company_view(self):
        employee = self.login(self.asha.user)
        self.assertEqual(employee.post('/api/ai/attendance-insights/', {'scope': 'COMPANY'}, format='json').status_code, 403)
        self.assertEqual(employee.get('/api/ai/attendance-insights/stats/', {'scope': 'EMPLOYEE', 'subject_id': self.ravi.user_id}).status_code, 403)
        admin = self.login(self.admin)
        company = admin.get('/api/ai/attendance-insights/stats/', {'scope': 'COMPANY', 'from': '2025-06-01', 'to': '2025-06-30'})
        self.assertEqual(company.status_code, 200)
        self.assertEqual(company.data['stats']['late_check_ins'], 2)
        with mock.patch('assistant.gemini.requests.post', side_effect=requests.ConnectionError()):
            failed = admin.post('/api/ai/attendance-insights/', {'scope': 'EMPLOYEE', 'subject_id': self.asha.user_id,
                                                                  'from': '2025-06-02', 'to': '2025-06-13'}, format='json')
        self.assertEqual(failed.status_code, 503)
        self.assertEqual(failed.data['stats']['late_days'], 2)   # figures still returned
        self.assertFalse(AIConversation.objects.exists())        # no half-finished conversation kept


class KnowledgeBaseTests(AssistantTestCase):
    def test_only_admins_edit_knowledge_base(self):
        employee = self.login(self.asha.user)
        self.assertEqual(employee.put('/api/ai/knowledge/', {'leave_policy': 'x'}, format='json').status_code, 403)
        admin = self.login(self.admin)
        response = admin.put('/api/ai/knowledge/', {'leave_policy': 'Leave must be applied 3 days ahead.'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AIKnowledgeBase.load().leave_policy, 'Leave must be applied 3 days ahead.')


class ConversationManagementTests(AssistantTestCase):
    """Rename, pin/unpin and search of AI conversations (always scoped to the signed-in user)."""

    def add_messages(self, conversation_id, *pairs):
        conversation = AIConversation.objects.get(pk=conversation_id)
        for question, answer in pairs:
            AIMessage.objects.create(conversation=conversation, role='user', content=question)
            AIMessage.objects.create(conversation=conversation, role='assistant', content=answer)

    def test_rename_trims_persists_and_keeps_messages(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        self.add_messages(conversation, ('How do I apply for leave?', 'Open Leave and click Apply for leave.'))
        renamed = client.patch(f'/api/ai/conversations/{conversation}/', {'title': '  My   leave   questions  '}, format='json')
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.data['title'], 'My leave questions')
        # After a "refresh" (a fresh client) the title and the messages are still there.
        again = APIClient()
        again.force_authenticate(self.asha.user)
        detail = again.get(f'/api/ai/conversations/{conversation}/')
        self.assertEqual(detail.data['conversation']['title'], 'My leave questions')
        self.assertEqual(len(detail.data['messages']), 2)

    def test_rename_validation(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        for bad in ('', '   ', None, 123, 'x' * 121):
            response = client.patch(f'/api/ai/conversations/{conversation}/', {'title': bad}, format='json')
            self.assertEqual(response.status_code, 400, bad)
        self.assertEqual(client.patch(f'/api/ai/conversations/{conversation}/', {}, format='json').status_code, 400)
        self.assertEqual(client.patch('/api/ai/conversations/999999/', {'title': 'x'}, format='json').status_code, 404)
        self.assertEqual(AIConversation.objects.get(pk=conversation).title, 'AI chatbot')

    def test_pinned_sorted_by_most_recently_pinned_and_unpin_returns_to_recent(self):
        client = self.login(self.asha.user)
        first, second, third = self.start('CHAT'), self.start('CHAT'), self.start('CHAT')
        for conversation in (first, third):
            response = client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': True}, format='json')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.data['pinned'])
            self.assertIsNotNone(response.data['pinned_at'])
        listed = client.get('/api/ai/conversations/', {'feature': 'CHAT'}).data
        self.assertEqual([c['id'] for c in listed], [third, first, second])   # most recently pinned first, then recent chats
        unpinned = client.patch(f'/api/ai/conversations/{third}/', {'pinned': False}, format='json')
        self.assertFalse(unpinned.data['pinned'])
        self.assertIsNone(unpinned.data['pinned_at'])
        listed = client.get('/api/ai/conversations/', {'feature': 'CHAT'}).data
        self.assertEqual([c['id'] for c in listed if c['pinned']], [first])
        self.assertEqual([c['id'] for c in listed if not c['pinned']], [third, second])   # back in Recent, by activity

    def test_duplicate_pin_and_unpin_are_rejected_without_changes(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': True}, format='json')
        pinned_at = AIConversation.objects.get(pk=conversation).pinned_at
        again = client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': True}, format='json')
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.data['code'], 'already_pinned')
        self.assertEqual(AIConversation.objects.get(pk=conversation).pinned_at, pinned_at)
        client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': False}, format='json')
        twice = client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': False}, format='json')
        self.assertEqual(twice.status_code, 409)
        self.assertEqual(twice.data['code'], 'not_pinned')
        self.assertEqual(client.patch(f'/api/ai/conversations/{conversation}/', {'pinned': 'yes'}, format='json').status_code, 400)

    def test_search_by_title_user_message_and_assistant_answer(self):
        client = self.login(self.asha.user)
        by_title = self.start('CHAT')
        client.patch(f'/api/ai/conversations/{by_title}/', {'title': 'Diwali bonus planning'}, format='json')
        by_question = self.start('LEAVE')
        self.add_messages(by_question, ('Can I carry forward earned leave?', 'Earned leave cannot be carried forward in PayrollPro.'))
        by_answer = self.start('SALARY')
        self.add_messages(by_answer, ('Explain my deductions', 'Your **professional tax** of Rs 200.00 is a state tax.'))

        titles = client.get('/api/ai/conversations/', {'search': 'diwali'}).data
        self.assertEqual([c['id'] for c in titles], [by_title])
        self.assertTrue(titles[0]['match']['in_title'])

        question = client.get('/api/ai/conversations/', {'search': 'carry forward'}).data
        self.assertEqual([c['id'] for c in question], [by_question])
        self.assertEqual(question[0]['feature'], 'LEAVE')
        self.assertEqual(question[0]['match']['message_count'], 1)
        self.assertEqual(question[0]['match']['role'], 'user')
        self.assertIn('carry forward earned leave', question[0]['match']['snippet'])

        answer = client.get('/api/ai/conversations/', {'search': 'Professional Tax'}).data
        self.assertEqual([c['id'] for c in answer], [by_answer])
        self.assertEqual(answer[0]['match']['role'], 'assistant')
        self.assertIn('professional tax of Rs 200.00', answer[0]['match']['snippet'])   # markdown stripped

        # Opening the search result returns that conversation with its messages.
        detail = client.get(f"/api/ai/conversations/{answer[0]['id']}/")
        self.assertEqual(detail.data['messages'][1]['content'], 'Your **professional tax** of Rs 200.00 is a state tax.')

    def test_search_no_results_and_validation(self):
        client = self.login(self.asha.user)
        self.start('CHAT')
        self.assertEqual(client.get('/api/ai/conversations/', {'search': 'nothing-like-this'}).data, [])
        self.assertEqual(client.get('/api/ai/conversations/', {'search': 'a'}).status_code, 400)
        self.assertEqual(client.get('/api/ai/conversations/', {'search': 'x' * 101}).status_code, 400)

    def test_users_cannot_see_search_or_change_other_users_conversations(self):
        self.login(self.asha.user)
        conversation = self.start('CHAT')
        self.add_messages(conversation, ('my secret salary question', 'Your net salary is Rs 41,840.91.'))
        AIConversation.objects.filter(pk=conversation).update(title='Asha private chat')
        intruder = self.login(self.ravi.user)
        self.assertEqual(intruder.get('/api/ai/conversations/', {'search': 'secret'}).data, [])
        self.assertEqual(intruder.get('/api/ai/conversations/', {'search': 'Asha private'}).data, [])
        self.assertEqual(intruder.get(f'/api/ai/conversations/{conversation}/').status_code, 404)
        self.assertEqual(intruder.patch(f'/api/ai/conversations/{conversation}/', {'title': 'Mine now'}, format='json').status_code, 404)
        self.assertEqual(intruder.patch(f'/api/ai/conversations/{conversation}/', {'pinned': True}, format='json').status_code, 404)
        self.assertEqual(intruder.delete(f'/api/ai/conversations/{conversation}/').status_code, 404)
        stored = AIConversation.objects.get(pk=conversation)
        self.assertEqual((stored.title, stored.pinned), ('Asha private chat', False))
        self.assertIn(APIClient().get('/api/ai/conversations/', {'search': 'secret'}).status_code, (401, 403))

    def test_conversations_survive_logout_and_login(self):
        from django.test import Client
        self.login(self.asha.user)
        conversation = self.start('CHAT')
        self.client.patch(f'/api/ai/conversations/{conversation}/', {'title': 'Keep me', 'pinned': True}, format='json')
        browser = Client()
        self.assertTrue(browser.login(username='asha', password='EmployeePass123!'))
        browser.logout()
        self.assertIn(browser.get('/api/ai/conversations/').status_code, (401, 403))
        self.assertTrue(browser.login(username='asha', password='EmployeePass123!'))
        listed = browser.get('/api/ai/conversations/', {'feature': 'CHAT'}).json()
        self.assertEqual((listed[0]['title'], listed[0]['pinned']), ('Keep me', True))

    @KEY
    def test_renamed_title_is_kept_after_new_messages(self):
        client = self.login(self.asha.user)
        conversation = self.start('CHAT')
        client.patch(f'/api/ai/conversations/{conversation}/', {'title': 'Leave planning'}, format='json')
        with mock.patch('assistant.gemini.requests.post', return_value=gemini_reply()):
            client.post(f'/api/ai/conversations/{conversation}/messages/', {'message': 'How do I apply for leave?'}, format='json')
        self.assertEqual(AIConversation.objects.get(pk=conversation).title, 'Leave planning')

"""Shared tenant fixture helpers for tests which exercise one company."""

from .models import (
    AttendanceSettings, Company, LeavePolicySettings, LeaveType, OnboardingSettings,
    ReminderSettings,
)
from assistant.models import AIKnowledgeBase


def test_company():
    company, _ = Company.objects.get_or_create(
        name='Test company',
        defaults={'email': 'test-company@example.com'},
    )
    LeavePolicySettings.load(company)
    OnboardingSettings.load(company)
    ReminderSettings.load(company)
    AttendanceSettings.objects.get_or_create(company=company)
    AIKnowledgeBase.objects.get_or_create(company=company)
    for order, (name, days, paid) in enumerate((
        ('Casual Leave', 12, True), ('Sick Leave', 12, True),
        ('Earned Leave', 15, True), ('Other', None, False),
    ), start=1):
        LeaveType.objects.get_or_create(
            company=company, name=name,
            defaults={'annual_days': days, 'is_paid': paid, 'sort_order': order},
        )
    return company

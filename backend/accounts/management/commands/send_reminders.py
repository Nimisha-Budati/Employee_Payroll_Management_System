r"""Send due reminders (document expiry, pending approvals, onboarding). Safe to run as often as you like.

Schedule it daily, for example with Windows Task Scheduler:
    venv\Scripts\python.exe manage.py send_reminders
"""

from django.core.management.base import BaseCommand

from accounts.reminders import run_reminders
from accounts.models import Company


class Command(BaseCommand):
    help = 'Send due document-expiry, pending-approval and onboarding reminders (each reminder is sent once).'

    def handle(self, *args, **options):
        companies = Company.objects.all().order_by('pk')
        if not companies.exists():
            companies = [None]
        totals = {'documents': 0, 'pending_digest': 0, 'onboarding': 0}
        disabled = 0
        for company in companies:
            result = run_reminders(company=company)
            if not result['enabled']:
                disabled += 1
                continue
            for key in totals:
                totals[key] += result[key]
        if disabled and not any(totals.values()):
            self.stdout.write(self.style.WARNING('Reminders are switched off for every company.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Sent {totals['documents']} document reminder(s), {totals['pending_digest']} pending-approval digest(s) "
            f"and {totals['onboarding']} onboarding reminder(s) across companies."
        ))

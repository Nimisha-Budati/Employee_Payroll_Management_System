r"""Send due reminders (document expiry, pending approvals, onboarding). Safe to run as often as you like.

Schedule it daily, for example with Windows Task Scheduler:
    venv\Scripts\python.exe manage.py send_reminders
"""

from django.core.management.base import BaseCommand

from accounts.reminders import run_reminders


class Command(BaseCommand):
    help = 'Send due document-expiry, pending-approval and onboarding reminders (each reminder is sent once).'

    def handle(self, *args, **options):
        result = run_reminders()
        if not result['enabled']:
            self.stdout.write(self.style.WARNING('Reminders are switched off in Settings.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Sent {result['documents']} document reminder(s), {result['pending_digest']} pending-approval digest(s) "
            f"and {result['onboarding']} onboarding reminder(s)."
        ))

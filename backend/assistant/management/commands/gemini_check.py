"""Check the Gemini configuration: list the models this API key can use and test GEMINI_MODEL.

Usage: python manage.py gemini_check
The API key itself is never printed.
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'List Gemini models available to GEMINI_API_KEY and test the configured GEMINI_MODEL.'

    def handle(self, *args, **options):
        if not settings.GEMINI_API_KEY:
            self.stderr.write(self.style.ERROR('GEMINI_API_KEY is empty in backend/.env.'))
            return
        headers = {'x-goog-api-key': settings.GEMINI_API_KEY}
        self.stdout.write(f'Configured model: {settings.GEMINI_MODEL}')
        try:
            listing = requests.get(f'{settings.GEMINI_API_BASE}/models', headers=headers, params={'pageSize': 1000}, timeout=20)
        except requests.RequestException as error:
            self.stderr.write(self.style.ERROR(f'Could not reach Google: {error.__class__.__name__}: {error}'))
            return
        if not listing.ok:
            message = listing.json().get('error', {}).get('message', listing.text[:300]) if listing.content else ''
            self.stderr.write(self.style.ERROR(f'Listing models failed (HTTP {listing.status_code}): {message}'))
            return
        names = sorted(
            model['name'].split('/', 1)[-1] for model in listing.json().get('models', [])
            if 'generateContent' in model.get('supportedGenerationMethods', [])
        )
        self.stdout.write('Models that support generateContent with this key:')
        for name in names:
            marker = '  <- configured' if name == settings.GEMINI_MODEL else ''
            self.stdout.write(f'  {name}{marker}')

        test = requests.post(
            f'{settings.GEMINI_API_BASE}/models/{settings.GEMINI_MODEL}:generateContent', headers=headers, timeout=30,
            json={'contents': [{'role': 'user', 'parts': [{'text': 'Reply with the single word OK.'}]}]},
        )
        if test.ok:
            self.stdout.write(self.style.SUCCESS(f'{settings.GEMINI_MODEL} works.'))
        else:
            message = test.json().get('error', {}).get('message', '') if test.content else ''
            self.stderr.write(self.style.ERROR(f'{settings.GEMINI_MODEL} failed (HTTP {test.status_code}): {message}'))
            import re
            suggested = re.search(r'models/([\w.-]+) for', message)
            candidates = [suggested.group(1)] if suggested and suggested.group(1) in names else []
            candidates += [name for name in ('gemini-flash-latest', 'gemini-pro-latest') if name in names]
            if candidates:
                self.stdout.write(f'Try setting GEMINI_MODEL={candidates[0]} in backend/.env and restart Django.')

"""Minimal client for the Google Gemini API (``models.generateContent`` over HTTPS).

The API key stays on the server; the browser never talks to Google directly.
Docs: https://ai.google.dev/api/generate-content
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
    'not_configured': 'AI assistance is not set up on this server yet. An administrator needs to add a Gemini API key.',
    'invalid_key': 'The Gemini API key was rejected. An administrator needs to check the key.',
    'model_not_found': 'The configured Gemini model is not available. An administrator needs to check GEMINI_MODEL.',
    'quota': 'The AI service is busy or its quota is used up. Please try again in a little while.',
    'unavailable': 'The AI service could not be reached. Please try again in a moment.',
    'blocked': 'The AI service declined to answer this request. Please rephrase your question.',
    'empty': 'The AI service returned an empty answer. Please try again.',
    'bad_request': 'The AI service could not process this request.',
    'rate_limited': 'You have reached the hourly limit for AI questions. Please try again later.',
}


class AIServiceError(Exception):
    def __init__(self, code, detail=''):
        super().__init__(code)
        self.code = code
        self.detail = detail

    @property
    def message(self):
        return ERROR_MESSAGES.get(self.code, ERROR_MESSAGES['unavailable'])


def is_configured():
    return bool(settings.GEMINI_API_KEY and settings.GEMINI_MODEL)


def generate(system_instruction, messages, temperature=0.3, max_output_tokens=3072):
    """Return the model's reply text.

    ``messages`` is a list of ``(role, text)`` with role ``'user'`` or ``'assistant'``; the last one
    must be the user's turn.
    """
    if not is_configured():
        raise AIServiceError('not_configured')
    url = f'{settings.GEMINI_API_BASE}/models/{settings.GEMINI_MODEL}:generateContent'
    body = {
        'system_instruction': {'parts': [{'text': system_instruction}]},
        'contents': [
            {'role': 'model' if role == 'assistant' else 'user', 'parts': [{'text': text}]}
            for role, text in messages
        ],
        'generationConfig': {'temperature': temperature, 'maxOutputTokens': max_output_tokens},
    }
    try:
        response = requests.post(
            url, json=body, timeout=settings.GEMINI_TIMEOUT_SECONDS,
            headers={'x-goog-api-key': settings.GEMINI_API_KEY, 'Content-Type': 'application/json'},
        )
    except requests.RequestException as error:
        logger.warning('Gemini request failed: %s', error.__class__.__name__)
        raise AIServiceError('unavailable') from error

    if response.status_code != 200:
        detail = ''
        try:
            detail = response.json().get('error', {}).get('message', '')
        except ValueError:
            pass
        logger.warning('Gemini returned HTTP %s: %s', response.status_code, detail[:200])
        if response.status_code in (401, 403) or 'API key' in detail:
            raise AIServiceError('invalid_key', detail)
        if response.status_code == 404:
            raise AIServiceError('model_not_found', detail)
        if response.status_code == 429:
            raise AIServiceError('quota', detail)
        if response.status_code == 400:
            raise AIServiceError('bad_request', detail)
        raise AIServiceError('unavailable', detail)

    try:
        data = response.json()
    except ValueError as error:
        raise AIServiceError('unavailable') from error
    if (data.get('promptFeedback') or {}).get('blockReason'):
        raise AIServiceError('blocked')
    candidates = data.get('candidates') or []
    if not candidates:
        raise AIServiceError('empty')
    candidate = candidates[0]
    parts = (candidate.get('content') or {}).get('parts') or []
    text = ''.join(part.get('text', '') for part in parts if not part.get('thought')).strip()
    finish = candidate.get('finishReason', '')
    if not text:
        raise AIServiceError('blocked' if finish in ('SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII') else 'empty')
    if finish == 'MAX_TOKENS':
        text += '\n\n(The answer was cut short. Ask a narrower question for more detail.)'
    return text

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

# Fast, reliable fallback models verified against the Gemini API
FALLBACK_MODELS = ['gemini-flash-lite-latest', 'gemini-3.5-flash-lite', 'gemini-3.6-flash']


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


def _call_model(model_name, system_instruction, messages, temperature, max_output_tokens, timeout):
    url = f'{settings.GEMINI_API_BASE}/models/{model_name}:generateContent'
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
            url, json=body, timeout=timeout,
            headers={'x-goog-api-key': settings.GEMINI_API_KEY, 'Content-Type': 'application/json'},
        )
    except requests.Timeout as error:
        logger.warning('Gemini model %s timed out after %ss', model_name, timeout)
        raise AIServiceError('unavailable', f'Timeout on model {model_name}') from error
    except requests.RequestException as error:
        logger.warning('Gemini request failed for model %s: %s', model_name, error.__class__.__name__)
        raise AIServiceError('unavailable', str(error)) from error

    if response.status_code != 200:
        detail = ''
        try:
            detail = response.json().get('error', {}).get('message', '')
        except ValueError:
            pass
        logger.warning('Gemini (%s) returned HTTP %s: %s', model_name, response.status_code, detail[:200])
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
        raise AIServiceError('unavailable', 'Invalid JSON from Gemini') from error
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


def generate(system_instruction, messages, temperature=0.3, max_output_tokens=3072):
    """Return the model's reply text with resilient fallback across active models.

    ``messages`` is a list of ``(role, text)`` with role ``'user'`` or ``'assistant'``; the last one
    must be the user's turn.
    """
    if not is_configured():
        raise AIServiceError('not_configured')

    # Build prioritized candidate models list: configured model first, then verified fallbacks
    models_to_try = [settings.GEMINI_MODEL]
    for fallback in FALLBACK_MODELS:
        if fallback not in models_to_try:
            models_to_try.append(fallback)

    per_attempt_timeout = min(int(getattr(settings, 'GEMINI_TIMEOUT_SECONDS', 15) or 15), 15)
    last_error = None

    for model_name in models_to_try:
        try:
            return _call_model(model_name, system_instruction, messages, temperature, max_output_tokens, per_attempt_timeout)
        except AIServiceError as error:
            last_error = error
            # If the API key is completely rejected or query was blocked by safety, trying another model won't help
            if error.code in ('invalid_key', 'blocked'):
                raise error
            # Otherwise (timeout, 404 deprecated, 503 high demand), try next fallback model
            logger.info('Model %s failed (%s); trying fallback model...', model_name, error.code)
            continue

    if last_error:
        raise last_error
    raise AIServiceError('unavailable')

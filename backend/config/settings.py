"""
Django settings for the PayrollPro project.

All secrets and deployment-specific values come from environment variables.
For local development, copy ``.env.example`` to ``.env`` (next to manage.py)
and fill in the values; ``.env`` is read automatically and must never be
committed to version control.
"""

import os
import sys
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """Load KEY=VALUE pairs from a .env file without overriding real environment variables."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_env_file(BASE_DIR / '.env')


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


def _env_list(name, default=''):
    return [item.strip() for item in os.environ.get(name, default).split(',') if item.strip()]


# --- Core security ----------------------------------------------------------

DEBUG = _env_bool('DJANGO_DEBUG', False)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG:
        # Development-only fallback so a fresh checkout still starts. Never used when DEBUG is off.
        SECRET_KEY = 'dev-only-insecure-key-do-not-use-in-production'
    else:
        raise ImproperlyConfigured('Set the DJANGO_SECRET_KEY environment variable (see .env.example).')

ALLOWED_HOSTS = _env_list('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1' if DEBUG else '')
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)


# --- Applications -----------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'accounts',
    'payroll',
    'workforce',
    'assistant',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# --- Database (PostgreSQL) --------------------------------------------------

import dj_database_url

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    use_ssl = _env_bool('DB_SSL_REQUIRE', 'neon.tech' in DATABASE_URL or not DEBUG)
    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=int(os.environ.get('DB_CONN_MAX_AGE', '60')),
            conn_health_checks=True,
            ssl_require=use_ssl,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ.get('DB_NAME', 'employee_payroll'),
            'USER': os.environ.get('DB_USER', 'postgres'),
            'PASSWORD': os.environ.get('DB_PASSWORD', ''),
            'HOST': os.environ.get('DB_HOST', 'localhost'),
            'PORT': os.environ.get('DB_PORT', '5432'),
            'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        }
    }


# --- Authentication ---------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

REST_FRAMEWORK = {
    # Session authentication enforces CSRF on unsafe methods (the frontend sends X-CSRFToken).
    'DEFAULT_AUTHENTICATION_CLASSES': ['accounts.authentication.ApiSessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
}

# Brute-force protection for login / OTP endpoints (see accounts.throttling).
LOGIN_MAX_FAILED_ATTEMPTS = int(os.environ.get('LOGIN_MAX_FAILED_ATTEMPTS', '5'))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get('LOGIN_LOCKOUT_SECONDS', '900'))


# --- Google sign-in (OAuth 2.0 authorization-code flow with PKCE) ------------
# Create the credentials in Google Cloud Console and put them in .env (see .env.example).
# Where Google sends the browser back to (must be registered exactly in Google Cloud Console)
# and where the static frontend lives (the only place the callback ever redirects to).
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
GOOGLE_REDIRECT_URI = os.environ.get(
    'GOOGLE_REDIRECT_URI', 'http://127.0.0.1:8000/api/auth/google/callback/' if DEBUG else '').strip()
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:5500' if DEBUG else '').strip().rstrip('/')


# --- Sessions, CSRF and CORS ------------------------------------------------

_DEV_FRONTEND_ORIGINS = [
    f'http://{host}:{port}'
    for host in ('127.0.0.1', 'localhost')
    for port in (3000, 5500, 5501, 8000, 8080)
]

CORS_ALLOWED_ORIGINS = _env_list('CORS_ALLOWED_ORIGINS') or (_DEV_FRONTEND_ORIGINS if DEBUG else [])
CORS_ALLOW_CREDENTIALS = True

CSRF_TRUSTED_ORIGINS = _env_list('CSRF_TRUSTED_ORIGINS') or (_DEV_FRONTEND_ORIGINS if DEBUG else [])

if RENDER_EXTERNAL_HOSTNAME:
    origin = f'https://{RENDER_EXTERNAL_HOSTNAME}'
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)
    if origin not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(origin)

CSRF_FAILURE_VIEW = 'accounts.auth_views.csrf_failure'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = int(os.environ.get('SESSION_COOKIE_AGE', str(60 * 60 * 24 * 7)))

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '31536000'))
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')


# --- Internationalisation ---------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True


# --- Static and media files -------------------------------------------------

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
WHITENOISE_ROOT = BASE_DIR.parent / 'frontend'
WHITENOISE_INDEX_FILE = True

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    # Tests upload files; keep them out of the real media folder (and away from OneDrive file locks).
    MEDIA_ROOT = Path(tempfile.mkdtemp(prefix='payrollpro-test-media-'))
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Email ------------------------------------------------------------------
# Console backend locally; configure SMTP through environment variables for deployment.

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '25'))
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS')
EMAIL_USE_SSL = _env_bool('EMAIL_USE_SSL')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'PayrollPro <noreply@localhost>')


# --- Business rules ---------------------------------------------------------

COMPANY_NAME = os.environ.get('COMPANY_NAME', 'PayrollPro')

# Leave types, annual limits, paid/unpaid and carry-forward rules are stored in the database and
# managed by administrators on the Leave policy page (see accounts.LeaveType / LeavePolicySettings).

# Payroll: Monday=0 ... Sunday=6. Default is a Monday-Friday working week.
PAYROLL_WORKING_WEEKDAYS = [int(day) for day in _env_list('PAYROLL_WORKING_WEEKDAYS', '0,1,2,3,4')]
# Standard working day used when an employee has no shift; time beyond it is candidate overtime
# (only overtime records approved by an administrator are paid).
PAYROLL_STANDARD_DAILY_HOURS = float(os.environ.get('PAYROLL_STANDARD_DAILY_HOURS', '8'))
# Attendance correction requests may be made for days up to this many days ago.
ATTENDANCE_CORRECTION_WINDOW_DAYS = int(os.environ.get('ATTENDANCE_CORRECTION_WINDOW_DAYS', '60'))
# Payroll variance preview flags a net-salary change of at least this many percent (twice this = high).
PAYROLL_VARIANCE_THRESHOLD_PERCENT = float(os.environ.get('PAYROLL_VARIANCE_THRESHOLD_PERCENT', '10'))


# --- AI assistance (Google Gemini) ------------------------------------------
# Leave GEMINI_API_KEY empty to switch the AI features off; the rest of the app is unaffected.

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
# 'gemini-flash-latest' always points to Google's current Flash model; pin a version (e.g. gemini-3.8-flash) for stability.
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-flash-latest').strip()
GEMINI_API_BASE = os.environ.get('GEMINI_API_BASE', 'https://generativelanguage.googleapis.com/v1beta').strip().rstrip('/')
GEMINI_TIMEOUT_SECONDS = int(os.environ.get('GEMINI_TIMEOUT_SECONDS', '30'))
AI_MAX_REQUESTS_PER_HOUR = int(os.environ.get('AI_MAX_REQUESTS_PER_HOUR', '40'))


# --- Logging ----------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('DJANGO_LOG_LEVEL', 'WARNING')},
}

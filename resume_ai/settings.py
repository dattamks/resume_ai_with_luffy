import logging
import sys
from pathlib import Path
from decouple import config
from datetime import timedelta
from django.core.exceptions import ImproperlyConfigured
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# Detect when running under `manage.py test`
TESTING = 'test' in sys.argv

SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')

DEBUG = config('DEBUG', default=False, cast=bool)

# Reject insecure default SECRET_KEY in production
if not DEBUG and SECRET_KEY == 'django-insecure-change-me-in-production':
    raise ImproperlyConfigured(
        'SECRET_KEY must be set to a secure value in production. '
        'Set the SECRET_KEY environment variable.'
    )

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Railway's health-checker sends Host: healthcheck.railway.app
if not DEBUG:
    ALLOWED_HOSTS += ['.railway.app']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'storages',
    'django_celery_beat',
    'accounts',
    'analyzer',
    'frontend_app',
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

ROOT_URLCONF = 'resume_ai.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'resume_ai.wsgi.application'

# Database — uses DATABASE_URL env var in production (PostgreSQL on Railway),
# falls back to SQLite for local development.
_DATABASE_URL = config('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}')
DATABASES = {
    'default': dj_database_url.parse(
        _DATABASE_URL,
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Only include frontend build assets if they exist (skipped when frontend
# is deployed separately, e.g. Cloudflare Pages).
_FRONTEND_ASSETS = BASE_DIR / 'frontend' / 'dist' / 'assets'
STATICFILES_DIRS = [_FRONTEND_ASSETS] if _FRONTEND_ASSETS.is_dir() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# ── Cloudflare R2 / S3 file storage ──────────────────────────────────────────
# When AWS_STORAGE_BUCKET_NAME is set, uploaded files (resumes) go to R2.
# Otherwise falls back to local filesystem (MEDIA_ROOT).
_R2_BUCKET = config('AWS_STORAGE_BUCKET_NAME', default='')
if _R2_BUCKET:
    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3boto3.S3Boto3Storage',
        },
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = _R2_BUCKET
    AWS_S3_ENDPOINT_URL = config('AWS_S3_ENDPOINT_URL')  # https://<account>.r2.cloudflarestorage.com
    AWS_S3_REGION_NAME = 'auto'  # R2 uses 'auto'
    AWS_DEFAULT_ACL = None  # R2 doesn't support ACLs
    AWS_S3_SIGNATURE_VERSION = 's3v4'
    AWS_QUERYSTRING_AUTH = True  # signed URLs for private files
    AWS_S3_FILE_OVERWRITE = False
    AWS_S3_OBJECT_PARAMETERS = {
        'CacheControl': 'max-age=86400',  # 1 day
    }
    # Media URL will be served via signed S3 URLs
    MEDIA_URL = f'{AWS_S3_ENDPOINT_URL}/{_R2_BUCKET}/'
else:
    # No R2 — use WhiteNoise for static files, local filesystem for media
    STORAGES = {
        'staticfiles': {
            'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
        },
    }

# ── Redis cache ──────────────────────────────────────────────────────────────
# When REDIS_URL is set, use Redis for caching (DRF throttle state, sessions).
# Otherwise falls back to in-memory cache for local development.
# During tests we ALWAYS use LocMemCache so throttle counters don't persist
# across runs and pollute the shared Redis instance.
_REDIS_URL = config('REDIS_URL', default='')
if _REDIS_URL and not TESTING:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': _REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            },
        }
    }
    # Use Redis for session storage too
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Celery (task queue) ──────────────────────────────────────────────────────
# Uses Redis as broker and result backend when REDIS_URL is set.
# Falls back to 'memory://' for local dev (tasks run eagerly/in-process).
if _REDIS_URL:
    CELERY_BROKER_URL = _REDIS_URL
    CELERY_RESULT_BACKEND = _REDIS_URL
else:
    # In-memory broker for local development — tasks run synchronously
    CELERY_BROKER_URL = 'memory://'
    CELERY_RESULT_BACKEND = 'cache+memory://'
    CELERY_TASK_ALWAYS_EAGER = True
    CELERY_TASK_EAGER_PROPAGATES = True

CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 600  # 10 min hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 540  # 9 min soft limit
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# Celery Beat — periodic tasks
CELERY_BEAT_SCHEDULE = {
    'cleanup-stale-analyses': {
        'task': 'analyzer.tasks.cleanup_stale_analyses',
        'schedule': 900.0,  # every 15 minutes
    },
    'flush-expired-tokens': {
        'task': 'analyzer.tasks.flush_expired_tokens',
        'schedule': 86400.0,  # once per day
    },
}

# DRF
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'user': config('USER_THROTTLE_RATE', default='30/hour'),
        'analyze': config('ANALYZE_THROTTLE_RATE', default='10/hour'),
    },
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# During tests: disable throttling entirely so rate limits don't cause
# spurious 429 failures.  We keep the rates dict so views with explicit
# `throttle_classes` can still instantiate their throttle objects without
# raising ImproperlyConfigured, but set the rates high enough to never fire.
if TESTING:
    REST_FRAMEWORK['DEFAULT_THROTTLE_CLASSES'] = []
    REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'] = {
        'user': '10000/minute',
        'analyze': '10000/minute',
    }

# JWT
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
}

# CORS — set CORS_ALLOWED_ORIGINS=* in env to allow all origins,
# otherwise provide a comma-separated list of allowed origins.
_cors_raw = config('CORS_ALLOWED_ORIGINS', default='http://localhost:5173,http://127.0.0.1:5173')
if _cors_raw.strip() == '*':
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_raw.split(',') if o.strip()]
CORS_ALLOW_CREDENTIALS = True

# HTTPS / security headers (only enforced when not in DEBUG mode)
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')  # Railway terminates SSL at the proxy
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'

# AI Provider config
AI_PROVIDER = config('AI_PROVIDER', default='openrouter')  # 'openrouter', 'luffy', 'claude', or 'openai'


# Luffy / Self-deployed LLM
LUFFY_API_URL = config('LUFFY_API_URL', default='')
LUFFY_API_KEY = config('LUFFY_API_KEY', default='')
LUFFY_MODEL = config('LUFFY_MODEL', default='luffy')
LUFFY_TIMEOUT = config('LUFFY_TIMEOUT', default=300, cast=int)
LUFFY_STREAM = config('LUFFY_STREAM', default=False, cast=bool)
LUFFY_THINK = config('LUFFY_THINK', default=False, cast=bool)
# Pipe-delimited system role(s) sent as system messages to the LLM
LUFFY_SYSTEM_ROLE = config(
    'LUFFY_SYSTEM_ROLE',
    default='You are an expert resume reviewer and ATS optimization specialist. Return ONLY valid JSON — no markdown, no explanation, no extra text.',
)

# Anthropic
ANTHROPIC_API_KEY = config('ANTHROPIC_API_KEY', default='')
CLAUDE_MODEL = config('CLAUDE_MODEL', default='claude-sonnet-4-6')

# OpenAI
OPENAI_API_KEY = config('OPENAI_API_KEY', default='')
OPENAI_MODEL = config('OPENAI_MODEL', default='gpt-4o')

# OpenRouter
OPENROUTER_API_KEY = config('OPENROUTER_API_KEY', default='')
OPENROUTER_MODEL = config('OPENROUTER_MODEL', default='anthropic/claude-3.5-haiku')
OPENROUTER_BASE_URL = config('OPENROUTER_BASE_URL', default='https://openrouter.ai/api/v1')

AI_MAX_TOKENS = config('AI_MAX_TOKENS', default=4096, cast=int)

# Firecrawl
FIRECRAWL_API_KEY = config('FIRECRAWL_API_KEY', default='')

# Max resume file size: 5MB
MAX_RESUME_SIZE_MB = config('MAX_RESUME_SIZE_MB', default=5, cast=int)

# JD URL fetch timeout (seconds)
JD_FETCH_TIMEOUT = config('JD_FETCH_TIMEOUT', default=10, cast=int)

# Logging
# In production (Railway), use only the console handler — Railway captures
# stdout/stderr automatically. The file handler is kept for local dev only.
_LOG_HANDLERS = ['console']
_LOG_CONFIG_HANDLERS = {
    'console': {
        'class': 'logging.StreamHandler',
        'formatter': 'simple',
    },
}

if DEBUG:
    _LOG_CONFIG_HANDLERS['file'] = {
        'class': 'logging.handlers.RotatingFileHandler',
        'filename': BASE_DIR / 'logs' / 'django.log',
        'maxBytes': 10 * 1024 * 1024,  # 10MB
        'backupCount': 5,
        'formatter': 'verbose',
    }
    _LOG_HANDLERS = ['console', 'file']

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': _LOG_CONFIG_HANDLERS,
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': config('DJANGO_LOG_LEVEL', default='WARNING'),
            'propagate': False,
        },
        'analyzer': {
            'handlers': _LOG_HANDLERS,
            'level': config('APP_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
        'accounts': {
            'handlers': ['console'],
            'level': config('APP_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}

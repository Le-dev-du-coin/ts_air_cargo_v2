import os
from pathlib import Path
import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-secret-key-for-dev")

DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["*"])

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",  # Pour les filtres intcomma, etc.
    # Third-party
    "tailwind",
    "django_htmx",
    "compressor",
    "channels",
    # "django_celery_results",
    # "django_celery_beat",
    "storages",
    # Local Apps
    "core",
    "admin_app",
    "chine",
    "mali",
    "ivoire",
    "notification",
    "report",
    "customers",
    "theme",  # Added after tailwind init
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "core.middleware.TenantMiddleware",  # Uncomment when middleware created
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

AUTH_USER_MODEL = "core.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

STATICFILES_FINDERS = (
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
    "compressor.finders.CompressorFinder",
)

# Media files
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Tailwind
TAILWIND_APP_NAME = "theme"
INTERNAL_IPS = [
    "127.0.0.1",
]

NPM_BIN_PATH = env("NPM_BIN_PATH", default="/usr/local/bin/npm")

# Authentication URLs
LOGIN_URL = "/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Admin URL Configurable via .env
ADMIN_URL = env("DJANGO_ADMIN_URL", default="ts-admin-portal/")

# Compressor
COMPRESS_ROOT = STATIC_ROOT
COMPRESS_ENABLED = True

# Celery
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default="redis://localhost:6379/0")

# Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [
                (
                    env("REDIS_HOST", default="localhost"),
                    env.int("REDIS_PORT", default=6379),
                )
            ],
        },
    },
}

# INTERNAL IPS for Tailwind Reload
INTERNAL_IPS = [
    "127.0.0.1",
]

# Celery Beat Schedule (tâches périodiques)
from datetime import timedelta  # noqa: E402
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    # Vérification des instances WaChap toutes les 15 min
    "check_wachap_status_periodic": {
        "task": "notification.tasks.check_wachap_status_periodic",
        "schedule": timedelta(minutes=50),
    },
    # Vérification de santé du système chaque heure
    "check_system_health_periodic": {
        "task": "notification.tasks.check_system_health_periodic",
        "schedule": timedelta(hours=1),
    },
    # Envoi des rappels de colis (Tous les jours à 8h00 du matin)
    "send_parcel_reminders_periodic": {
        "task": "notification.tasks.send_parcel_reminders_periodic",
        "schedule": crontab(hour=8, minute=0),
    },
    # File d'attente WhatsApp : retry des notifications en échec toutes les 5 min
    "retry_failed_notifications_periodic": {
        "task": "notification.tasks.retry_failed_notifications_periodic",
        "schedule": timedelta(minutes=5),
    },
    # Rapport journalier global — En production : crontab(hour=23, minute=50)
    "send_daily_report_mali": {
        "task": "notification.tasks.send_daily_report_mali",
        "schedule": crontab(hour=23, minute=50),
    },
}

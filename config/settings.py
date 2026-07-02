"""
Django settings for FluxTrack.

Env-driven (see .env / .env.example). SQL Server only (dev, test, prod)
via mssql-django; local Express uses a self-signed cert (Encrypt=yes;
TrustServerCertificate=yes), prod (RDS) trusts a real cert chain — the
difference is purely DB_ODBC_EXTRA in each .env.
"""
from pathlib import Path
import os

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


# --- Core ---
SECRET_KEY = env("SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    # local apps
    "accounts",
    "campus",
    "scheduling",
    "verification",
    "ops",
    "web",
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
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database: SQL Server only (dev, test, prod) ---
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": env("DB_NAME", "fluxtrack"),
        "USER": env("DB_USER", ""),          # dedicated login, NOT sa
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "1433"),
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            # env-driven encryption: local Express self-signed (trust it);
            # RDS real cert chain in prod is just a different DB_ODBC_EXTRA
            "extra_params": env(
                "DB_ODBC_EXTRA",
                "Encrypt=yes;TrustServerCertificate=yes",
            ),
        },
        # isolate parallel Wave-2 test runs — each plan can point its
        # runner at a distinct test DB via DB_TEST_NAME (default test_fluxtrack)
        "TEST": {"NAME": env("DB_TEST_NAME", "test_fluxtrack")},
    }
}
# Local dev may use a LocalDB / integrated-security instance (Windows auth,
# no SQL login). Prod (RDS) keeps SQL auth via DB_USER/DB_PASSWORD above.
# Env-driven so the code is identical across environments — only .env differs.
if env_bool("DB_TRUSTED_CONNECTION", False):
    DATABASES["default"]["OPTIONS"]["trusted_connection"] = "yes"

# --- Auth ---
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]
LOGIN_URL = "/login"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login"

# --- I18N / TZ (MMCM, Davao City) ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

# --- Static / media ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# --- FluxTrack policy defaults (SRS §8; all overridable in SystemSetting) ---
FLUXTRACK_POLICY = {
    "grace_minutes": 15,
    "room_hold_minutes": 30,
    "early_end_threshold_minutes": 15,
    "manual_code_rate_limit_per_min": 5,
    "materialization_horizon_days": 14,
    "poll_interval_seconds": 8,
    "reporting_week_start": "monday",
}

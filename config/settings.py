"""
Django settings for FluxTrack.

Env-driven (see .env / .env.example). SQL Server only (dev, test, prod)
via mssql-django; local Express uses a self-signed cert (Encrypt=yes;
TrustServerCertificate=yes), prod (RDS) trusts a real cert chain — the
difference is purely DB_ODBC_EXTRA in each .env.
"""
from pathlib import Path
import os
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return env(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_list(key, default=""):
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# --- Web push (VAPID, NOTIF-02) ---
# Self-signed application server key: the private PEM signs every push and is a
# secret (threat T-05-03) — kept out of git via *.pem/keys/ and referenced by
# path, never inlined. Empty defaults keep the app booting when push is
# unconfigured; the 05-03 outbox sender treats an empty key path as "push off".
VAPID_PUBLIC_KEY = env("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY_PATH = env("VAPID_PRIVATE_KEY_PATH", "")
VAPID_SUB = env("VAPID_SUB", "")
JOB_RUN_RETENTION_DAYS = int(env("JOB_RUN_RETENTION_DAYS", "30"))
SCHEDULER_STALE_MINUTES = int(env("SCHEDULER_STALE_MINUTES", "5"))

# --- Core ---
FLUXTRACK_ENV = env("FLUXTRACK_ENV", "development").strip().lower()
IS_PRODUCTION = FLUXTRACK_ENV in {"production", "prod"}
SECRET_KEY = env("SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DEBUG", False)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# Nginx terminates TLS and supplies X-Forwarded-Proto. Django must understand
# that boundary before it constructs absolute OAuth URLs or enforces HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True
SECURE_SSL_REDIRECT = IS_PRODUCTION
SESSION_COOKIE_SECURE = IS_PRODUCTION
CSRF_COOKIE_SECURE = IS_PRODUCTION
SECURE_HSTS_SECONDS = int(env(
    "SECURE_HSTS_SECONDS", "31536000" if IS_PRODUCTION else "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = IS_PRODUCTION
SECURE_HSTS_PRELOAD = IS_PRODUCTION
SECURE_REFERRER_POLICY = "same-origin"

# Shared across every Gunicorn worker. The table is migration-managed by
# ops.SharedCacheEntry, so a normal ``migrate`` makes the cache deploy-ready.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": env("CACHE_TABLE", "fluxtrack_cache"),
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 100000},
    }
}

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "social_django",
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
    # Intercepts AuthForbidden (deny_unprovisioned) and redirects to
    # SOCIAL_AUTH_LOGIN_ERROR_URL with a message instead of a raw 500.
    # Must sit AFTER AuthenticationMiddleware and BEFORE MessageMiddleware so
    # the messages framework is available to carry the refusal (D-06/D-09#2).
    "social_django.middleware.SocialAuthExceptionMiddleware",
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
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
                # Global notification bell context (NOTIF-01): poll_ms + unread
                # count + VAPID public key on every page, both shells (D-02).
                "web.context.notifications",
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
LOGIN_REDIRECT_URL = "/"      # home() routes by role (D-09 #1)
LOGOUT_REDIRECT_URL = "/login"

# The PKCE subclass is the REAL Entra path and MUST be first (registering the
# stock AzureADTenantOAuth2 silently ignores USE_PKCE — Pitfall 1). ModelBackend
# stays second for break-glass superuser + the DEBUG dev-login stub (D-01/D-03).
AUTHENTICATION_BACKENDS = [
    "accounts.backends.AzureADTenantOAuth2PKCE",
    "django.contrib.auth.backends.ModelBackend",
]

# --- python-social-auth (Microsoft Entra ID, single tenant) ---
# Setting prefix is derived from the backend .name "azuread-tenant-oauth2"
# (inherited unchanged by the PKCE subclass). Creds live in .env (D-04).
SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY = env("SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY")
SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET = env("SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET")
SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID = env("SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID")
SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_USE_PKCE = True   # D-02 (honored by the subclass)

# Pin to the exact registered redirect URI to avoid host-derivation drift
# (localhost, not 127.0.0.1; trailing slash) — else AADSTS50011 (Pitfall 3).
SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI = (
    env(
        "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI",
        "http://localhost:8000/auth/complete/azuread-tenant-oauth2/",
    )
)

# A refused login (AuthForbidden from deny_unprovisioned) must be intercepted by
# SocialAuthExceptionMiddleware and redirected here with a message, not raised as
# an unhandled traceback (DEBUG=True) / generic 500 (DEBUG=False) — D-06/D-09#2.
SOCIAL_AUTH_RAISE_EXCEPTIONS = False
SOCIAL_AUTH_LOGIN_ERROR_URL = "/login"

# Customized pipeline: associate the tenant identity with a PRE-PROVISIONED
# seeded User by email (D-05), refuse if none exists (D-06/AUTH-03 — create_user
# is REMOVED, never auto-provision), then persist User.azure_oid from the 'oid'
# claim. accounts.pipeline.* is created in Plan 02; this is a lazy dotted-string
# tuple resolved only during an auth request, so check/migrate/tests don't import
# it yet.
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.social_auth.associate_by_email",  # D-05 first-login bridge
    "accounts.pipeline.deny_unprovisioned",                 # D-06 refuse if no user
    "social_core.pipeline.social_auth.associate_user",
    "accounts.pipeline.write_azure_oid",                    # D-05 write azure_oid=oid
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
)

# --- I18N / TZ (MMCM, Davao City) ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

# --- Static / media ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# Manifest (hashed, far-future-cacheable) storage in production; plain storage in
# development.
#
# The manifest backend is right for prod and actively hostile in dev: {% static %}
# resolves through staticfiles.json, WhiteNoise loads that manifest ONCE at process
# start, and runserver then serves the hashed copy out of STATIC_ROOT. So editing a
# .css/.js file changed nothing on screen until you ran collectstatic AND restarted
# the server -- and a stale manifest fails silently by serving the previous build,
# which reads as "my CSS didn't apply" rather than as a build-step problem.
#
# In DEBUG the staticfiles app serves straight from STATICFILES_DIRS, so an edit is
# live on reload with no build step.
#
# NOTE: the test runner forces DEBUG=False, so tests still resolve through the
# manifest and still need `manage.py collectstatic` after adding a NEW static file
# (a missing entry raises ValueError). That is a real packaging signal, so it is
# left in place on purpose.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))

# Send X-Content-Type-Options: nosniff (SecurityMiddleware is already installed).
# Written down rather than inherited: MEDIA_ROOT holds user-uploaded content --
# FAC-12 profile photos -- and content sniffing is precisely the mechanism that
# turns "a file the server calls image/jpeg" into "a file the browser decides to
# execute". Modern Django is believed to default this to True, but nobody in this
# project has verified that default, and a security control worth having is worth
# not inheriting silently.
SECURE_CONTENT_TYPE_NOSNIFF = True

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
    "sweep_interval_minutes": 5,   # ENV-04: dedicated-scheduler sweep cadence (JOB-02)
    "modality_shift_lead_days": 2,  # MOD-01/D-02: modality-shift lead-time gate in whole calendar days (Asia/Manila)
    "push_outbox_interval_seconds": 15,  # D-09/NOTIF-02: scheduler cadence draining the push outbox (policy-driven, never hardcoded)
}

# Console output is captured by systemd/journald in production. Request errors
# retain logger, process, and timestamp context without writing append-forever
# files on the EC2 volume.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} pid={process:d} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "apscheduler": {
            "handlers": ["console"],
            "level": env("SCHEDULER_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}


def _validate_production_settings():
    """Refuse to boot a production process with an unsafe deployment boundary."""
    if not IS_PRODUCTION:
        return

    violations = []
    if SECRET_KEY == "dev-insecure-change-me" or len(SECRET_KEY) < 50:
        violations.append("SECRET_KEY must be a unique secret of at least 50 characters")
    if DEBUG:
        violations.append("DEBUG must be False")
    if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
        violations.append("ALLOWED_HOSTS must contain explicit production hosts")

    redirect = SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI
    parsed_redirect = urlparse(redirect)
    if parsed_redirect.scheme != "https" or not parsed_redirect.netloc:
        violations.append(
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI must be an HTTPS URL")
    redirect_host = (parsed_redirect.hostname or "").lower()
    redirect_host_allowed = any(
        redirect_host == allowed.lower()
        or (allowed.startswith(".") and (
            redirect_host == allowed[1:].lower()
            or redirect_host.endswith(allowed.lower())
        ))
        for allowed in ALLOWED_HOSTS
    )
    if redirect_host and not redirect_host_allowed:
        violations.append(
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI host must be in "
            "ALLOWED_HOSTS")

    required = {
        "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY": (
            SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY),
        "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET": (
            SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET),
        "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID": (
            SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID),
        "DB_NAME": DATABASES["default"]["NAME"],
        "DB_USER": DATABASES["default"]["USER"],
        "DB_PASSWORD": DATABASES["default"]["PASSWORD"],
        "DB_HOST": DATABASES["default"]["HOST"],
    }
    for name, value in required.items():
        if not value:
            violations.append(f"{name} must be set")

    db_extra = DATABASES["default"]["OPTIONS"]["extra_params"].lower()
    if "encrypt=yes" not in db_extra or "trustservercertificate=yes" in db_extra:
        violations.append(
            "DB_ODBC_EXTRA must enforce Encrypt=yes without trusting the server certificate")

    if violations:
        raise ImproperlyConfigured(
            "Invalid production configuration: " + "; ".join(violations))


_validate_production_settings()

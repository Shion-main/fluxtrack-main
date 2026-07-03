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
    "http://localhost:8000/auth/complete/azuread-tenant-oauth2/"
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
    "sweep_interval_minutes": 5,   # ENV-04: dedicated-scheduler sweep cadence (JOB-02)
}

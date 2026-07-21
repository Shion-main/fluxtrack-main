# External Integrations

**Analysis Date:** 2026-07-21
**Repository revision:** `6cff9a7` (2026-07-20)

## APIs & External Services

**Identity:**
- Microsoft Entra ID (single tenant) - OAuth 2.0 Authorization Code flow with an application-owned PKCE mixin.
  - SDK/client: `social-auth-app-django==6.0.0` / `social_core` (`accounts/backends.py`).
  - Routes: `/auth/login/azuread-tenant-oauth2/` and `/auth/complete/azuread-tenant-oauth2/` via `social_django.urls` (`config/urls.py`).
  - Local callback is explicitly pinned to `http://localhost:8000/auth/complete/azuread-tenant-oauth2/` (`config/settings.py`). Production HTTPS callback cutover is not yet configured.
  - Auth: `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID`.
  - Provisioning model: accounts must already exist. `accounts/pipeline.py` rejects unknown/inactive identities, associates by email, stores the Entra `oid`, and writes durable audit events; it never self-registers users.

**Browser push service:**
- Standards-based Web Push - the browser supplies its push-service endpoint; there is no project-specific push vendor.
  - SDK/client: browser `PushManager` in `static/js/push.js`; server `pywebpush` in `ops/push.py`.
  - Auth: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY_PATH`, `VAPID_SUB`.
  - Subscription endpoints: `/notifications/push/subscribe` and `/notifications/push/unsubscribe` (`web/urls.py`, `web/push.py`).
  - Delivery: only the dedicated scheduler drains recent notification rows. HTTP 404/410 prunes dead subscriptions; transient failures retain them; a 10-second send timeout isolates request handling (`ops/push.py`, `scheduling/management/commands/runscheduler.py`).

**Microsoft Teams links:**
- Faculty-provided public Teams meeting URLs support online-class verification (`web/faculty.py`, `web/checker.py`).
- FluxTrack validates HTTPS and the `teams.microsoft.com` hostname before storage/use; it does not call a Microsoft Teams API or hold Teams API credentials (`web/faculty.py`).

**Frontend CDNs:**
- jsDelivr hosts Franken UI 2.1.2 and `html5-qrcode` 2.3.8; htmx.org hosts HTMX 2.0.6 (`templates/base.html`, `templates/faculty/scan.html`, `templates/checker/scan.html`).
- Dependencies are runtime CDN loads, not locally built/vendored assets. Phase 15 explicitly owns CDN vendoring (`.planning/ROADMAP.md`).

## Data Storage

**Databases:**
- Microsoft SQL Server through `mssql-django==1.7.3` and `pyodbc`/ODBC Driver 18 (`config/settings.py`, `requirements.txt`).
  - Connection: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_ODBC_EXTRA`; optional `DB_TRUSTED_CONNECTION`; isolated tests can set `DB_TEST_NAME`.
  - Encryption: `DB_ODBC_EXTRA` controls driver parameters. Local development defaults to encrypted connection with trusted self-signed certificate; planned RDS uses the managed certificate chain (`config/settings.py`, `docs/IT_ARCHITECTURE.md`).
  - Client: Django ORM. Raw application SQL is not the normal persistence path; migrations are authoritative.
  - Local target: SQL Server LocalDB/Express. Production target: AWS RDS SQL Server Express, not yet represented by checked-in infrastructure.

**File Storage:**
- Django `FileSystemStorage` under `MEDIA_ROOT` is the configured default (`config/settings.py`).
- Stored content includes faculty profile photos, staged imports, and generated weekly reports (`accounts/photos.py`, `ops/import_staging.py`, `ops/reports.py`).
- Callers use `default_storage`, preserving a future remote-storage seam (`web/faculty.py`, `web/dean.py`, `web/ifo.py`, `ops/reports.py`). Despite an old model docstring mentioning S3 in `ops/models.py`, no S3 backend or `boto3` dependency is configured.
- Static assets use WhiteNoise's compressed manifest storage when `DEBUG=False`; local development serves `static/` directly (`config/settings.py`).

**Caching:**
- Django's implicit default local-memory cache is used; no explicit `CACHES` setting or Redis/Memcached client is detected (`web/scan.py`, `web/checker.py`, `config/settings.py`).
- Cache entries currently enforce rate limits and short-lived idempotency. They are process-local under multi-worker deployment, so Phase 15's shared-cache work is required before those guarantees span Gunicorn workers (`.planning/ROADMAP.md`).

## Authentication & Identity

**Auth Provider:**
- Microsoft Entra ID is the real SSO integration; Django `ModelBackend` remains second for break-glass administration and the `DEBUG` development-login path (`config/settings.py`, `accounts/backends.py`).
- Sessions use Django's database-backed session application and CSRF middleware (`config/settings.py`).
- DRF defaults to session authentication and `IsAuthenticated`, though current JSON routes are plain Django views rather than a DRF API surface (`config/settings.py`, `web/`).
- Authorization is role- and scope-based in application decorators/services, using the custom `accounts.User` model and assignments (`accounts/models.py`, `web/*.py`, `verification/models.py`).

**Identity lifecycle tools:**
- `accounts/management/commands/link_entra.py` links pre-provisioned users to Entra identities.
- `accounts/pipeline.py` audits both successful Entra login and rejected unprovisioned login.

## Monitoring & Observability

**Error Tracking:**
- No Sentry, Application Insights, OpenTelemetry, or other external error-tracking SDK is detected.

**Logs and operational records:**
- Security and business changes are stored in the database-backed `AuditLog` model (`ops/models.py`, `accounts/pipeline.py`, domain services).
- Every scheduled execution is wrapped by `ops/jobrun.py`, which records a `JobRun`; failures generate in-app System Admin notifications.
- No production `LOGGING` configuration or structured log shipper is checked in. Phase 15 owns logging hardening (`.planning/ROADMAP.md`).

## CI/CD & Deployment

**Hosting:**
- Current checked-in runtime is local Django plus SQL Server.
- Documented production target is AWS: Nginx and Gunicorn on one EC2 instance, one separate APScheduler systemd service, and RDS SQL Server Express in a private subnet (`docs/IT_ARCHITECTURE.md`).
- This topology is planning/documentation, not deployed code: no Terraform/CloudFormation/CDK, Dockerfile, Nginx config, systemd unit, or Gunicorn dependency is checked in.

**CI Pipeline:**
- Not detected. No `.github/workflows/`, GitLab pipeline, or equivalent project CI configuration is present.
- Tests run through Django management commands documented in `README.md`.

**Deployment process:**
- The documented manual sequence is install requirements, migrate, collect static assets, and restart the web and scheduler units (`docs/IT_ARCHITECTURE.md`).
- Database backup/restore is expected from RDS managed snapshots, but no backup automation is encoded in this repository.

## Environment Configuration

**Required application variables:**
- Core: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`.
- Database: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_ODBC_EXTRA`; optional `DB_TRUSTED_CONNECTION`, `DB_TEST_NAME`.
- Entra: `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID`.
- Push: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY_PATH`, `VAPID_SUB`.

**Secrets location:**
- `.env` is present and loaded by `config/settings.py`; `.env.example` documents setup. Real values must remain uncommitted.
- VAPID private key material is referenced by filesystem path. Key/certificate files and the `keys/` directory are excluded from the codebase map and must never be committed.
- `config/settings.py` contains a development-only fallback secret and permissive defaults. Production must explicitly provide secure values and disable debug.

## Webhooks & Callbacks

**Incoming:**
- Entra OAuth callback: `/auth/complete/azuread-tenant-oauth2/` (`config/urls.py`, `config/settings.py`). This is an interactive OAuth redirect, not a generic webhook.
- Browser push subscription persistence: `/notifications/push/subscribe` and `/notifications/push/unsubscribe` accept authenticated browser requests (`web/urls.py`, `web/push.py`).
- Checker offline replay posts queued actions back to Django for full server-side revalidation (`static/checker/offline_queue.js`, `web/checker.py`, `web/urls.py`).
- No third-party inbound webhook receiver is detected.

**Outgoing:**
- OAuth authorization/token/JWKS traffic is handled by `social_core` against Microsoft Entra (`accounts/backends.py`).
- Web-push POSTs go to each browser-supplied HTTPS push endpoint (`ops/push.py`).
- End-user browsers navigate to validated Microsoft Teams links; the server performs no Teams API request (`web/faculty.py`, `web/checker.py`).
- No email/SMS provider, payment processor, analytics service, map service, or generic outgoing webhook is detected.

## Scheduled and Background Integrations

- `scheduling/management/commands/runscheduler.py` is the only scheduler construction site. Run exactly one process.
- Four registered jobs share the database: materialize every six hours, sweep at policy cadence, generate prior-week reports Monday at 06:00 Asia/Manila, and drain push notifications at policy cadence.
- APScheduler uses the in-memory job store; schedule definitions are recreated on process start. `JobRun` records execution outcomes, not future schedule state.
- There is no Celery, broker, queue service, or cloud scheduler.

---

*Integration audit: 2026-07-21*

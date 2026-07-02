# External Integrations

**Analysis Date:** 2026-07-02

## Wiring Status Legend

This distinction is the most important thing in this document for planning:

- **WIRED** — actually connected and working in the running app today.
- **STUBBED** — a placeholder stands in for the real integration; the real one is not connected.
- **SPECIFIED, NOT BUILT** — named in the SRS/design and sometimes scaffolded (a model field, a commented dependency, an env var), but no working integration code exists.

**Headline:** None of the external cloud/identity/messaging integrations (Entra ID, AWS RDS/S3/EC2, MS Teams, Web Push VAPID) are wired today. The app runs fully self-contained on SQLite with a DEBUG-only dev-login stub. Every integration below is either STUBBED or SPECIFIED-NOT-BUILT.

## APIs & External Services

**CDN asset delivery (WIRED):**
- jsDelivr CDN — the only live external network dependency at runtime. Loaded in `templates/base.html:12-16`:
  - Franken UI 2.1.2 (`franken-ui@2.1.2` core.min.css, utilities.min.css, core.iife.js, icon.iife.js)
  - htmx 2.0.6 (`htmx.org@2.0.6`)
  - html5-qrcode 2.3.8 — camera QR decoding, loaded in `templates/faculty/scan.html:4`
  - No SDK/auth; anonymous public CDN GETs. To be replaced by a local Tailwind standalone-CLI build later (`templates/base.html:11`).

**Microsoft Entra ID — identity provider (STUBBED):**
- SRS §3.3 / AUTH-01: OAuth 2.0 Authorization Code + PKCE to obtain an ID token; backend verifies against Microsoft's JWKS endpoint.
- **What actually runs:** a DEBUG-only dev-login stub — `web/views.py:login_view` (`web/views.py:47-63`) signs in as any seeded user by username with no password. `docs/USE_CASES.md` marks AUTH-01/02 as "⬜ Not started" and calls the stub "explicitly a stub, not a security boundary."
- Scaffolding present: `accounts/models.py:27-28` reserves an `azure_oid` field mapping to the Entra object id; `PyJWT`/`cryptography`/`requests` are in `requirements.txt:16-18` marked "wired in Phase 2"; env vars `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_CLIENT_SECRET` are commented in `.env.example:14-17`.
- No JWKS, JWT verification, OAuth, or PKCE code exists anywhere in the source. Django username/password auth (`AUTH_USER_MODEL = accounts.User`) backs the stub.

**Microsoft Teams — online session links (SPECIFIED, NOT BUILT):**
- SRS §3.3 / FAC-08: Online sessions reference a Teams meeting link supplied by faculty; "Verify and Start" uses the link instead of a QR scan.
- Scaffolding present: `scheduling/models.py:109` `teams_link = models.URLField(blank=True)` (and its migration `scheduling/migrations/0001_initial.py:68`).
- No integration: nothing reads, validates, or acts on the Teams link; no Teams API call, no "Verify and Start" flow. It is an unused optional URL field. FAC-08 is not among the built surfaces (`docs/USE_CASES.md`).

## Data Storage

**Databases:**
- **SQLite (WIRED, dev):** `config/settings.py:90-96`, file `db.sqlite3` in repo root. This is the live database today.
- **MySQL 8.0 on AWS RDS (SPECIFIED, switch built, NOT connected):** selectable via `DB_ENGINE=mysql` (`config/settings.py:78-89`); connection vars `DB_HOST`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_PORT` (commented in `.env.example:6-12`). Requires uncommenting `mysqlclient` (`requirements.txt:21`). No live RDS instance.
- **SQL Server on AWS RDS Express (SPECIFIED, NOT BUILT — supersedes MySQL):** `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §1 — via `mssql-django` + `pyodbc` + ODBC Driver 18, driven by registrar IT requirement. No `mssql` branch, dependencies, or ODBC config in code yet; pending a Django 6 compatibility spike.

**File Storage:**
- **Local filesystem (WIRED):** default `FileSystemStorage`, `MEDIA_ROOT=BASE_DIR/media` (`config/settings.py:117-122`).
- **AWS S3 (SPECIFIED, NOT BUILT):** SRS §2.4/§3.3 designates S3 for profile photos and generated report files. `ops/models.py:86-95` `WeeklyReport.csv_path`/`pdf_path` comment "files reside in S3", but no S3 client, `boto3`, or `django-storages` dependency exists — paths would resolve to the local filesystem. The deployment design (`...deployment-and-dev-practice-design.md` §2) explicitly drops S3: "media files live on the EC2 instance's EBS volume."

**Caching:**
- None. No Redis/Memcached; no `CACHES` configured. Live surfaces use htmx polling (`poll_interval_seconds=8` in `FLUXTRACK_POLICY`), not a cache or push channel.

## Authentication & Identity

**Auth Provider:**
- Target: Microsoft Entra ID SSO (see above) — STUBBED.
- Current: Django session auth over the dev-login stub. DRF configured for `SessionAuthentication` + `IsAuthenticated` (`config/settings.py:126-133`). Per-view role scoping via decorators (`faculty_required`, `ifo_required` in `web/faculty.py` / `web/ifo.py`); `docs/USE_CASES.md` flags AUTH-04 as partial (applied per view, not framework-wide).
- Divergence noted in `docs/USE_CASES.md`: SRS specifies a backend-issued JWT for API calls; the current build uses session auth. To be resolved before Entra work.

## Monitoring & Observability

**Error Tracking:**
- None. No Sentry or equivalent; no error-tracking dependency.

**Logs:**
- Django defaults only; no custom `LOGGING` config in `config/settings.py`. Application-level auditing is done in-DB via the `AuditLog` model (`ops/models.py:56-73`) — every write event writes an audit row (project convention, `...deployment-and-dev-practice-design.md` §3), which is a data trail, not observability tooling.

## CI/CD & Deployment

**Hosting:**
- Target: single AWS EC2 `t3.micro` — Nginx (TLS via certbot) → Gunicorn → Django systemd service, plus APScheduler as a second systemd service (`...deployment-and-dev-practice-design.md` §2). SPECIFIED, NOT BUILT — no provisioning scripts, Dockerfile, Gunicorn/Nginx config, or systemd unit files in the repo.
- WhiteNoise (`config/settings.py:49,119`) is the one production-serving piece already wired (static file serving from the app process).

**CI Pipeline:**
- None. No `.github/workflows`, no CI config. The definition of done is enforced manually via `docs/DEVELOPMENT.md` conventions (`...deployment-and-dev-practice-design.md` §3), not automation.

## Environment Configuration

**Required env vars (all optional in dev — defaults cover local SQLite run):**
- Core: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` (`.env.example:2-4`).
- DB (only when `DB_ENGINE=mysql`): `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` (`.env.example:6-12`).
- Entra (Phase 2, unused): `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET` (`.env.example:14-17`).

**Secrets location:**
- A gitignored `.env` file at repo root, read by `python-dotenv` (`config/settings.py:13`). Only `.env.example` is committed; no real `.env` present. No secrets manager integration.

## Webhooks & Callbacks

**Incoming:**
- None. No webhook endpoints. The closest thing is the OAuth redirect/callback that Entra SSO will eventually require — not built.

**Outgoing:**
- None wired. **Web Push (VAPID) is SPECIFIED, NOT BUILT** (SRS §3.3 / NOTIF-02): the system is meant to deliver VAPID web-push notifications for floor activity and key events. Scaffolding: `ops/models.py:43-53` `PushSubscription` model (endpoint URL + `keys` JSONField) comment "Web-push (VAPID) subscription endpoint (NOTIF-02)". No VAPID key generation, no `pywebpush`/push dependency, no push-send code, and no client-side `PushManager.subscribe()` in the service worker (`web/views.py` `SW_JS` has no push listener). Notifications exist only as in-DB `Notification` rows (`ops/models.py:25-40`), not delivered externally.

---

*Integration audit: 2026-07-02*

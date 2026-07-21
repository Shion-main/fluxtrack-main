# Technology Stack

**Analysis Date:** 2026-07-21
**Repository revision:** `6cff9a7` (2026-07-20)

## Languages

**Primary:**
- Python 3.12 - Django application, domain logic, management commands, scheduled jobs, imports, reporting, and tests (`manage.py`, `accounts/`, `campus/`, `scheduling/`, `verification/`, `ops/`, `web/`). The supported interpreter is documented in `README.md`; no Python version file is checked in.
- Django template language / HTML - server-rendered pages and HTMX fragments (`templates/`).

**Secondary:**
- JavaScript (browser-native ES5/ES6, no bundler) - PWA/service-worker behavior, web push, QR scanning orchestration, offline Checker replay, and dynamic UI (`static/js/`, `static/checker/offline_queue.js`, `static/faculty/modality.js`, `templates/faculty/scan.html`, `templates/checker/scan.html`).
- CSS - application shells and specialist boards/timetables (`static/css/`, `static/faculty/faculty.css`).
- SQL - reference SQL Server schema documentation (`docs/db_schema.sql`); production schema changes are Django migrations under each app's `migrations/` directory.

## Runtime

**Environment:**
- Python 3.12 is the documented development runtime (`README.md`).
- Django exposes WSGI and ASGI entry points at `config/wsgi.py` and `config/asgi.py`; the documented target deployment runs WSGI through Gunicorn, but Gunicorn is not present in `requirements.txt` and no service-unit configuration is checked in.
- A second, long-lived Python process runs `scheduling/management/commands/runscheduler.py`; never start scheduling from a web worker or `AppConfig.ready()`.
- Browser runtime is required for HTMX, camera QR scanning, IndexedDB replay, service workers, notifications, and PushManager.

**Package Manager:**
- pip with `requirements.txt`.
- Lockfile: missing. Only selected dependencies are exact-pinned; many use lower bounds/ranges, so installs are not fully reproducible.
- No `package.json`, Node lockfile, or frontend build pipeline is checked in. Production remains Node-free at the current revision.

## Frameworks

**Core:**
- Django 6.0.6 - monolithic server-rendered web application, ORM, migrations, authentication, forms-by-view, admin, and test runner (`requirements.txt`, `config/settings.py`).
- Django REST Framework >=3.15 - installed and configured globally for session authentication and authenticated access (`config/settings.py`). No DRF serializer, APIView, ViewSet, or router implementation is detected; JSON endpoints are ordinary Django views in `web/`.
- HTMX 2.0.6 - progressive enhancement and fragment polling/swaps, loaded from jsDelivr/htmx.org in `templates/base.html`.
- Franken UI 2.1.2 - Tailwind-derived CSS/JS component layer loaded from jsDelivr in `templates/base.html`; there is currently no local Tailwind compilation.

**Testing:**
- Django `TestCase`, `TransactionTestCase`, and `SimpleTestCase` - the repository's test framework (`accounts/tests*.py`, `campus/tests.py`, `scheduling/tests*.py`, `verification/tests.py`, `ops/tests*.py`, `web/tests*.py`).
- `unittest.mock` - patching and test doubles where external/storage behavior needs isolation (`ops/tests_push.py`, `ops/tests_reports.py`, `web/tests_dean_reporting.py`).

**Build/Dev:**
- Django management commands - migrations, static collection, fixture/import workflows, report generation, and scheduler execution (`manage.py`, `*/management/commands/`).
- WhiteNoise >=6.6 - static delivery middleware and production compressed-manifest storage (`config/settings.py`).
- No Dockerfile, Compose file, Procfile, CI workflow, formatter config, linter config, or IaC is detected at repository root.

## Key Dependencies

**Critical:**
- `mssql-django==1.7.3` - the only configured database backend (`config/settings.py`); it pulls `pyodbc` and requires system ODBC Driver 18.
- `social-auth-app-django==6.0.0` - Microsoft Entra single-tenant OAuth integration (`accounts/backends.py`, `accounts/pipeline.py`, `config/urls.py`).
- `APScheduler>=3.10,<4` - exactly one `BlockingScheduler` with four jobs: materialization, sweep, weekly report, and push outbox (`scheduling/management/commands/runscheduler.py`). Keep the `<4` constraint because the code uses the APScheduler 3 API.
- `pywebpush>=2.3,<3` - VAPID web-push delivery and dead-endpoint handling (`ops/push.py`).
- `reportlab>=4.2,<5` - in-memory PDF generation for reports (`scheduling/report_render.py`).

**Infrastructure and media:**
- `python-dotenv>=1.0` - loads repository-local `.env` before settings resolve (`config/settings.py`).
- `qrcode[pil]>=7.4` and `Pillow>=10.0` - room QR posters and image/profile-photo handling (`accounts/photos.py`, IFO poster flows in `web/ifo.py`).
- `pypandoc_binary==1.17` - bundled Pandoc runtime used by `scheduling/management/commands/regenerate_srs_docx.py`; `FluxTrack_SRS.docx` is generated from `FluxTrack_SRS.md`.
- `PyJWT>=2.8`, `cryptography>=42.0`, and `requests>=2.31` - explicitly constrained transitive requirements supporting social-auth/OAuth (`requirements.txt`); application modules do not directly implement their own token or HTTP client flow.
- Python standard library `zipfile` and `xml.etree.ElementTree` - `.xlsx` ingestion without pandas/openpyxl (`scheduling/xlsx.py`).

**Browser-delivered dependencies:**
- `html5-qrcode@2.3.8` from jsDelivr - faculty and Checker camera scanning (`templates/faculty/scan.html`, `templates/checker/scan.html`).
- HTMX and Franken UI are CDN dependencies (`templates/base.html`), so a cold client currently needs outbound internet access even when the Django application is locally hosted.

## Configuration

**Environment:**
- `.env` and `.env.example` exist. Never commit or inspect real `.env` values; `config/settings.py` loads them with `python-dotenv`.
- Core variables consumed by settings: `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`.
- SQL Server variables: `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_ODBC_EXTRA`, `DB_TEST_NAME`, `DB_TRUSTED_CONNECTION` (`config/settings.py`).
- Entra variables: `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET`, `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID` (`config/settings.py`).
- Push variables: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY_PATH`, `VAPID_SUB`; the private key is referenced by path and must stay outside version control (`config/settings.py`, `ops/push.py`).
- Product policy defaults live in `FLUXTRACK_POLICY` and can be overridden by the database-backed system setting path (`config/settings.py`, `ops/policy.py`). Do not duplicate grace periods, polling intervals, scheduler cadence, or reporting policy in feature code.

**Build:**
- `config/settings.py` is the single settings module.
- Development static files come directly from `static/`; production uses `collectstatic` into `staticfiles/` with `CompressedManifestStaticFilesStorage`.
- Tests force the production-style static manifest behavior; after adding a new static asset, run `manage.py collectstatic` before tests that resolve it (`config/settings.py`).
- Default media storage is `FileSystemStorage` rooted at `media/` (`config/settings.py`).

## Data and File Formats

- SQL Server is the system of record; do not introduce SQLite-only behavior. A `db.sqlite3` artifact exists at repository root but is not selected by `config/settings.py`.
- CSV import/export uses the Python standard library and shared injection hardening (`scheduling/importing.py`, `scheduling/report_render.py`, `web/hr.py`).
- XLSX import is a deliberately small standard-library parser (`scheduling/xlsx.py`).
- Generated report bytes use Django `default_storage`, currently local filesystem (`ops/reports.py`, `web/dean.py`, `web/ifo.py`).

## Platform Requirements

**Development:**
- Python 3.12, pip, and Microsoft ODBC Driver 18 for SQL Server (`README.md`, `requirements.txt`).
- A reachable SQL Server instance; local Windows development supports SQL authentication or `DB_TRUSTED_CONNECTION` (`config/settings.py`).
- Two processes for a full local system: `manage.py runserver` and `manage.py runscheduler` (`README.md`).
- Camera/service-worker/push features depend on a compatible browser; real web-push delivery needs a secure origin outside localhost.

**Production target (planned, not provisioned in this repository):**
- One AWS EC2 host with Nginx, Gunicorn, WhiteNoise, and two systemd services (web plus scheduler), connecting to AWS RDS SQL Server Express over ODBC/TLS (`docs/IT_ARCHITECTURE.md`, `.planning/ROADMAP.md`).
- Phase 15 owns deploy hardening: shared cache, HTTPS/proxy settings, media separation, CDN vendoring, scheduler resilience, logging, retention, and backups (`.planning/ROADMAP.md`). Treat those items as absent until implementation/configuration lands.
- No checked-in AWS IaC, Nginx config, systemd units, Gunicorn dependency, deployment workflow, or shared-cache backend exists at this revision.

---

*Stack analysis: 2026-07-21*

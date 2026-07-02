# Technology Stack

**Analysis Date:** 2026-07-02

## Languages

**Primary:**
- Python 3.12 — all backend code (Django apps `accounts/`, `campus/`, `scheduling/`, `verification/`, `ops/`, `web/`, plus `config/`). Invoked on Windows via the `py -3.12` launcher (see `README.md`).
- HTML (Django templates) — server-rendered UI under `templates/` (e.g. `templates/base.html`, `templates/faculty/scan.html`, `templates/ifo/live.html`).

**Secondary:**
- Vanilla JavaScript — two isolated client-side modules only: the camera QR scanner (`html5-qrcode`, loaded in `templates/faculty/scan.html`) and the service worker (`SW_JS` string in `web/views.py`). The IndexedDB Checker offline queue is specified but currently exists only in the proof-of-concept `poc/app.py`, not in the shipped `web/` app.
- CSS — supplied by Franken UI (Tailwind) via CDN; no hand-authored stylesheet and no Tailwind build step wired yet.

**Explicitly NOT used:** No React, no client-side SPA framework, and no Node.js runtime. There is no `package.json`, no `node_modules`, and no JS build tool anywhere in the repo. All frontend libraries are pulled from a CDN at runtime.

## Runtime

**Environment:**
- CPython 3.12 (`README.md` pins `py -3.12`). No `.python-version` or `.nvmrc` file present.
- WSGI application: `config.wsgi.application` (referenced in `config/settings.py:75`).

**Package Manager:**
- pip. Install command: `py -3.12 -m pip install --user -r requirements.txt` (`README.md`).
- Lockfile: missing. Dependencies are declared with floor/ceiling ranges in `requirements.txt`; there is no `requirements.lock`, `Pipfile.lock`, or `poetry.lock`.

## Frameworks

**Core:**
- Django `>=5.0,<7.0` (`requirements.txt:3`) — full-stack framework and system of record. Serves the server-rendered UI, the REST API, and static assets as a single application. Settings in `config/settings.py`, URL root `config/urls`. SRS records the target version as Django 6.
- Django REST Framework `>=3.15` (`requirements.txt:4`) — REST API layer. Configured in `config/settings.py:126-133` with `SessionAuthentication` and `IsAuthenticated` as defaults.

**Testing:**
- Django's built-in test runner (unittest-based). Test files present: `web/tests.py` (others per app). No pytest, no separate test framework, no coverage tool declared in `requirements.txt`.

**Build/Dev:**
- WhiteNoise `>=6.6` (`requirements.txt:6`) — serves compressed, hashed static files directly from the Django process on EC2. Wired as middleware (`config/settings.py:49`) and as the `staticfiles` storage backend `whitenoise.storage.CompressedManifestStaticFilesStorage` (`config/settings.py:119`).
- No Tailwind CLI / frontend bundler is wired. `templates/base.html:11` notes Franken UI is CDN-loaded "for dev; standalone-CLI build wired later (SRS §2.4)".

## Key Dependencies

**Critical:**
- `python-dotenv >=1.0` (`requirements.txt:5`) — loads `.env` at startup (`config/settings.py:10,13`). All configuration flows through this.
- `qrcode[pil] >=7.4` (`requirements.txt:9`) — generates room QR posters (IFO-01), used by `web/ifo.py` (`room_qr`, `room_poster`).
- `Pillow >=10.0` (`requirements.txt:10`) — imaging. Also used inline to generate PWA app icons on the fly (`web/views.py:143` `icon()` view draws the icon with `PIL.ImageDraw`).

**Infrastructure:**
- `APScheduler >=3.10` (`requirements.txt:13`) — intended for scheduled jobs JOB-01/02/03 (session materialization, weekly reports). DECLARED BUT NOT WIRED: no `BackgroundScheduler` or APScheduler import exists anywhere in the Python source. Scheduled work is currently run manually via management commands (`materialize_sessions`, `import_offerings` — see `README.md`).
- `PyJWT >=2.8`, `cryptography >=42.0`, `requests >=2.31` (`requirements.txt:16-18`) — listed for Entra ID token verification, marked "wired in Phase 2". DECLARED BUT NOT WIRED: no JWT/JWKS/OAuth code exists yet (see INTEGRATIONS.md).
- `mysqlclient >=2.2` (`requirements.txt:21`) — commented out; to be uncommented for MySQL 8.0 on AWS RDS.

## Configuration

**Environment:**
- Env-driven via `python-dotenv`. `config/settings.py:16-21` defines `env()` and `env_bool()` helpers reading `os.environ`. `.env` is loaded from `BASE_DIR / ".env"` at import time.
- Template file: `.env.example` (committed). Local dev runs entirely on defaults (SQLite) with no `.env` required. A real `.env` is gitignored and NOT present in the repo.
- Key vars (see `.env.example`): `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`; `DB_ENGINE`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`/`DB_HOST`/`DB_PORT` (commented, for MySQL); `ENTRA_TENANT_ID`/`ENTRA_CLIENT_ID`/`ENTRA_CLIENT_SECRET` (commented, Phase 2). Defaults in code: `SECRET_KEY="dev-insecure-change-me"`, `DEBUG=True`, `ALLOWED_HOSTS="*"`.
- **Policy configuration:** `FLUXTRACK_POLICY` dict in `config/settings.py:136-144` holds tunable business-rule defaults (`grace_minutes=15`, `room_hold_minutes=30`, `manual_code_rate_limit_per_min=5`, `materialization_horizon_days=14`, `poll_interval_seconds=8`, etc.). These are seeded into the DB-backed `SystemSetting` model (`ops/models.py:76`) and read at runtime via `ops/policy.py`'s `get_policy()` — code must never hardcode these constants (per `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §3).

**Build:**
- `config/settings.py` — single settings module (no split dev/prod settings files); all environment differences are env-var driven.
- No `pyproject.toml`, `setup.cfg`, `tox.ini`, or CI config files present.

## Database

- **Development (current):** SQLite. `config/settings.py:90-96` selects `django.db.backends.sqlite3` at `BASE_DIR / db.sqlite3` whenever `DB_ENGINE != "mysql"`. The dev DB file `db.sqlite3` is committed/present in the repo root.
- **Production switch (built, not exercised):** `config/settings.py:78-89` — setting `DB_ENGINE=mysql` selects `django.db.backends.mysql` with `utf8mb4`, targeting MySQL 8.0 on AWS RDS. Requires uncommenting `mysqlclient` in `requirements.txt`. Not connected to any live RDS instance.
- **Planned migration (design only, NOT implemented):** `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §1 supersedes the MySQL plan with SQL Server via `mssql-django` + `pyodbc` + Microsoft ODBC Driver 18, driven by a registrar IT requirement. This adds a third `mssql` branch to the existing `DB_ENGINE` switch and appends `mssql-django`/`pyodbc` to `requirements.txt`. Status: approved design, pending a compatibility spike against Django 6; neither the settings branch nor the dependencies exist in the code yet.

## Static & Template Serving

- **Static files:** `STATIC_URL=/static/`, source dir `static/` (`STATICFILES_DIRS`), collected to `staticfiles/` (`STATIC_ROOT`), served by WhiteNoise with compressed+hashed manifest storage (`config/settings.py:113-119`). The only source static content today is `static/icons/` (empty of committed files).
- **Media:** `MEDIA_URL=/media/`, `MEDIA_ROOT=BASE_DIR/media`, default `FileSystemStorage` (`config/settings.py:117-122`). No cloud object storage backend configured — generated report files and any uploads live on the local filesystem / EC2 EBS volume.
- **Templates:** Django template backend, `APP_DIRS=True` plus a project-level `templates/` dir (`config/settings.py:60-73`). Base shell `templates/base.html` loads Franken UI + htmx from CDN and registers the service worker. No template caching or custom loaders configured.
- **PWA shell served dynamically from Python** (not static files): `web/views.py` serves `/manifest.webmanifest` (`manifest()`), `/sw.js` (`service_worker()` returning the inline `SW_JS` string), and `/icon-<size>.png` (`icon()` drawing icons at request time with Pillow). Routed in `web/urls.py:24-26`.

## Platform Requirements

**Development:**
- Windows (primary): Python 3.12 via `py -3.12`; console is cp1252, so management commands print ASCII only (per `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §3). Runs with SQLite and zero external services: `py -3.12 manage.py runserver 127.0.0.1:8020`.
- Internet access required at page load for the Franken UI / htmx / html5-qrcode CDN assets.

**Production (target, not yet provisioned):**
- Single AWS EC2 `t3.micro`: Nginx (TLS via certbot; HTTPS required for PWA service workers) → Gunicorn → Django as a systemd service, with APScheduler as a second systemd service on the same instance. Database on AWS RDS for SQL Server Express (`db.t3.micro`). Media on the instance's EBS volume (no S3). See `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §2. None of this is provisioned or scripted in the repo.

---

*Stack analysis: 2026-07-02*

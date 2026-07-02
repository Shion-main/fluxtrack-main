# Codebase Structure

**Analysis Date:** 2026-07-02

## Directory Layout

```
fluxtrack-main/
├── config/         # Django project: settings, root urls, wsgi/asgi
├── accounts/       # User (7-role RBAC) + Department; seed_demo command
├── campus/         # Building / Floor / Room (rooms hold qr_token + manual_code)
├── scheduling/     # AcademicTerm, Schedule, Session + resolver.py + import/materialize commands
├── verification/   # Assignment, CheckerValidation (Checker/Guard duty + source-of-truth)
├── ops/            # Booking, Notification, PushSubscription, AuditLog, SystemSetting, WeeklyReport + policy.py
├── web/            # Frontend layer: dev-login, home, scan views, faculty/ifo surfaces, PWA shell
├── templates/      # Django templates (Franken UI + htmx); base.html + per-surface dirs
├── static/         # Static assets (icons/); served by whitenoise
├── data/           # gitignored registrar source CSVs (PII) — import_offerings input
├── docs/           # USE_CASES.md build reference, design specs, session logs
├── poc/            # throwaway proof-of-concept (offline-queue IndexedDB pattern) + screenshots
├── manage.py       # Django entry point (use `py -3.12 manage.py ...`)
├── requirements.txt
├── README.md
└── FluxTrack_SRS.md  # source-of-truth spec (§2.1 = intended architecture)
```

Each Django app follows the standard layout: `models.py`, `admin.py`, `apps.py`, `views.py`, `migrations/`, `tests.py`. The `web` app additionally splits its view code across `views.py`, `faculty.py`, `ifo.py`, `scan.py` and owns `urls.py`.

## Directory Purposes

**`config/`:**
- Purpose: Django project glue.
- Key files: `config/settings.py` (env-driven, SQLite dev / MySQL prod, `FLUXTRACK_POLICY` defaults, installed apps, session auth), `config/urls.py` (root router → `admin/` + `include("web.urls")`), `config/wsgi.py`, `config/asgi.py`.

**`accounts/`:**
- Purpose: Identity and org units.
- Contains: `User(AbstractUser)` with `role` (7-value `Role` TextChoices), `department`, `azure_oid`, `profile_photo`; `Department`.
- Key files: `accounts/models.py`, `accounts/management/commands/seed_demo.py`.

**`campus/`:**
- Purpose: Physical spaces.
- Contains: `Building` → `Floor` → `Room`. Room carries resolver-only `qr_token` + `manual_code` (never rendered client-side) and `code_rotated_at/by`.
- Key files: `campus/models.py`.

**`scheduling/`:**
- Purpose: Academic time model + the scan decision engine.
- Contains: `AcademicTerm`, `AcademicBreak`, `Schedule` (recurring slot), `Session` (dated occurrence, all attendance state), `Modality`/`DayOfWeek`/`SessionStatus`/`CheckinMethod` enums.
- Key files: `scheduling/models.py`, `scheduling/resolver.py` (**pure** outcome logic), `scheduling/tests.py` (16 resolver tests), `scheduling/management/commands/import_offerings.py`, `scheduling/management/commands/materialize_sessions.py`.

**`verification/`:**
- Purpose: Checker/Guard duty and physical verification (the authoritative presence record).
- Contains: `Assignment` (on-duty grant, floors M2M), `CheckerValidation` (verify/flag actions), `DutyRole`/`AssignmentType`/`ValidationAction` enums. Models exist; no surface built yet.
- Key files: `verification/models.py`.

**`ops/`:**
- Purpose: Operational cross-cutting data + policy access.
- Contains: `Booking`, `Notification`, `PushSubscription`, `AuditLog`, `SystemSetting`, `WeeklyReport`.
- Key files: `ops/models.py`, `ops/policy.py` (`get_policy` — SystemSetting override with settings fallback).

**`web/`:**
- Purpose: The entire presentation/controller layer. Fetches context, gates by role, calls resolver/policy, applies side effects, renders templates. No models of its own.
- Key files:
  - `web/urls.py` — the app URL map.
  - `web/views.py` — dev-login stub, role-routed `home` (`SURFACES` dict maps role → home cards), PWA shell (manifest, service worker JS, generated PNG icons).
  - `web/faculty.py` — `faculty_required` decorator, `schedule`, `scan_page`.
  - `web/ifo.py` — `ifo_required` decorator, rooms list/detail, QR poster + PNG, live polling views.
  - `web/scan.py` — the scan trio: `_room_from_payload`, `_apply`, `_notify_ifo`, `resolve`, `confirm`, `deep_link`.

**`templates/`:**
- Purpose: Server-rendered UI (no separate frontend build).
- Contains: `base.html` (Franken UI + htmx CDN, PWA registration, auth header chrome), per-surface subdirs.
- Key files: `templates/web/{home,login}.html`, `templates/faculty/{schedule,scan}.html` + `_outcome.html`, `templates/ifo/{rooms,room_detail,poster,live}.html` + `_live_rows.html`.

## Key File Locations

**Entry Points:**
- `config/urls.py`: root URL router.
- `web/urls.py`: application routes.
- `manage.py`: CLI / server entry (`py -3.12 manage.py runserver 127.0.0.1:8020`).

**Configuration:**
- `config/settings.py`: env-driven settings; `FLUXTRACK_POLICY` policy defaults.
- `.env` / `.env.example`: environment variables (existence noted only — do not read secrets).

**Core Logic:**
- `scheduling/resolver.py`: pure scan-outcome decision engine.
- `web/scan.py`: side-effect applier + two-step confirmation.
- `ops/policy.py`: policy value resolution.

**Testing:**
- `scheduling/tests.py`: 16 resolver unit tests (the only substantive test module today; other apps' `tests.py` are stubs).

## Naming Conventions

**Apps:** lowercase, single-word domain names (`accounts`, `campus`, `scheduling`, `verification`, `ops`, `web`).

**Files:**
- Standard Django module names per app. The `web` app splits views by surface into separate modules (`faculty.py`, `ifo.py`, `scan.py`) rather than one large `views.py`.

**Templates — mirror surface/route names:**
- Directory mirrors the role/surface: `templates/faculty/`, `templates/ifo/`, `templates/web/`.
- Full-page template filename matches the view/route: `faculty/schedule.html` ↔ `faculty.py:schedule` ↔ `/faculty/schedule`.
- **`_`-prefixed files are htmx partial fragments** returned to a swap target, not full pages: `faculty/_outcome.html`, `ifo/_live_rows.html`.

**URL names:** snake_case, `surface_action` (`faculty_schedule`, `ifo_room_detail`, `scan_resolve`).

**Models:** singular PascalCase; enums as nested/module-level `TextChoices`/`IntegerChoices` (`SessionStatus`, `CheckinMethod`, `Role`, `DutyRole`, `ValidationAction`).

**Private helpers:** `_`-prefixed module functions in views (`_room_from_payload`, `_apply`, `_notify_ifo`, `_today_sessions`, `_deep_link`).

## Where to Add New Code

**New role-facing surface (e.g. Checker, Guard, Dean, HR):**
- Views: new `web/<role>.py` module with a `<role>_required` decorator modeled on `web/faculty.py:faculty_required` / `web/ifo.py:ifo_required`.
- Routes: add `path(...)` entries to `web/urls.py` and import the new module there.
- Home cards: add/adjust the role's entry in `web/views.py:SURFACES`.
- Templates: new `templates/<role>/` dir; full pages named after the route, htmx fragments `_`-prefixed.

**New business decision logic:**
- Keep it pure where possible — follow `scheduling/resolver.py`: a function taking pre-fetched data + injected policy/`now`, returning a result object, with side effects applied by the caller. The SRS mandates this shape for reporting aggregates (`docs/USE_CASES.md` RPT-05).
- Unit-test it in the owning app's `tests.py` without DB fixtures, mirroring `scheduling/tests.py`.

**New state-changing action:**
- Apply the mutation in the web layer (e.g. a `web/*.py` view or an `_apply`-style helper) and write an `AuditLog` row alongside it — never mutate without auditing.

**New model / domain data:**
- Place in the owning app's `models.py` (`ops/` for operational/cross-cutting data, `scheduling/` for academic time, `verification/` for duty/verification). Register in that app's `admin.py`. Generate a migration.

**New tunable value:**
- Add a default to `config/settings.py:FLUXTRACK_POLICY`, read it via `ops/policy.py:get_policy`, and (optionally) seed a `SystemSetting` row for override.

**New batch/scheduled job:**
- Add a management command under the owning app's `management/commands/` (pattern: `scheduling/management/commands/materialize_sessions.py`). A dedicated scheduler process is not yet wired (JOB infra pending).

## Special Directories

**`data/`:**
- Purpose: Raw registrar CSVs (course offerings, PII) consumed by `import_offerings`.
- Generated: No (external source). Committed: No (gitignored).

**`static/` vs `staticfiles/`:**
- `static/` is source assets (committed, e.g. `static/icons/`); `staticfiles/` is the whitenoise collect target (`STATIC_ROOT`, generated, not committed).

**`poc/`:**
- Purpose: Throwaway proof-of-concept (notably the IndexedDB offline-queue pattern for the future Checker offline slice) + screenshots. Reference only, not part of the app.

**`docs/`:**
- Purpose: `USE_CASES.md` (authoritative build status per role), design specs under `docs/superpowers/specs/`, session logs under `docs/sessions/`. Committed.

**`migrations/`:**
- Standard Django migrations per app. Generated + committed.

---

*Structure analysis: 2026-07-02*

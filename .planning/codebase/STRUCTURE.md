# Codebase Structure

**Analysis Date:** 2026-07-21

## Directory Layout

```text
fluxtrack-main/
├── config/          # Django composition: settings, root URLs, WSGI/ASGI
├── accounts/        # Identity, roles, departments, Entra pipeline, photos
├── campus/          # Buildings, floors, rooms, credentials, safe deletion
├── scheduling/      # Academic/calendar domain, services, reports, jobs, commands
├── verification/    # Checker/Guard assignments and validation rules
├── ops/             # Cross-domain operational models and infrastructure services
├── web/             # Role-oriented HTTP controllers and URL map
├── templates/       # Full server-rendered pages and htmx fragments by surface
├── static/          # Source CSS, JavaScript, and brand assets
├── staticfiles/     # Generated collectstatic output; do not edit
├── media/           # Runtime uploads, staged imports, generated reports
├── data/fixtures/   # Committed synthetic import fixture
├── docs/            # Product/architecture/audit/session references
├── .planning/       # GSD project state, phases, graph, and codebase maps
├── .agents/         # Project-local command-routing skills
├── .claude/         # Prior Claude/GSD command and agent assets
├── .codex/          # Codex hooks and project integration assets
├── poc/             # Isolated proof-of-concept code, not production imports
├── DEFAULT SCREENS/ # Design reference images
├── manage.py        # Django CLI entry point
├── requirements.txt # Python dependency pins
├── README.md        # Developer setup and operating commands
└── FluxTrack_SRS.md # System requirements reference
```

## Directory Purposes

**`config/`:**
- Purpose: Compose the Django runtime.
- Contains: settings, root URL routing, WSGI, ASGI.
- Key files: `config/settings.py`, `config/urls.py`, `config/wsgi.py`, `config/asgi.py`.
- Add only project-wide configuration here; domain behavior belongs in an owning app.

**`accounts/`:**
- Purpose: Own user identity and organizational membership.
- Contains: `Department`, custom `User`, seven-value `Role`, Entra PKCE backend/pipeline, image normalization, admin, migrations, seed/link commands.
- Key files: `accounts/models.py`, `accounts/backends.py`, `accounts/pipeline.py`, `accounts/photos.py`, `accounts/management/commands/seed_demo.py`, `accounts/management/commands/link_entra.py`.

**`campus/`:**
- Purpose: Own physical-space identity and room credentials/state.
- Contains: `Building`, `Floor`, `Room`, case-sensitive QR/manual credential generation, safe deletion probes, CRUD tests.
- Key files: `campus/models.py`, `campus/codes.py`, `campus/services.py`.
- Boundary: keep this lower-level app free of imports from `scheduling`, `verification`, and `ops`; use reverse model accessors in `campus/services.py`.

**`scheduling/`:**
- Purpose: Own academic time, attendance occurrences, modality workflow, materialization, reporting truth, and scheduled academic jobs.
- Contains: term/break/suspension/schedule/session/modality models; pure scan resolver; modality and schedule services; merge/suspension logic; import/xlsx utilities; report aggregates/renderers; management commands.
- Key files: `scheduling/models.py`, `scheduling/resolver.py`, `scheduling/services.py`, `scheduling/schedule_ops.py`, `scheduling/merge.py`, `scheduling/suspensions.py`, `scheduling/jobs.py`, `scheduling/reporting.py`, `scheduling/report_render.py`, `scheduling/importing.py`, `scheduling/xlsx.py`.
- Commands: `scheduling/management/commands/` owns import, room-master load, session materialization, sweep/scheduler, online assignment, reports, resets, and audits.

**`verification/`:**
- Purpose: Own duty authority and Checker observations.
- Contains: floor/online `Assignment`, `CheckerValidation`, pure scan/assignment distribution rules, online-session assignment orchestration.
- Key files: `verification/models.py`, `verification/resolver.py`, `verification/services.py`.

**`ops/`:**
- Purpose: Own cross-domain operational records and infrastructure-facing services.
- Contains: bookings, import staging, notifications/mutes/subscriptions, audits, conflict flags, job runs, settings, weekly report metadata; availability, occupancy, notification, push, reports, guard alerts, policy, staging, job wrappers.
- Key files: `ops/models.py`, `ops/availability.py`, `ops/occupancy.py`, `ops/notify.py`, `ops/notifications.py`, `ops/push.py`, `ops/reports.py`, `ops/import_staging.py`, `ops/jobrun.py`, `ops/policy.py`, `ops/guard_alerts.py`.

**`web/`:**
- Purpose: Own all application HTTP controllers and route-to-template composition.
- Contains: `web/urls.py`; shared auth/home/PWA views; role modules; notification/push endpoints; pagination, room-state, and reporting presentation helpers.
- Key files by surface:
  - Shared: `web/views.py`, `web/context.py`, `web/urls.py`
  - Faculty/physical scan: `web/faculty.py`, `web/scan.py`
  - Verification/security: `web/checker.py`, `web/guard.py`
  - Reporting/approval: `web/dean.py`, `web/hr.py`, `web/ifo.py`
  - Operations: `web/notifications.py`, `web/push.py`, `web/sys.py`
  - Read-model helpers: `web/room_state.py`, `web/reporting_common.py`, `web/pagination.py`
- Models: `web/models.py` is intentionally empty; persistent concepts belong to a domain app.

**`templates/`:**
- Purpose: Render full pages and htmx fragments.
- Contains: `templates/base.html`, shared `_console.html`, `_pager.html`, `_room_code.html`, and role directories `faculty/`, `checker/`, `guard/`, `dean/`, `hr/`, `ifo/`, `sys/`, `notifications/`, `reports/`, `web/`.
- Rule: `_`-prefixed files are partials; non-prefixed files are full page/surface templates.

**`static/`:**
- Purpose: Store hand-authored frontend assets with no Node build.
- Contains: CSS under `static/css/`, role/PWA scripts under `static/js/`, `static/checker/`, `static/faculty/`, and brand images under `static/brand/`.
- Key files: `static/css/app.css`, `static/css/tokens.css`, `static/js/push.js`, `static/js/board.js`, `static/checker/offline_queue.js`, `static/faculty/modality.js`.

**`.planning/`:**
- Purpose: Store current GSD roadmap/state, requirements, phase artifacts, knowledge graph, and codebase maps consumed by planning/execution.
- Key files: `.planning/PROJECT.md`, `.planning/STATE.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, `.planning/codebase/*.md`.
- Current execution context is recorded here; consult it before relying on status text in `README.md` or older session docs.

**`docs/`:**
- Purpose: Store product, architecture, audit, user-flow, and collaboration history.
- Key files: `docs/AUDIT-2026-07-19.md`, `docs/PLAN-2026-07-20-post-audit-milestone.md`, `docs/USE_CASES.md`, `docs/USER_FLOWS.md`, `docs/IT_ARCHITECTURE.md`, `docs/ARCHITECTURE.md`, `docs/sessions/`.

## Key File Locations

**Entry Points:**
- `manage.py`: Django command entry.
- `config/urls.py`: root HTTP router.
- `web/urls.py`: complete application route map.
- `config/wsgi.py`: synchronous deployment entry.
- `config/asgi.py`: ASGI-compatible entry; no websocket application is implemented.
- `scheduling/management/commands/runscheduler.py`: dedicated background-process entry.

**Configuration:**
- `config/settings.py`: installed apps, SQL Server, Entra/social-auth, middleware, storage, timezone, REST defaults, and `FLUXTRACK_POLICY`.
- `requirements.txt`: Python runtime dependency pins.
- `.env` and `.env.example`: environment configuration exists; never read or commit values from these files.

**Core Logic:**
- `scheduling/resolver.py`: pure faculty physical-scan outcomes.
- `verification/resolver.py`: pure Checker duty/scan decisions and online distribution.
- `scheduling/services.py`: modality request/approval lifecycle.
- `scheduling/reporting.py`: canonical reporting/utilization aggregates.
- `scheduling/jobs.py`: no-show sweep and room-conflict detection.
- `ops/availability.py`: shared room/faculty conflict rules.
- `ops/notify.py`: sole notification creation path.
- `campus/services.py`: safe-delete dependency probes.

**Persistence:**
- `accounts/models.py`: user and department.
- `campus/models.py`: building, floor, room.
- `scheduling/models.py`: academic/calendar/attendance/modality records.
- `verification/models.py`: assignments and validations.
- `ops/models.py`: cross-domain operations and observability records.
- `<app>/migrations/`: generated, committed schema history for each owning app.

**Testing:**
- Tests are colocated by app as `<app>/tests.py` and focused `<app>/tests_*.py` modules.
- Shared scheduling fixture builders live in `scheduling/test_support.py`.
- High-density integration coverage is in `web/tests_*.py`, `scheduling/tests_*.py`, and `ops/tests_*.py`.

## Naming Conventions

**Files:**
- Use lowercase snake_case Python modules: `schedule_ops.py`, `report_render.py`, `import_staging.py`.
- Keep standard Django filenames (`models.py`, `admin.py`, `apps.py`, `views.py`, `migrations/`).
- Split role controllers into `web/<role>.py`; split focused tests into `tests_<feature>.py` beside the owning code.
- Name management command modules after their CLI command: `run_status_sweep.py`, `generate_weekly_report.py`.
- Name htmx partials with a leading underscore: `templates/ifo/_board.html`, `templates/notifications/_rows.html`.

**Directories:**
- Django apps are singular lowercase domain names: `accounts`, `campus`, `scheduling`, `verification`, `ops`, `web`.
- Template directories match role or shared surface names.
- Static feature directories match their surface when the script is not globally shared.

**Routes and views:**
- URL names use snake_case with a surface prefix: `faculty_online_start`, `ifo_room_toggle_service`, `checker_floor_rows`.
- Public view functions mirror route actions; internal helpers use a leading underscore.
- Literal routes such as `ifo/rooms/new` must precede variable converters such as `ifo/rooms/<str:code>` in `web/urls.py`.

**Domain types:**
- Models/dataclasses use PascalCase; enum choice classes use PascalCase and uppercase members.
- Service verbs state the transition: `submit_modality_shift`, `apply_approval`, `suspend_classes`, `release_room`, `generate_week_reports`.

## Where to Add New Code

**New role-facing feature:**
- Controller: add to the existing `web/<role>.py`; create a new role module only if the role has no module.
- Route: register in `web/urls.py` with the role prefix and role decorator.
- Full template: `templates/<role>/<surface>.html`.
- htmx fragment: `templates/<role>/_<fragment>.html`.
- Surface-only JavaScript: `static/<role>/<feature>.js`; broadly shared JavaScript: `static/js/<feature>.js`.
- Tests: `web/tests_<feature>.py` when HTTP authorization/rendering is the subject.

**New deterministic business rule:**
- Place a pure rule in the owning domain, following `scheduling/resolver.py` or `verification/resolver.py`.
- Pass ORM-derived values, policy, and clock explicitly; do not query or call `timezone.now()` inside pure rules.
- Add focused unit tests in the owning app's `tests_<feature>.py` or existing resolver test module.

**New multi-model workflow:**
- Place orchestration in the owning app service (`scheduling/services.py`, a focused `scheduling/<feature>.py`, `verification/services.py`, or `ops/<feature>.py`).
- Revalidate mutable authority inside `transaction.atomic()`, write `AuditLog`, and create notifications through `ops/notify.py`.
- Keep `web/*.py` responsible for request parsing, scoping, response status, and rendering.

**New persistent concept:**
- Identity/org: `accounts/models.py`.
- Physical campus: `campus/models.py`.
- Academic/calendar/attendance: `scheduling/models.py`.
- Duty/verification: `verification/models.py`.
- Cross-domain operational infrastructure: `ops/models.py`.
- Add the migration and admin registration in the same app; use string FK references across app boundaries.

**New report or metric:**
- Aggregate/reduction: `scheduling/reporting.py`.
- CSV/PDF primitives: `scheduling/report_render.py`.
- Shared range/status presentation: `web/reporting_common.py`.
- Role delivery: `web/dean.py`, `web/hr.py`, or `web/ifo.py` plus the matching template.
- Scheduled artifact/storage/fan-out: `ops/reports.py`.
- Protect independent dashboard metrics with `scheduling/reporting.py:safe_card`.

**New scheduled job:**
- Domain callable: place in the owning domain module and return a meaningful affected-row count.
- Registration/cadence: `scheduling/management/commands/runscheduler.py` only.
- Execution wrapper: use `ops/jobrun.py:run_job` so `/sys/jobs` and failure notifications remain complete.
- One-shot operator entry, if needed: `scheduling/management/commands/<command>.py`.

**New tunable policy:**
- Default: `config/settings.py:FLUXTRACK_POLICY`.
- Access: `ops/policy.py:get_policy`.
- Runtime override: `ops.models.SystemSetting`; do not hardcode the same value in consumers.

**New notification type:**
- Taxonomy/category/push eligibility: `ops/notifications.py`.
- Creation: `ops/notify.py:notify` from the state-changing workflow.
- Presentation: reuse `web/notifications.py` and `templates/notifications/`.
- Never create `Notification` directly from feature code.

**New import format or source:**
- Parsing/classification: `scheduling/importing.py` or `scheduling/xlsx.py`.
- CLI orchestration: `scheduling/management/commands/import_offerings.py`.
- Web upload lifecycle: `ops/import_staging.py` and `web/ifo.py`.
- Synthetic committed fixtures: `data/fixtures/`; never commit registrar PII/raw production exports.

## Special Directories

**`staticfiles/`:**
- Purpose: `collectstatic` output served by WhiteNoise.
- Generated: Yes.
- Committed: Runtime/build artifact; do not hand-edit.

**`media/`:**
- Purpose: Default storage for profile photos, staged imports, and generated weekly reports.
- Generated: Yes, runtime-owned.
- Committed: No application source should depend on checked-in contents.

**`data/fixtures/`:**
- Purpose: Safe synthetic registrar input for tests and development.
- Generated: No.
- Committed: Yes.

**`poc/`:**
- Purpose: Isolated proof-of-concept material.
- Generated: No.
- Committed: Yes.
- Constraint: production modules must not import from `poc/`.

**`.planning/`:**
- Purpose: GSD planning, verification, graph, and codebase-intelligence artifacts.
- Generated: Partly tool-generated, partly authored.
- Committed: Yes.

**`.agents/`, `.claude/`, `.codex/`:**
- Purpose: Agent/command integration and prior collaboration context.
- Generated: Tool-managed.
- Committed: Repository status determines tracked content; application runtime must not import these directories.

**`DEFAULT SCREENS/`:**
- Purpose: Visual requirements/reference screenshots.
- Generated: No.
- Committed: Yes.

**`keys/`:**
- Purpose: Runtime private-key location referenced by configuration.
- Generated: Environment-managed.
- Committed: Never commit private key material.

---

*Structure analysis: 2026-07-21*

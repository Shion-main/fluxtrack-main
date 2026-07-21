<!-- refreshed: 2026-07-21 -->
# Architecture

**Analysis Date:** 2026-07-21

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Django HTTP entry points                                            │
│ `config/urls.py` -> `web/urls.py` -> role-specific view modules     │
├───────────────┬───────────────┬───────────────┬─────────────────────┤
│ Faculty/scan  │ Checker/Guard │ Dean/HR       │ IFO/System/Notif    │
│ `web/faculty` │ `web/checker` │ `web/dean.py` │ `web/ifo.py`        │
│ `web/scan.py` │ `web/guard.py`│ `web/hr.py`   │ `web/sys.py`        │
└───────┬───────┴───────┬───────┴───────┬───────┴──────────┬──────────┘
        │               │               │                  │
        ▼               ▼               ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Business rules and orchestration                                    │
│ `scheduling/{resolver,services,reporting,jobs,suspensions}.py`      │
│ `verification/{resolver,services}.py`                               │
│ `ops/{availability,occupancy,notify,reports,push,policy}.py`        │
│ `campus/{services,codes}.py`                                        │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Django ORM domains -> SQL Server                                    │
│ `accounts` | `campus` | `scheduling` | `verification` | `ops`      │
└───────────────────────────────┬─────────────────────────────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Side-effect adapters                                                │
│ templates/htmx, default_storage, pywebpush, APScheduler, Entra OAuth│
└─────────────────────────────────────────────────────────────────────┘
```

FluxTrack is a server-rendered Django monolith. Django views own HTTP concerns and role gates; reusable domain services own multi-step writes; pure resolvers and reporting functions own decisions and reductions; Django models persist to Microsoft SQL Server. There is no JSON application API or client-side state store. htmx replaces server-rendered fragments, while small JavaScript modules handle the PWA, push subscriptions, board polling, modality UI, and Checker offline replay.

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Project composition | Settings, middleware, SQL Server, Entra/social-auth, storage, policy defaults | `config/settings.py` |
| HTTP routing | Mount admin, OAuth callbacks, and all application routes | `config/urls.py`, `web/urls.py` |
| Identity | Custom user, seven roles, departments, PKCE backend, pre-provisioned Entra pipeline, photo normalization | `accounts/models.py`, `accounts/backends.py`, `accounts/pipeline.py`, `accounts/photos.py` |
| Campus | Building/floor/room hierarchy, opaque room credentials, service state, safe-delete blockers | `campus/models.py`, `campus/codes.py`, `campus/services.py` |
| Scheduling | Terms, calendars, recurring schedules, dated sessions, modality tickets, scan rules, lifecycle writes | `scheduling/models.py`, `scheduling/resolver.py`, `scheduling/services.py` |
| Verification | Floor/online duty grants, Checker decisions, online-session assignment | `verification/models.py`, `verification/resolver.py`, `verification/services.py` |
| Operations | Bookings, staged imports, notifications, push, audit, conflicts, jobs, policy, reports | `ops/models.py`, `ops/*.py` |
| Presentation | Role-scoped controllers and htmx/page rendering | `web/*.py`, `templates/` |
| Background processing | Materialization, sweep/conflicts, weekly reports, push outbox, staging cleanup | `scheduling/management/commands/runscheduler.py` |

## Pattern Overview

**Overall:** Layered modular monolith with thin HTTP adapters, ORM-backed domain services, pure rule cores, and explicit background-job orchestration.

**Key Characteristics:**
- Keep deterministic decisions free of ORM and clocks: `scheduling/resolver.py` and `verification/resolver.py` accept prepared context and `now`.
- Put atomic, multi-model workflows in services such as `scheduling/services.py`, `scheduling/suspensions.py`, and `scheduling/schedule_ops.py`; views validate HTTP input and delegate.
- Use `Notification` as a database outbox and `ops.notify.notify()` as its single write path; delivery occurs asynchronously in `ops/push.py`.
- Record operational writes explicitly in `ops.models.AuditLog`; this is a coding invariant, not middleware or a signal.
- Treat `Session` as the dated attendance and room-occupancy record; `Schedule` remains the recurring source definition.

## Layers

**Composition and adapters:**
- Purpose: Configure runtime services and translate HTTP/CLI events into application calls.
- Location: `config/`, `web/urls.py`, `scheduling/management/commands/`, `accounts/management/commands/`
- Contains: URL maps, auth middleware, environment-backed settings, management commands, WSGI/ASGI bootstraps.
- Depends on: Django, third-party adapters, presentation and service modules.
- Used by: web server, scheduler process, operators.

**Presentation/controllers:**
- Purpose: Authenticate, authorize, parse request data, scope ORM queries, invoke services, and render HTML/CSV/PDF/PNG/JS responses.
- Location: `web/`
- Contains: shared entry/auth/PWA views in `web/views.py`; role modules `faculty.py`, `checker.py`, `guard.py`, `dean.py`, `hr.py`, `ifo.py`, `sys.py`; cross-role notification and push endpoints.
- Depends on: domain models and services, Django rendering/auth/signing/cache.
- Used by: `web/urls.py`.
- Constraint: every new view must apply the appropriate role decorator; role enforcement is per view.

**Domain services and pure rules:**
- Purpose: Centralize business invariants, transactions, reusable query/reduction logic, and state transitions.
- Location: `scheduling/`, `verification/`, `ops/`, `campus/services.py`
- Contains: scan resolvers, modality workflow, schedule operations, suspensions, merge propagation, availability/occupancy, reporting aggregates, notification/report orchestration, safe deletion probes.
- Depends on: lower domain models; pure modules depend only on passed values and stdlib.
- Used by: web views, management commands, other services.

**Persistence:**
- Purpose: Store identity, campus, academic, verification, and operational state.
- Location: `accounts/models.py`, `campus/models.py`, `scheduling/models.py`, `verification/models.py`, `ops/models.py`
- Depends on: Django ORM and string-referenced cross-app relations.
- Used by: all services, views, admin, commands.
- Database: SQL Server only through `mssql-django`; token columns use case-sensitive collation while ordinary identity data retains database-default comparison behavior.

**Server-rendered UI:**
- Purpose: Produce full pages and htmx fragments without a separate frontend build.
- Location: `templates/`, `static/`
- Contains: role directories, shared shells/partials, CSS, board/push/offline-queue JavaScript.
- Depends on: view contexts and named URL routes.

## Data Flow

### Faculty Physical Check-In

1. `/scan?t=...` or `/faculty/scan` enters `web/scan.py:deep_link`; POST `/scan/resolve` parses a QR token or rate-limited six-digit code in `web/scan.py:_room_from_payload`.
2. `web/scan.py:resolve` rejects out-of-service rooms, loads the faculty's local-date sessions and unreleased active occupant, and injects policy values into `scheduling/resolver.py:resolve_faculty_scan`.
3. The pure resolver returns a `Resolution`; destructive outcomes are serialized into a signed, user-bound, 180-second confirmation token.
4. `web/scan.py:_apply` mutates the session, propagates co-scheduled siblings through `scheduling/merge.py`, writes `AuditLog`, and fans operational notifications through `ops/notify.py`. Check-in and force-handover groups are transactional.
5. The response is rendered as `templates/faculty/_outcome.html`; minute-scoped cache keys prevent duplicate application.

### Checker Verification and Offline Replay

1. `web/checker.py` re-gates the user against active `verification.Assignment` records for FLOOR or ONLINE scope.
2. Room context becomes a `_SessionState`; `verification/resolver.py:resolve_checker_scan` decides whether the floor, assignment window, and current state permit an action.
3. `web/checker.py:_apply_action` writes `CheckerValidation`, updates session state when applicable, propagates merged outcomes, audits, and notifies via `ops.notify.notify()`.
4. `static/checker/offline_queue.js` retains offline scans; `/checker/replay` revalidates the original room/time context server-side before applying, so queued client data is not authority.

### Modality-Shift Approval

1. `web/faculty.py` gathers user input but `scheduling/services.py:submit_modality_shift` derives affected sessions, enforces policy lead time, checks faculty/time/room conflicts, routes to the active department Dean, and creates one request with item rows transactionally.
2. `web/dean.py` scopes the queue to the Dean's department and invokes `scheduling/services.py:apply_approval` or `reject_modality_shift`.
3. Approval re-locks and revalidates the pending request, resolves room reservations, updates current sessions and future materialization instructions, assigns online checkers where applicable, audits, and notifies.
4. `scheduling/management/commands/materialize_sessions.py` applies approved `ModalityShiftItem` instructions when future dated sessions are generated.

### Import Preview and Commit

1. `/ifo/import/preview` validates the upload and calls `ops/import_staging.py:stage_upload`; bytes stream to `default_storage`, ownership/lifecycle goes to `ImportStaging`, and only an opaque token goes into the Django session.
2. `web/ifo.py` runs the shared registrar import in dry-run mode and renders a preview.
3. `/ifo/import/commit` resolves the token by both owner and unconsumed state, invokes `scheduling/management/commands/import_offerings.py`, then marks the staging row consumed; discard and scheduler cleanup remove abandoned files.
4. Import parsing and classification live in `scheduling/importing.py` and `scheduling/xlsx.py`; room credentials come from `campus/codes.py`.

### Reporting and Utilization

1. Dean, HR, and IFO views derive date/department scope in `web/reporting_common.py` and their role module.
2. `scheduling/reporting.py` performs reusable ORM aggregates and pure reductions for attendance, lateness, verification coverage, scorecards, room utilization, heat grids, saturation, room breakdown, ghost rooms, and building/floor rollups.
3. Each dashboard card is isolated through `scheduling/reporting.py:safe_card`, preventing one failed aggregate from removing the whole page.
4. `scheduling/report_render.py` renders CSV/PDF bytes; web views stream on-demand responses, while `ops/reports.py` stores weekly artifacts under server-built names and creates recipient-scoped notifications.

### Background Jobs and Push

1. Exactly one dedicated `manage.py runscheduler` process constructs APScheduler jobs in `scheduling/management/commands/runscheduler.py`.
2. Each callable passes through `ops/jobrun.py:run_job`, which records running/ok/failed state and notifies System Admins on failure.
3. Jobs materialize sessions, sweep no-shows and contradictory occupancy (`scheduling/jobs.py`), generate weekly reports (`ops/reports.py`), drain the notification push outbox (`ops/push.py`), and clear abandoned import staging.
4. `web/sys.py:jobs` reads `JobRun`; the web workers never start schedulers or synchronously call external push endpoints.

**State Management:**
- Durable state is in SQL Server models; uploaded/report bytes use Django `default_storage` under `MEDIA_ROOT` in the configured runtime.
- Authentication uses Django database sessions. Transient rate limits/idempotency use Django cache; confirmation state uses signed tokens.
- UI state is server-derived. The Checker offline queue is the sole durable browser-side workflow state and is re-authorized on replay.

## Key Abstractions

**Recurring schedule versus dated session:**
- Purpose: Separate registrar intent from the occurrence whose attendance and occupancy changes.
- Examples: `scheduling/models.py:Schedule`, `scheduling/models.py:Session`, `scheduling/management/commands/materialize_sessions.py`.
- Pattern: edit/cancel recurring definitions through `scheduling/schedule_ops.py`; apply attendance and room effects to dated sessions.

**Pure resolver plus side-effect applier:**
- Purpose: Make policy decisions deterministic and testable.
- Examples: `scheduling/resolver.py` with `web/scan.py:_apply`; `verification/resolver.py` with `web/checker.py:_apply_action`.
- Pattern: gather trusted server context, call pure decision code with an injected clock/policy, then apply one audited transition.

**Service-owned transactional workflow:**
- Purpose: Keep multi-model invariants independent of a specific HTML view.
- Examples: `scheduling/services.py`, `scheduling/suspensions.py`, `scheduling/schedule_ops.py`, `verification/services.py`.
- Pattern: re-gate inside `transaction.atomic()`, write model state and audit together, send notification after the durable decision.

**Notification outbox:**
- Purpose: Decouple in-app event creation from unreliable external push delivery.
- Examples: `ops/notify.py`, `ops/models.py:Notification`, `ops/push.py`, `web/notifications.py`.
- Pattern: create through `notify()` only; filtering/muting shares `ops/notifications.py`; scheduler stamps `pushed_at` after handling.

**Policy lookup:**
- Purpose: Allow operational tuning without code changes.
- Examples: `ops/policy.py:get_policy`, `ops/models.py:SystemSetting`, `config/settings.py:FLUXTRACK_POLICY`.
- Pattern: read the database override first and fall back to the configured default; never duplicate policy literals in callers.

## Entry Points

**HTTP:**
- Location: `config/urls.py`
- Triggers: WSGI/ASGI request.
- Responsibilities: Mount `/admin/`, `/auth/` social-auth callbacks, and `web.urls`; serve media only in DEBUG.

**Application routes:**
- Location: `web/urls.py`
- Triggers: all application paths.
- Responsibilities: Route faculty, scan, Dean, Checker, HR, IFO, Guard, System Admin, notification, push, and PWA endpoints.

**Authentication:**
- Location: `accounts/backends.py`, `accounts/pipeline.py`, `config/settings.py`
- Triggers: `/auth/login/azuread-tenant-oauth2/` and OAuth callback.
- Responsibilities: PKCE Entra exchange, associate only pre-provisioned users, persist Azure object ID, retain Django `ModelBackend` for break-glass/local behavior.

**CLI and jobs:**
- Location: `manage.py`, `scheduling/management/commands/`, `accounts/management/commands/`
- Triggers: operator or dedicated service.
- Responsibilities: migrate/seed/import/materialize/reset, generate reports, audit merges, assign online duties, one-shot sweep, long-running scheduler.

## Architectural Constraints

- **Process model:** Synchronous Django web workers plus exactly one independent APScheduler process; do not initialize scheduling inside WSGI/ASGI workers.
- **Database:** SQL Server semantics matter. Avoid SQLite-specific assumptions and materialize querysets before nested writes where pyodbc streaming cursors can raise `HY010`.
- **Dependency direction:** `campus` is the lowest spatial domain. `campus/services.py` must not import upward into scheduling/verification/ops; inspect reverse relations instead.
- **Authorization:** Role checks are decorators in each `web/*.py` module and data scope is query-level. There is no global RBAC middleware, so omission on a new route is a security defect.
- **Audit:** `AuditLog` coverage is explicit. Any new write path must add its audit event in the same workflow.
- **Time:** Operational decisions use aware datetimes and `timezone.localdate()` under `Asia/Manila`; weekly and attendance scopes use local `Session.date`.
- **Storage:** Client filenames are display data only. Build paths server-side and access files through `default_storage`.
- **Global state:** Django settings and default cache are global configuration; no application-owned mutable singleton is used. LocMemCache remains process-local, so do not store cross-request durable workflow data there.
- **Circular imports:** Cross-app model relations use string references. Services sometimes use narrow local imports (for example report recipients) to avoid module cycles; preserve that direction.

## Anti-Patterns

### Business Logic in Templates or JavaScript

**What happens:** A client computes role authority, attendance status, availability, or report truth.
**Why it's wrong:** Offline and htmx requests can be replayed or forged, and parallel surfaces drift from scheduler/report rules.
**Do this instead:** Keep the decision in `scheduling/resolver.py`, `verification/resolver.py`, `scheduling/services.py`, or `scheduling/reporting.py`; treat `static/checker/offline_queue.js` as a queue whose entries are revalidated by `web/checker.py`.

### Direct Notification Writes

**What happens:** Code creates `ops.models.Notification` directly.
**Why it's wrong:** Recipient expansion, muting categories, in-app visibility, and push-outbox behavior can diverge.
**Do this instead:** Call `ops/notify.py:notify` and define shared notification semantics in `ops/notifications.py`.

### Mutating a Schedule to Record One Occurrence

**What happens:** Attendance, room release, or a one-day exception is written to `Schedule`.
**Why it's wrong:** `Schedule` is recurring intent and would alter unrelated dates.
**Do this instead:** mutate `Session` through `web/scan.py`, `ops/occupancy.py`, `scheduling/suspensions.py`, or the relevant service; reserve `scheduling/schedule_ops.py` for recurring changes.

### Starting Jobs in Web Workers

**What happens:** APScheduler or external push delivery runs during app startup/request handling.
**Why it's wrong:** Multi-worker deployment duplicates jobs and remote failures delay requests.
**Do this instead:** register work only in `scheduling/management/commands/runscheduler.py` and wrap it with `ops/jobrun.py:run_job`.

### Relying on ORM `on_delete` for Operator-Safe Deletion

**What happens:** A view calls `.delete()` and lets `PROTECT`, `CASCADE`, or `SET_NULL` determine user-visible behavior.
**Why it's wrong:** errors are unnamed and nullable reservation relations can lose meaning silently.
**Do this instead:** call `campus/services.py:room_delete_blockers`, `floor_delete_blockers`, or `building_delete_blockers` before deletion and render the specific blockers.

## Error Handling

**Strategy:** Expected business refusals are values or domain exceptions; unsafe/missing HTTP resources use Django responses; background failures become durable job status and operator notifications.

**Patterns:**
- Pure resolvers return named outcome dataclasses rather than raising (`scheduling/resolver.py`, `verification/resolver.py`).
- Services raise user-safe domain errors such as `ModalityShiftError` and `ImportStagingError`; views translate them into rendered validation failures.
- Invalid or expired confirmation/replay tokens return 400; missing scoped objects use 404; role decorators raise 403.
- Multi-row state changes use `transaction.atomic()` and re-check mutable state inside the transaction.
- Reporting pages isolate optional cards with `safe_card`; scheduler jobs catch at `run_job`, persist failure detail, and notify System Admins.
- Web-push delivery never raises into the scheduler loop and prunes only definitively expired endpoints.

## Cross-Cutting Concerns

**Logging:** Business and security events use `ops.models.AuditLog`; scheduled execution health uses `ops.models.JobRun`. Framework logging is not the operational source of truth.
**Validation:** Django views parse request shape, services recompute authority and domain constraints, pure resolvers decide outcomes, and storage paths/tokens are server-built.
**Authentication:** Django sessions with Microsoft Entra tenant OAuth2 + PKCE via `accounts/backends.py`; `accounts/pipeline.py` refuses automatic provisioning. `ModelBackend` remains configured for break-glass/local access.
**Authorization:** One role per `accounts.User`, per-view decorators, department/floor/assignment ownership filters, and superuser bypass where explicitly implemented.
**Notifications:** `ops.notify.notify()` creates rows; `ops/notifications.py` owns categories/mutes/visibility; `ops/push.py` drains key events asynchronously.
**Observability:** `/sys/jobs` reads durable `JobRun` rows; IFO conflict and notification surfaces expose operational exceptions.

---

*Architecture analysis: 2026-07-21*

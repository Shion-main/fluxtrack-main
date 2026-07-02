# Architecture

**Analysis Date:** 2026-07-02

## Pattern Overview

**Overall:** Server-rendered Django MVT (Model–View–Template) with htmx partials over a layered backend, built around a pure, side-effect-free resolver core.

FluxTrack is a single Django project. The Django backend is the system of record — it owns data, business rules, and authorization — and renders every interface server-side using Django templates. htmx progressively enhances those templates with partial updates and live-surface polling; Franken UI (Tailwind, CDN) supplies the component styling. There is no separate Node runtime, no SPA framework, and no client-issued API contract — auth is Django session-based throughout (`request.user`), not JWT (the SRS's §2.1 JWT language is unimplemented; see `docs/USE_CASES.md` AUTH divergence note).

**Key Characteristics:**
- One decision engine (`scheduling/resolver.py`) is a **pure function**: no DB queries, no writes, no clock reads. The web layer gathers context, calls it, and applies the returned outcome. This is the deliberate, tested (16 tests) central abstraction — see below.
- **Layered backend per the SRS §2.1 intent** (models → business rules → views), but implemented pragmatically: models and a resolver/policy "service" layer exist; DRF serializers are largely unused (server-rendered HTML, not a JSON API) though `rest_framework` is installed and configured for session auth.
- **Role gating is per-view, not middleware** — decorators (`faculty_required`, `ifo_required`) applied on each view function. There is no framework-level RBAC guarantee; every new surface must add its own check.
- **Every state-changing operation writes an `AuditLog` row** (`ops/models.py`) — auditing is a convention enforced in the side-effect layer, not a signal/middleware.
- **Configurable policy values** flow through one lookup (`ops/policy.py:get_policy`) reading `SystemSetting` rows with fallback to `settings.FLUXTRACK_POLICY`.

## Layers

**Domain models (system of record):**
- Purpose: Own all persistent data, choices/enums, and derived properties.
- Location: `accounts/models.py`, `campus/models.py`, `scheduling/models.py`, `verification/models.py`, `ops/models.py`
- Contains: `User` (7-role RBAC) + `Department`; `Building`/`Floor`/`Room`; `AcademicTerm`/`AcademicBreak`/`Schedule`/`Session`; `Assignment`/`CheckerValidation`; `Booking`/`Notification`/`PushSubscription`/`AuditLog`/`SystemSetting`/`WeeklyReport`.
- Depends on: Django ORM only.
- Used by: resolver (reads model instances), web views, management commands, admin.
- Note: some models carry fields for unbuilt features (e.g. `Session.teams_link`, `declared_modality`, `code_rotated_at`) — scaffolding ahead of surfaces.

**Resolver core (pure business rules):**
- Purpose: Decide the outcome of a faculty scan. No side effects.
- Location: `scheduling/resolver.py`
- Contains: `resolve_faculty_scan(...)` and the `Resolution` dataclass; outcome constants (`CHECKED_IN`, `ABSENT`, `WRONG_ROOM`, `ROOM_OCCUPIED`, `EARLY_END`, `TOO_EARLY`, `ONLINE_REJECT`, `NO_SCHEDULE`, `CHECKED_OUT`); the `CONFIRM_OUTCOMES` set.
- Depends on: nothing but stdlib (`dataclasses`, `datetime`). Receives pre-fetched sessions, ids, and `now` as arguments — never touches the ORM or `timezone.now()`.
- Used by: `web/scan.py` only.
- Tested by: `scheduling/tests.py` (16 tests) in isolation, no DB fixtures needed for the decision logic.

**Policy layer:**
- Purpose: Single source for tunable operational values (grace window, room hold, rate limits, poll interval).
- Location: `ops/policy.py:get_policy`
- Pattern: `SystemSetting` row (int-coerced) overrides `settings.FLUXTRACK_POLICY` default. Editable today via Django admin only.

**Web / presentation layer (views + side effects):**
- Purpose: Fetch context, gate by role, call resolver/policy, apply state changes, render templates.
- Location: `web/views.py` (dev-login, role-routed home, PWA shell), `web/faculty.py`, `web/ifo.py`, `web/scan.py`
- Depends on: all domain models, resolver, policy, Django auth/signing/cache.
- Used by: URL router (`web/urls.py`).

**Templates (server-rendered UI + htmx):**
- Location: `templates/` — `base.html` shell, `web/`, `faculty/`, `ifo/` surface dirs.
- Pattern: full-page templates plus `_`-prefixed partials returned to htmx swaps (`_outcome.html`, `_live_rows.html`).

**Batch / jobs layer (management commands):**
- Location: `scheduling/management/commands/import_offerings.py`, `materialize_sessions.py`, `accounts/management/commands/seed_demo.py`
- Note: run manually today; no scheduler process wired (JOB-01/02/03 per `docs/USE_CASES.md`).

## Data Flow

**Faculty scan → check-in (the core closed loop):**

1. Faculty hits `web/scan.py:deep_link` via QR (`/scan?t=TOKEN`, `@login_required` bounces anonymous users through sign-in and back) or opens the scan page and submits a manual 6-digit code.
2. POST lands on `web/scan.py:resolve`. `_room_from_payload` parses the payload: QR token → `Room` by `qr_token`; 6-digit code → rate-limit check via `cache` + `get_policy("manual_code_rate_limit_per_min")`, then `Room` by `manual_code`. A bad/rate-limited payload short-circuits to an error outcome (and an `AuditLog` row for rate-limit/bad-code).
3. `resolve` gathers **context**: today's `Session`s for this faculty (`select_related`), and any other faculty's ACTIVE session occupying the scanned room.
4. It calls the **pure** `resolver.resolve_faculty_scan(sessions_today, room.pk, occupying, now, grace_min=..., early_end_min=...)` with policy values injected. Returns a `Resolution(outcome, session_id, prior_session_id, needs_confirm)`.
5. **Branch on `needs_confirm`:**
   - Two-step outcomes (`wrong-room`, `room-occupied`, `early-end`): `resolve` signs the resolution into a `confirm_token` (`django.core.signing.dumps`, salt `fluxtrack.scan.confirm`, 180s max age, bound to `user_id`) and renders `faculty/_outcome.html` with a confirm form. No state change yet.
   - One-step outcomes: idempotency guard (`cache` key `scan-idem:user:session:minute`) prevents re-apply, then `_apply` runs.
6. On confirm, POST hits `web/scan.py:confirm`: it `signing.loads` the token (rejects expired/wrong-user), rebuilds the `Resolution`, and calls `_apply` with the supplied `reason`.
7. `_apply` performs **all side effects**: mutates the `Session` (status, `actual_start`/`actual_end`, `checkin_method`, handover linkage, etc.), writes an `AuditLog` row via the local `audit()` helper, and for wrong-room / force-handover calls `_notify_ifo` to create a `Notification` per active IFO Admin.
8. `faculty/_outcome.html` partial is returned to the htmx swap.

**Live monitoring flow (IFO):**
`ifo/live.html` polls `/ifo/live/rows` every `poll_interval_seconds` (from policy) → `web/ifo.py:live_rows` renders `ifo/_live_rows.html` with today's sessions. Polling, not websockets (SRS §2.1).

**State Management:**
- Server-side only. Session state lives in the `Session` model; auth in Django sessions; transient scan state (rate-limit counters, idempotency keys, two-step confirmations) in the cache and in signed tokens. No client-side store.

## Key Abstractions

**Pure resolver + side-effect applier (the central pattern):**
- Purpose: Separate the *decision* (what outcome does this scan produce?) from the *effect* (mutate DB, audit, notify). The decision is deterministic and unit-testable without a database; the effect is thin and imperative.
- Examples: `scheduling/resolver.py:resolve_faculty_scan` (decision) vs. `web/scan.py:_apply` (effect).
- Pattern: web layer fetches context → calls pure function with injected policy + `now` → applies returned `Resolution`. The SRS names reporting aggregates as the next code to follow this same shape (`docs/USE_CASES.md` RPT-05).

**Two-step signed confirmation:**
- Purpose: Outcomes that overwrite others' data (room change, force handover, early end) require an explicit second action, tamper-proof and user-bound.
- Examples: `web/scan.py:resolve` (signs) / `confirm` (verifies + applies), constants `CONFIRM_SALT`, `CONFIRM_MAX_AGE`.
- Pattern: `django.core.signing` round-trip carrying the full resolution; nothing persists until confirm.

**Policy lookup with fallback:**
- Purpose: Runtime-tunable operational values without redeploy.
- Examples: `ops/policy.py:get_policy`, defaults in `config/settings.py:FLUXTRACK_POLICY`, overrides in `ops.SystemSetting`.

**Per-role decorators:**
- Purpose: Server-side role/data scoping (AUTH-04).
- Examples: `web/faculty.py:faculty_required`, `web/ifo.py:ifo_required`. Both wrap `@login_required`, allow superusers, and raise `PermissionDenied` otherwise. New roles (checker/guard/dean/hr) each need their own equivalent.

**AuditLog-on-every-write:**
- Purpose: Immutable trail of all state changes (SYS-03, §6.2).
- Examples: `ops/models.py:AuditLog`; the `audit()` closure and rate-limit/bad-code logging in `web/scan.py`.
- Pattern: create an `AuditLog(actor, event_type, target_type, target_id, payload)` alongside each mutation. Convention, not enforced by signals.

## Entry Points

**HTTP root:**
- Location: `config/urls.py` → mounts `admin/` and delegates everything else to `web.urls` via `include("web.urls")`. Serves media in DEBUG.
- Triggers: all web requests.

**Application URL map:**
- Location: `web/urls.py`
- Responsibilities: routes home/login/logout, the scan trio (`/scan`, `/scan/resolve`, `/scan/confirm`), faculty surfaces, IFO surfaces, and the PWA shell (`manifest.webmanifest`, `sw.js`, generated icons).

**WSGI/ASGI:**
- Location: `config/wsgi.py`, `config/asgi.py` (WSGI is the deployment target).

**Management commands (batch entry):**
- Location: `scheduling/management/commands/` (`import_offerings`, `materialize_sessions`), `accounts/management/commands/seed_demo`.

**Dev-login stub:**
- Location: `web/views.py:login_view` — DEBUG-only, signs in any seeded user by username, no password. Explicitly a stand-in for Entra ID SSO (AUTH-01/02), not a security boundary.

## Error Handling

**Strategy:** Discrete outcomes over exceptions for scan flow; Django defaults elsewhere.

**Patterns:**
- Scan failures return a named outcome string rendered into `faculty/_outcome.html` (`bad-payload`, `rate-limited`, `no-schedule`, `too-early`, `online-reject`) — no exception, no state change.
- Two-step token failures return `HttpResponseBadRequest` (expired/invalid signature, wrong user).
- Role failures raise `PermissionDenied` (403) from the decorators.
- Missing objects use `get_object_or_404` in IFO views.
- Idempotency guard (`web/scan.py:resolve`) prevents duplicate application of the same outcome within a minute.

## Cross-Cutting Concerns

**Logging:** `AuditLog` model rows on every write (business audit). No separate application logging framework configured.
**Validation:** Payload shape validated in `_room_from_payload` (regex for 6-digit codes, URL parse for tokens); resolver encodes all scan business rules.
**Authentication:** Django session auth (`login()`/`request.user`), `LOGIN_URL=/login`. `User.is_active` gates the auth backend and dev-login. Entra ID SSO not yet wired.
**Authorization:** Per-view role decorators; superusers bypass. Room `qr_token`/`manual_code` are resolver-only, never rendered client-side.
**Policy/config:** `get_policy` + `SystemSetting` fallback to `FLUXTRACK_POLICY`.

---

*Architecture analysis: 2026-07-02*

# Coding Conventions

**Analysis Date:** 2026-07-02

FluxTrack is a solo-developed Django project (flat apps at repo root: `accounts/`,
`campus/`, `scheduling/`, `verification/`, `ops/`, `web/`). The conventions below
are the ones actually present in the code, not aspirational. Four are called out
explicitly as project rules in
`docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §3
(resolver stays pure, every write emits an `AuditLog`, policy via `get_policy()`,
management-command output is ASCII-only) — treat those as hard rules when adding code.

## Naming Patterns

**Files:**
- Django app modules use plain lowercase names (`models.py`, `admin.py`, `views.py`).
- The `web/` app splits views by role/surface into separate modules rather than one
  fat `views.py`: `web/faculty.py`, `web/ifo.py`, `web/scan.py`, `web/views.py`.
  New role surfaces (Checker, HR, Dean, Guard) should follow this — one module per
  surface, wired in `web/urls.py`.
- htmx partial templates are prefixed with an underscore: `templates/faculty/_outcome.html`,
  `templates/ifo/_live_rows.html`. Full-page templates are not: `templates/ifo/rooms.html`.

**Functions:**
- `snake_case` for all functions and view callables (`resolve_faculty_scan`, `room_detail`,
  `live_rows`).
- Private/module-internal helpers are prefixed with a single underscore:
  `_room_from_payload`, `_apply`, `_notify_ifo` (`web/scan.py`); `_today_sessions`,
  `_deep_link` (`web/ifo.py`); `_login_ctx` (`web/views.py`); `_report` (`import_offerings.py`).
- Role-guard decorators are named `<role>_required`: `faculty_required` (`web/faculty.py:14`),
  `ifo_required` (`web/ifo.py:18`).

**Variables:**
- `snake_case` locals. Short, conventional loop names are used freely (`s` for a session,
  `r` for a room, `d` for a date, `o` for parsed command options).

**Types / Classes:**
- `PascalCase` (`Resolution`, `FakeSession`, `AuditLog`, `SystemSetting`).
- Enumerations use Django `TextChoices` / `IntegerChoices` with `UPPER_SNAKE` members and
  a `(value, label)` pair: `Modality`, `SessionStatus`, `CheckinMethod`
  (`scheduling/models.py:6,70,77`), `Role` (`accounts/models.py:14`),
  `DayOfWeek` as `IntegerChoices` (`scheduling/models.py:12`). Never hand-roll status
  strings — reference the choices class.

**Constants:**
- Module-level `UPPER_SNAKE`. The resolver defines outcome identifiers as module constants
  (`CHECKED_IN`, `WRONG_ROOM`, … `scheduling/resolver.py:14-22`) and a
  `CONFIRM_OUTCOMES` set. `web/scan.py` defines `CONFIRM_SALT`, `CONFIRM_MAX_AGE`.
  Callers reference `R.CHECKED_IN` etc. rather than the bare string.

## Code Style

**Formatting:**
- No autoformatter or linter is configured (no `.eslintrc`, `.prettierrc`, `pyproject.toml`,
  `setup.cfg`, `tox.ini`, `.flake8` present). Style is maintained by hand.
- 4-space indentation, roughly 90–100 column soft wrap. Continuation lines align under the
  opening delimiter (see the multi-line `Session.objects.filter(...)` chains in `web/scan.py`).

**Docstrings — the strongest convention in the codebase:**
- Every module opens with a one-line-to-paragraph docstring that names the SRS requirement
  ID(s) it implements. Examples:
  - `"""Scan endpoints (SCAN-01..07): payload lookup, rate limiting, idempotency, …"""` (`web/scan.py:1`)
  - `"""Faculty surfaces (mobile-first, §2.5): today/week schedule (FAC-01) and check-in."""` (`web/faculty.py:1`)
  - `"""Operations: bookings, notifications, push, audit, settings, reports (SRS §5)."""` (`ops/models.py:1`)
- Requirement tags (`SCAN-04`, `FAC-06`, `IFO-01`, `§6.6`, `JOB-01`) are threaded through
  inline comments too, tying code back to `FluxTrack_SRS.md`. Preserve this — it is how the
  code stays traceable to the spec. When adding a function that implements a requirement,
  cite the requirement ID.

## Import Organization

Three groups, blank-line separated, alphabetical within group (standard Django layout):

1. Standard library (`import re`, `from datetime import timedelta`, `from functools import wraps`)
2. Django / third-party (`from django.contrib.auth.decorators import login_required`,
   `from django.core import signing`)
3. Local apps (`from accounts.models import Role`, `from ops.policy import get_policy`,
   `from scheduling import resolver as R`)

- The resolver is conventionally imported aliased as `R` (`from scheduling import resolver as R`)
  so call sites read `R.resolve_faculty_scan(...)`, `R.CHECKED_IN` (`web/scan.py:23`,
  `scheduling/tests.py:7`).
- No path aliases (plain Django absolute app imports). No barrel/`__init__` re-exports;
  app `__init__.py` files are empty.

## Established Patterns (project rules — do not violate)

**1. Pure resolver (`scheduling/resolver.py`).**
The scan decision logic is a pure function: no ORM queries, no `save()`, no `timezone.now()`
inside it — `now` and all policy values are passed in as arguments
(`resolve_faculty_scan(sessions_today, scanned_room_id, occupying_session_id, now, *, grace_min, early_end_min, open_min=15)`).
It returns a `Resolution` dataclass, never mutates anything, never raises for business outcomes.
The web layer (`web/scan.py`) does all fetching and all writing. Keep it this way; planned
reporting aggregates (RPT-05, SRS §6.6) are to follow the same pure-function shape.

**2. `AuditLog` row on every state change.**
Every write in `web/scan.py._apply` is paired with an `audit(...)` call
(`session.checked_in`, `session.marked_absent`, `session.checked_out`, `session.ended_early`,
`session.room_changed`, `session.force_handover`). Even non-mutating rejections that matter for
security are logged (`scan.rate_limited`, `scan.bad_manual_code` in `_room_from_payload`).
`AuditLog` (`ops/models.py:56`) fields: `actor`, `event_type` (dotted `noun.verb`),
`target_type`, `target_id`, `payload` (JSON). New write paths must emit one.

**3. Policy via `get_policy()` / `SystemSetting` — never hardcode.**
Tunable values come from `get_policy("grace_minutes")` etc.
(`ops/policy.py:7`), which reads a `SystemSetting` row and falls back to
`settings.FLUXTRACK_POLICY` (`config/settings.py:136-144`). Call sites:
`web/scan.py:153-154` (`grace_minutes`, `early_end_threshold_minutes`),
`web/scan.py:46` (`manual_code_rate_limit_per_min`). Templates/views that need the poll
interval read `settings.FLUXTRACK_POLICY["poll_interval_seconds"]` (`web/ifo.py:64`).
Do not introduce magic numbers for grace windows, rate limits, horizons, or poll intervals.

**4. Management commands print ASCII only (Windows console is cp1252).**
Command output uses `self.stdout.write(self.style.SUCCESS(...))` / `self.style.ERROR(...)`
and ASCII arrows `->` instead of Unicode (`materialize_sessions.py:64`, and the docstrings/
comments in `import_offerings.py` use `->`). Avoid emoji and box-drawing characters in command
output. See `scheduling/management/commands/materialize_sessions.py`,
`.../import_offerings.py`, `accounts/management/commands/seed_demo.py`.

**5. Per-view role decorators.**
Authorization is a stacked decorator, not middleware. `faculty_required` / `ifo_required`
wrap `@login_required` and raise `PermissionDenied` on role mismatch (superuser bypasses):

```python
def ifo_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.IFO_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```

State-changing scan endpoints additionally stack `@require_http_methods(["POST"])`
(`web/scan.py:135-136,175-176`). New role surfaces get their own `<role>_required` decorator.

**6. Two-step confirmation via signed tokens.**
Outcomes in `CONFIRM_OUTCOMES` (`wrong-room`, `room-occupied`, `early-end`) are not applied on
first scan. `resolve` signs the resolution with `django.core.signing.dumps(..., salt=CONFIRM_SALT)`
(`web/scan.py:159`); `confirm` verifies with `signing.loads(..., salt=CONFIRM_SALT,
max_age=CONFIRM_MAX_AGE)` and re-checks `user_id` ownership before calling `_apply`
(`web/scan.py:177-192`). Use signed tokens (not session state) for any deferred confirm flow.

**7. Rate limiting + idempotency via Django cache (locmem).**
Manual-code entry is rate-limited per user-per-minute with a cache counter
(`cache.get_or_set` / `cache.incr`, `web/scan.py:44-52`). Applied outcomes are made idempotent
per `user:session:minute` key so a double-tap does not re-apply (`web/scan.py:165-171`). No
Redis — Django's default locmem cache backs both.

## Query Conventions

- Always `select_related(...)` for foreign keys touched in templates/loops to avoid N+1:
  `web/ifo.py:29-30`, `web/scan.py:146-147`, `web/faculty.py:29-30`.
- Read a single row with `.first()` and handle `None` explicitly (`web/scan.py:40,53,148`);
  use `get_object_or_404` for URL-addressed detail views (`web/ifo.py:49,83,92`).
- Order querysets explicitly (`.order_by("scheduled_start")`); models also set `Meta.ordering`.

## Error Handling

**Business outcomes are values, not exceptions.**
The resolver enumerates nine discrete outcomes (`scheduling/resolver.py:14-22`) and always
returns a `Resolution`; `needs_confirm` is a computed field set in `__post_init__` based on
membership in `CONFIRM_OUTCOMES`. Callers branch on `resolution.outcome`; the template
(`templates/faculty/_outcome.html`) is a flat `{% if/elif %}` chain over every outcome string,
each carrying a `data-outcome="..."` hook. There is no exception-based control flow for the
happy/edge paths.

**Exceptions reserved for hard faults:**
- Bad/expired signed token -> `HttpResponseBadRequest` (`web/scan.py:181-184`).
- Role mismatch -> `PermissionDenied` (the `_required` decorators).
- Malformed/absent input degrades to a rendered error partial rather than a 500:
  `_room_from_payload` returns `(None, "rate-limited" | "bad-payload")` and the view renders
  `_outcome.html` with `{"error": ...}` (`web/scan.py:140-142`), which the template maps to a
  friendly alert (`_outcome.html:1-10`).

**Graceful-degradation intent (planned, not yet built).**
SRS RPT-05 (`FluxTrack_SRS.md:339`) requires report aggregates to be pure, independently tested
functions that degrade gracefully — a single failed aggregate must not blank the page; available
sections render while failed sections show an error state. When reporting lands, each aggregate
should be isolated so one raising does not take down the whole report view.

## Logging

- No structured logging framework is configured. Management commands write to
  `self.stdout` / `self.stderr` via `self.style.*`.
- The durable record of "what happened" is the `AuditLog` table, not log files. Prefer an
  `AuditLog` row over a log line for anything security- or state-relevant.

## Comments

- Comment the *why*, not the *what*. Good examples: the service-worker cache notes on why `/`
  is never precached (`web/views.py:95-98,116-118`), and the idempotency/rate-limit rationale
  comments in `web/scan.py`.
- Section dividers use `# --- label ---` (`web/scan.py:30,62,134`; `web/ifo.py:73`).
- Tie non-obvious logic back to a requirement ID in the comment.

## Function & Module Design

- Functions stay small and single-purpose. `web/scan.py` decomposes the flow into
  `_room_from_payload` (input -> room), `resolve_faculty_scan` (decision), `_apply` (effects),
  `_notify_ifo` (side notification), and thin view callables that orchestrate them.
- Views return `render(request, template, ctx)`; htmx endpoints render the `_partial.html`,
  full navigations render the full-page template.
- No barrel files; import directly from the module that defines the symbol.

## Frontend Conventions

- Franken UI (Tailwind) is loaded from CDN in `templates/base.html:12-15`; htmx from CDN at
  `:16`. No Node build step.
- CSRF for htmx is set once globally via `hx-headers` on `<body>`:
  `hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'` (`templates/base.html:24`). Forms that
  POST also include `{% csrf_token %}` (`_outcome.html:63`).
- htmx partials target an element and swap `innerHTML`
  (`hx-post="/scan/confirm" hx-target="#outcome" hx-swap="innerHTML"`, `_outcome.html:62,81,102`).
- Live surfaces poll on the policy-driven interval rather than using websockets (`web/ifo.py:62-70`).
- UI classes use Franken UI's `uk-*` component classes plus Tailwind utilities.

---

*Convention analysis: 2026-07-02*

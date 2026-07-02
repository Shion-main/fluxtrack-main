# Architecture Research

**Domain:** Faculty attendance / facility utilization — subsequent milestone (integration into an existing layered Django MVT + htmx system)
**Researched:** 2026-07-02
**Confidence:** HIGH (grounded in the mapped codebase and the three approved design specs under `docs/superpowers/specs/`, not training-data inference)

> Scope note: The existing architecture is already mapped in `.planning/codebase/ARCHITECTURE.md` (pure resolver core + side-effect applier, per-view role decorators, `AuditLog` on every write, `get_policy()` lookup, htmx `_partial.html` swaps). This document does **not** re-derive it. It answers: *how do the new/unbuilt components fit that architecture and its conventions?* Every recommendation extends an existing precedent rather than introducing a novel pattern.

## Standard Architecture

### System Overview

New components (marked `NEW`) layered onto the existing structure. The existing pure-resolver / side-effect-applier split is replicated for every new decision surface.

```
┌──────────────────────────────────────────────────────────────────────┐
│  ENTRY PROCESSES (two OS processes, one EC2 instance)                  │
├────────────────────────────────┬─────────────────────────────────────┤
│  Gunicorn (web workers ×N)      │  APScheduler service (exactly 1)     │
│  web/*.py views                 │  NEW config/scheduler.py bootstrap   │
│   scan · faculty · ifo          │   → registers JOB-01/02/03 triggers  │
│   NEW dean · checker · guard·hr │                                      │
└───────────────┬─────────────────┴──────────────────┬──────────────────┘
                │  (both call the SAME service layer)  │
┌───────────────┴──────────────────────────────────────┴────────────────┐
│  PURE DECISION LAYER (no ORM, no clock, no writes — unit-testable)      │
│  ┌────────────────┐ ┌────────────────────┐ ┌───────────────────────┐   │
│  │ resolver.py    │ │ NEW sweep.py       │ │ NEW modality.py       │   │
│  │ (exists, 16 t) │ │ plan_status_sweep()│ │ eligibility / lead    │   │
│  └────────────────┘ └────────────────────┘ └───────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ NEW ops/reports.py — pure aggregate fns (RPT-05 §6.6), isolated   │ │
│  └──────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│  APPLIER / SERVICE LAYER (does ORM writes + AuditLog + notify)          │
│  ┌───────────────────┐ ┌──────────────────────┐ ┌───────────────────┐  │
│  │ scan.py:_apply    │ │ NEW jobs.py appliers │ │ NEW occupancy     │  │
│  │ (exists)          │ │ run_status_sweep()   │ │ release_room()    │  │
│  │                   │ │ generate_weekly...() │ │ is_room_free()    │  │
│  └───────────────────┘ └──────────────────────┘ └───────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ NEW ops/notifications.py — notify() single write path + web push  │ │
│  └──────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│  POLICY: ops/policy.py get_policy()   │  AUDIT: ops/models.py AuditLog  │
├────────────────────────────────────────────────────────────────────────┤
│  DOMAIN MODELS (system of record)                                      │
│  scheduling: Session (room_released_at ·) + NEW ModalityShiftRequest    │
│  ops: Notification · PushSubscription · WeeklyReport · SystemSetting    │
│  verification: Assignment · CheckerValidation                           │
└────────────────────────────────────────────────────────────────────────┘
```

The one hard structural rule that shapes everything: **the scheduler is a separate process, so any logic a job needs must live in an importable module that both the web layer and the job layer call — never inside a view function and never inside a management command's `handle()`.**

### Component Responsibilities

| Component | Responsibility | Location (new unless noted) | Follows precedent |
|-----------|----------------|------------------------------|-------------------|
| Scheduler bootstrap | `django.setup()`, register JOB-01/02/03 cron triggers, block | `config/scheduler.py` (or `ops/scheduler.py`) | — (new infra) |
| JOB-01 logic | Materialize sessions from schedules | extract to `scheduling/jobs.py:materialize_sessions()` from existing command | resolver "logic in module" |
| JOB-02 decision | Decide no-shows / room releases / conflicts (pure) | `scheduling/sweep.py:plan_status_sweep()` | `resolver.resolve_faculty_scan` |
| JOB-02 applier | Apply the sweep plan: write status/`room_released_at`, audit, notify | `scheduling/jobs.py:run_status_sweep()` | `scan.py:_apply` |
| JOB-03 report | Build + persist `WeeklyReport`, notify IFO + Deans | `ops/jobs.py:generate_weekly_reports()` | `_apply` + aggregates |
| Notify service | Single write path for `Notification` rows + web push | `ops/notifications.py:notify()` | generalizes `scan.py:_notify_ifo` |
| Report aggregates | Pure, isolated attendance/utilization aggregates | `ops/reports.py` | resolver / RPT-05 §6.6 |
| Modality state machine | Validate lead time, transition request, auto room-release/assign | `scheduling/modality.py` + `ModalityShiftRequest` model | resolver + `_apply` |
| Occupancy helper | Consistent `release_room()` write + `is_room_free()` read | `scheduling/occupancy.py` | `_apply` (write) / policy (read) |
| Dean surface | Dashboard + dept-scoped reporting (DEAN-04/01-03) | `web/dean.py` + `templates/dean/` | `web/ifo.py` + `ifo_required` |

## Recommended Project Structure

New files only; the flat-app layout is fixed (deployment design §Context — no folder reorg).

```
config/
└── scheduler.py            # NEW APScheduler entry (systemd runs this); django.setup() + triggers

scheduling/
├── resolver.py             # EXISTS — pure scan decision (unchanged)
├── sweep.py                # NEW pure JOB-02 planner: plan_status_sweep(sessions, now, *, policy)
├── occupancy.py            # NEW release_room() applier + is_room_free()/find_free_room() reads
├── modality.py             # NEW eligibility (pure) + approve_request() applier (state machine)
├── jobs.py                 # NEW job appliers: materialize_sessions(), run_status_sweep()
├── models.py               # EXTEND — add ModalityShiftRequest; JOB-01 online room_released_at patch
├── tests.py                # EXTEND — sweep planner + modality eligibility unit tests (no DB)
└── management/commands/
    ├── materialize_sessions.py  # EXISTS — thin wrapper now calling jobs.materialize_sessions()
    └── run_status_sweep.py      # NEW thin CLI wrapper calling jobs.run_status_sweep()

ops/
├── notifications.py        # NEW notify(users,...) / notify_ifo() / notify_deans() + push dispatch
├── reports.py              # NEW pure aggregate functions (IFO-09 / RPT-04 / DEAN-04 / JOB-03 share)
├── jobs.py                 # NEW generate_weekly_reports() applier (JOB-03)
└── policy.py               # EXISTS — add modality_shift_lead_days / room_hold_minutes defaults

web/
├── scan.py                 # EXTEND — replace private _notify_ifo with ops.notifications.notify_ifo
├── dean.py                 # NEW dean_required decorator + dashboard + dept reports (DEAN-04)
├── notifications.py        # NEW in-app list (NOTIF-01) + push subscribe + mute prefs (NOTIF-03)
├── checker.py / guard.py / hr.py   # NEW role surfaces (out of this doc's core scope)
└── reporting.py            # NEW RPT surfaces calling ops/reports.py aggregates
```

### Structure Rationale

- **`scheduling/sweep.py`, `modality.py` sit beside `resolver.py`:** all three are the academic-time decision engines. Keeping them together makes the "pure decision" layer discoverable and testable as one unit in `scheduling/tests.py` (mirrors the existing 16-test module).
- **`ops/` gets the cross-cutting services (`notifications.py`, `reports.py`, `jobs.py`):** `ops` already owns `Notification`, `PushSubscription`, `WeeklyReport`, `AuditLog`, `SystemSetting`, and `policy.py`. Cross-cutting operational services belong with their models, exactly as `policy.py` lives with `SystemSetting`.
- **`config/scheduler.py`:** the scheduler is project glue (like `wsgi.py`/`asgi.py`), not domain logic — it only wires triggers to imported job functions.
- **Occupancy in `scheduling/`, not `campus/`:** release state is a property of a `Session`'s lifecycle (`room_released_at` lives on `Session`), so the helper that stamps it belongs where sessions do.

## Architectural Patterns

### Pattern 1: Pure planner + thin applier (extend the resolver precedent to JOB-02)

**What:** Split every new stateful job the way scan is split — a pure function decides *what should happen*, a thin applier *does it* (ORM writes + `AuditLog` + notify). The planner takes pre-fetched rows, an injected `now`, and injected policy values; returns a list of intended actions; touches no ORM, no clock, no `save()`.

**When to use:** JOB-02 status sweep (Q2) — mark no-shows Absent, release rooms after hold, raise conflict flags. Also modality eligibility (Q5).

**Trade-offs:** One extra module and a small dataclass per decision surface, in exchange for DB-free unit tests and a single place where the rule lives. This is already the project's central abstraction — the cost was accepted for the resolver.

**Critical integration constraint:** The sweep's Absent rule *must* match the resolver's (`now > scheduled_start + grace`), or a scan and the sweep will disagree about the same session. Extract the shared predicate (e.g. `resolver.is_absent(session, now, grace)`) and have both call it. This is the single highest-risk coupling in the milestone.

```python
# scheduling/sweep.py — pure, mirrors resolver.py exactly
from dataclasses import dataclass

MARK_ABSENT = "mark-absent"
RELEASE_ROOM = "release-room"
FLAG_CONFLICT = "flag-conflict"

@dataclass
class SweepAction:
    kind: str
    session_id: int
    detail: dict

def plan_status_sweep(sessions, now, *, grace_min, room_hold_min):
    """sessions: pre-fetched candidate Sessions. No ORM, no timezone.now(), no writes."""
    actions = []
    for s in sessions:
        # reuse the resolver's absent threshold — do NOT re-derive it here
        if s.status == "scheduled" and now > s.scheduled_start + timedelta(minutes=grace_min):
            actions.append(SweepAction(MARK_ABSENT, s.id, {}))
        # room releases room_hold_min after end (or after absent determination)
        if s.room_released_at is None and now > s.scheduled_end + timedelta(minutes=room_hold_min):
            actions.append(SweepAction(RELEASE_ROOM, s.id, {}))
        ...
    return actions
```

```python
# scheduling/jobs.py — thin applier, mirrors scan.py:_apply (writes + AuditLog + notify)
def run_status_sweep():
    now = timezone.now()
    candidates = Session.objects.filter(date=timezone.localdate()).select_related("schedule", "room")
    plan = plan_status_sweep(list(candidates), now,
                             grace_min=get_policy("grace_minutes"),
                             room_hold_min=get_policy("room_hold_minutes"))
    for a in plan:
        s = ...  # apply mutation
        AuditLog.objects.create(actor=None, event_type=f"session.{a.kind}", ...)  # system actor
        if a.kind == FLAG_CONFLICT:
            notify_ifo("Room conflict", ...)   # via ops/notifications.py
```

### Pattern 2: One scheduler process, jobs as imported functions (Q1)

**What:** A single dedicated APScheduler process (second systemd service, deployment design §2) runs `config/scheduler.py`, which calls `django.setup()` then registers `BlockingScheduler` cron jobs that import and call `scheduling/jobs.py` / `ops/jobs.py` functions. The management commands become thin CLI wrappers calling the *same* functions.

**When to use:** All three jobs. JOB-01 already exists as a command — refactor its `handle()` body into `scheduling/jobs.py:materialize_sessions()` so the command and the scheduler share one implementation (no logic duplication).

**Trade-offs vs. `call_command`:** The scheduler *could* invoke `call_command("materialize_sessions")`, which avoids refactoring, but that re-parses args, prints to stdout, and can't return structured results. Extracting to a plain function is cleaner and is what the modality feature needs anyway (it patches JOB-01's Session-creation logic — Q5 — which must be reachable outside a command).

**Duplicate-execution avoidance (the actual risk):** Do **not** start APScheduler in an `AppConfig.ready()` — Gunicorn forks N workers, so that yields N schedulers and every job fires N times. The dedicated process guarantees exactly one scheduler. Additionally set `max_instances=1` + `coalesce=True` per job, and because these jobs are idempotent (JOB-01 uses `get_or_create`; JOB-02/03 should be written idempotently by keying on session/status/week), an accidental overlap self-heals.

```python
# config/scheduler.py — systemd ExecStart target
import django; django.setup()   # after DJANGO_SETTINGS_MODULE is set
from apscheduler.schedulers.blocking import BlockingScheduler
from scheduling.jobs import materialize_sessions, run_status_sweep
from ops.jobs import generate_weekly_reports

sched = BlockingScheduler(timezone="Asia/Manila")
sched.add_job(materialize_sessions, "cron", hour=1, max_instances=1, coalesce=True)   # JOB-01
sched.add_job(run_status_sweep, "cron", minute="*/5", max_instances=1, coalesce=True) # JOB-02
sched.add_job(generate_weekly_reports, "cron", day_of_week="mon", hour=2)             # JOB-03
sched.start()
```

### Pattern 3: Single notification write path (Q3)

**What:** Promote the private `web/scan.py:_notify_ifo` to a shared `ops/notifications.py:notify(users, type, title, body, link="")` that bulk-creates `Notification` rows and dispatches web push to each user's `PushSubscription` endpoints (VAPID), honoring mute prefs (NOTIF-03). Provide role-targeted convenience wrappers so every event uses one path.

**When to use:** Every notifier — scan (room change/handover), JOB-02 conflict flags, modality approval (IFO + faculty), JOB-03 (`RPT-02`: IFO **and** relevant Deans, per dean-dashboard design §2).

**Trade-offs:** Web push must be best-effort — a failed push (dead endpoint) must never break the caller (a scan, an approval, a job). Wrap push dispatch in try/except per subscription; the durable record is the `Notification` row, push is enhancement. Push dispatch runs fine from the scheduler process (it is just HTTPS to the push service).

```python
# ops/notifications.py — the ONE write path
def notify(users, *, type, title, body, link=""):
    rows = [Notification(user=u, type=type, title=title, body=body, link=link) for u in users]
    Notification.objects.bulk_create(rows)
    for u in users:                      # NOTIF-02 push, best-effort, mute-aware (NOTIF-03)
        _push_best_effort(u, title, body, link)

def notify_ifo(title, body, link=""):    # replaces scan.py:_notify_ifo verbatim in behavior
    notify(User.objects.filter(role=Role.IFO_ADMIN, is_active=True),
           type="room_event", title=title, body=body, link=link)

def notify_deans(department, title, body, link=""):
    notify(User.objects.filter(role=Role.DEAN, department=department, is_active=True), ...)
```

### Pattern 4: Isolated aggregate functions with graceful degradation (Q4)

**What:** Reporting aggregates live in `ops/reports.py` as independent functions, each taking a scope argument (`department=None` → all/IFO, a department → Dean) and returning a plain dict/list. Each is read-only (no writes, no `AuditLog`, no notify — that is the boundary that keeps them "pure" per RPT-05/§6.6). The *view* calls each aggregate inside its own try/except so one failing aggregate renders an error partial while the rest of the page renders (the graceful-degradation intent recorded in `CONVENTIONS.md`).

**When to use:** IFO-09 dashboard (`web/ifo.py`), Dean dashboard DEAN-04 (`web/dean.py`), RPT-04 faculty scorecard (`web/reporting.py`), and JOB-03 weekly report generation (`ops/jobs.py`) — all four call the same functions, differing only by scope.

**Trade-offs:** True "no-DB" purity is impossible for aggregates (they read the ORM). "Pure" here means deterministic-given-DB-state + no side effects; test them with small fixtures, and keep each independently callable so isolation at the view boundary is real.

```python
# ops/reports.py — read-only, scope-parameterized, independently testable
def attendance_summary(term, department=None):
    qs = Session.objects.filter(schedule__term=term)
    if department:
        qs = qs.filter(faculty__department=department)   # Dean scope reuses IFO logic
    ...
    return {"scheduled": ..., "held": ..., "absences": ..., "attendance_pct": ...}
```

```python
# web/dean.py — each aggregate isolated so one failure doesn't blank the page
def dashboard(request):
    cards = {}
    for name, fn in [("attendance", attendance_summary), ("scorecard", faculty_scorecard)]:
        try:    cards[name] = fn(term, department=request.user.department)
        except Exception:  cards[name] = {"error": True}
    return render(request, "dean/dashboard.html", {"cards": cards})
```

### Pattern 5: Modality state machine reusing `room_released_at` + occupancy helper (Q5, Q6)

**What:** `ModalityShiftRequest` (new model in `scheduling/models.py`) carries the state (`pending_dean → approved | dean_rejected`, withdraw-while-pending). `scheduling/modality.py` splits the logic: pure lead-time eligibility (`effective_date − now ≥ modality_shift_lead_days` via `get_policy`), a DB-reading `find_free_room()` for Online→F2F (narrow same-slot conflict check only — *not* a general booking system), and an `approve_request()` applier that transitions state, mutates affected Sessions, calls the shared `release_room()`, audits, and notifies (IFO + faculty).

**Reuse of `room_released_at`:** This feature is its first writer. F2F→Online approval stamps `room_released_at = approval time` (immediate release, not the `room_hold_minutes` timer). Online→F2F clears it (room now held) after `find_free_room()` assigns one; if none free, the approval **fails outright** (no partial apply). Recurring scope also updates `Schedule.modality`.

**Interaction with JOB-01 (materialize):** because JOB-01 logic is now a shared function (Pattern 2), patch it in one place — when materializing a Session from an already-Online Schedule, stamp `room_released_at` at creation (design §4), so future online sessions are born released rather than sitting forever unreleased.

### Pattern 6: Explicit, single-source room-release / occupancy (Q6)

**What:** Occupancy is currently implicit (derived at scan time via `Session.objects.filter(room, status=ACTIVE)`; `room_released_at` exists but is never written). Three writers will now manipulate release — JOB-02 sweep (release after hold), scan force-handover (completes prior session), modality approval (immediate release). Route all three through one applier so the stamp + audit are identical everywhere.

```python
# scheduling/occupancy.py
def release_room(session, when, *, reason, actor=None):
    """Single writer for room_released_at. Every releaser calls this — never sets the field inline."""
    session.room_released_at = when
    session.save(update_fields=["room_released_at"])
    AuditLog.objects.create(actor=actor, event_type="session.room_released",
                            target_type="session", target_id=str(session.pk),
                            payload={"reason": reason})

def is_room_free(room, at_dt, term):
    """Shared read predicate: no ACTIVE session, no held scheduled session, no conflicting booking.
    modality.find_free_room() and future IFO booking (IFO-05) both build on this."""
    ...
```

**Trade-offs:** A thin indirection, but it prevents the exact drift the modality-shift design was written to eliminate — "a room that was never expected to be held sits with an unset `room_released_at` and nothing ever sets it." One helper, one audit event, three consistent callers.

## Data Flow

### Job process flow (JOB-02, the representative case)

```
systemd timer / cron trigger (APScheduler process)
    ↓
config/scheduler.py  →  scheduling/jobs.py:run_status_sweep()
    ↓ fetch candidate Sessions (ORM)          ↓ get_policy(grace, room_hold)
    ↓
scheduling/sweep.py:plan_status_sweep(...)   ← PURE (no ORM/clock/writes)
    ↓ returns [SweepAction ...]
    ↓
applier loop:  Session.save()  +  AuditLog row  +  release_room()  +  notify_ifo(conflicts)
```

### Modality approval flow (Q5)

```
Faculty submits ModalityShiftRequest (web/faculty.py)
    ↓ scheduling/modality.py eligibility gate (lead days)  — reject if inside window
Dean opens queue (web/dean.py, dean_required) → approve
    ↓ scheduling/modality.py:approve_request()
    ├─ F2F→Online:  session.declared_modality=online; release_room(session, now)   [immediate]
    ├─ Online→F2F:  find_free_room() → assign or FAIL outright
    ├─ recurring:   Schedule.modality updated; JOB-01 patch stamps future online sessions
    ├─ AuditLog row (approval)
    └─ notify_ifo(...) + notify(faculty, ...)     [informational; IFO cannot block]
```

## Build Order & Dependencies

The PROJECT.md build order is `env → JOB-02 → IFO-06 → Checker → modality → notif → reporting → Guard/Dean/HR`. The new-component dependencies refine it:

| Slice | Introduces | Depends on (must exist first) |
|-------|------------|-------------------------------|
| **env / scheduler** | `config/scheduler.py`; extract JOB-01 to `scheduling/jobs.py:materialize_sessions()` | nothing (JOB-01 logic exists) |
| **JOB-02 sweep** | `scheduling/sweep.py` (pure) + `jobs.py:run_status_sweep()` + `occupancy.release_room()` + `run_status_sweep` command | shared Absent predicate extracted from resolver; `room_hold_minutes` policy |
| **notify write path** | `ops/notifications.py:notify()/notify_ifo()`; refactor `scan.py:_notify_ifo` | — (small foundation; pull *forward* to just before JOB-02 conflict flags need it) |
| **modality** | `ModalityShiftRequest` model; `scheduling/modality.py`; `web/dean.py` approval view; JOB-01 online-release patch | `release_room()` (JOB-02 slice), `notify_ifo` (notify slice), JOB-01 extraction (env slice) |
| **notif surface** | `web/notifications.py` NOTIF-01 list + NOTIF-02 push dispatch + NOTIF-03 mute | `ops/notifications.py` write path already emitting rows |
| **reporting** | `ops/reports.py` aggregates; `ops/jobs.py:generate_weekly_reports()` (JOB-03); RPT-04 | `notify_deans` (RPT-02); aggregates before Dean dashboard |
| **Dean dashboard (DEAN-04)** | `web/dean.py` dashboard reusing `ops/reports.py` | `ops/reports.py` aggregates; `WeeklyReport` rows from JOB-03 |

**Two dependencies to surface for phase planning:**
1. **The shared notify() write path is a hidden prerequisite for JOB-02, modality, and reporting.** It is listed *after* modality in the PROJECT order, but JOB-02's conflict flags and modality's approval notices both need it. Recommend landing `ops/notifications.py` (write path + `notify_ifo` refactor) as a small foundation task before/with JOB-02; the *read surface* (NOTIF-01) and *push* (NOTIF-02/03) can stay in the later notif slice.
2. **`occupancy.release_room()` is introduced by JOB-02 but consumed by modality and force-handover.** Build it in the JOB-02 slice as the single writer, then have modality reuse it rather than stamping `room_released_at` inline.

## Anti-Patterns

### Anti-Pattern 1: Starting APScheduler inside `AppConfig.ready()`

**What people do:** Register jobs in a Django app's `ready()` hook so "it just runs with the server."
**Why it's wrong:** Gunicorn forks N workers → N schedulers → every job fires N times (N Absent-sweeps, N weekly reports). This is the classic Django-scheduler footgun.
**Do this instead:** One dedicated process (`config/scheduler.py`, second systemd service per deployment design §2), `BlockingScheduler`, `max_instances=1`, idempotent jobs.

### Anti-Pattern 2: Putting job logic in `handle()` or a view

**What people do:** Write JOB-02 logic in a management command's `handle()`, or the modality room-release inside the Dean approval view.
**Why it's wrong:** The scheduler process can't import a `handle()` cleanly, and the modality feature needs JOB-01's Session-creation logic reachable outside a command. Logic trapped in a command/view can't be unit-tested DB-free the way the resolver is.
**Do this instead:** Logic in `scheduling/jobs.py` / `scheduling/modality.py`; commands and views are thin wrappers. Pure decisions in `sweep.py`/`modality.py`.

### Anti-Pattern 3: Re-deriving occupancy in each feature

**What people do:** Each of sweep, handover, and modality writes `room_released_at` inline and re-implements "is this room free."
**Why it's wrong:** The three drift apart — exactly the failure the modality-shift design was written to prevent (unset `room_released_at` that nothing ever sets).
**Do this instead:** One `occupancy.release_room()` writer + one `is_room_free()` reader; all three callers go through them.

### Anti-Pattern 4: A second notification path

**What people do:** Copy `_notify_ifo` into modality.py and reports.py, or create `Notification` rows inline in a job.
**Why it's wrong:** Push dispatch, mute prefs (NOTIF-03), and the row shape diverge per copy; a new event forgets push.
**Do this instead:** Everything calls `ops/notifications.py:notify()`.

### Anti-Pattern 5: Side effects in report aggregates

**What people do:** Have an aggregate write a cache row, an `AuditLog`, or send a notification.
**Why it's wrong:** Breaks the RPT-05/§6.6 "pure, independently tested" contract and the per-aggregate try/except isolation — a write failure inside one aggregate corrupts state, not just a rendered card.
**Do this instead:** Aggregates are read-only. Writes (WeeklyReport rows, notifications) live in the JOB-03 applier that *calls* the aggregates.

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Scheduler process ↔ service layer | direct function import after `django.setup()` | never `AppConfig.ready`; shares the same ORM/settings, different process |
| `sweep.py`/`modality.py` (pure) ↔ `jobs.py`/views (applier) | plan object in, ORM writes out | mirrors `resolver.py` ↔ `scan.py:_apply` |
| resolver ↔ sweep | shared Absent predicate | must agree or scan and sweep contradict — highest-risk coupling |
| all writers ↔ `occupancy.release_room()` | single writer for `room_released_at` | Q6 consistency guarantee |
| all notifiers ↔ `ops/notifications.notify()` | single Notification+push write path | Q3 |
| IFO-09 / DEAN-04 / RPT-04 / JOB-03 ↔ `ops/reports.py` | scope-parameterized aggregate calls | Q4 reuse; department filter is the only difference |

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Web Push (VAPID) | `PushSubscription.endpoint`/`keys` → HTTPS from notify()/scheduler | best-effort; failure never breaks caller (NOTIF-02) |
| RDS SQL Server | `mssql-django` + pyodbc; `DB_ENGINE=mssql` branch | Django 6.0.6 compat unspiked — flag for reporting-heavy aggregate SQL |
| Filesystem (EBS) | `WeeklyReport.csv_path`/`pdf_path` on local media, not S3 | deployment design §2 — model docstring says "S3" but design supersedes it |

## Sources

- `.planning/codebase/ARCHITECTURE.md`, `STRUCTURE.md`, `CONVENTIONS.md` — existing mapped architecture (HIGH)
- `scheduling/resolver.py`, `scheduling/models.py`, `web/scan.py`, `ops/models.py`, `ops/policy.py`, `scheduling/management/commands/materialize_sessions.py`, `verification/models.py` — read directly (HIGH)
- `docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md` — approved (HIGH)
- `docs/superpowers/specs/2026-07-02-dean-dashboard-design.md` — approved (HIGH)
- `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` — approved; scheduler-as-second-systemd-service, MSSQL, EBS-not-S3 (HIGH)
- `.planning/PROJECT.md` — build order, scope, active requirements (HIGH)

---
*Architecture research for: FluxTrack subsequent milestone — integrating scheduled jobs, status sweep, notifications, reporting, modality shift, and explicit occupancy into the existing layered Django architecture*
*Researched: 2026-07-02*

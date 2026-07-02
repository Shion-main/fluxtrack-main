# Phase 2: Correctness Foundations - Research

**Researched:** 2026-07-03
**Domain:** Django background jobs (APScheduler), pure-predicate extraction, notification write-path service, occupancy/conflict detection
**Confidence:** HIGH (codebase + APScheduler patterns verified against current docs; two flagged open questions)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Sweep cadence:** runs **every 5 minutes** via APScheduler. This interval IS the "within one sweep interval" guarantee (worst-case ~5 min from grace expiry to Absent). Not 1 min (churn), not 15 min (too slow).
- **No-show predicate (JOB-02a/b):** the sweep reuses the scan resolver's grace predicate (`now > scheduled_start + grace`, `grace = get_policy("grace_minutes")`) — extract/share **ONE** predicate so scan-time and sweep-time can never disagree. A pure decision function determines no-show; the sweep applies it. This is the **highest-risk coupling** in the phase.
- **Backfill:** the sweep marks Absent **any** still-`scheduled` session whose grace has expired, regardless of date (not just today's) — self-heals after a scheduler outage.
- **Idempotent:** only `SCHEDULED` → `ABSENT`. `active`, `completed`, already-`absent` are never touched. Mirrors `web/scan.py::_apply` guard (`if session.status == SessionStatus.SCHEDULED`).
- **Room conflicts (JOB-02c):** sweep **still raises** room-conflict notifications to IFO when occupancy is contradictory. **Deduped until resolved** — one notification per distinct conflict; do NOT re-notify on later sweeps while the same conflict is unresolved.
- **NO timer-based auto-release.** The sweep does NOT free rooms after a hold window. `room_released_at` is never stamped by the sweep.
- **`release_room()` helper:** built + fully tested in Phase 2 (stamps `Session.room_released_at`, single source of truth for releasing a room). The sweep does NOT call it. Phase 4's MOD-03 calls it on →Online approval.
- **`notify()` (NOTIF-00):** one service creates `Notification` rows for any role/event. Replaces `_notify_ifo` **entirely** — after this phase `_notify_ifo` is gone and no other inline `Notification.objects.create(...)` notifier remains outside `notify()`. Migrate the two `_notify_ifo` call sites in `web/scan.py` (Room change ~L113, Force handover ~L129) with equivalent title/body/link. Preserve existing `Notification` fields — no model change for NOTIF-00 itself. `notify()` targets a role (all active users of it) or a specific user.
- **Scheduler (ENV-04):** **one dedicated process** — a second systemd service in prod, never inside a Gunicorn web worker. Jobs must not double-fire across workers. Jobs registered: materialize (JOB-01), sweep (JOB-02), weekly report (JOB-03 — register slot/wiring even though the report body lands Phase 6).
- **Last-run status recorded** (ok/failed, rows affected, timestamp) for the future SYS-04 dashboard (Phase 7). Introduce a `JobRun`-style record.
- **Job failure surfacing:** on **failure only**, fire `notify()` to System Admins. Record every run's status, but only notify on failure. No success/heartbeat notifications.

### Claude's Discretion
- Exact module/function placement for the extracted grace predicate (likely `scheduling/resolver.py` or a small shared helper it imports).
- The `notify()` signature (role vs user targeting, kwargs) and where it lives (likely `ops/`).
- The `JobRun` model shape and where last-run status is stored.
- The conflict-detection query and the exact dedup key for room-conflict notifications.
- APScheduler wiring details (jobstore, executor, how the dedicated process is launched in dev vs prod).

### Deferred Ideas (OUT OF SCOPE)
- **Timer-based automatic room release** — moved out. Room release only via approved modality shift (MOD-03, Phase 4). `room_hold_minutes` policy retained for possible future use.
- **SYS-04 job-monitoring dashboard** — `JobRun` recorded in Phase 2, but the dashboard reading it is Phase 7.
- **Weekly-report job body** — scheduler registers/wires the JOB-03 slot in Phase 2; report generation itself is Phase 6 (RPT-01/02).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NOTIF-00 | Shared `notify()` write-path service creating `Notification` rows for any role/event, replacing `_notify_ifo` | §"notify() Service Design" — signature, `ops/notify.py` placement, role fan-out reusing the exact `_notify_ifo` query, migration of both scan call sites, dedup hook for conflicts |
| JOB-02a | Pure decision function for no-show-past-grace, reusing the scan resolver's grace predicate | §"Shared Grace Predicate" — extract `is_no_show_past_grace(scheduled_start, now, grace_min)` as one pure function both `resolve_faculty_scan` and the sweep import; keeps the 16 resolver tests green |
| JOB-02b | Status sweep marks no-show sessions Absent independent of any scan | §"Status Sweep" — backfill query, `SCHEDULED→ABSENT` idempotency guard mirroring `_apply`, per-write `AuditLog`, ASCII management-command wrapper |
| JOB-02c | Sweep raises deduped room-conflict flag via `notify()`; `release_room()` helper built+tested but invoked only by MOD-03 | §"Room-Conflict Detection & Dedup" (RoomConflictFlag model recommendation) + §"release_room() Helper" |
| ENV-04 | All jobs run via APScheduler in one dedicated process, no double-fire, last-run status recordable | §"APScheduler Architecture" (BlockingScheduler + management command, MemoryJobStore, coalesce/max_instances, dedicated systemd process) + §"JobRun Model & Job Wrapper" |
</phase_requirements>

## Summary

This is a backend-correctness phase with **zero new user-facing surfaces**. Five requirements form one coherent slice: a single notification write path, a shared no-show predicate, a status sweep that makes "Absent" trustworthy without a scan, a room-conflict safety net, and one dedicated scheduler process with recordable run status. The codebase is small, well-conventioned, and already contains every model and pattern needed — the work is almost entirely *net-new services wired to existing models*, not schema churn. Only two tiny model additions are indicated (`JobRun`, and a recommended `RoomConflictFlag` for clean dedup); `Notification`, `Session`, `AuditLog`, and `SystemSetting` are all sufficient as-is.

The single highest-risk item is the **shared grace predicate**. Today the comparison `now > scheduled_start + grace` lives inline at `scheduling/resolver.py:89`. It must be extracted into one pure function that both `resolve_faculty_scan` and the new sweep import, so scan-time and sweep-time can never diverge. The 16 existing `FacultyResolverTests` assert *outcomes* (not the predicate directly), so extraction is safe as long as `resolve_faculty_scan`'s behavior is byte-for-byte preserved — the refactor is internal.

For scheduling, APScheduler **3.11.x** is the current stable line (4.0 is still a pre-release rewrite — do **not** adopt it; the existing `APScheduler>=3.10` pin is correct). The industry-standard pattern for "one dedicated process, never double-fires across Gunicorn workers" is a **`BlockingScheduler` inside a Django management command**, launched as its own process (a terminal in dev, a second systemd unit in prod). The critical anti-pattern to forbid: starting a `BackgroundScheduler` in `AppConfig.ready()` — that fires once *per web worker* and is exactly the double-fire bug ENV-04 exists to prevent. A **`MemoryJobStore`** is correct here because the three jobs are code-defined constants, not user-managed schedules; a DB jobstore (and the `django-apscheduler` package) would add an MSSQL-coupled dependency for no benefit.

**Primary recommendation:** Extract one pure `is_no_show_past_grace()` predicate; build `notify()` in `ops/notify.py` and delete `_notify_ifo`; run the sweep + materialize + (stub) weekly-report as plain callable services wrapped by a `run_job` observability decorator that writes `JobRun` rows and notifies System Admins on failure; register all three on a single `BlockingScheduler` started only by a dedicated `manage.py runscheduler` management command (never in `AppConfig.ready`).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| APScheduler | 3.11.x (pin `>=3.10,<4`) | In-process cron/interval scheduling | Already in `requirements.txt`; the mainstream pure-Python scheduler; 3.x is the stable line. 4.0 is a partial rewrite still in pre-release. |
| Django | 6.0.6 (pinned) | ORM, management commands, `timezone` utils | Project standard; management-command framework hosts the scheduler process and the sweep CLI. |
| mssql-django | 1.7.3 (pinned) | SQL Server backend | Jobs run ordinary ORM queries through it; **no APScheduler DB jobstore touches it** under the recommended design. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| (stdlib) `datetime.timedelta` | — | grace math in the pure predicate | The predicate stays dependency-free and pure (SRS §6.6). |
| (stdlib) `logging` / `self.stdout` | — | scheduler process console output | Console + `JobRun` rows are the observability surface; no new logging framework (per Conventions §Logging). |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Plain APScheduler + `MemoryJobStore` + custom `JobRun` | `django-apscheduler` (adds `DjangoJobStore` + `DjangoJobExecution`) | Rejected: it persists schedules and execution rows in the DB via the ORM, coupling scheduling to MSSQL and duplicating the `JobRun` concept. Our jobs are fixed code constants, not user-edited schedules — persistence buys nothing and adds a dependency + migration risk on SQL Server. |
| `BlockingScheduler` in a management command | `BackgroundScheduler` in `AppConfig.ready()` | **Forbidden** — fires once per Gunicorn worker → the exact double-fire ENV-04 prohibits. |
| Cutoff query + shared pure predicate | Celery + celery-beat + broker | Massive over-engineering for a single-instance capstone; SRS §6.7 explicitly calls for a "dedicated process," which APScheduler-in-a-command satisfies with zero extra infrastructure. |

**Installation:** No new packages. `APScheduler>=3.10` is already in `requirements.txt`. (Optionally tighten to `>=3.10,<4` to prevent an accidental 4.0 jump.)

**Version verification (2026-07-03):** APScheduler latest stable is **3.11.3** (PyPI, 3.x line). APScheduler **4.0 is still pre-release** — its scheduler classes were merged into a single `Scheduler` with `run_until_stopped()`/`start_in_background()`, and it drops the 3.x jobstore import path. Stay on 3.x. Django 6.0.6 and mssql-django 1.7.3 are the phase-1-verified, pinned versions.

## Architecture Patterns

### Recommended File Layout (flat apps — no new app)
```
scheduling/
├── resolver.py                         # ADD: is_no_show_past_grace() pure predicate; L89 calls it
├── jobs.py                             # NEW: sweep_no_shows(now), detect_room_conflicts(now) service fns (return counts)
├── management/commands/
│   ├── materialize_sessions.py         # EXISTING JOB-01 (optionally extract core into a callable)
│   ├── run_status_sweep.py             # NEW: thin ASCII CLI wrapper calling scheduling.jobs.sweep_no_shows
│   └── runscheduler.py                 # NEW: BlockingScheduler process — registers all 3 jobs
ops/
├── models.py                           # ADD: JobRun; (recommended) RoomConflictFlag
├── notify.py                           # NEW: notify() write-path service
├── jobrun.py  (or jobs.py)             # NEW: run_job() observability wrapper (writes JobRun, notifies SysAdmin on fail)
└── occupancy.py                        # NEW: release_room(session, ...) helper (built now, called by MOD-03 in P4)
web/scan.py                             # EDIT: delete _notify_ifo; route both call sites through notify()
```
Rationale: matches the established "one module per concern, import directly, no barrel files" convention. `notify()` and `JobRun` live in `ops/` (which already owns `Notification`, `AuditLog`, `SystemSetting`) per CONTEXT's steer. Sweep decision logic lives in `scheduling/` next to the resolver it shares a predicate with.

### Pattern 1: Pure predicate extraction (JOB-02a) — the load-bearing refactor
**What:** Lift the inline grace comparison into one pure function; both the resolver and the sweep import it.
**When to use:** Any time two code paths must agree on the same rule.
**Example:**
```python
# scheduling/resolver.py  (pure — no ORM, no timezone.now(), primitives in)
from datetime import timedelta

def is_no_show_past_grace(scheduled_start, now, grace_min):
    """True if `now` is past the check-in grace window for a session
    starting at `scheduled_start` (JOB-02a). The SINGLE shared no-show
    predicate: scan-time (resolve_faculty_scan) and sweep-time (JOB-02b)
    both call this so they can never disagree. Pure: aware datetimes in,
    bool out, no side effects (SRS §6.6)."""
    return now > scheduled_start + timedelta(minutes=grace_min)

# ...inside resolve_faculty_scan, replace L89:
    if is_no_show_past_grace(candidate.scheduled_start, now, grace_min):
        return Resolution(ABSENT, candidate.id)
```
**Why the 16 tests stay green:** `FacultyResolverTests` assert `resolve_faculty_scan` *outcomes* (e.g. `test_checkin_after_grace_is_absent` at +16 min → `ABSENT`, `test_checkin_within_grace_is_present` at +14 min → `CHECKED_IN`). The boundary math is unchanged, so every assertion holds. Add *new* direct tests for `is_no_show_past_grace` (boundary at exactly `+grace`, just under, just over).

**Critical scope note:** The sweep does **NOT** reuse `resolve_faculty_scan` wholesale — that function is scan-context-specific (room match, occupancy, online reject, window containment). The *shared atom* is exactly `is_no_show_past_grace`. The resolver only reaches its ABSENT branch for a session whose window contains `now` in the scanned room; the sweep applies the predicate to **every** still-`scheduled` session regardless of room/window/date (backfill). Sharing the atomic predicate — not the whole resolver — is what the "never disagree" guarantee means.

### Pattern 2: Pure-decision-core + thin-apply-layer for the sweep (JOB-02b)
**What:** Mirror the existing resolver/`_apply` split. A service function decides + applies + audits; a management command is a thin ASCII wrapper.
**Example:**
```python
# scheduling/jobs.py
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.models import Session, SessionStatus
from scheduling.resolver import is_no_show_past_grace

def sweep_no_shows(now=None):
    """JOB-02b: mark every still-SCHEDULED session whose grace has expired
    ABSENT, regardless of date (backfill/self-heal). Idempotent: only
    SCHEDULED -> ABSENT; active/completed/absent untouched. Returns count."""
    now = now or timezone.now()
    grace_min = get_policy("grace_minutes")
    cutoff = now - timedelta(minutes=grace_min)         # DB pre-filter derived from the SAME grace value
    marked = 0
    qs = Session.objects.filter(status=SessionStatus.SCHEDULED,
                                scheduled_start__lt=cutoff)
    for s in qs.iterator():
        # Re-affirm via the shared predicate so the ORM cutoff and the
        # authoritative predicate are provably one rule (see coupling test).
        if not is_no_show_past_grace(s.scheduled_start, now, grace_min):
            continue
        with transaction.atomic():
            s.status = SessionStatus.ABSENT
            s.save(update_fields=["status"])
            AuditLog.objects.create(actor=None, event_type="session.marked_absent",
                                    target_type="session", target_id=str(s.pk),
                                    payload={"by": "sweep"})
        marked += 1
    return marked
```
`actor=None` is valid — `AuditLog.actor` is `null=True, on_delete=SET_NULL` (system-initiated write). The `payload={"by": "sweep"}` distinguishes sweep-marked from scan-marked absences (both use the same `event_type` the scan path already emits).

### Pattern 3: `BlockingScheduler` in a dedicated management command (ENV-04)
**What:** One long-lived process owns all jobs. Never started inside the web app.
**Example:**
```python
# scheduling/management/commands/runscheduler.py
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Run the single dedicated FluxTrack scheduler (JOB-01/02/03)."

    def handle(self, *args, **o):
        sched = BlockingScheduler(timezone=settings.TIME_ZONE)  # Asia/Manila
        # each job wrapped by run_job(...) -> writes JobRun, notifies SysAdmin on failure
        sched.add_job(job_materialize, IntervalTrigger(hours=6),
                      id="materialize", max_instances=1, coalesce=True,
                      misfire_grace_time=3600, replace_existing=True)
        sched.add_job(job_sweep, IntervalTrigger(minutes=5),
                      id="sweep", max_instances=1, coalesce=True,
                      misfire_grace_time=300, replace_existing=True)
        sched.add_job(job_weekly_report, CronTrigger(day_of_week="mon", hour=6),
                      id="weekly_report", max_instances=1, coalesce=True,
                      replace_existing=True)   # body stubbed until Phase 6
        self.stdout.write(self.style.SUCCESS("Scheduler started: materialize/sweep/weekly_report."))
        try:
            sched.start()          # blocks
        except (KeyboardInterrupt, SystemExit):
            sched.shutdown()
```
- **Dev launch:** a second terminal → `py -3.12 manage.py runscheduler` (alongside `runserver`).
- **Prod launch:** a second systemd unit running the same command (per the deployment spec §2 — "a second systemd service on the same instance").
- `max_instances=1` + `coalesce=True` prevent a slow sweep from overlapping itself and collapse a burst of missed ticks into one run. `misfire_grace_time` tolerates a late tick; even if a tick is skipped entirely, the **next** sweep backfills (self-heal), so misfire tuning is not safety-critical.
- **Backfill vs. APScheduler misfire are independent:** the sweep's own `scheduled_start__lt=cutoff` query is what recovers past no-shows after an outage — not APScheduler's misfire logic.

### Anti-Patterns to Avoid
- **Starting the scheduler in `AppConfig.ready()` / on import.** Runs once per Gunicorn worker → duplicate/missed jobs. This is the single failure mode ENV-04 targets. The scheduler starts **only** from the dedicated `runscheduler` command.
- **Adding a DB jobstore (`django-apscheduler`).** Couples scheduling to MSSQL, duplicates `JobRun`, and buys nothing for fixed code-defined jobs. Use `MemoryJobStore` (the default).
- **Reusing `resolve_faculty_scan` for the sweep.** It's scan-context-specific; share only the atomic `is_no_show_past_grace` predicate.
- **Re-notifying IFO every 5 minutes for a persistent conflict.** Violates the dedup requirement — gate on an unresolved flag (see below).
- **Hardcoding grace/interval magic numbers.** Grace comes from `get_policy("grace_minutes")`. Cadence is a code constant here (5 min) but consider reading it from policy for symmetry (discretion).

## notify() Service Design (NOTIF-00)

**Recommended signature (discretion — this is a concrete proposal):**
```python
# ops/notify.py
from django.contrib.auth import get_user_model
from ops.models import Notification

def notify(*, type, title, body="", link="", role=None, users=None):
    """Single write-path for Notification rows (NOTIF-00). Target EITHER a
    role (fan out to all active users of that role) OR an explicit user
    iterable. Returns the created Notification list. This is the only place
    Notification.objects.create(...) is allowed to be called."""
    recipients = list(users) if users is not None else []
    if role is not None:
        recipients += list(get_user_model().objects.filter(role=role, is_active=True))
    return [Notification.objects.create(user=u, type=type, title=title,
                                        body=body, link=link) for u in recipients]
```
- **Role fan-out** reproduces `_notify_ifo` exactly: `filter(role=Role.IFO_ADMIN, is_active=True)`. `Role` lives in `accounts.models` with members `FACULTY, CHECKER, IFO_ADMIN, HR_ADMIN, GUARD, DEAN, SYSTEM_ADMIN`.
- **Migration of the two call sites** in `web/scan.py` (preserve `type="room_event"`, titles/bodies):
  ```python
  # was: _notify_ifo("Room change", f"...")            (L113)
  notify(role=Role.IFO_ADMIN, type="room_event", title="Room change", body=f"...")
  # was: _notify_ifo("Force handover", f"...")          (L129)
  notify(role=Role.IFO_ADMIN, type="room_event", title="Force handover", body=f"...")
  ```
  Then **delete** `_notify_ifo` and its `from django.contrib.auth import get_user_model` local import.
- **Callers this phase:** scan room-change + force-handover (migrated), sweep room-conflict flags, job-failure alerts to System Admins.
- **AuditLog question (discretion):** Convention §2 requires an `AuditLog` on state changes. A notification is itself a record, and its *triggering* action is already audited (e.g. `session.room_changed`, `session.marked_absent`). Recommendation: `notify()` does **not** emit its own `AuditLog` (avoids doubling every event); the domain action that triggered it carries the audit. Flag for planner confirmation.

## Room-Conflict Detection & Dedup (JOB-02c)

### What counts as "contradictory occupancy"
Given `Session` fields (`status`, `room`, `scheduled_start/end`, `actual_start/end`, `room_released_at`):
1. **Primary (recommended for Phase 2): two or more `ACTIVE` sessions holding the same room** with `room_released_at IS NULL`. A single physical room cannot host two simultaneous active classes — the clearest, cheapest, false-positive-free signal.
   ```python
   from django.db.models import Count
   conflicts = (Session.objects.filter(status=SessionStatus.ACTIVE, room_released_at__isnull=True)
                .values("room_id").annotate(n=Count("id")).filter(n__gt=1))
   ```
2. **Secondary (optional): overrun.** An `ACTIVE` session past its `scheduled_end` while another session in the same room has an open scheduled window (`scheduled_start - open_lead <= now`). More logic, more false positives (a class legitimately running long). Recommend deferring/omitting unless the planner wants it — the primary signal already satisfies "contradictory occupancy raises a flag."

### Dedup mechanism — recommended: a small `RoomConflictFlag` model
The `Notification` model has no dedup key and no resolved-state, and conflicts fan out to N IFO admins — re-detecting every 5 min would re-notify N rows each time. A tiny source-of-truth flag cleanly satisfies "one notification per distinct conflict, deduped until resolved," and gives IFO-08 (Phase 7, "resolve room-conflict notifications") something concrete to resolve.
```python
# ops/models.py
class RoomConflictFlag(models.Model):
    room = models.ForeignKey("campus.Room", on_delete=models.CASCADE, related_name="conflict_flags")
    conflict_key = models.CharField(max_length=120)   # deterministic, e.g. f"room:{room_id}"
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["conflict_key"], condition=models.Q(resolved_at__isnull=True),
            name="uniq_open_conflict_per_key")]   # at most one OPEN flag per key
```
Sweep logic each run:
- Compute the current conflict set (keys). For each key with **no open flag** → create the flag + `notify(role=IFO_ADMIN, type="room_conflict", ...)` (first detection only).
- For each **open flag whose key is no longer in the current set** → stamp `resolved_at` (auto-resolve when the conflict clears). This makes re-notification impossible while unresolved and correctly re-flags if the same room conflicts again later.
- **Dedup key:** `f"room:{room_id}"` (one open conflict per room) is simplest and matches "one per distinct conflict" + manual IFO resolution. A sorted-session-id-tuple key is an alternative if per-pair granularity is wanted (discretion).

**Filtered `UniqueConstraint` on MSSQL:** mssql-django emits filtered unique indexes for partial constraints (Phase 1 already relies on exactly this — `azure_oid` nullable-unique landed as a filtered unique index). So a "one open flag per key" partial constraint is a known-good pattern on this backend.

**Note:** If the planner prefers *no new model*, the fallback is to query for an existing unread `Notification` of `type="room_conflict"` whose `link`/`body` encodes the room, and skip if present — but that's fragile (per-user rows, no clean resolved-state) and does not serve IFO-08. The flag model is the recommended path.

## release_room() Helper (JOB-02c — built now, called in Phase 4)

```python
# ops/occupancy.py
from django.utils import timezone
from ops.models import AuditLog

def release_room(session, *, actor=None, now=None):
    """Single source of truth for releasing a room: stamp room_released_at.
    Built + tested in Phase 2; INVOKED ONLY by MOD-03 (Phase 4) on an
    approved ->Online modality shift. The status sweep must NEVER call this
    (no timer-based auto-release, decided 2026-07-03)."""
    now = now or timezone.now()
    session.room_released_at = now
    session.save(update_fields=["room_released_at"])
    AuditLog.objects.create(actor=actor, event_type="session.room_released",
                            target_type="session", target_id=str(session.pk),
                            payload={"released_at": now.isoformat()})
```
Tests must assert: (a) it stamps `room_released_at` + writes the audit row; (b) the **sweep never stamps `room_released_at`** (guard test proving the cut of auto-release).

## JobRun Model & Job Wrapper (ENV-04)

### JobRun model (serves ENV-04 now, SYS-04 in Phase 7)
```python
# ops/models.py
class JobRun(models.Model):
    job_name = models.CharField(max_length=60)          # "materialize" | "sweep" | "weekly_report"
    status = models.CharField(max_length=10)            # "running" | "ok" | "failed"
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    rows_affected = models.IntegerField(default=0)
    detail = models.TextField(blank=True)               # error message or summary
    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["job_name", "-started_at"])]
```
SYS-04 (Phase 7) reads the latest `JobRun` per `job_name`. "Last-run status recordable" = one row per execution.

### Observability wrapper (centralizes recording + failure notification)
```python
# ops/jobrun.py
from django.utils import timezone
from accounts.models import Role
from ops.models import JobRun
from ops.notify import notify

def run_job(job_name, fn):
    """Wrap a job callable: record a JobRun, notify System Admins on FAILURE
    ONLY (ENV-04 — record every run's status, notify only on failure)."""
    run = JobRun.objects.create(job_name=job_name, status="running",
                                started_at=timezone.now())
    try:
        rows = fn() or 0
        run.status, run.rows_affected = "ok", int(rows)
    except Exception as exc:                       # noqa: BLE001 — jobs must not crash the process
        run.status, run.detail = "failed", repr(exc)[:2000]
        notify(role=Role.SYSTEM_ADMIN, type="job_failed",
               title=f"Job failed: {job_name}", body=repr(exc)[:500])
    finally:
        run.finished_at = timezone.now()
        run.save()
    return run
```
Each APScheduler job is `lambda: run_job("sweep", sweep_no_shows)` etc. Catching `Exception` here also protects the `BlockingScheduler` process from dying on a single bad run.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Interval/cron scheduling | A `while True: sleep()` loop or OS cron shelling into `manage.py` | APScheduler `IntervalTrigger`/`CronTrigger` in one `BlockingScheduler` | Handles misfire/coalesce/timezone; SRS §6.7 wants an in-app dedicated process, and it's already a dependency. |
| Preventing multi-worker double-fire | Redis/DB lock hand-rolled around a `BackgroundScheduler` in web workers | A separate process (management command + systemd unit) | Structural isolation is simpler and bulletproof; no lock to get wrong. |
| Two code paths agreeing on "no-show" | Copy the `now > start + grace` check into the sweep | One extracted pure `is_no_show_past_grace()` both import | Duplicated rules drift; this is the phase's stated highest risk. |
| Notification fan-out to a role | Inline `for u in ...: Notification.objects.create(...)` in each caller | `notify(role=..., ...)` | NOTIF-00 exists precisely to make this one path; inline notifiers are what's being deleted. |
| Conflict dedup / "already flagged" | Ad-hoc scan of Notification bodies each sweep | `RoomConflictFlag` with a partial-unique open-per-key constraint | Gives a real resolved-state (IFO-08) and makes dedup a DB invariant, not a query heuristic. |
| Job run history | `print()` / log-scraping | `JobRun` rows via the `run_job` wrapper | SYS-04 needs queryable last-run status; a table is the record (Conventions §Logging: prefer a row over a log line). |

**Key insight:** Almost every "custom" temptation here (cron loops, worker locks, duplicated predicates, inline notifiers) is a correctness hazard the phase was created to eliminate. The disciplined move is a separate process + one shared predicate + one write path.

## Common Pitfalls

### Pitfall 1: Scheduler double-fires across Gunicorn workers
**What goes wrong:** Jobs run N times (N = worker count) or create duplicate rows.
**Why:** A `BackgroundScheduler` started in `AppConfig.ready()` or at import time runs inside every worker.
**How to avoid:** Start the scheduler *only* in the dedicated `runscheduler` management command (its own process). Add a guard test that importing/booting the Django app does **not** instantiate/start a scheduler.
**Warning signs:** Duplicate `JobRun` rows with near-identical `started_at`; a session marked absent twice in the audit log.

### Pitfall 2: The grace predicate silently drifts between scan and sweep
**What goes wrong:** A session is `ABSENT` per one path and not the other; "Absent" becomes untrustworthy — defeating the whole phase.
**Why:** The comparison is copy-pasted instead of shared.
**How to avoid:** One `is_no_show_past_grace()`, imported by both. Add a **coupling-integrity test** (see Validation Architecture) asserting both paths agree on identical inputs.
**Warning signs:** Two `timedelta(minutes=grace)` literals in the codebase; a sweep that recomputes grace differently from `get_policy`.

### Pitfall 3: Online sessions marked Absent by the sweep (OPEN QUESTION — see below)
**What goes wrong:** Online sessions (which the scanner *rejects* rather than starts) sit `SCHEDULED` and the sweep marks them `ABSENT` — potentially wrong once FAC-08 "Verify & Start" (Phase 7) lands.
**Why:** The sweep's backfill query is modality-agnostic; the resolver treats online specially (`ONLINE_REJECT`) but the sweep doesn't.
**How to avoid:** Decide explicitly (Open Question 1). Recommended interim: mark all `SCHEDULED`-past-grace sessions Absent regardless of modality (a session nobody started *is* a no-show), and document that FAC-08 will flip started online sessions to `ACTIVE` (thus untouched) in Phase 7.
**Warning signs:** Online-modality faculty appearing Absent in reports.

### Pitfall 4: MSSQL test-DB churn / TransactionTestCase requirement
**What goes wrong:** Sweep/notify tests wrap work in `transaction.atomic()`; a plain `TestCase` can mask commit behavior, and management-command tests need committed data.
**Why:** Phase 1 already hit this — `ImportPathTests`/`R3ParityTests` use `TransactionTestCase` because the commands wrap work in `atomic()`.
**How to avoid:** Use `TestCase` for straightforward ORM assertions; use `TransactionTestCase` for tests that exercise the management-command wrappers or rely on commit semantics. Point the runner at the isolated `test_fluxtrack` DB (`DB_TEST_NAME`), already wired in settings.
**Warning signs:** Tests passing on SQLite mental-model but failing on MSSQL; connection/threading errors.

### Pitfall 5: ASCII-only management-command output (Windows cp1252)
**What goes wrong:** Unicode arrows/emoji in `runscheduler`/`run_status_sweep` output crash on the Windows console.
**Why:** Project rule (Conventions §4) — commands print ASCII only; use `->` not `→`.
**How to avoid:** Mirror `materialize_sessions.py` exactly (`self.style.SUCCESS(...)`, ASCII `->`).
**Warning signs:** `UnicodeEncodeError: 'charmap'` in dev.

### Pitfall 6: APScheduler thread + pyodbc connections
**What goes wrong:** Default `ThreadPoolExecutor` runs jobs on worker threads; each thread opens its own DB connection — fine, but long-lived idle connections can go stale.
**Why:** Django closes connections per-request in the web path, but a scheduler process has no request cycle.
**How to avoid:** Keep jobs short; optionally call `django.db.close_old_connections()` at the start/end of each job wrapper (`run_job`) to avoid stale-connection errors in a long-running process. `max_instances=1` avoids concurrent runs of the *same* job.
**Warning signs:** Intermittent "connection is closed"/timeout errors after the process has idled overnight.

## Code Examples

### Coupling-integrity: scan and sweep never disagree
```python
# scheduling/tests.py (new) — proves the single-predicate guarantee (JOB-02a)
from datetime import timedelta
from scheduling.resolver import is_no_show_past_grace, resolve_faculty_scan
# For a session whose window contains `now` in the scanned room, the resolver's
# ABSENT decision must equal the shared predicate for the SAME (start, now, grace).
def test_resolver_absent_iff_predicate_true(self):
    for delta in (-1, 0, 1, 14, 15, 16):
        now = T0 + timedelta(minutes=delta)
        r = resolve([sess()], now=now)          # window contains now, same room
        pred = is_no_show_past_grace(T0, now, 15)
        self.assertEqual(r.outcome == R.ABSENT, pred)
```

### Sweep idempotency + independence-of-scan (JOB-02b)
```python
# scheduling/tests.py (new, TestCase / TransactionTestCase)
def test_sweep_marks_unscanned_no_show_absent(self):
    s = make_session(scheduled_start=now - timedelta(minutes=20))  # past 15-min grace
    sweep_no_shows(now=now)
    s.refresh_from_db(); self.assertEqual(s.status, SessionStatus.ABSENT)
def test_sweep_is_idempotent_on_active_completed_absent(self):
    # active/completed/already-absent sessions are untouched; rerun changes nothing
    ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| APScheduler 3.x `BlockingScheduler`/`BackgroundScheduler` | 4.0 merges both into one `Scheduler` (`run_until_stopped()`/`start_in_background()`), splits Task/Schedule/Job | 4.0 still pre-release (as of 2026-07) | **Do not adopt 4.0.** Stay on 3.11.x; the `>=3.10` pin is right. Tighten to `<4` to be safe. |
| Hand-rolled cron / worker-embedded scheduler | Dedicated process (management command + systemd unit) | Long-standing best practice | Matches SRS §6.7 + deployment spec §2 exactly. |
| `django-apscheduler` DB jobstore for persistence | `MemoryJobStore` for fixed code-defined jobs | N/A | Avoids MSSQL coupling; our jobs aren't user-edited schedules. |

**Deprecated/outdated:**
- APScheduler 4.0 APIs (`Scheduler`, `run_until_stopped`) — not yet stable; ignore for this phase.

## Open Questions

1. **Should the sweep mark ONLINE sessions Absent?**
   - What we know: the scanner *rejects* online (`ONLINE_REJECT`), never starts them; FAC-08 "Verify & Start" (the online start path) is Phase 7. The sweep's backfill query is modality-agnostic.
   - What's unclear: whether marking a still-`SCHEDULED` online session Absent past grace is correct now, or premature until FAC-08 exists.
   - Recommendation: for Phase 2, mark all `SCHEDULED`-past-grace sessions Absent regardless of modality (a session nobody started is genuinely a no-show); document that FAC-08 will make started online sessions `ACTIVE` (untouched). Alternatively, exclude effective-online sessions from the sweep and revisit in Phase 7. **Ask the user** — this affects report correctness.

2. **Conflict dedup key granularity: per-room vs per-session-pair?**
   - What we know: CONTEXT leaves the dedup key to the planner; IFO-08 (Phase 7) will resolve flags.
   - What's unclear: whether IFO wants one flag per room or one per conflicting pair.
   - Recommendation: start with `f"room:{room_id}"` (one open flag per room) — simplest, matches manual resolution; revisit if per-pair detail is needed.

3. **Does `notify()` emit its own AuditLog?**
   - Recommendation: no — the triggering domain action is already audited; notifications are their own record. Confirm with planner to satisfy Convention §2 intent without doubling every event.

## Validation Architecture

*(nyquist_validation is enabled — `.planning/config.json` → `workflow.nyquist_validation: true`.)*

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django test runner (`unittest`), Django 6.0.6 — `SimpleTestCase` (pure), `TestCase`/`TransactionTestCase` (DB) |
| Config file | none — settings-driven; test DB `test_fluxtrack` via `DATABASES.default.TEST.NAME` (`DB_TEST_NAME`), MSSQL |
| Quick run command | `py -3.12 manage.py test scheduling.tests.FacultyResolverTests` (pure, no DB, fast) |
| Full suite command | `py -3.12 manage.py test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JOB-02a | `is_no_show_past_grace` true/false at grace boundary (14/15/16 min) | unit (SimpleTestCase) | `py -3.12 manage.py test scheduling.tests.NoShowPredicateTests` | ❌ Wave 0 (add to scheduling/tests.py) |
| JOB-02a | Coupling: resolver ABSENT ⇔ predicate for same inputs (never disagree) | unit (SimpleTestCase) | `py -3.12 manage.py test scheduling.tests.CouplingIntegrityTests` | ❌ Wave 0 |
| JOB-02b | Sweep marks an unscanned no-show ABSENT (independent of scan) | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ Wave 0 |
| JOB-02b | Sweep backfills past-date no-shows (self-heal after outage) | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ Wave 0 |
| JOB-02b / criterion 5 | Idempotency: active/completed/already-absent untouched on rerun | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ Wave 0 |
| JOB-02b | Every sweep-marked absence writes an `AuditLog` (`session.marked_absent`, `by=sweep`) | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ Wave 0 |
| JOB-02c | Contradictory occupancy (2 active/room) raises ONE IFO conflict notification | integration | `py -3.12 manage.py test scheduling.tests.RoomConflictTests` | ❌ Wave 0 |
| JOB-02c | Dedup: a second sweep does NOT re-notify an unresolved conflict; auto-resolves when cleared | integration | `py -3.12 manage.py test scheduling.tests.RoomConflictTests` | ❌ Wave 0 |
| JOB-02c | `release_room()` stamps `room_released_at` + audits; the sweep NEVER stamps it | integration | `py -3.12 manage.py test ops.tests.ReleaseRoomTests` | ❌ Wave 0 (ops/tests.py) |
| NOTIF-00 | `notify(role=...)` fans out to all active users of that role | integration | `py -3.12 manage.py test ops.tests.NotifyTests` | ❌ Wave 0 |
| NOTIF-00 | Scan room-change / force-handover route through `notify()` (IFO rows created) | integration | `py -3.12 manage.py test web.tests.ScanNotifyTests` | ❌ Wave 0 (web/tests.py) |
| NOTIF-00 | `_notify_ifo` is gone; no inline `Notification.objects.create` outside `ops/notify.py` | unit (source guard) | `py -3.12 manage.py test ops.tests.SingleWritePathTests` | ❌ Wave 0 |
| ENV-04 | Job wrapper records a `JobRun` (ok, rows_affected) on success | integration | `py -3.12 manage.py test ops.tests.JobRunTests` | ❌ Wave 0 |
| ENV-04 | Job failure records `status=failed` AND notifies System Admins (only on failure) | integration | `py -3.12 manage.py test ops.tests.JobRunTests` | ❌ Wave 0 |
| ENV-04 | Booting the Django app does NOT start a scheduler (no per-worker double-fire) | unit (guard) | `py -3.12 manage.py test ops.tests.NoImplicitSchedulerTests` | ❌ Wave 0 |
| ENV-04 | `runscheduler` registers exactly 3 jobs (materialize/sweep/weekly_report) | unit | `py -3.12 manage.py test scheduling.tests.SchedulerWiringTests` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the touched app's fast tests — e.g. `py -3.12 manage.py test scheduling.tests.FacultyResolverTests scheduling.tests.NoShowPredicateTests` (pure, sub-second), plus the specific DB test class for the task.
- **Per wave merge:** the full app suites touched that wave — `py -3.12 manage.py test scheduling ops web`.
- **Phase gate:** full suite green before `/gsd:verify-work` — `py -3.12 manage.py test`. Must include the existing 16 resolver tests (unchanged) + Phase-1 datetime/import parity tests (still green) + all new Phase-2 classes.

### Wave 0 Gaps
- [ ] `scheduling/tests.py` — add `NoShowPredicateTests`, `CouplingIntegrityTests`, `SweepTests`, `RoomConflictTests`, `SchedulerWiringTests` (file exists; extend it — the resolver + MSSQL foundation tests already live here, reuse the `make_session(...)` factory at L135).
- [ ] `ops/tests.py` — add `NotifyTests`, `SingleWritePathTests`, `JobRunTests`, `NoImplicitSchedulerTests`, `ReleaseRoomTests` (file exists; extend).
- [ ] `web/tests.py` — add `ScanNotifyTests` (verifies migrated `notify()` call sites; file exists).
- [ ] Shared fixture: promote/reuse `scheduling.tests.make_session(...)` (L135) as the session factory for sweep/conflict tests; add a helper to spin up two active sessions sharing one room for conflict tests.
- [ ] Framework install: **none** — Django test runner + MSSQL `test_fluxtrack` already in place and green (Phase 1).

## Sources

### Primary (HIGH confidence)
- Codebase (read directly): `scheduling/resolver.py`, `web/scan.py`, `ops/models.py`, `ops/policy.py`, `scheduling/models.py`, `scheduling/tests.py`, `config/settings.py`, `scheduling/management/commands/materialize_sessions.py`, `accounts/models.py` (Role), `requirements.txt`.
- Project docs: `.planning/phases/02-correctness-foundations/02-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/codebase/CONVENTIONS.md`, `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`.
- [APScheduler PyPI / 3.11.x docs](https://apscheduler.readthedocs.io/en/3.x/faq.html) — BlockingScheduler-in-dedicated-process pattern, no interprocess sync, jobstore guidance.
- [APScheduler version history / migration (4.0 pre-release)](https://apscheduler.readthedocs.io/en/master/migration.html) — 3.11.3 latest stable; 4.0 rewrite unreleased.

### Secondary (MEDIUM confidence)
- [django-apscheduler (jcass77)](https://github.com/jcass77/django-apscheduler) — corroborates the multi-worker double-fire problem and the dedicated-`BlockingScheduler`-process remedy; used to *justify NOT adopting* its DB jobstore here.
- [Common APScheduler+Django mistakes (Ghorbanpoor, Medium)](https://sepgh.medium.com/common-mistakes-with-using-apscheduler-in-your-python-and-django-applications-100b289b812c) — anti-pattern of starting the scheduler in app init / per worker.

### Tertiary (LOW confidence)
- [Run APScheduler with Gunicorn (Enqueue Zero)](https://enqueuezero.com/projects/apscheduler/gunicorn.html) — community note on separate-process launch; consistent with primary docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — APScheduler 3.11.x verified current; already pinned; MSSQL/Django versions phase-1-verified.
- Architecture (predicate extraction, notify, sweep, JobRun): HIGH — grounded in read source + established project conventions; refactor preserves the 16 resolver tests.
- Scheduler process design: HIGH — pattern confirmed by APScheduler docs + community consensus; matches deployment spec §2 verbatim.
- Room-conflict dedup model: MEDIUM — recommended `RoomConflictFlag` is a design proposal (discretion); filtered-unique on MSSQL is proven from Phase 1.
- Online-session sweep behavior: LOW — genuinely open (Open Question 1), needs user decision.

**Research date:** 2026-07-03
**Valid until:** ~2026-08-03 (stable stack; re-check only if APScheduler 4.0 ships and the pin is loosened).

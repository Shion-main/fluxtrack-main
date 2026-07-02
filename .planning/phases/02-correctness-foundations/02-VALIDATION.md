---
phase: 2
slug: correctness-foundations
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `02-RESEARCH.md` § Validation Architecture. Task IDs are assigned by the planner; the requirement→test map below is the contract each task must satisfy.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (`unittest`), Django 6.0.6 — `SimpleTestCase` (pure, no DB), `TestCase`/`TransactionTestCase` (DB-backed on MSSQL) |
| **Config file** | none — settings-driven; test DB `test_fluxtrack` via `DATABASES.default.TEST.NAME` (`DB_TEST_NAME`), SQL Server 2025 LocalDB (Windows integrated auth) |
| **Quick run command** | `py -3.12 manage.py test scheduling.tests.FacultyResolverTests scheduling.tests.NoShowPredicateTests` (pure, sub-second) |
| **Full suite command** | `py -3.12 manage.py test` |
| **Estimated runtime** | Quick ~1s (pure); full suite ~30–60s (MSSQL DB setup dominates) |

---

## Sampling Rate

- **After every task commit:** the touched app's fast tests — e.g. `py -3.12 manage.py test scheduling.tests.FacultyResolverTests scheduling.tests.NoShowPredicateTests` (pure) plus the specific DB test class for that task.
- **After every plan wave:** the full app suites touched that wave — `py -3.12 manage.py test scheduling ops web`.
- **Before `/gsd:verify-work`:** full suite green — `py -3.12 manage.py test`. MUST include the existing 16 resolver tests (unchanged) + Phase-1 datetime/import-parity + CS-collation tests (still green) + all new Phase-2 classes.
- **Max feedback latency:** ~60 seconds (full suite).

---

## Per-Requirement Verification Map

Task IDs (`02-NN-MM`) are filled in by the planner; every task that implements a requirement below MUST wire to the matching test class.

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| JOB-02a | `is_no_show_past_grace` true/false at grace boundary (14 / 15 / 16 min) | unit (SimpleTestCase) | `py -3.12 manage.py test scheduling.tests.NoShowPredicateTests` | ❌ W0 (extend scheduling/tests.py) | ⬜ pending |
| JOB-02a | Coupling: resolver ABSENT ⇔ predicate for identical inputs (scan & sweep never disagree) | unit (SimpleTestCase) | `py -3.12 manage.py test scheduling.tests.CouplingIntegrityTests` | ❌ W0 | ⬜ pending |
| JOB-02b | Sweep marks an unscanned no-show ABSENT independent of any scan | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ W0 | ⬜ pending |
| JOB-02b | Sweep backfills past-date no-shows (self-heal after scheduler outage) | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ W0 | ⬜ pending |
| JOB-02b | **Online exclusion:** sweep does NOT mark an online (`declared_modality or schedule.modality == online`) no-show Absent — leaves it `scheduled` | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ W0 | ⬜ pending |
| JOB-02b / criterion 5 | Idempotency: active / completed / already-absent untouched on rerun | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ W0 | ⬜ pending |
| JOB-02b | Every sweep-marked absence writes an `AuditLog` (`session.marked_absent`, `by=sweep`) | integration | `py -3.12 manage.py test scheduling.tests.SweepTests` | ❌ W0 | ⬜ pending |
| JOB-02c | Contradictory occupancy (2 active sessions / one room) raises ONE IFO conflict notification | integration | `py -3.12 manage.py test scheduling.tests.RoomConflictTests` | ❌ W0 | ⬜ pending |
| JOB-02c | Dedup: a second sweep does NOT re-notify an unresolved conflict; auto-resolves when cleared | integration | `py -3.12 manage.py test scheduling.tests.RoomConflictTests` | ❌ W0 | ⬜ pending |
| JOB-02c | `release_room()` stamps `room_released_at` + audits; the **sweep NEVER stamps it** | integration | `py -3.12 manage.py test ops.tests.ReleaseRoomTests` | ❌ W0 (ops/tests.py) | ⬜ pending |
| NOTIF-00 | `notify(role=...)` fans out to all active users of that role | integration | `py -3.12 manage.py test ops.tests.NotifyTests` | ❌ W0 | ⬜ pending |
| NOTIF-00 | Scan room-change / force-handover route through `notify()` (IFO rows created, `type="room_event"`) | integration | `py -3.12 manage.py test web.tests.ScanNotifyTests` | ❌ W0 (web/tests.py) | ⬜ pending |
| NOTIF-00 | `_notify_ifo` is gone; no inline `Notification.objects.create` outside `ops/notify.py` | unit (source guard) | `py -3.12 manage.py test ops.tests.SingleWritePathTests` | ❌ W0 | ⬜ pending |
| ENV-04 | Job wrapper records a `JobRun` (ok, rows_affected) on success | integration | `py -3.12 manage.py test ops.tests.JobRunTests` | ❌ W0 | ⬜ pending |
| ENV-04 | Job failure records `status=failed` AND notifies System Admins (only on failure) | integration | `py -3.12 manage.py test ops.tests.JobRunTests` | ❌ W0 | ⬜ pending |
| ENV-04 | Booting the Django app does NOT start a scheduler (no per-worker double-fire) | unit (guard) | `py -3.12 manage.py test ops.tests.NoImplicitSchedulerTests` | ❌ W0 | ⬜ pending |
| ENV-04 | `runscheduler` registers exactly 3 jobs (materialize / sweep / weekly_report) | unit | `py -3.12 manage.py test scheduling.tests.SchedulerWiringTests` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scheduling/tests.py` — add `NoShowPredicateTests`, `CouplingIntegrityTests`, `SweepTests`, `RoomConflictTests`, `SchedulerWiringTests` (file exists; extend it — resolver + MSSQL foundation tests already live here; reuse the `make_session(...)` factory at ~L135).
- [ ] `ops/tests.py` — add `NotifyTests`, `SingleWritePathTests`, `JobRunTests`, `NoImplicitSchedulerTests`, `ReleaseRoomTests` (file exists; extend).
- [ ] `web/tests.py` — add `ScanNotifyTests` (verifies the migrated `notify()` call sites).
- [ ] Shared fixture: reuse `scheduling.tests.make_session(...)` as the session factory; add a helper spinning up two active sessions sharing one room for conflict tests.
- [ ] Framework install: **none** — Django test runner + MSSQL `test_fluxtrack` already in place and green (Phase 1).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| APScheduler dedicated process actually fires jobs on the 5-min cadence in a live run | ENV-04 | Wall-clock scheduler timing over minutes isn't unit-testable without freezing time across a process boundary; wiring/registration IS unit-tested (`SchedulerWiringTests`), but the live tick is observational | Run `py -3.12 manage.py runscheduler`, confirm a `JobRun` row appears for `sweep` within ~5 min and no duplicate rows appear when a second web worker is also running |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

# Session — 2026-07-03: Phase 2 discussed, planned, executed + verified

## What was done

- **Phase 1 executed + completed** (`/gsd:execute-phase 1`): 3 plans across 2 waves,
  all verified against real SQL Server (LocalDB). MSSQL cutover shipped with an
  env-driven `DB_TRUSTED_CONNECTION` toggle (LocalDB + Windows auth in dev, SQL-auth
  in prod). ENV-01/ENV-02 complete.
- **Phase 2 discussed** (`/gsd:discuss-phase 2`): locked four behavior decisions —
  sweep every 5 min, room-conflict notifications deduped until resolved, **no
  timer-based auto-release** (cut; room release moves to MOD-03 / Phase 4), and
  job-failure surfacing (record `JobRun` + notify System Admins on failure only).
  Amended **JOB-02c** and Phase-2 success criterion #2 in `REQUIREMENTS.md` /
  `ROADMAP.md` to match the auto-release cut.
- **Online-session model clarified (user input).** Online classes get the **same
  grace period** as F2F, and are **Checker-verified via the class's public MS Teams
  link** (the online analog of a room scan), not faculty-self-declared. This is a
  Phase-3 capability — captured into ROADMAP Phase 3 (new criterion #6) and amended
  into **CHK-02 / CHK-03**, flagged to reconcile with FAC-08. For Phase 2 the sweep
  **excludes online** from Absent-marking until that verify path ships.
- **Phase 2 planned** (`/gsd:plan-phase 2`): research (HIGH confidence) → Nyquist
  VALIDATION.md → 5 plans in 3 waves → plan-checker **PASSED first pass**.
- **Phase 2 executed** (`/gsd:execute-phase 2`): all 5 plans, TDD (RED→GREEN),
  atomic commits. Verifier confirmed 5/5 must-haves against real source + a live
  re-run of the suite.

## Plans shipped (Phase 2)

- **02-01** (wave 1) — extracted `is_no_show_past_grace` shared predicate; resolver
  and sweep provably agree; 16 legacy resolver tests preserved (JOB-02a).
- **02-02** (wave 1) — `ops/notify.py::notify()` single write path; both
  `web/scan.py` call sites migrated; `_notify_ifo` deleted; source-guard test (NOTIF-00).
- **02-03** (wave 2) — status sweep + `RoomConflictFlag` deduped conflict flags;
  online excluded (Phase-3 hook); sweep never stamps `room_released_at` (JOB-02b/c).
- **02-04** (wave 2) — `release_room()` helper in `ops/occupancy.py`, built + tested,
  zero Phase-2 callers (reserved for MOD-03) (JOB-02c).
- **02-05** (wave 3) — `runscheduler` (`BlockingScheduler`, 3 jobs), `JobRun`
  observability, `run_job` failure-only admin notify, APScheduler pinned `<4` (ENV-04).

## Key finding — the MSSQL sweep bug (caught by live verification)

The verifier's human-verification step (driving the sweep against a real database)
surfaced a genuine defect unit tests missed:

- **Bug:** `sweep_no_shows` (and `detect_room_conflicts`' auto-resolve loop) iterated
  a `SELECT` cursor via `.iterator()` while issuing per-row `save()` + `AuditLog`
  INSERTs inside the loop. On SQL Server / pyodbc (single active result set per
  connection, MARS off) this raises `HY010 "Function sequence error (SQLFetch)"` as
  soon as there are real F2F no-shows to mark. Unit tests passed only because 1–2
  rows drain the cursor before the first write.
- **Fix** (`92b7027`): materialize each candidate queryset into a list before
  mutating (cursor closed first). Added a 5-row batch regression test.
- **Confirmed live on the dev MSSQL DB:** a fabricated batch of 5 F2F no-shows now
  marks 5/5 Absent, `run_job` status `ok`, no error. Fabricated rows cleaned up.
- Scheduler wiring re-confirmed on real settings: `build_scheduler()` → one
  `BlockingScheduler`, exactly 3 jobs (materialize 6h, sweep 5m, weekly_report
  Mon 06:00), unstarted.

Lesson worth keeping: **on MSSQL, never mutate rows while iterating an open query
cursor** — materialize first (`list(qs)`), or use bulk `.update()`.

## State at session end

- **Phases 1–2 of 8 complete**, both verified against real SQL Server.
- Requirements complete this milestone: ENV-01/02, NOTIF-00, JOB-02a/b/c, ENV-04.
- New dev-DB tables applied during testing: `ops_roomconflictflag`, `ops_jobrun`.
- Docs refreshed: `README.md` (MSSQL setup, jobs/scheduler, structure, status) and
  new **`docs/PROGRESS.md`** collaborator status board.
- GSD note: the CLI moved this session to `~/.claude/gsd-core/bin/gsd-tools.cjs`.

## Next up

**Phase 3 — Duty Assignments & Checker Verification.** Already pre-loaded with the
Checker-verifies-online-via-MS-Teams-link design (ROADMAP criterion #6 + amended
CHK-02/03). Start with `/gsd:discuss-phase 3`.

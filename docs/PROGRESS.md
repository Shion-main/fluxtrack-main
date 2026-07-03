# FluxTrack — Progress Board

**Last updated:** 2026-07-03
**Milestone:** v1.2 — *Faculty can request a lead-time-gated modality shift that a
Dean approves, with rooms auto-released or auto-assigned, and the SRS brought back
in sync with reality.*

This is the collaborator-facing status board. For the authoritative detail behind
every item, see the tracked planning artifacts under **`.planning/`** (roadmap,
per-phase context/research/plans/verification) and the formal **`FluxTrack_SRS.md`**.

---

## At a glance

**3 of 8 phases complete**, all verified against real SQL Server.

```
Phase 1  ████████████  ✓ Complete   MSSQL Environment & Data Foundation
Phase 2  ████████████  ✓ Complete   Correctness Foundations
Phase 3  ████████████  ✓ Complete   Duty Assignments & Checker Verification
Phase 4  ░░░░░░░░░░░░  ○ Next        Modality Shift Approval & SRS v1.2
Phase 5  ░░░░░░░░░░░░  ○ Pending     Notifications — Read Surface & Web Push
Phase 6  ░░░░░░░░░░░░  ○ Pending     Reporting Engine & Reporting Surfaces
Phase 7  ░░░░░░░░░░░░  ○ Pending     Remaining Operational Surfaces
Phase 8  ░░░░░░░░░░░░  ○ Pending     Auth Cutover & AWS Deployment
```

Requirements: **15 of 57 built** this milestone (ENV-01/02, NOTIF-00, JOB-02a/b/c,
ENV-04, IFO-06, CHK-01/02/03/04/05/07/08), on top of the previously-shipped
foundation (scan resolver, Faculty check-in, IFO room/schedule surface).

---

## Phase status

| # | Phase | Status | Requirements | Notes |
|---|-------|--------|--------------|-------|
| 1 | MSSQL Environment & Data Foundation | ✓ Complete | ENV-01, ENV-02 | Runs on SQL Server; timezone + collation round-trips proven |
| 2 | Correctness Foundations | ✓ Complete | NOTIF-00, JOB-02a/b/c, ENV-04 | Shared `notify()`, status sweep, dedicated scheduler |
| 3 | Duty Assignments & Checker Verification | ✓ Complete | IFO-06, CHK-01..05/07/08 | Floor assignments gate on-duty Checker; room scan + photo + verify/flag; floor board; online verify via MS Teams link; offline replay. 103 tests green, code review clean |
| 4 | Modality Shift Approval & SRS v1.2 | ○ Pending | MOD-01..06, DOC-01 | Dean-approved shift; `release_room()` gets its caller here |
| 5 | Notifications — Read Surface & Web Push | ○ Pending | NOTIF-01/02/03 | In-app list + VAPID push + mute prefs |
| 6 | Reporting Engine & Reporting Surfaces | ○ Pending | RPT-01..05, IFO-09, DEAN-01..04, HR-01..03 | One shared aggregate layer |
| 7 | Remaining Operational Surfaces | ○ Pending | GRD-01..05, IFO-01b/02/03b/05/08, FAC-08/11/12, SYS-04 | Guard, IFO ops, Faculty self-service, job monitoring |
| 8 | Auth Cutover & AWS Deployment | ○ Pending | AUTH-01/03/05, DEPLOY-01/02 | Entra ID SSO, Tailwind build, EC2 + RDS |

---

## What's built and verified

### Previously shipped (foundation)
- Django 6 domain models across `accounts / campus / scheduling / verification / ops`,
  env-driven settings, policy system (`get_policy()` / `SystemSetting`)
- Role-routed home + DEBUG dev-login stub (stands in for Entra ID until Phase 8)
- Scan resolver pure core + Faculty check-in end-to-end (SCAN-01..07, FAC-01..06/09/10)
- IFO room + schedule surface, per-term view, live "today" polling
- CSV schedule import + session materialization (management commands)

### Phase 1 — MSSQL Environment & Data Foundation ✓
- FluxTrack runs on **SQL Server** via `mssql-django` (Django pinned 6.0.6,
  mssql-django 1.7.3); single env-driven `mssql` DB branch in `config/settings.py`
- Timezone-aware timestamps round-trip through `datetime2` with **no Asia/Manila
  drift** (proven by test)
- **Case-sensitive collation** (`Latin1_General_100_CS_AS`) on `qr_token` /
  `manual_code` only; the rest of the DB stays case-insensitive (e.g. emails)
- Registrar CSV import + materialization reproduce the validated slice on MSSQL

### Phase 2 — Correctness Foundations ✓
- **`notify()`** (`ops/notify.py`) — the single notification write path; the ad-hoc
  `_notify_ifo` is gone and no inline notifier remains
- **Status sweep** (`scheduling/jobs.py`, `run_status_sweep` command) — marks
  no-show F2F/Blended sessions Absent independent of any scan, using the **same
  grace predicate the live scanner uses** (so scan and sweep never disagree);
  backfills past dates (self-heals after an outage); idempotent; audited.
  (Online sessions were excluded here until Phase 3 shipped the Checker/Teams
  verify path — that exclusion has since been removed; see Phase 3.)
- **Room-conflict flags** — contradictory occupancy raises one **deduped**
  IFO notification (`RoomConflictFlag`), auto-resolving when cleared
- **`release_room()`** (`ops/occupancy.py`) — shared occupancy helper, built and
  tested now; its only caller arrives in Phase 4 (modality approval). No
  timer-based auto-release.
- **Dedicated scheduler** (`runscheduler` command) — one `BlockingScheduler`
  running materialize / sweep / weekly-report, never inside a web worker; each run
  records a `JobRun` (last-run status), and failures notify System Admins.

> A note on rigor: the Phase 2 sweep bug (`HY010` on SQL Server from mutating rows
> while a query cursor was open) was caught by live-testing against a real database,
> not just unit tests — fixed and re-confirmed live before the phase was accepted.

### Phase 3 — Duty Assignments & Checker Verification ✓
- **Pure gating core** (`verification/resolver.py`) — `resolve_checker_scan` decides
  every checker outcome (off-duty / wrong-floor / empty / absent-excluded /
  already-verified / actionable) with no ORM; the web layer re-runs it server-side
  on every action and never trusts client-supplied gating. `distribute_online_sessions`
  is the deterministic round-robin core.
- **IFO duty assignments** (`web/ifo.py`, IFO-06) — non-admin UI to assign
  Checkers/Guards to floors (shift or standing) and grant online duty; granting
  online duty round-robins that date's unowned online sessions to a covering checker.
- **Checker room scan** (`web/checker.py`, CHK-01..05) — QR/manual-code → current
  room session state + scheduled faculty photo for identity match; records Verify /
  Flag-identity / Flag-not-present / Confirm-empty; flags reach IFO **and** HR via
  `notify()`. Off-duty/wrong-floor/stale scans are refused and write nothing.
- **Floor board** (CHK-07) — htmx-polled, color+icon+label state cards, coverage %,
  and an oldest-unverified-first priority queue, scoped to the checker's active
  floors, Absent excluded.
- **Online verification** (CHK-02/03) — an on-duty checker opens the class's public
  MS Teams link and records Verify (which **activates** the session, the online
  analog of a room check-in) or Flag-not-present (→ Absent). This is what lets the
  JOB-02 sweep safely **include** online sessions — the Phase-2 exclusion was
  removed in lockstep with its tests.
- **Offline queue** (CHK-08) — scans captured offline queue in IndexedDB
  (`static/checker/offline_queue.js`) and replay on reconnect to a server endpoint
  that **re-validates each one against current state** through the same pure core —
  applied if still valid (original scan time preserved), else recorded and flagged
  to IFO; idempotent by client uuid.

> A note on rigor: a standard code review of the phase surfaced 5 correctness/robustness
> issues below the (clean) pure core — including an online round-robin that ignored the
> shift window (risking false "Absent" for genuinely-attended online classes) and a
> stale-session latch that could block verifying a room's later class. All were fixed
> with regression tests before the phase was accepted (full suite: 103 green).

---

## Running it yourself

See the [README](../README.md) for full setup. Quick version:

```
py -3.12 -m pip install --user -r requirements.txt
# set DB vars in .env (SQL Server) — see README "First-time setup"
py -3.12 manage.py migrate
py -3.12 manage.py seed_demo
py -3.12 manage.py runserver 127.0.0.1:8020
```

Background jobs: `py -3.12 manage.py run_status_sweep` (one-shot) or
`py -3.12 manage.py runscheduler` (all jobs on cadence).
Tests: `py -3.12 manage.py test`.

---

## How the work is planned

FluxTrack is built phase-by-phase with the GSD (get-shit-done) workflow. Each phase
leaves a durable trail under `.planning/phases/NN-name/`:

- `NN-CONTEXT.md` — decisions locked before planning
- `NN-RESEARCH.md` — technical investigation
- `NN-NN-PLAN.md` — executable task plans (one per wave item)
- `NN-NN-SUMMARY.md` — what each plan actually shipped
- `NN-VERIFICATION.md` — goal-backward verification report

Roadmap and requirement traceability live in `.planning/ROADMAP.md` and
`.planning/REQUIREMENTS.md`. Session-by-session narrative is in `docs/sessions/`.

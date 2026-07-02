---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: "**Goal**: Faculty can request a lead-time-gated modality shift that a Dean approves, with rooms auto-released or auto-assigned, and the SRS brought back in sync with reality."
status: executing
stopped_at: Completed 01-03-PLAN.md
last_updated: "2026-07-02T19:20:19.931Z"
last_activity: 2026-07-03 — Executed plan 01-03 (surgical CS collation on qr_token/manual_code + collation round-trip tests)
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 3
  completed_plans: 3
  percent: 67
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-02)

**Core value:** A faculty member checks in with one action, and the resulting attendance record is trustworthy — presence physically verified, lateness captured, ghost bookings detected.
**Current focus:** Phase 1 — MSSQL Environment & Data Foundation

## Current Position

Phase: 1 of 8 (MSSQL Environment & Data Foundation)
Plan: 3 of 3 in current phase (all complete)
Status: Executing — Phase 1 complete (Wave 1: 01-01; Wave 2: 01-02 + 01-03 in parallel)
Last activity: 2026-07-03 — Executed plan 01-03 (surgical CS collation on qr_token/manual_code + collation round-trip tests)

Progress: [███████░░░] 67%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 20 | 3 tasks | 3 files |
| Phase 01 P02 | 3 | 2 tasks | 2 files |
| Phase 01 P03 | 15 | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: notify() write path (NOTIF-00) pulled forward into Phase 2 (correctness foundations) — it is a prerequisite for JOB-02 conflict flags AND modality approval notices; only NOTIF-01/02/03 read+push stay in Phase 5.
- [Roadmap]: JOB-02's Absent rule and the scan resolver's Absent rule must share ONE extracted predicate (Phase 2) — highest-risk coupling in the milestone.
- [Roadmap]: IFO-06 floor assignments land at the start of Phase 3 — they hard-block Checker on-duty gating (CHK-01).
- [Roadmap]: Reporting aggregates (RPT-01/04) built once in Phase 6; IFO-09, DEAN-04, and HR consume them — DEAN-04 dashboard therefore sits in Phase 6, not Phase 4.
- [Roadmap]: Auth (Entra) + AWS/Tailwind deploy deferred to Phase 8 so cutover risk never blocks feature work; dev-login stub carries every earlier phase.
- [Phase 01]: Local dev DB is SQL Server 2025 LocalDB + Windows auth (DB_TRUSTED_CONNECTION), not Express + SQL login — settings made env-driven so prod SQL-auth is unchanged
- [Phase 01]: No fix-forward migration needed: all 0001_initial migrations applied cleanly on MSSQL (nullable-unique azure_oid as filtered unique index); 7 users seeded, surface serves 200
- [Phase 01]: [Phase 01]: MSSQL datetime2 stores UTC and an aware Asia/Manila instant round-trips with zero 8h drift — proven by DatetimeRoundTripTests (16:30 UTC and 00:00 UTC cases)
- [Phase 01]: [Phase 01]: R3-slice import+materialize parity (17/10/15/18/18) reproduced on SQL Server; CI-safe synthetic fixture (data/fixtures/r3_synthetic.csv) keeps the import path testable without the gitignored PII CSV
- [Phase 01]: [Phase 01]: CS token collation landed via hand-written RunSQL migration — mssql-django 1.7.3 db_collation AlterField emits no-op SQL (sqlmigrate confirmed); RunSQL owns DROP/ALTER/re-ADD
- [Phase 01]: [Phase 01]: qr_token/manual_code are NOT NULL → backed by UNIQUE CONSTRAINTS (not filtered indexes); recollation drops/re-adds the constraint by dynamically-discovered name

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 1]: MSSQL runtime behavior (collation case-insensitivity, datetime2/timezone round-trip) unproven — needs a dedicated spike with real round-trip tests before JOB-02 is built on top. An 8h Asia/Manila drift is possible if UTC storage is not verified.
- [Phase 8]: Tailwind v4 / Franken UI 2.1 build path (npm-plugin vs standalone-CLI) is MEDIUM confidence — needs a short build spike before committing to build-time-npm/Node-free production.
- [Phase 8]: Entra cutover can lock out all production login if DEBUG=False is flipped before SSO is proven end-to-end — keep a break-glass superuser; verify on staging.
- [General]: RDS SQL Server Express 10 GB cap + per-write AuditLog rows needs a retention/pruning job before real usage (address in Phase 8).

## Session Continuity

Last session: 2026-07-02T19:16:52.488Z
Stopped at: Completed 01-03-PLAN.md
Resume file: None

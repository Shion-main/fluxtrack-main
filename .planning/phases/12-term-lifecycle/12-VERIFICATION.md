---
phase: 12-term-lifecycle
verified: 2026-07-22T14:02:59+08:00
status: human_needed
score: 16/16 must-haves structurally and locally runtime verified
behavior_unverified: 2
overrides_applied: 0
---

# Phase 12: Term Lifecycle Verification Report

**Phase Goal:** Close/archive a term read-only, create and activate the next term without destroying attendance history, and make every live/reporting surface explicitly term-scoped.

**Verdict:** Implementation and local MSSQL runtime verification complete; production-shaped migration rehearsal and browser acceptance remain human gates.

## Goal Achievement

| Area | Status | Evidence |
|---|---|---|
| Explicit DRAFT/ACTIVE/ARCHIVED lifecycle and single-ACTIVE/date constraints | VERIFIED | `scheduling/models.py`, `scheduling/migrations/0008_term_lifecycle.py`, `scheduling/term_scope.py` |
| Transactional create/activate/close/reopen with authorization, preflight, audit, and rollback | VERIFIED | `scheduling/term_lifecycle.py`, lifecycle service/view regression tests |
| Draft-bound import and activation-owned materialization | VERIFIED | `ops/import_staging.py`, `web/ifo.py`, `scheduling/materialization.py` |
| Archived service/command/live-surface write freeze | VERIFIED | Plan 12-05/06 services, jobs, commands, and direct-ID guards |
| Django Admin archive freeze and AcademicTerm delete refusal | VERIFIED | `scheduling/admin_guards.py`, scheduling/verification/ops admin classes |
| Active-term operational jobs and role surfaces | VERIFIED | `scheduling/jobs.py`, `verification/services.py`, live web controllers |
| Term-owned weekly reports and term-qualified storage identity | VERIFIED | `ops/models.py`, `ops/migrations/0006_term_ownership.py`, `ops/reports.py` |
| HR, IFO, and Dean reports/exports use bounded explicit ReportScope | VERIFIED | `web/reporting_common.py`, `web/hr.py`, `web/ifo.py`, `web/dean.py` |
| Stored downloads prevent cross-term and cross-department PK access | VERIFIED | IFO pk+term lookup; Dean pk+term+department lookup |
| Legacy destructive/implicit term paths removed | VERIFIED | Production source audit: no `DEFAULT_TERM`, AcademicTerm boolean lookup/order, first-row term fallback, reset/clone UI path |

## Verification Performed

- All 12 plan summaries exist; execution manifest reports `incomplete_count: 0`.
- `python -m compileall -q scheduling verification ops web` passed.
- `git diff --check` passed.
- Targeted Phase 12 suite passed on MSSQL LocalDB: 187 tests, 0 failures.
- Full configured suite passed on MSSQL LocalDB: 1,219 tests, 0 failures, 2 intentional skips.
- `manage.py check` passed with no issues and `makemigrations --check --dry-run` reported no changes.
- `sqlmigrate scheduling 0008` confirmed the date CHECK, filtered single-ACTIVE unique index, and legacy `is_active` removal.
- `sqlmigrate ops 0006` confirmed the corrected MSSQL-safe order: backfill, legacy unique removal, `term_id` NOT NULL alteration, then term-qualified uniqueness and foreign keys.
- Migration regression tests exercised exact-one, zero-candidate, overlapping-candidate, and cross-term same-week report cases, including return-to-leaf cleanup after fail-loud cases.
- Production coupling audit passed for legacy/default term selection and known archived writer seams.
- Migration source inspection confirmed status backfill, fail-loud ambiguity checks, date ordering, filtered single-ACTIVE uniqueness, and term-qualified WeeklyReport uniqueness.
- Worktree audit shows no uncommitted Phase 12 code; only pre-existing `.planning/config.json` and untracked support/graphify files remain.

## Remaining Human Gates

1. Rehearse both migrations on a sanitized production-shaped MSSQL copy and compare pre/post term, schedule, session, attendance, assignment, and report counts.
2. Browser-walk the IFO lifecycle confirmations, archived Admin refusals, and HR/IFO/Dean term selectors/exports/downloads.

The local environment was hydrated with CPython 3.12 and the pinned dependencies, and all automated gates ran against SQL Server LocalDB rather than SQLite. The two remaining gates require production-shaped data and interactive browser judgment, so they are not claimed from automated tests.

## Human Verification Checklist

- Close a finished term, confirm all historical rows/reports remain readable and all archived POST/Admin mutation paths refuse without row or audit changes.
- Create/import a blank Draft, activate it, and confirm materialization plus the sole-ACTIVE invariant roll back atomically on injected failure.
- Switch HR, IFO, and Dean reporting between old/new terms; confirm bounded dates, preserved links, matching screen/export data, and no same-date cross-term rows.
- Attempt stored report downloads using a valid foreign-term PK and, for Dean, a foreign-department PK; confirm 404.

## Gaps Summary

No structural or local-runtime implementation gaps found. Phase completion remains `human_needed` solely for the production-shaped migration rehearsal and interactive browser acceptance above.

---
_Verified: 2026-07-22_
_Verifier: Codex (direct verification)_

---
phase: 12-term-lifecycle
verified: 2026-07-22T03:35:00+08:00
status: human_needed
score: 16/16 must-haves structurally verified
behavior_unverified: 4
overrides_applied: 0
---

# Phase 12: Term Lifecycle Verification Report

**Phase Goal:** Close/archive a term read-only, create and activate the next term without destroying attendance history, and make every live/reporting surface explicitly term-scoped.

**Verdict:** Implementation complete; runtime and migration rehearsal still require the hydrated Django/MSSQL environment.

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
- Production coupling audit passed for legacy/default term selection and known archived writer seams.
- Migration source inspection confirmed status backfill, fail-loud ambiguity checks, date ordering, filtered single-ACTIVE uniqueness, and term-qualified WeeklyReport uniqueness.
- Worktree audit shows no uncommitted Phase 12 code; only pre-existing `.planning/config.json` and untracked support/graphify files remain.

## Runtime Gates Still Required

1. Run the targeted Phase 12 Django suites and the full configured MSSQL suite.
2. Run `manage.py check`, `makemigrations --check --dry-run`, and inspect `sqlmigrate scheduling 0008` plus `sqlmigrate ops 0006`.
3. Rehearse both migrations on a sanitized production-shaped MSSQL copy and compare pre/post term, schedule, session, attendance, assignment, and report counts.
4. Browser-walk the IFO lifecycle confirmations, archived Admin refusals, and HR/IFO/Dean term selectors/exports/downloads.

These gates could not start locally: `py -3.12` reports no installed interpreter, and the available Python environment lacks Django. SQLite or source-only checks are not claimed as substitutes for MSSQL constraint/race acceptance.

## Human Verification Checklist

- Close a finished term, confirm all historical rows/reports remain readable and all archived POST/Admin mutation paths refuse without row or audit changes.
- Create/import a blank Draft, activate it, and confirm materialization plus the sole-ACTIVE invariant roll back atomically on injected failure.
- Switch HR, IFO, and Dean reporting between old/new terms; confirm bounded dates, preserved links, matching screen/export data, and no same-date cross-term rows.
- Attempt stored report downloads using a valid foreign-term PK and, for Dean, a foreign-department PK; confirm 404.

## Gaps Summary

No structural implementation gaps found. Phase completion is held at `human_needed` solely because the required Django/MSSQL and browser gates are unavailable in this shell.

---
_Verified: 2026-07-22_
_Verifier: Codex (direct verification)_

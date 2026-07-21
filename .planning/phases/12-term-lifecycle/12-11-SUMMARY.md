---
phase: 12-term-lifecycle
plan: 11
subsystem: admin
tags: [django-admin, archive-freeze, term-lifecycle]
requires: [12-05, 12-06]
provides:
  - "Shared Admin guard for direct and nested term ownership"
  - "Archive-safe save, single delete, and all-or-nothing bulk delete"
  - "Unconditional AcademicTerm deletion refusal"
requirements-completed: [A4, IFO-04]
status: complete
completed: 2026-07-22
---

# Phase 12 Plan 11: Django Admin Archive Freeze Summary

**Django Admin can no longer bypass the lifecycle archive freeze for scheduling, verification, or weekly-report records.**

## Accomplishments

- Added `TermOwnedAdminGuardMixin` and explicit owner resolution for direct term, schedule, and session paths.
- Guarded save, single-delete, and delete-selected paths for AcademicBreak, Schedule, Session, Assignment, CheckerValidation, and WeeklyReport.
- Denied AcademicTerm deletion in every lifecycle state while preserving the stronger AuditLog read-only policy and unrelated admin behavior.
- Added zero-mutation, writable-control, mixed-selection, nested-owner, and source-contract coverage.

## Commits

- `ba01360` test(12-11): add admin archive freeze coverage
- `1903230` feat(12-11): guard scheduling admin mutations
- `fbd5529` feat(12-11): guard term-owned cross-app admin

## Verification

- Python compilation passed for all modified admin and test modules.
- `git diff --check` and source inventory passed.
- Django runtime tests remain blocked because this machine has no usable Django environment; committed tests should be rerun in the hydrated environment.

## Self-Check: PASSED

All specified admin models are guarded, AcademicTerm deletion is unreachable through Admin, and no unrelated working-tree changes were included.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-22*

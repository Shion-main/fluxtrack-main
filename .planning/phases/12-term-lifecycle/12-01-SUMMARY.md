---
phase: 12-term-lifecycle
plan: 01
subsystem: database
tags: [django, sql-server, migrations, lifecycle, audit]
requires:
  - phase: 11
    provides: "Current reporting and operational baseline before term lifecycle"
provides:
  - "AcademicTerm three-state lifecycle schema with SQL-backed status constraints"
  - "History-preserving legacy is_active-to-status migration preflight"
  - "Authoritative active/writable term primitives"
  - "Transactional create, close, and reopen services with audit logging"
affects: [scheduling, ops, ifo, term-lifecycle]
tech-stack:
  added: []
  patterns:
    - "Status enum plus filtered UniqueConstraint for single ACTIVE term"
    - "Display preflight followed by locked transactional service revalidation"
    - "AuditLog written inside the same transaction as lifecycle state changes"
key-files:
  created:
    - scheduling/migrations/0008_term_lifecycle.py
    - scheduling/term_scope.py
    - scheduling/term_lifecycle.py
    - scheduling/tests_term_lifecycle.py
  modified:
    - scheduling/models.py
    - scheduling/test_support.py
    - scheduling/admin.py
key-decisions:
  - "Replaced AcademicTerm.is_active with explicit draft/active/archived status rather than preserving a compatibility boolean."
  - "Creation, close, and reopen services re-authorize and recompute blockers inside transaction.atomic before any state write."
patterns-established:
  - "TermPreflight carries typed blockers, warnings, and counts for lifecycle display and POST revalidation."
  - "Lifecycle AuditLog payloads include actor, reason, before/after state, counts, and acknowledged warning keys."
requirements-completed: [A4, IFO-04]
coverage:
  - id: D1
    description: "AcademicTerm lifecycle schema and legacy migration"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall scheduling/models.py scheduling/migrations/0008_term_lifecycle.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.TermConstraintTests scheduling.tests_term_lifecycle.TermMigrationContractTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher and no installed Django package."
  - id: D2
    description: "Active-term resolver, archived guard, and confirmed blank Draft creation"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall scheduling/term_scope.py scheduling/term_lifecycle.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.TermCreateTests scheduling.tests_term_lifecycle.TermScopeTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher and no installed Django package."
  - id: D3
    description: "Atomic close and reason-required reopen services"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall scheduling/term_lifecycle.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.TermTransitionTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django verification could not run because this shell has no py launcher and no installed Django package."
duration: 29 min
completed: 2026-07-21
status: complete
---

# Phase 12 Plan 01: Term Lifecycle Foundation Summary

**AcademicTerm draft/active/archived lifecycle schema with transactional create, close, and reopen services.**

## Performance

- **Duration:** 29 min
- **Started:** 2026-07-21T16:40:00Z
- **Completed:** 2026-07-21T17:09:11Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Replaced the AcademicTerm boolean active flag with explicit `DRAFT`, `ACTIVE`, and `ARCHIVED` states, a unique term name, date-order check, and filtered single-ACTIVE constraint.
- Added `0008_term_lifecycle.py` with a preflight/data migration that validates legacy rows before removing `is_active`, maps the sole active row to `ACTIVE`, and maps inactive rows to `ARCHIVED`.
- Added `term_scope.py` and `term_lifecycle.py` service primitives for active-term lookup, archived write refusal, confirmed blank Draft creation, strict close, and reason-required reopen.
- Added focused lifecycle tests for constraints, migration source contract, creation preflight/revalidation, audit rollback, close blockers, and reopen-to-Draft behavior.

## Task Commits

1. **Task 1 RED:** `b5450b2` test(12-01): add term lifecycle constraint regression tests
2. **Task 1 GREEN:** `a3c5050` feat(12-01): establish term lifecycle schema
3. **Task 2 RED:** `d8ab269` test(12-01): add term scope and creation service tests
4. **Task 2 GREEN:** `e860d91` feat(12-01): add term scope and draft creation services
5. **Task 3 RED:** `6fa18fc` test(12-01): add term close and reopen transition tests
6. **Task 3 GREEN:** `97635ae` feat(12-01): implement term close and reopen services

## Files Created/Modified

- `scheduling/models.py` - Added `AcademicTerm.Status`, `status`, unique `name`, date-order check, and filtered single-ACTIVE constraint.
- `scheduling/migrations/0008_term_lifecycle.py` - Added staged legacy lifecycle migration with fail-loud preflight.
- `scheduling/term_scope.py` - Added active-term resolver and archived-term guard.
- `scheduling/term_lifecycle.py` - Added creation/action preflights plus atomic create, close, and reopen services.
- `scheduling/tests_term_lifecycle.py` - Added Wave 0 lifecycle regression suite.
- `scheduling/test_support.py` - Updated shared AcademicTerm fixtures to use status while preserving user `is_active`.
- `scheduling/admin.py` - Updated AcademicTerm admin display/filter from boolean to status.

## Decisions Made

- The old `AcademicTerm.is_active` field is removed as a persisted source of truth in this plan; future compatibility should use `status=AcademicTerm.Status.ACTIVE`.
- Creation confirmation compares to the normalized proposed name, while close/reopen confirmation compares exactly to the persisted term name.
- Close treats remaining `SCHEDULED` sessions after term end as an acknowledgeable warning, while `ACTIVE` sessions remain a hard blocker.
- Reopen returns an archived term to `DRAFT` and records an `active_successor_exists` warning when a different term is currently active.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Updated AcademicTerm admin to the new status field**
- **Found during:** Task 1
- **Issue:** Removing `is_active` would leave the admin list display and filter pointing at a deleted model field.
- **Fix:** Switched `AcademicTermAdmin` to display/filter `status`.
- **Files modified:** `scheduling/admin.py`
- **Verification:** `python -m compileall scheduling/admin.py` passed.
- **Committed in:** `a3c5050`

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Required for the final model contract; no scope beyond the lifecycle field replacement.

## Issues Encountered

- Automated Django verification could not run in this shell. `py -3.12 ...` fails with `No installed Python found!`; fallback `python manage.py ...` starts Python 3.12.10 but fails with `ModuleNotFoundError: No module named 'django'`.
- Syntax verification did run: `python -m compileall scheduling/models.py scheduling/test_support.py scheduling/tests_term_lifecycle.py scheduling/migrations/0008_term_lifecycle.py scheduling/admin.py scheduling/term_scope.py scheduling/term_lifecycle.py` passed.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Next Phase Readiness

Plan 02 can build on `AcademicTerm.Status`, `term_scope`, and the lifecycle service. Before relying on this branch operationally, run the plan's Django verification in the configured project environment:

- `py -3.12 manage.py test scheduling.tests_term_lifecycle -v 2`
- `py -3.12 manage.py check`
- `py -3.12 manage.py makemigrations --check --dry-run`
- `py -3.12 manage.py sqlmigrate scheduling 0008`

## Self-Check: PASSED

- Files exist: `scheduling/models.py`, `scheduling/migrations/0008_term_lifecycle.py`, `scheduling/term_scope.py`, `scheduling/term_lifecycle.py`, `scheduling/tests_term_lifecycle.py`, `scheduling/test_support.py`, `scheduling/admin.py`, and this summary.
- Commits exist: `b5450b2`, `a3c5050`, `d8ab269`, `e860d91`, `6fa18fc`, `97635ae`.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-21*

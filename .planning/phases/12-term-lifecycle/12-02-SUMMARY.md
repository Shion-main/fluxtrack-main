---
phase: 12-term-lifecycle
plan: 02
subsystem: scheduling
tags: [django, term-lifecycle, scheduler, materialization, sql-server]
requires:
  - phase: 12-01
    provides: "AcademicTerm status lifecycle, active-term resolver, and transactional create/close/reopen services"
provides:
  - "Explicit-term session materialization service with active-only public command adapter"
  - "Atomic Draft activation that materializes the configured readiness horizon before ACTIVE status"
  - "Active-term command and scheduler scope regression coverage"
affects: [scheduling, term-lifecycle, jobs, ifo]
tech-stack:
  added: []
  patterns:
    - "Reusable batch service returns MaterializationResult(created, existing, skipped)"
    - "Public command resolves authoritative ACTIVE term or exact ACTIVE --term before delegating"
    - "Lifecycle activation owns the only production Draft materialization override"
key-files:
  created:
    - scheduling/materialization.py
  modified:
    - scheduling/management/commands/materialize_sessions.py
    - scheduling/term_lifecycle.py
    - scheduling/tests_term_lifecycle.py
    - scheduling/tests.py
key-decisions:
  - "Kept Draft materialization private to activate_term; public materialize_sessions refuses Draft and Archived terms."
  - "Activation records materialization counts in the term.activated AuditLog payload and lets unexpected materialization failures escape for full rollback."
patterns-established:
  - "Activation preflight treats empty schedules as an acknowledgeable warning, not a blocker."
  - "Scheduler materialization remains coupled to the command adapter rather than duplicating term resolution or recurrence logic."
requirements-completed: [A4, IFO-04]
coverage:
  - id: D1
    description: "Explicit-term materialization service and active-only command adapter"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall scheduling/materialization.py scheduling/management/commands/materialize_sessions.py scheduling/tests.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.ActivationMaterializationTests scheduling.tests.MaterializeCommandTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django tests could not run because this shell has no py launcher and no installed Django package."
  - id: D2
    description: "Atomic Draft activation with policy-horizon readiness materialization and rollback"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall scheduling/term_lifecycle.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.ActivationMaterializationTests scheduling.tests_term_lifecycle.SingleActiveTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django tests could not run because this shell has no py launcher and no installed Django package."
  - id: D3
    description: "Command and scheduler select exactly one intended ACTIVE term"
    requirement: IFO-04
    verification:
      - kind: other
        ref: "compileall plus fixed-string source checks for runscheduler call_command and command materialize_term delegation"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.ActiveTermJobScopeTests scheduling.tests_term_lifecycle.ActivationMaterializationTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Django tests could not run because this shell has no py launcher and no installed Django package."
duration: 9 min
completed: 2026-07-21
status: complete
---

# Phase 12 Plan 02: Term Lifecycle Readiness Activation Summary

**Explicit-term materialization and atomic Draft activation with active-only public scheduling jobs.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-07-21T17:14:40Z
- **Completed:** 2026-07-21T17:23:37Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Extracted `materialize_term(term, start, days, allow_draft=False)` into `scheduling/materialization.py`, preserving recurrence, breaks/suspensions, approved-shift hooks, idempotent `get_or_create`, and MSSQL list-before-write discipline.
- Converted `materialize_sessions` into a thin adapter with optional `--term`, authoritative ACTIVE fallback, Draft/Archived refusal, and `CommandError` expected-state failures.
- Added `activate_term` so Draft activation revalidates under lock, materializes the configured horizon inside the same transaction, writes `term.activated`, and rolls back sessions/status/audit on failure.
- Added regression coverage for explicit-term materialization, activation rollback/warnings, single-ACTIVE refusal, active-only command selection, idempotent reruns, and scheduler adapter coupling.

## Task Commits

1. **Task 1 RED:** `e079b07` test(12-02): add failing tests for explicit term materialization
2. **Task 1 GREEN:** `4dc7e54` feat(12-02): extract explicit term materialization
3. **Task 2 RED:** `fc4666d` test(12-02): add failing tests for atomic term activation
4. **Task 2 GREEN:** `53c7ca9` feat(12-02): activate draft terms atomically
5. **Task 3:** `1036bad` test(12-02): prove active term materialization scope

## Files Created/Modified

- `scheduling/materialization.py` - New explicit-term materialization service and approved-shift application path.
- `scheduling/management/commands/materialize_sessions.py` - Active-only command adapter with optional exact ACTIVE `--term`.
- `scheduling/term_lifecycle.py` - Added activation preflight/input validation and atomic `activate_term`.
- `scheduling/tests_term_lifecycle.py` - Added lifecycle/materialization, activation rollback, single-active, and command-scope tests.
- `scheduling/tests.py` - Added `MaterializeCommandTests` and updated touched fixtures to the `AcademicTerm.status` contract.

## Decisions Made

- Public materialization never receives the Draft override; only `activate_term` calls `materialize_term(..., allow_draft=True)` in production source.
- Empty schedules block activation until the warning key is acknowledged, then activation may proceed with zero sessions.
- The scheduler continues to call `materialize_sessions`, so it inherits active-term resolution instead of owning any term selection logic.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Automated Django verification could not run in this shell. `py -3.12 ...` fails with `No installed Python found!`; fallback `python manage.py check` fails with `ModuleNotFoundError: No module named 'django'`.
- Syntax/source verification did run: compileall passed for all modified Python files, and source checks confirmed command delegation, removal of the old active `.first()` lookup from the command, and lifecycle ownership of the Draft override.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Next Phase Readiness

Plan 03 can build on explicit `materialize_term`, active-only command behavior, and `activate_term`. Before operational use, run the Django/MSSQL verification in the configured project environment:

- `py -3.12 manage.py test scheduling.tests_term_lifecycle scheduling.tests -v 2`
- `py -3.12 manage.py check`

## Self-Check: PASSED

- Files exist: `scheduling/materialization.py`, `scheduling/management/commands/materialize_sessions.py`, `scheduling/term_lifecycle.py`, `scheduling/tests_term_lifecycle.py`, `scheduling/tests.py`, and this summary.
- Commits exist: `e079b07`, `4dc7e54`, `fc4666d`, `53c7ca9`, `1036bad`.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-21*

---
phase: 12-term-lifecycle
plan: 05
subsystem: scheduling
tags: [django, term-lifecycle, archive-freeze, commands, services]
requires:
  - phase: 12-02
    provides: "Explicit active-term resolver and active-only materialization command boundary"
  - phase: 12-03
    provides: "Durable term ownership for staged imports and weekly reports"
  - phase: 12-04
    provides: "Writable-term import guard and Draft-bound browser import flow"
provides:
  - "Shared archive write freeze enforced across schedule, suspension, modality, and merge service writers"
  - "Retired reset_term command that exits non-zero before any destructive ORM path"
  - "Authoritative active-term command resolution for seed_term and audit_merge_coverage"
  - "Writer-matrix tests for service and command archived-term refusal"
affects: [scheduling, term-lifecycle, commands, ifo]
tech-stack:
  added: []
  patterns:
    - "Public service mutator -> derive owning term -> lock/re-read -> require_writable_term -> write/audit/notify"
    - "Bulk suspension and merge writers include schedule__term predicates before status-guarded updates"
    - "Legacy operator commands fail closed instead of retaining historical deletion logic"
key-files:
  created:
    - .planning/phases/12-term-lifecycle/12-05-SUMMARY.md
  modified:
    - scheduling/schedule_ops.py
    - scheduling/suspensions.py
    - scheduling/services.py
    - scheduling/merge.py
    - scheduling/management/commands/reset_term.py
    - scheduling/management/commands/seed_term.py
    - scheduling/management/commands/audit_merge_coverage.py
    - scheduling/tests_term_lifecycle.py
    - scheduling/tests_suspensions.py
    - web/tests_schedule_ops.py
    - web/ifo.py
key-decisions:
  - "reset_term remains as a command name only, raising CommandError with lifecycle guidance before any ORM access."
  - "Modality request writers refuse mixed-term ownership instead of guessing which term owns the request."
  - "seed_term keeps its active-term operator flow but resolves through require_active_term and scopes term-owned rewrites to that term."
patterns-established:
  - "Archived writer matrix snapshots domain/audit/notification counts before attempting a refused service or command writer."
  - "Same-date cross-term fixtures prove suspension and merge bulk paths cannot mutate rows outside the owning term."
requirements-completed: [A4, IFO-04]
coverage:
  - id: D1
    description: "Archive freeze across reusable schedule, suspension, modality, and merge services"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall -q scheduling/schedule_ops.py scheduling/suspensions.py scheduling/services.py scheduling/merge.py web/ifo.py scheduling/tests_term_lifecycle.py scheduling/tests_suspensions.py web/tests_schedule_ops.py"
        status: pass
      - kind: other
        ref: "source inventory for require_writable_term/term predicates in service writers"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeServiceTests scheduling.tests_suspensions web.tests_schedule_ops -v 2"
        status: fail
    human_judgment: true
    rationale: "Django/MSSQL tests could not run because this shell has no py launcher and plain Python has no Django package."
  - id: D2
    description: "Retired reset_term and active/writable retained command resolution"
    requirement: A4
    verification:
      - kind: other
        ref: "python -m compileall -q scheduling/management/commands/reset_term.py scheduling/management/commands/seed_term.py scheduling/management/commands/audit_merge_coverage.py scheduling/tests_term_lifecycle.py"
        status: pass
      - kind: other
        ref: "source guard: reset_term has no DEFAULT_TERM, 2nd Term string, .delete(), Session.objects, or Schedule.objects; retained commands have no boolean active lookup"
        status: pass
      - kind: unit
        ref: "py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeCommandTests -v 2"
        status: fail
    human_judgment: true
    rationale: "Command behavior tests could not run in this shell; compile and source guards passed as fallback."
duration: 49 min
completed: 2026-07-21
status: complete
---

# Phase 12 Plan 05: Archive Writer Freeze Summary

**Archived terms now fail closed across reusable service and command writers before schedule/session history can be changed.**

## Performance

- **Duration:** 49 min
- **Started:** 2026-07-21T17:35:00Z
- **Completed:** 2026-07-21T18:24:08Z
- **Tasks:** 2
- **Files modified:** 11

## Accomplishments

- Added writable-term guards to schedule edit/cancel, suspension declare/lift, modality submit/withdraw/reject/apply, and merge present/absent propagation.
- Scoped bulk suspension and merge candidate queries by owning term so same-date rows from another term cannot be flipped by status-guarded updates.
- Replaced `reset_term` with a permanent non-zero `CommandError` adapter and removed its default target and destructive implementation.
- Updated `seed_term` and `audit_merge_coverage` to use authoritative active-term resolution; `seed_term` now scopes term-owned rewrites to the selected active term.
- Added `ArchiveFreezeServiceTests`, `ArchiveFreezeCommandTests`, and same-date suspension fixtures for service/command writer coverage.

## Task Commits

1. **Task 1 RED:** `ad73984` test(12-05): add archive freeze writer matrix
2. **Task 1 GREEN:** `4ac77ff` feat(12-05): guard archived service writers
3. **Task 2 GREEN:** `fb9f03d` feat(12-05): retire reset term command

## Files Created/Modified

- `scheduling/schedule_ops.py` - Locks schedule owner term and calls `require_writable_term` before schedule/session writes.
- `scheduling/suspensions.py` - Locks writable term, filters flips by `schedule__term`, and refuses archived declare/lift paths.
- `scheduling/services.py` - Enforces one writable owning term across modality submit/decision/apply writers.
- `scheduling/merge.py` - Guards anchor term and filters merge candidates to the anchor term before bulk updates.
- `scheduling/management/commands/reset_term.py` - Retired non-zero command adapter with lifecycle guidance only.
- `scheduling/management/commands/seed_term.py` - Active-term resolver and term-scoped rewrites for sessions, validations, assignments, and modality requests.
- `scheduling/management/commands/audit_merge_coverage.py` - Shared active-term resolver for the read-only audit command.
- `scheduling/tests_term_lifecycle.py` - Service and command archive-freeze writer matrix.
- `scheduling/tests_suspensions.py` - Same-date cross-term suspension fixtures and status-based term fixtures.
- `web/tests_schedule_ops.py` - Status-based active term fixture update.
- `web/ifo.py` - Adjacent schedule/suspension create boundaries now use the shared active/writable term helper.

## Decisions Made

- `reset_term` was retired rather than made explicit-target: old runbooks now fail loudly while preserving the command name.
- Mixed-term modality requests are refused at the service boundary because a single request cannot safely own more than one archive/freeze state.
- `seed_term` remains an active-term demo-data command, but term-owned destructive rewrites are narrowed to that active term.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Guarded adjacent IFO create boundaries**
- **Found during:** Task 1 (service writer guard implementation)
- **Issue:** Schedule creation and suspension declaration are public writer boundaries in `web/ifo.py`, while the plan's file list named the service modules. Leaving the adjacent view boundary unguarded would make the create side inconsistent with update/cancel and declare/lift.
- **Fix:** Reused `get_active_term()` and `require_writable_term()` in the affected IFO create paths.
- **Files modified:** `web/ifo.py`
- **Verification:** Compileall and source inventory passed; Django tests are environment-blocked.
- **Committed in:** `4ac77ff`

---

**Total deviations:** 1 auto-fixed (1 missing critical guard)
**Impact on plan:** The adjacent change was required to satisfy the plan's public-mutator archive-freeze contract. No unrelated behavior was refactored.

## Issues Encountered

- Required Django verification could not run in this shell:
  - `py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeServiceTests scheduling.tests_suspensions web.tests_schedule_ops -v 2` -> `No installed Python found!`
  - `py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeCommandTests -v 2` -> `No installed Python found!`
  - `py -3.12 manage.py test scheduling.tests_term_lifecycle scheduling.tests_suspensions web.tests_schedule_ops -v 2` -> `No installed Python found!`
  - `python manage.py check` -> `ModuleNotFoundError: No module named 'django'`
- Fallback verification passed:
  - `python -m compileall -q` over all touched Python source and test files.
  - Source guard confirmed `reset_term.py` has no `DEFAULT_TERM`, hardcoded 2nd-term string, `.delete()`, `Session.objects`, or `Schedule.objects`.
  - Source inventory confirmed the retained service/command writers use `require_writable_term`, `require_active_term`, or explicit status-based active scope.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None.

## Threat Flags

None beyond the plan threat model. This plan narrows existing service/command writer surfaces and retires the legacy destructive command.

## Next Phase Readiness

Plan 06 can build on service/command archive refusal and the retired reset path. Before operational use, run the Django/MSSQL verification in the configured project environment:

- `py -3.12 manage.py test scheduling.tests_term_lifecycle scheduling.tests_suspensions web.tests_schedule_ops -v 2`
- `py -3.12 manage.py check`

## Self-Check: PASSED

- Files exist: all modified code/test files and this summary.
- Commits exist: `ad73984`, `4ac77ff`, `fb9f03d`.
- No tracked files were deleted by either implementation commit.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-21*

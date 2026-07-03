---
phase: 04-modality-shift-approval-srs-v1-2
plan: 08
subsystem: ui
tags: [django, htmx, franken-ui, dean, modality-shift, authz, idor, approval]

# Dependency graph
requires:
  - phase: 04-05
    provides: apply_approval + reject_modality_shift (the re-gated decision consequences the views delegate to)
  - phase: 04-07
    provides: faculty surface + make_shift_fixture shape the Dean surface mirrors for consistency
provides:
  - Dean department-scoped pending-approval queue at /dean/requests
  - Dean approve (POST-only, service-delegated) at /dean/requests/<pk>/approve
  - Dean reject (POST-only, reason-required) at /dean/requests/<pk>/reject
  - dean_required role gate (clone of ifo_required)
  - DeanModalityAuthzTests (non-Dean denial, cross-department IDOR, ->Online apply, D-07 no-room denial, reject-with/without-reason)
affects: [phase-05 (notification read surface)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Role gate cloned from ifo_required: dean_required denies unless role==DEAN or is_superuser"
    - "Object-level re-gate delegated to the service: approve/reject re-fetch by pk and let apply_approval/reject_modality_shift re-check Dean+same-department+PENDING inside the transaction (never a client snapshot)"
    - "D-07 no-room DENIED is a returned outcome, not an exception: the view surfaces the denial message at 200; only a genuine service refusal (cross-department/non-pending) renders at 400"
    - "reject requires a non-empty reason (400 otherwise) mirroring ifo.assignment_create validated-POST"

key-files:
  created:
    - web/dean.py
    - templates/dean/queue.html
    - templates/dean/_queue.html
  modified:
    - web/urls.py
    - web/tests.py

key-decisions:
  - "The view never mutates state: apply_approval/reject_modality_shift own the transaction, availability re-check, audit, and notifications; the view only fetches by pk and renders the outcome"
  - "A no-room ->F2F approval is surfaced by inspecting the returned request.status == DENIED (the service handles the all-or-nothing rollback); this is a 200 with a denial message, never a 400/500"
  - "The second-department test fixture uses prefix 'dep2' (distinct first-two-chars from 'web08') because make_shift_fixture derives room.manual_code from prefix[:2] and would otherwise collide on a UNIQUE constraint"
  - "queue is scoped server-side (filter department=request.user.department); another department's request is excluded from the queryset, never merely hidden in the template"

patterns-established:
  - "Dean approval surface: @dean_required on every view; POST-only + service guard-delegation for every decision"
  - "Approve/reject htmx-swap the #dean-queue-panel partial in place; error/denial both re-render the updated queue"

requirements-completed: [MOD-02, MOD-04]

coverage:
  - id: D1
    description: "dean_required + queue: department-scoped PENDING list behind the role gate; other departments never listed; non-Dean denied"
    requirement: "MOD-02"
    verification:
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_non_dean_approve_denied"
        status: pass
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_cross_department_approve_refused_stays_pending"
        status: pass
    human_judgment: false
  - id: D2
    description: "approve: POST-only, delegates to apply_approval; ->Online apply sets effective-Online + room_released_at and notifies requester + IFO"
    requirement: "MOD-02"
    verification:
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_online_approve_applies_and_notifies"
        status: pass
    human_judgment: false
  - id: D3
    description: "no-room ->F2F approve is a terminal DENIED with a reason and the session provably unchanged (D-07 REVISED)"
    requirement: "MOD-04"
    verification:
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_no_room_f2f_approve_denies_session_unchanged"
        status: pass
    human_judgment: false
  - id: D4
    description: "reject: POST-only, records reason + notifies requester; empty reason -> 400, stays PENDING"
    requirement: "MOD-02"
    verification:
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_reject_records_reason_and_notifies"
        status: pass
      - kind: integration
        ref: "web/tests.py#DeanModalityAuthzTests.test_reject_empty_reason_is_400_and_stays_pending"
        status: pass
    human_judgment: false
  - id: D5
    description: "Dean queue + approve/reject controls render correctly (Franken UI consistency, mobile-first, htmx swap)"
    verification: []
    human_judgment: true
    rationale: "The queue's visual layout, Franken UI consistency, and the in-place htmx swap after a decision need an in-browser human check; only the server-side authz/consequence is unit-proven."

# Metrics
duration: 30min
completed: 2026-07-04
status: complete
---

# Phase 04 Plan 08: Dean Modality-Shift Approval Surface Summary

**Department-scoped Dean pending-approval queue with POST-only approve/reject wired to the 04-05 apply/reject services, cloning the role-gate + validated-POST + object-level re-gate patterns so an approval becomes a room release/assignment or a terminal D-07 denial.**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-07-04T00:00:00Z
- **Completed:** 2026-07-04T00:30:00Z
- **Tasks:** 3
- **Files modified:** 5 (3 created, 2 modified)

## Accomplishments
- `dean_required` decorator: clone of `ifo_required` denying unless `role == Role.DEAN` or superuser.
- `queue` view + `dean/queue.html` + `dean/_queue.html`: PENDING requests scoped strictly to `department=request.user.department`, showing requester, target modality, window, affected schedules, any time-move, and the preferred room. Another department's request is excluded server-side.
- `approve` view: POST-only, `@dean_required`; re-fetches by pk and delegates to `apply_approval` (the service re-checks Dean+same-department+PENDING and owns the transaction/audit/notify). A ->Online approval applies the release; a no-room ->F2F approval returns a terminal `DENIED` request surfaced as a clear denial message; a cross-department/non-pending approve raises and re-renders the queue at 400.
- `reject` view: POST-only, requires a non-empty reason (400 otherwise), delegates to `reject_modality_shift`.
- `DeanModalityAuthzTests` (6 cases); full `web` suite green (18 tests); full project suite green (204 tests).

## Task Commits

Each task was committed atomically:

1. **Task 1: dean_required gate + department-scoped approval queue** - `21279cb` (feat)
2. **Task 2: approve/reject POST actions wired to 04-05 services** - `2b66500` (feat)
3. **Task 3: DeanModalityAuthzTests** - `f6e6f3d` (test)

**Plan metadata:** (docs: complete plan — final commit)

## Files Created/Modified
- `web/dean.py` - New: `dean_required` decorator + `queue`/`approve`/`reject` views + `_queue_ctx` helper.
- `web/urls.py` - Added `dean_queue` / `dean_approve` / `dean_reject` routes and imported `dean`.
- `web/tests.py` - Added `DeanModalityAuthzTests` (6 cases); extended the scheduling.models import (`Modality`, `ModalityShiftItem`) and imported `IN_WINDOW_DATE`.
- `templates/dean/queue.html` - Page shell hosting the `#dean-queue-panel`.
- `templates/dean/_queue.html` - htmx-swappable queue partial with approve/reject action forms and error/message alerts.

## Decisions Made
- The view never mutates state directly: it fetches by pk and calls the service, which owns the transaction, availability re-check, audit, and notifications (the TOCTOU/IDOR-safe delegation, T-04-01/T-04-03).
- The D-07 no-room denial is detected by inspecting the returned `request.status == DENIED` (the service performs the all-or-nothing rollback and sets DENIED) and rendered at 200 with a message — a genuine service refusal (cross-department / non-pending) is the only 400 path.
- The cross-department test uses fixture prefix `dep2` (not `web08b`) because `make_shift_fixture` derives `room.manual_code` from `prefix[:2]`; two prefixes sharing their first two chars collide on a UNIQUE constraint.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The cross-department test initially used a second fixture prefix (`web08b`) that shared its first two characters with the base fixture (`web08`); since `make_shift_fixture` builds `room.manual_code` from `prefix[:2]`, this violated the `UQ_campus_room_manual_code` UNIQUE constraint. Switched the second department's prefix to `dep2` (distinct first-two-chars). Caught by the failing test before commit; all 6 pass after the fix.
- The full test suite regenerated `FluxTrack_SRS.docx` as a side-effect of another plan's DOC-01 management command; this file is out of scope for 04-08 and was reverted (not committed) to keep the working tree clean.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Dean approval surface complete and authz/consequence-proven; the modality-shift approval workflow (faculty submit -> Dean decide -> room release/assign or terminal denial) is now end-to-end.
- Notification rows are written by the 04-05 services; the in-app read surface remains Phase 5 (out of scope here).
- The queue's visual/mobile-first polish and the htmx in-place swap (coverage D5) warrant an in-browser human check during phase verification.

## Self-Check: PASSED

All created/modified files present on disk; all three task commits (`21279cb`, `2b66500`, `f6e6f3d`) exist in git history.

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-04*

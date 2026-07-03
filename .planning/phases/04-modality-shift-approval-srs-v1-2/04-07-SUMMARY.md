---
phase: 04-modality-shift-approval-srs-v1-2
plan: 07
subsystem: ui
tags: [django, htmx, franken-ui, faculty, modality-shift, authz, idor]

# Dependency graph
requires:
  - phase: 04-04
    provides: submit_modality_shift / withdraw_modality_shift creation-side services
  - phase: 04-05
    provides: apply_approval + resolve_shift_room availability semantics the picker mirrors
  - phase: 04 (ops/availability)
    provides: available_rooms_for / available_times_for picker queries
provides:
  - Faculty submit form (availability-first picker) at /faculty/modality/new
  - Faculty "my requests" status list at /faculty/modality/mine
  - Faculty withdraw (POST-only, guard-delegated) at /faculty/modality/<pk>/withdraw
  - FacultyModalityAuthzTests (non-faculty denial, IDOR foreign-withdraw, 400-not-500, routed submit)
  - FAC-07 self-declare path retired (this workflow is the sole faculty modality-change entry point)
affects: [04-08 (dean surface / SRS v1.2), phase-05 (notification read surface)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Validated-POST, 400-not-500 view mirroring ifo.assignment_create (parse_date/enum/pk-numeric before ORM)"
    - "Availability-first picker: view reads available_rooms_for/available_times_for; room pick is a preference only (server re-resolves at approval)"
    - "IDOR re-gate delegated to the service: withdraw view re-fetches by pk and lets withdraw_modality_shift re-check requester+PENDING"
    - "htmx submit with HX-Redirect on success; form partial re-render at 400 on error"

key-files:
  created:
    - templates/faculty/modality_new.html
    - templates/faculty/_modality_form.html
    - templates/faculty/modality_mine.html
  modified:
    - web/faculty.py
    - web/urls.py
    - web/tests.py

key-decisions:
  - "Submit is htmx-driven with HX-Redirect to the my-requests list on success; a plain (non-htmx) POST falls back to a 302 redirect"
  - "Preferred room is passed to the service as a preference only; the view never trusts the client room pk (service re-resolves at approval, D-06)"
  - "Withdraw re-renders the full modality_mine.html page (status 400 on refusal) rather than a new partial, honoring the plan's 3-template artifact list"
  - "Valid-submit test uses a session 30 days out so the real-clock lead-time gate passes (the view cannot inject a fake now)"

patterns-established:
  - "Faculty modality surface: @faculty_required on every view; POST-only + guard-delegation for state changes"
  - "Availability-first picker preview built from the next upcoming session per active schedule"

requirements-completed: [MOD-01, MOD-05, MOD-06]

coverage:
  - id: D1
    description: "modality_new: availability-first submit form; validates format before write, 400-not-500, calls submit_modality_shift; never trusts client room pk"
    requirement: "MOD-01"
    verification:
      - kind: integration
        ref: "web/tests.py#FacultyModalityAuthzTests.test_malformed_submit_is_400_not_500"
        status: pass
      - kind: integration
        ref: "web/tests.py#FacultyModalityAuthzTests.test_valid_submit_creates_one_pending_routed_to_dean"
        status: pass
      - kind: integration
        ref: "web/tests.py#FacultyModalityAuthzTests.test_non_faculty_denied"
        status: pass
    human_judgment: false
  - id: D2
    description: "modality_mine list + withdraw: requester-scoped status list; withdraw refused for foreign/non-pending tickets (IDOR guard delegated to service)"
    requirement: "MOD-05"
    verification:
      - kind: integration
        ref: "web/tests.py#FacultyModalityAuthzTests.test_foreign_withdraw_refused_and_stays_pending"
        status: pass
    human_judgment: false
  - id: D3
    description: "FAC-07 self-declare path retired: modality-shift request is the sole faculty modality-change entry point"
    requirement: "MOD-06"
    verification:
      - kind: integration
        ref: "web/tests.py#FacultyModalityAuthzTests.test_no_faculty_self_declare_route_exists"
        status: pass
    human_judgment: false
  - id: D4
    description: "Availability-first picker UI (room pick vs let-the-app-decide, alternative-time surfacing) renders correctly and reads real availability"
    verification: []
    human_judgment: true
    rationale: "The picker's visual layout, Franken UI consistency, and mobile-first usability need an in-browser human check; only the server-side validation/authz is unit-proven."

# Metrics
duration: 35min
completed: 2026-07-03
status: complete
---

# Phase 04 Plan 07: Faculty Modality-Shift Surface Summary

**Availability-first faculty submit form + "my requests" status list with guard-delegated withdraw, wiring the faculty side of the modality-shift workflow to the 04-04/04-05 services and retiring the FAC-07 self-declare path.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-07-03T16:00:00Z
- **Completed:** 2026-07-03T16:35:00Z
- **Tasks:** 3
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments
- `modality_new` view: GET renders an availability-first picker (rooms/times from `available_rooms_for`/`available_times_for`); POST validates format before any write, re-renders `_modality_form.html` at 400 on bad input, re-resolves schedules to the requester's own, passes the room pick as a mere preference, and calls `submit_modality_shift`.
- `modality_mine` view + template: requester-scoped status list (pending/approved/rejected/withdrawn/denied) with decision reason and a Withdraw control shown only while PENDING.
- `modality_withdraw` view: POST-only, re-fetches by pk and delegates the requester+PENDING guard to `withdraw_modality_shift` (IDOR-safe).
- FAC-07 retired: a module docstring documents the replacement and `FacultyModalityAuthzTests` asserts no self-declare route exists.
- 5 passing authz/validation tests; full `web` suite green (12 tests).

## Task Commits

Each task was committed atomically:

1. **Task 1: modality_new view + availability-first picker template** - `1f62967` (feat)
2. **Task 2: modality_mine list + withdraw** - `815f2c3` (feat)
3. **Task 3: Faculty authz/validation tests + FAC-07 retirement note** - `7847c9e` (test)

**Plan metadata:** (docs: complete plan — final commit)

## Files Created/Modified
- `web/faculty.py` - Added `modality_new`, `modality_mine`, `modality_withdraw` views + `_modality_new_ctx`/`_modality_mine_ctx` helpers; module docstring documents the FAC-07 retirement.
- `web/urls.py` - Added `faculty_modality_new` / `_mine` / `_withdraw` routes.
- `web/tests.py` - Added `FacultyModalityAuthzTests` (5 cases).
- `templates/faculty/modality_new.html` - Submit page shell hosting the `#modality-panel` picker.
- `templates/faculty/_modality_form.html` - Availability-first picker partial (htmx-swappable, 400 error re-render target).
- `templates/faculty/modality_mine.html` - Requester-scoped status list with withdraw control.

## Decisions Made
- Submit is htmx-driven; success returns `HX-Redirect` to the my-requests list, with a plain 302 redirect fallback for non-htmx clients (keeps the Django test Client assertion simple and gives real users a full-page nav rather than nesting the list into the form panel).
- The preferred room is only a preference passed to the service; the view never trusts the client room pk (the service re-resolves rooms at Dean approval, D-06).
- Withdraw re-renders the full `modality_mine.html` page (400 on refusal) instead of introducing a fourth template, honoring the plan's 3-template artifact list.

## Deviations from Plan

None - plan executed exactly as written. (The FAC-07 retirement docstring specified in Task 3 was authored alongside the Task 1 module rewrite since both live in `web/faculty.py`; it landed in the Task 1 commit rather than the Task 3 commit — content-identical to the plan, no behavior change.)

## Issues Encountered
- A `{% comment %}` header placed before `{% extends %}` in `modality_mine.html` would violate Django's "extends must be first tag" rule; reordered so `{% extends %}` is first. Caught before commit; full suite green.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Faculty surface complete and authz/validation-proven. Ready for 04-08 (Dean approval queue + SRS v1.2).
- Notification rows are written by the 04-04/04-05 services; the in-app read surface remains Phase 5 (out of scope here).
- The picker's visual/mobile-first polish (coverage D4) warrants an in-browser human check during phase verification.

## Self-Check: PASSED

All created/modified files present on disk; all three task commits (`1f62967`, `815f2c3`, `7847c9e`) exist in git history.

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-03*

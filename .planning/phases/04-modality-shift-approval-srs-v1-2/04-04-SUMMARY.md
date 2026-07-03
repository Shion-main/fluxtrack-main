---
phase: 04-modality-shift-approval-srs-v1-2
plan: 04
subsystem: scheduling
tags: [modality-shift, lead-time-gate, dean-routing, service-layer, tdd]
requires:
  - "scheduling.models: ModalityShiftRequest, ModalityShiftItem, ModalityShiftStatus (04-01)"
  - "scheduling.test_support.make_shift_fixture (04-01)"
  - "ops.availability: available_rooms_for, faculty_has_conflict (04-03)"
  - "ops.policy.get_policy, ops.notify.notify, ops.models.AuditLog (Phase 2)"
  - "accounts.models: Role.DEAN, User.department (Phase 1)"
provides:
  - "scheduling.services.is_before_lead_cutoff(earliest_affected_date, now)"
  - "scheduling.services.route_to_dean(faculty)"
  - "scheduling.services.affected_sessions(request)"
  - "scheduling.services.submit_modality_shift(...)"
  - "scheduling.services.withdraw_modality_shift(request, actor)"
  - "scheduling.services.reject_modality_shift(request, dean, reason)"
  - "scheduling.services.ModalityShiftError"
affects:
  - "04-05 (apply-approval consumes the persisted ModalityShiftItem set + stamped Dean)"
  - "04-06 (materialize consumes the same items for born-released/assigned)"
  - "04-08 (Dean-gated approval checks against the Dean stamped here)"
tech-stack:
  added: []
  patterns:
    - "gather-context -> validate -> transactional write -> notify-once -> AuditLog (mirrors verification/services.py)"
    - "server-clock-only lead-time gate (never client time); policy-driven lead via get_policy"
    - "object-level ownership/role + PENDING re-gate re-read inside the transaction (03-02 re-gate)"
key-files:
  created:
    - "scheduling/services.py"
  modified:
    - "scheduling/tests.py"
decisions:
  - "Refusals raise a domain ModalityShiftError (message carried for a friendly 400) rather than returning a sentinel; success returns the persisted ModalityShiftRequest"
  - "time_move is a (new_start_time, new_end_time) pair applied to every item; preferred_rooms is a {schedule|pk: Room} mapping re-validated against available_rooms_for (client room pk never trusted)"
  - "withdraw/reject re-fetch the request fresh inside the transaction (no select_for_update) to re-gate status without MSSQL lock quirks"
metrics:
  duration: "~30 min"
  completed: "2026-07-03"
  tasks: 3
  commits: 6
  tests-added: 21
status: complete
---

# Phase 4 Plan 04: Modality-Shift Creation Side Summary

Server-validated request-creation side of the modality-shift workflow: a policy-driven, server-clock-only lead-time gate (D-02), deterministic department-Dean routing (D-09), in-window scope resolution over one atomic multi-schedule ticket (D-01/D-19), a faculty double-book guard for bundled time-moves (D-16/D-17), and withdraw/reject state transitions with re-gated ownership guards and D-11 notifications — all in `scheduling/services.py`, mirroring the proven `verification/services.py` shape.

## What Was Built

Six functions in a new `scheduling/services.py`, driven test-first (RED test commit then GREEN feat commit per task):

- **`is_before_lead_cutoff(earliest_affected_date, now)`** — cutoff = Manila-midnight of `(earliest - get_policy("modality_shift_lead_days"))`; refuses at/after, allows strictly before. Reads the lead from the policy register (never a literal) and compares against a server clock only.
- **`route_to_dean(faculty)`** — active `Role.DEAN` of the faculty's department, or defensive `None` on a missing department / vacant seat (one-Dean-per-department is a runtime invariant, `.first()` is defensive).
- **`affected_sessions(request)`** — per-item SCHEDULED/ACTIVE sessions inside `[window_start, window_end]`; out-of-window sessions are never returned.
- **`submit_modality_shift(...)`** — validates target modality/window, gates on the earliest affected date, routes to the Dean, creates ONE `ModalityShiftRequest` (PENDING) with one `ModalityShiftItem` per schedule, notifies the Dean once, and writes an AuditLog — all inside `transaction.atomic()`. Time-moves are accepted only with an F2F/Blended target (D-16) and only when they never double-book the faculty (D-17); preferred rooms are re-validated server-side.
- **`withdraw_modality_shift(request, actor)`** — requester + PENDING (re-read in-txn) -> WITHDRAWN, audited, silent (no notify).
- **`reject_modality_shift(request, dean, reason)`** — routed department Dean + PENDING -> REJECTED with reason/decided_by/decided_at, audited, notifies the requester once.

`ModalityShiftError` is the single creation-side refusal type; any guard failure raises it and writes nothing (no partial state change).

## Verification

- `py -3.12 manage.py test scheduling.tests.LeadTimeGateTests scheduling.tests.DeanRoutingTests scheduling.tests.ShiftScopeTests scheduling.tests.WithdrawTests -v2` — 21 tests, green.
- `py -3.12 manage.py test scheduling` — 65 tests, green (no regression).

Boundary coverage includes Manila 23:59-vs-00:00 both directions, policy-override of the lead (proving `get_policy` not a literal), earliest-date keying for windowed requests, recurring-window in/out-of-window resolution, multi-schedule item-per-schedule atomicity, time-move Online-refusal + double-book refusal + valid-move ticket, and IDOR guards (foreign withdraw, cross-department reject, non-PENDING transitions).

## Deviations from Plan

### Auto-added test coverage (Rule 2 — correctness completeness)

Beyond the plan's named suites I added guard tests directly implied by the threat model and acceptance criteria: `test_gate_reads_policy_not_a_literal` (T-04-04 — proves policy-driven lead), `test_too_late_request_refused` and `test_missing_dean_refused_at_submit` (submit-time D-02/D-09 refusals), `test_valid_f2f_time_move_creates_time_move_ticket` (positive D-16 path), and `test_cross_department_dean_reject` / `test_non_pending_reject_refused` (T-04-01 IDOR). No production behavior changed — these exercise the specified behavior more completely.

No other deviations — the plan executed as written.

## Notes for Downstream Plans

- **04-05 (apply-approval)** consumes the persisted `ModalityShiftItem` set and the `dean` stamped on the request; it owns the `assigned_room` finalization (D-06) and the →Online `release_room()` / →F2F room-assign consequence — none of that is done here (submit changes no sessions).
- Refusals are raised as `ModalityShiftError`; the web layer (04-07/04-08) should catch it and render a friendly 400.
- `submit_modality_shift` validates a preferred room against `available_rooms_for(session)` (the session's own slot). For a bundled time-move the room is still finalized at approval, so preferred-room-at-the-new-slot validation is intentionally left to 04-05's approval re-resolution.

## Self-Check: PASSED

- FOUND: scheduling/services.py (is_before_lead_cutoff, route_to_dean, affected_sessions, submit_modality_shift, withdraw_modality_shift, reject_modality_shift)
- FOUND commits: 5c9e079, 3fe4fe8, e5fcd41, cb20286, 8824bd4, 03deaaf
- Tests: 21 new (4 suites) green; full scheduling suite 65 green

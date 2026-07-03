---
phase: 03-duty-assignments-checker-verification
plan: 02
subsystem: verification
tags: [checker, scan, pure-core, thin-apply, notify, gating, htmx, franken-ui]
requires:
  - verification.resolver.resolve_checker_scan (03-01)
  - verification.models.AssignmentScope / Assignment.scope (03-01)
  - verification.models.ValidationAction (VERIFIED / FLAG_* / VERIFIED_EMPTY, 03-01)
  - ops.notify.notify (Phase 2 single write path)
  - web/scan.py seam (pure-core / thin-apply / rate-limit / idempotency)
provides:
  - web.checker.checker_required (Role.CHECKER guard)
  - web.checker._active_floor_ids (current on-duty floor pks)
  - web.checker._room_session_state (F2F/Blended room state for the pure core)
  - web.checker._apply_action (CheckerValidation + AuditLog + IFO/HR notify)
  - web.checker.resolve / action / scan_page views + /checker/* routes
  - templates/checker/scan.html + _outcome.html (UI-SPEC-conformant)
affects:
  - 03-04 (floor board reuses _active_floor_ids + the room-state queryset)
  - 03-05 (online Verify-activation + Flag-not-present branch extend _apply_action)
  - 03-06 (offline replay re-runs resolve_checker_scan through the same seam)
tech-stack:
  added: []
  patterns: [pure-core-decides, thin-apply-audits, server-side-re-gate, notify-single-write-path, htmx-partial-outcome-chain]
key-files:
  created:
    - web/checker.py
    - templates/checker/scan.html
    - templates/checker/_outcome.html
  modified:
    - verification/tests.py
    - web/urls.py
    - web/views.py
decisions:
  - The action endpoint re-identifies the room from POST room_id and UNCONDITIONALLY re-runs resolve_checker_scan against current _active_floor_ids before any write — the client's gating is never trusted (T-03-03/05).
  - _active_floor_ids treats a standing FLOOR posting (date NULL) as always on-duty; a shift is on-duty when date==today and start<=now<=end (either time bound may be NULL).
  - identity_match is derived server-side (False for flag_identity_mismatch, True for verified) rather than trusting the client-sent hidden field.
  - Online sessions read as an empty room in this plan (no room-scan target); online Verify-activation and Flag-not-present are deferred to 03-05.
metrics:
  duration: ~6m
  completed: 2026-07-03
  tasks: 3
  files: 6
status: complete
---

# Phase 3 Plan 02: Checker Room-Scan Verification Summary

Built the on-duty Checker room-scan loop for F2F/Blended sessions — a `checker_required` surface that resolves a scanned room through the pure gating core from 03-01, returns the live session state plus the scheduled faculty's photo for identity matching, and records Verify / Confirm-empty (one tap) or note-required Flag identity-mismatch / Flag not-present, with flags fired to IFO **and** HR immediately via `notify()`. Every action POST is re-identified from `room_id` and re-gated server-side against current on-duty state before any write.

## What Was Built

### Task 1 — CheckerScanDBTests + fixture mixin (TDD RED)
`verification/tests.py` gains a DB-backed section: `_CheckerFixtureMixin` (mirrors `scheduling.tests._JobFixtureMixin`, minting distinct unique keys per `_room()`/`_faculty()`/`_checker()`/`_ifo_admin()`/`_hr_admin()` so one test persists many rows without a UNIQUE collision) and `CheckerScanDBTests` covering all seven behaviors — on-duty gating (off-duty/wrong-floor/actionable), session+photo surfacing, Verify → `verified_by_checker`, empty-note flag rejection, IFO+HR notify, the server-side action re-gate, and the `confirmed_absent` retirement guard. Tests drive the surface through Django's test `Client` over the `/checker/*` routes using the rate-limit-free QR-token payload path. Confirmed RED before Task 2 (six failed on 404 routing; the enum guard passed as it needs no route).

### Task 2 — web/checker.py + routes (+ templates, GREEN)
`web/checker.py` is a faithful mirror of `web/scan.py`'s seam:
- `checker_required` — `Role.CHECKER` guard (superuser bypass), mirroring `ifo_required`.
- `_active_floor_ids(user, now)` — the server's sole source of the checker's floors: active FLOOR-scoped CHECKER assignments, standing (date NULL) or shift-covering-now.
- `_room_from_payload` — QR token (rate-limit-free) or six-digit manual code (per-user-per-minute cache rate limit; audits `checker.rate_limited` / `checker.bad_manual_code`).
- `_room_session_state` — today's non-online, non-completed session in the room as a `_SessionState` value object (or `(None, None)` for an empty room); online reads as empty (03-05 owns online).
- `_apply_action` — thin write: `CheckerValidation` + `AuditLog`, and for both flags `notify(role=IFO_ADMIN)` **and** `notify(role=HR_ADMIN)`.
- `resolve` and `action` — both call `R.resolve_checker_scan`; `action` re-identifies the room from POST `room_id`, recomputes state, and unconditionally re-runs the pure core against `_active_floor_ids` before any write; non-actionable outcomes render a refusal partial (audited `checker.action_refused`) and write nothing; empty-note flags are rejected with a 200 error partial; applied actions are idempotency-guarded per `checker-idem:{user}:{session|room}:{minute}`.

Routes `/checker/scan`, `/checker/resolve`, `/checker/action` wired in `web/urls.py`.

### Task 3 — home wiring
`web/views.py` `SURFACES[Role.CHECKER]` "Scan a room" card now points at `/checker/scan`; "Floor view" stays `#` (03-04). The `checker/scan.html` + `_outcome.html` templates conform to the approved 03-UI-SPEC: mobile-first scan shell (camera + six-digit manual), a flat `data-outcome` chain over every resolver outcome, the faculty photo with an initials-avatar `{% else %}` fallback, one-tap Verify/Confirm-empty, and two note-required flag forms — each form carrying hidden `room_id` (and `session_id` when present) for server re-identification.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Templates authored in Task 2, not Task 3**
- **Found during:** Task 2
- **Issue:** The `resolve`/`action` views call `render(..., "checker/_outcome.html")`, and `CheckerScanDBTests` (Task 1) drive the surface through the Client. With the templates absent (planned for Task 3), every rendering test raised `TemplateDoesNotExist`, so Task 2's "tests green" done-criterion was unreachable.
- **Fix:** Authored `templates/checker/scan.html` and `_outcome.html` — already UI-SPEC-conformant — as part of the Task 2 commit so the endpoints render and the suite goes green. Task 3 then handled the `web/views.py` home wiring and verified template conformance.
- **Files modified:** templates/checker/scan.html, templates/checker/_outcome.html (committed in Task 2)
- **Commit:** f04f190

**2. [Rule 3 - Blocking] Multi-line `{# #}` comment broke template parse**
- **Found during:** Task 2
- **Issue:** The `_outcome.html` header used a multi-line `{# ... {% if/elif %} ... #}` comment; Django parsed the `{% if/elif %}` token inside it and raised `TemplateSyntaxError: Invalid block tag 'if/elif'`.
- **Fix:** Replaced it with a `{% comment %}…{% endcomment %}` block (no bare `{% %}` tokens inside).
- **Files modified:** templates/checker/_outcome.html
- **Commit:** f04f190

**3. [Adjustment] RED via routing 404, not ImportError**
- **Found during:** Task 1
- **Issue:** The plan expected RED via `ImportError`/`AttributeError` on `web.checker`. Importing `web.checker` at the top of `verification/tests.py` would have errored the whole module (breaking the passing pure `SimpleTestCase` suites too).
- **Fix:** Drove the DB tests through the test `Client` over the `/checker/*` routes instead; RED manifested as 404 (routes unwired) rather than an import error — still genuinely RED, never green-by-stub, and it keeps the pure suites importable. The plan explicitly permits the Client-driven approach.
- **Files modified:** verification/tests.py
- **Commit:** 2f6b214

## Verification Results

- `py -3.12 manage.py test verification.tests.CheckerScanDBTests` — 7 tests, OK (all CHK-01/02/03/04/05 behaviors incl. `test_action_refused_when_no_longer_on_duty`).
- `py -3.12 manage.py test verification scheduling web` — 59 tests, OK (no regression to Faculty scan / sweep / pure cores).
- Task-2 grep gates: `resolve_checker_scan` count >= 2 in `web/checker.py` (re-gate at both resolve and action), `checker_required` present, `notify(` >= 2 on the flag path, `AuditLog.objects.create` >= 1.
- Task-3 grep gates: all six outcome branches present in `_outcome.html`; `profile_photo` + `{% else %}` fallback present; hidden `room_id` present; `/checker/scan` present in `web/views.py`.

## Threat Mitigations Applied

- **T-03-03 (EoP, off-duty/wrong-floor scan):** `checker_required` + server-side `_active_floor_ids` gating via the pure core; the client never supplies its floor. Verified by `test_active_assignment_grants_scan`.
- **T-03-04 (Repudiation, no-reason flag):** empty-note flags rejected server-side (200 error partial, no row); every accepted action writes an `AuditLog`. Verified by `test_flag_requires_note`.
- **T-03-05 (Spoofing, forged/stale action POST):** `action` re-identifies the room from POST `room_id` and unconditionally re-runs `resolve_checker_scan` against current `_active_floor_ids` before `_apply_action`; a stale/off-duty POST is refused (audited `checker.action_refused`) and writes nothing. Verified by `test_action_refused_when_no_longer_on_duty`.
- **T-03-06 (Info disclosure, faculty photo):** the photo renders only inside the `active-unverified` branch, reachable only when `_active_floor_ids` includes the room's floor.
- **T-03-07 (DoS, manual-code brute force):** per-user-per-minute cache rate limit on the manual-code path; audits `checker.rate_limited`.

## Known Stubs

None that block the plan goal. The "Floor view" home card intentionally stays `href="#"` — the CHK-07 floor board is 03-04. Online room scans intentionally read as empty here; online Verify-activation and Flag-not-present are 03-05.

## Notes for Downstream Plans

- **03-04 (floor board):** reuse `_active_floor_ids(user, now)` and the `_room_session_state` room queryset (exclude COMPLETED, exclude online) so the board, coverage denominator, and queue stay consistent (Pitfall 5).
- **03-05 (online):** extend `_apply_action` with the online branch (Verify → `status=ACTIVE` + `actual_start` + `checkin_method=ONLINE_MANUAL`; Flag-not-present → `status=ABSENT`). `_room_session_state` currently short-circuits online to empty — online is scanned from the online list, not the room QR.
- **03-06 (offline replay):** the replay endpoint re-runs `resolve_checker_scan` through this exact seam; `_apply_action` already accepts `scanned_at` and `offline=True` for the original-timestamp write.

## Self-Check: PASSED
- FOUND: web/checker.py
- FOUND: templates/checker/scan.html
- FOUND: templates/checker/_outcome.html
- FOUND: verification/tests.py (CheckerScanDBTests)
- FOUND: web/urls.py (/checker/* routes)
- FOUND: web/views.py (/checker/scan home wiring)
- FOUND commit: 2f6b214 (test RED), f04f190 (feat surface), 4339f6f (feat home wiring)

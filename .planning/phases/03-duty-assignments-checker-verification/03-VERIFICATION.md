---
phase: 03-duty-assignments-checker-verification
verified: 2026-07-03T03:16:25Z
status: passed
score: 6/6 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 3: Duty Assignments & Checker Verification Verification Report

**Phase Goal:** An on-duty Checker can verify physical presence room-by-room, online and offline, and only while actually assigned to that floor.
**Verified:** 2026-07-03T03:16:25Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | IFO can assign a Checker/Guard to a floor by shift or standing posting, and only that assignment grants on-duty powers | ✓ VERIFIED | `web/ifo.py::assignment_create` (IFO-gated, validated) creates `Assignment(role, type, scope, floors, date/start/end)`; `web/checker.py::_active_floor_ids` is the SOLE source of on-duty floors, reading only active `Assignment` rows via the shared `R.assignment_covers_now` predicate (standing=date NULL always on; shift gated to its window). `AssignmentCreateTests.test_ifo_creates_floor_assignment`, `test_ifo_creates_online_duty_assignment`, `test_non_ifo_forbidden` (403) all pass. |
| 2 | Off-duty/wrong-floor scan refused with clear reason; on-duty scan returns session state + faculty photo | ✓ VERIFIED | `verification/resolver.py::resolve_checker_scan` returns distinct `OFF_DUTY`/`WRONG_FLOOR` outcomes (pure, SimpleTestCase-verified: `test_off_duty_refused`, `test_wrong_floor_refused`). `templates/checker/_outcome.html` renders a named alert per outcome. Active-unverified branch renders `session.faculty.profile_photo.url` with an initials-avatar `{% else %}` fallback. `CheckerScanDBTests.test_active_assignment_grants_scan`, `test_scan_returns_session_and_photo` pass. |
| 3 | Checker can Verify / Flag identity mismatch / Flag not present / Confirm empty; Verify marks checker-verified; flags reach IFO+HR (no dispute workflow) | ✓ VERIFIED | `web/checker.py::_apply_action` writes `CheckerValidation` + `AuditLog` per action; `Session.verified_by_checker` is a derived property (`validations.filter(action="verified").exists()`). Flags fire `notify(role=Role.IFO_ADMIN, ...)` AND `notify(role=Role.HR_ADMIN, ...)` unconditionally, no confirm/dispute step. `test_verify_marks_verified`, `test_flag_requires_note`, `test_flag_notifies_ifo_and_hr` pass. CR-02 fix (`_OUTCOME_ACTIONS` congruence gate) additionally prevents a forged action/outcome mismatch (`test_incongruent_action_is_refused`). |
| 4 | Floor view shows coverage progress + oldest-unverified-first priority queue, excluding Absent | ✓ VERIFIED | `web/checker.py::floor_rows` builds ONE shared queryset (`.exclude(status=SessionStatus.ABSENT)`, ordered `scheduled_start`) feeding cards, the priority queue, and the coverage denominator together (Pitfall-5 guard). `FloorBoardTests.test_coverage_excludes_absent`, `test_priority_queue_oldest_first`, `test_board_excludes_online`, `test_board_scoped_to_active_floor` all pass. Poll interval is `settings.FLUXTRACK_POLICY["poll_interval_seconds"]`-driven, not hardcoded. |
| 5 | Offline scan replays on reconnect, re-validated server-side against current state before applying, or flagged for IFO | ✓ VERIFIED | `web/checker.py::replay` re-derives `_active_floor_ids` + `_room_session_state` server-side per item and re-runs the SAME pure `R.resolve_checker_scan`, never trusting the offline snapshot; a non-actionable/incongruent item is recorded (`AuditLog checker.replay_conflict`) and `notify(role=Role.IFO_ADMIN, ...)` fires, never applied. `ReplayTests.test_valid_replay_applies` (original `scanned_at` preserved, `offline_queued=True`), `test_stale_replay_flags_ifo`, `test_replay_idempotent`, `test_replay_missing_client_uuid_rejected`, `test_replay_manual_code_rate_limited` all pass. Client: `static/checker/offline_queue.js` — IndexedDB queue keyed by `crypto.randomUUID()`, visible "offline / N queued" banner, drains to `/checker/replay`, feature-detects `window.indexedDB` and degrades without crashing. |
| 6 | Online session: on-duty Checker notified + redirected to public MS Teams link; verification marks the online session present, feeding the JOB-02 sweep | ✓ VERIFIED | `verification/services.py::assign_online_sessions` round-robins online sessions to online-duty Checkers (window-aware, CR-05-fixed) and fires a write-only `notify(users=[checker], type="online_assigned", ...)` per newly-assigned Checker. `web/checker.py::online_open` redirects to `session.teams_link` (or flags IFO + shows "no link" when empty). `_apply_action`'s online branch sets `status=ACTIVE`, `actual_start`, `checkin_method=ONLINE_MANUAL` on Verify (`test_online_verify_activates_session`) and `status=ABSENT` on Flag-not-present (`test_online_flag_not_present_absent`). `scheduling/jobs.py::sweep_no_shows` no longer excludes online (`Modality.ONLINE` guard removed) — confirmed by rewritten `test_online_no_show_declared_now_absent`, `test_online_no_show_via_schedule_now_absent`, and `test_verified_online_not_marked_absent` (all passing), proving the coupling (Verify-activates ships in the same plan as the exclusion removal). |

**Score:** 6/6 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `verification/resolver.py` | Pure gating + round-robin core | ✓ VERIFIED | No ORM/`timezone.now()` calls; `CheckerResolution.__post_init__` computes `actionable`; `assignment_covers_now` shared predicate (IN-03 fix) |
| `verification/models.py` | AssignmentScope, Session.online_checker, retired ValidationAction members | ✓ VERIFIED | `AssignmentScope.FLOOR/ONLINE`; `ValidationAction` = {VERIFIED, FLAG_IDENTITY_MISMATCH, FLAG_NOT_PRESENT, VERIFIED_EMPTY} only |
| `verification/migrations/0002_assignment_scope.py`, `0003_retire_dead_validation_actions.py`, `scheduling/migrations/0002_session_online_checker.py` | Additive/state-only migrations | ✓ VERIFIED | All three exist; `makemigrations --check --dry-run` reports "No changes detected" |
| `web/checker.py` | checker_required, resolve/action/replay/floor/online views | ✓ VERIFIED | All views present, server-side re-gate on every write path (action, replay, online) |
| `verification/services.py` | assign_online_sessions apply layer | ✓ VERIFIED | Delegates round-robin to pure core; materializes queryset first (MSSQL HY010 guard); window-aware eligibility (CR-05 fixed) |
| `web/ifo.py` | assignments_list, assignment_create | ✓ VERIFIED | IFO-gated, validates date/time/floor format before ORM write (CR-04 fixed, no 500) |
| `scheduling/jobs.py` | sweep_no_shows online-inclusion | ✓ VERIFIED | `Modality.ONLINE` exclusion guard removed; shared `is_no_show_past_grace` predicate reused |
| `templates/checker/*` (scan, _outcome, floor, _floor_rows, online_list, _online_list, online_open) | UI surfaces | ✓ VERIFIED | All render substantive, wired markup (photo/placeholder, action forms with hidden room_id/session_id, coverage bar, priority queue, Teams-link redirect) |
| `templates/ifo/assignments.html`, `_assignment_form.html` | IFO assignment UI | ✓ VERIFIED | Non-admin create form + roster list |
| `static/checker/offline_queue.js` | IndexedDB offline queue | ✓ VERIFIED | Vanilla JS, feature-detected, posts to `/checker/replay`, banner + sync summary |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `web/checker.py:resolve` | `verification/resolver.py:resolve_checker_scan` | direct call | WIRED | No inline gating in the view |
| `web/checker.py:action` | `verification/resolver.py:resolve_checker_scan` | UNCONDITIONAL re-derivation before write | WIRED | `resolve_checker_scan` called twice in the file (resolve + action); `_active_floor_ids` re-derived server-side |
| `web/checker.py:replay` | `verification/resolver.py:resolve_checker_scan` | per-item re-derivation | WIRED | Same pure core reused; offline snapshot never trusted |
| `web/checker.py:_apply_action` (flags) | `ops/notify.py:notify` | role=IFO_ADMIN + role=HR_ADMIN | WIRED | Both fire unconditionally, no dispute step |
| `verification/services.py:assign_online_sessions` | `verification/resolver.py:distribute_online_sessions` | direct call | WIRED | Round-robin not reimplemented |
| `web/ifo.py:assignment_create` (scope=ONLINE) | `verification/services.py:assign_online_sessions` | direct call | WIRED | Triggered on roster save |
| `scheduling/jobs.py:sweep_no_shows` | `scheduling/resolver.py:is_no_show_past_grace` | shared predicate | WIRED | Same predicate used by online and F2F/Blended, proving the coupling |
| `web/checker.py:_apply_action` (online Verify) | `scheduling/models.py:Session` | status=ACTIVE + checkin_method=ONLINE_MANUAL | WIRED | The online analog of a faculty check-in, lets the sweep skip verified online sessions |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| IFO-06 | 03-01, 03-03 | IFO assigns Checkers/Guards to floors/online; assignment grants on-duty powers | ✓ SATISFIED | `Assignment` model + scope extension, `assignment_create` view, `_active_floor_ids`/`_is_online_on_duty` gates |
| CHK-01 | 03-01, 03-02 | Checker gains powers only while on duty on the scanned floor | ✓ SATISFIED | `resolve_checker_scan` OFF_DUTY/WRONG_FLOOR outcomes, server-side re-gate on every write |
| CHK-02 | 03-02, 03-03, 03-05 | Room scan returns session+photo; online session notifies + redirects to Teams | ✓ SATISFIED | `_room_session_state` + photo render; `online_assigned` notify + `online_open` Teams redirect |
| CHK-03 | 03-02, 03-05 | Verify/Flag identity mismatch/Flag not present/Verified empty, including online | ✓ SATISFIED | `_VALID_ACTIONS`, `_ONLINE_ACTIONS`, `_apply_action` online branch |
| CHK-04 | 03-02 | Verify marks session checker-verified | ✓ SATISFIED | `Session.verified_by_checker` property, `test_verify_marks_verified` |
| CHK-05 | 03-02 | Flag identity mismatch surfaced to IFO+HR, no dispute workflow | ✓ SATISFIED | Dual `notify()` calls, unconditional |
| CHK-07 | 03-04 | Floor view: coverage, priority queue, color-coded cards, excludes Absent | ✓ SATISFIED | `floor_rows` single shared queryset, `_CARD_STYLES` color+icon+label tokens |
| CHK-08 | 03-06 | Offline scans queue + replay, re-validated server-side, never blindly trusted | ✓ SATISFIED | `replay` endpoint, `offline_queue.js` IndexedDB queue |

No orphaned requirements found — REQUIREMENTS.md's Phase-3 mapping (IFO-06, CHK-01..05, CHK-07, CHK-08) matches exactly what the six plans declare.

### Anti-Patterns Found

None. Grepped all 17 phase-modified files (resolver.py, services.py, models.py, checker.py, ifo.py, urls.py, jobs.py, and all checker/ifo templates + offline_queue.js) for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not yet implemented|coming soon` — zero matches.

### Code Review Resolution

A standard-depth code review (`03-REVIEW.md`, reviewed 2026-07-03T02:53:42Z) found 5 Critical + 3 Warning issues after the six plans landed. All 8 were confirmed fixed in the current source:

| ID | Issue | Fix confirmed in |
|----|-------|-------------------|
| CR-01 | Stale-ABSENT session latch blocks a later same-room session | `web/checker.py::_room_session_state` now prefers ACTIVE, else the window-containing session |
| CR-02 | `action_val` not validated against resolved `outcome` | `_OUTCOME_ACTIONS` congruence gate in `action()` and `replay()` |
| CR-03 | Non-numeric `room_id` causes a 500 | `.isdigit()` guard added before the ORM filter |
| CR-04 | Unvalidated date/time/floor POST fields cause a 500 | `parse_date`/`parse_time`/`isdigit()` validation in `web/ifo.py::assignment_create` |
| CR-05 | Online round-robin ignores shift window | `_online_duty_assignments` + per-session eligibility grouping via shared `assignment_covers_now` |
| WR-01 | TOCTOU race in idempotency check-then-set | `cache.add()` atomic claim in `action`, `replay`, `_online_action` |
| WR-02 | Replay manual-code path has no rate limit | `_replay_manual_code_allowed` per-checker-per-minute cap |
| WR-03 | Missing `client_uuid` bypasses idempotency | Items with empty `client_uuid` rejected outright (`status: flagged, reason: bad-payload`) |

`py -3.12 manage.py test` (full suite): **103 tests, OK** (independently re-run during this verification, not taken from SUMMARY claims). `py -3.12 manage.py test verification scheduling web`: 83 tests, OK. `py -3.12 manage.py makemigrations --check --dry-run`: No changes detected.

### Human Verification Required

None. All must-haves resolved to VERIFIED via direct source inspection and an independently re-run test suite; no visual/real-time/external-service behavior in this phase's scope required human judgment beyond what the shipped Django test suite already exercises server-side.

### Gaps Summary

No gaps found. All 8 requirement IDs (IFO-06, CHK-01..05, CHK-07, CHK-08) are satisfied with wired, tested code. The one high-risk coupling this phase called out — removing the JOB-02 sweep's online exclusion in lockstep with the online-Verify-activates path — was independently confirmed: `scheduling/jobs.py` no longer branches on `Modality.ONLINE`, and the three related `SweepTests` (two rewritten to inclusion semantics, one new verified-online-skipped case) all pass. The post-plan code review's 5 Critical findings (including two — CR-01 stale-session latch, CR-05 shift-window-blind round-robin — that would have silently produced incorrect Absent markings) were verified fixed in the current source, not merely claimed fixed in SUMMARY/REVIEW frontmatter.

---

_Verified: 2026-07-03T03:16:25Z_
_Verifier: Claude (gsd-verifier)_

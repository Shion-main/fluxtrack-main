---
phase: 04-modality-shift-approval-srs-v1-2
verified: 2026-07-04T00:00:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:

  - test: "Open the regenerated FluxTrack_SRS.docx in Word/LibreOffice and confirm the MOD area (4.4), DEAN-04 row, the removed CHK-06 row, and the policy-register row render with tables/headings intact."
    expected: "The DOCX visually matches the .md content — no broken tables, no missing sections, no encoding artifacts from the pandoc conversion."
    why_human: "Automated tests only assert the .docx is non-empty and byte-writable; pandoc's table/heading rendering fidelity is a visual property no grep/unit test can see."

  - test: "As a faculty user, open /faculty/modality/new, pick a ->F2F/Blended target, and exercise the availability-first picker (pick a specific room/time, pick 'let the app decide', and trigger a time-move suggestion when the preferred slot is full)."
    expected: "The picker renders real room/time options from available_rooms_for/available_times_for, Franken-UI styling is consistent with other faculty pages, and the form is usable on a mobile-width viewport."
    why_human: "Server-side validation/authz is unit-proven (FacultyModalityAuthzTests), but visual layout, Franken-UI consistency, and mobile-first usability require an in-browser check (flagged by the 04-07 executor itself, coverage item D4)."

  - test: "As a Dean user, open /dean/requests, approve a pending ->Online request and a pending ->F2F request (one with a free room, one with none), and reject a request with a reason — observe the htmx in-place queue swap after each action."
    expected: "The queue updates in place without a full page reload, success/denial/error messages are clearly distinguishable, and the layout is Franken-UI consistent."
    why_human: "Approve/reject consequences are unit-proven (DeanModalityAuthzTests) against persisted state and Notification rows, but the htmx swap behavior and visual message clarity require an in-browser check (flagged by the 04-08 executor itself, coverage item D5)."
---

# Phase 4: Modality Shift Approval & SRS v1.2 Verification Report

**Phase Goal:** Faculty can request a lead-time-gated modality shift that a Dean approves, with rooms auto-released or auto-assigned, and the SRS brought back in sync with reality.
**Verified:** 2026-07-04
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A faculty member can submit a modality-shift request (F2F/Blended↔Online) for a single or recurring session at least `modality_shift_lead_days` (default 2) ahead; a too-late request is refused | ✓ VERIFIED | `config/settings.py:211` sets `modality_shift_lead_days: 2`; `scheduling/services.py:67-83` `is_before_lead_cutoff` gates on server clock + `get_policy`; `scheduling/services.py:141-264` `submit_modality_shift` gathers in-window sessions across schedules, gates, routes, and persists one atomic ticket; `scheduling.tests.LeadTimeGateTests`, `ShiftScopeTests.test_too_late_request_refused`, `test_recurring_window_resolves_only_in_window_sessions`, `test_multi_schedule_ticket_has_item_per_schedule` all pass. `web/faculty.py` `modality_new` wires the form to the service with 400-not-500 validation; `FacultyModalityAuthzTests.test_valid_submit_creates_one_pending_routed_to_dean` and `test_malformed_submit_is_400_not_500` pass. |
| 2 | The request routes to the faculty member's department Dean, who can approve or reject with a reason; the faculty member can withdraw while still pending | ✓ VERIFIED | `route_to_dean` (`scheduling/services.py:86-101`) filters `Role.DEAN` by department; refusal on missing dept/vacant seat proven by `DeanRoutingTests`. `reject_modality_shift` and `withdraw_modality_shift` (`scheduling/services.py:271-329`) re-gate ownership/role + PENDING status inside the transaction; `WithdrawTests` (owner-pending success, foreign-withdraw refusal, cross-department reject refusal, non-pending refusal) all pass. Dean web surface (`web/dean.py` `queue`/`approve`/`reject`) is department-scoped and POST-only; `DeanModalityAuthzTests` (non-Dean denied, cross-department IDOR refused, reject with/without reason) pass. Faculty web surface (`web/faculty.py` `modality_mine`/`modality_withdraw`) shows status + withdraw-while-pending; `FacultyModalityAuthzTests.test_foreign_withdraw_refused_and_stays_pending` passes. |
| 3 | Approving a →Online shift turns the affected session(s) Online and releases the room immediately (`room_released_at` stamped, not held on the timer); newly materialized Online sessions are born released | ✓ VERIFIED | `_apply_online` (`scheduling/services.py:435-450`) sets `declared_modality=Online` and calls `release_room()` (never nulls the room FK); `ApplyOnlineTests.test_online_approval_releases_room_and_flips_modality` and `test_out_of_window_session_untouched` pass. `EffectiveModalityCouplingTests` proves the resolver/sweep-read expression sees Online post-apply. `materialize_sessions.py` `_apply_approved_shift` (lines 25-75) born-releases future in-window sessions on `was_created`; `BornReleasedTests` (future session born released, out-of-window untouched, idempotent re-run) all pass. `ops/occupancy.py` confirms `release_room()` remains the sole caller-gated-to-MOD-03 path (no timer). |
| 4 | Approving a →F2F/Blended shift auto-assigns a free room in the same building, or fails outright with a clear reason if none is free (no silent partial apply); IFO is notified informationally | ✓ VERIFIED | `resolve_shift_room` + `_apply_f2f` (`scheduling/services.py:361-432`) re-resolve the room INSIDE the approval transaction (original-if-free else first-free-in-building), storing the reservation on `item.assigned_room`; `ApplyF2FTests` (original kept, taken→reassigned, time-move rewrite) and `ApproveRaceTests` (TOCTOU re-resolution) pass. No-free-room / faculty double-book raises `_NoRoomAvailable`, rolled back via nested savepoint, sets terminal `DENIED` with a reason — `ApplyF2FNoRoomTests` (no-partial-apply asserted) passes. IFO informational notify fires on every successful apply; `ShiftNotifyTests` (submit→Dean, approve→requester+IFO, reject/deny→requester) all pass. Materialize born-assigned path (`materialize_sessions.py`) applies the reservation (never re-resolves) with a defensive no-crash guard; `BornAssignedTests` (reserved room, time-move, defensive no-room fallback notifying IFO) all pass. Dean web surface surfaces DENIED as a clear message, not a false success; `DeanModalityAuthzTests.test_no_room_f2f_approve_denies_session_unchanged` passes. |
| 5 | The SRS is revised to v1.2 — new MOD area, removed CHK-06, amended FAC-07/CHK-03, RPT-02-notifies-Deans, and `modality_shift_lead_days` in the policy register — in both `.md` and `.docx` | ✓ VERIFIED | `FluxTrack_SRS.md`: Revision History has the `1.2` row (line 30); MOD-01..06 requirements table present (lines 283-288); FAC-07 marked superseded (line 270); CHK-03 amended, no "Confirm absent", online sessions included (line 296); CHK-06 row absent (grep confirms zero matches); RPT-02 notifies "IFO and the relevant Dean(s)" (line 351); `modality_shift_lead_days` in the §8 policy register (line 486). `scheduling/management/commands/regenerate_srs_docx.py` regenerates `FluxTrack_SRS.docx` deterministically from the `.md` via bundled `pypandoc_binary`; `scheduling.tests_srs.SrsV12DocTests` (marker presence + regeneration) both pass. `FluxTrack_SRS.docx` exists (29265 bytes, non-empty, regenerated as recently as the last full-suite run per the DOC-01 smoke test side-effect). |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scheduling/models.py` | `ModalityShiftStatus`, `ModalityShiftRequest`, `ModalityShiftItem` | ✓ VERIFIED | Present with all fields exactly as specced (lines 134-216); no stray `Session.modality` column added |
| `config/settings.py` | `modality_shift_lead_days: 2` in `FLUXTRACK_POLICY` | ✓ VERIFIED | Line 211, resolved only via `get_policy()` |
| `scheduling/migrations/0003_modality_shift_request.py` | migration | ✓ VERIFIED | Full suite migrates cleanly (204 tests pass against a fresh test DB) |
| `scheduling/test_support.py` | `make_shift_fixture()` | ✓ VERIFIED | Used across `ops.tests`, `scheduling.tests`, `web.tests`; `FixtureSmokeTests` passes |
| `ops/availability.py` | `room_is_free`, `free_rooms_in_building`, `available_rooms_for`, `available_times_for`, `faculty_has_conflict` | ✓ VERIFIED | All five functions present with half-open overlap, request-aware occupancy (D-18), building scope, Booking-awareness; `RoomAvailabilityTests` (21 cases) all pass |
| `scheduling/services.py` | `is_before_lead_cutoff`, `route_to_dean`, `affected_sessions`, `submit_modality_shift`, `withdraw_modality_shift`, `reject_modality_shift`, `apply_approval`, `_apply_online`, `_apply_f2f`, `resolve_shift_room` | ✓ VERIFIED | All present, wired end-to-end, exercised by 38+ passing tests across `LeadTimeGateTests`/`DeanRoutingTests`/`ShiftScopeTests`/`WithdrawTests`/`ApplyOnlineTests`/`ApplyF2FTests`/`ApproveRaceTests`/`ApplyF2FNoRoomTests`/`ShiftNotifyTests`/`EffectiveModalityCouplingTests` |
| `scheduling/management/commands/materialize_sessions.py` | born-released/born-assigned hook | ✓ VERIFIED | `_apply_approved_shift` (lines 25-107) fires only on `was_created`; `BornReleasedTests`/`BornAssignedTests` (6 cases) all pass |
| `web/faculty.py` | `modality_new`, `modality_mine`, `modality_withdraw` | ✓ VERIFIED | Present, `@faculty_required`, 400-not-500 validated POST, service-delegated withdraw; `FacultyModalityAuthzTests` (5 cases) pass |
| `web/dean.py` | `dean_required`, `queue`, `approve`, `reject` | ✓ VERIFIED | Present, department-scoped queue, POST-only re-gated decisions; `DeanModalityAuthzTests` (6 cases) pass |
| `web/urls.py` | faculty + dean modality routes | ✓ VERIFIED | `faculty_modality_new/_mine/_withdraw`, `dean_queue/_approve/_reject` all registered (lines 16-24) |
| Templates (5) | faculty submit/mine, dean queue | ✓ VERIFIED | All 5 files exist (16-110 lines each, non-trivial content); exercised without raising by the passing web test suites |
| `scheduling/management/commands/regenerate_srs_docx.py` | pandoc-based regeneration command | ✓ VERIFIED | BaseCommand calling `pypandoc.convert_file`; regenerates a non-empty `.docx`; `SrsV12DocTests` pass |
| `FluxTrack_SRS.md` (v1.2) | revised SRS | ✓ VERIFIED | All 7 anchored edits present (see Truth 5 evidence) |
| `FluxTrack_SRS.docx` (v1.2) | regenerated binary | ✓ VERIFIED | 29265 bytes, non-empty, reproducible from the `.md` via one command |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `web/faculty.py:modality_new` | `scheduling.services.submit_modality_shift` | direct call, service re-resolves rooms | ✓ WIRED | Confirmed in source; `FacultyModalityAuthzTests` proves end-to-end submit creates a PENDING request |
| `web/faculty.py:modality_withdraw` | `scheduling.services.withdraw_modality_shift` | direct call, IDOR guard delegated | ✓ WIRED | `test_foreign_withdraw_refused_and_stays_pending` proves the re-gate fires through the view |
| `web/dean.py:approve` | `scheduling.services.apply_approval` | direct call, TOCTOU/IDOR re-gate delegated | ✓ WIRED | `test_cross_department_approve_refused_stays_pending`, `test_online_approve_applies_and_notifies` prove both refusal and success paths through the view |
| `web/dean.py:reject` | `scheduling.services.reject_modality_shift` | direct call | ✓ WIRED | `test_reject_records_reason_and_notifies` |
| `ops/availability.room_is_free` | `ModalityShiftItem.assigned_room` (D-18 request-aware) | ORM filter on approved items | ✓ WIRED | `test_approved_f2f_reservation_occupies_before_materialize` proves an unmaterialized future reservation reads as occupied |
| `scheduling/services._apply_online` | `ops/occupancy.release_room` | direct call | ✓ WIRED | `ApplyOnlineTests.test_online_approval_releases_room_and_flips_modality` |
| `scheduling/services._apply_f2f` | `ops/availability.resolve_shift_room` (via `room_is_free`/`free_rooms_in_building`) | direct call, re-resolved inside transaction | ✓ WIRED | `ApproveRaceTests.test_preferred_room_taken_at_approval_reresolves` |
| `materialize_sessions._apply_approved_shift` | `ModalityShiftItem.assigned_room` (D-18 apply-not-reresolve) | ORM filter + direct field read | ✓ WIRED | `BornAssignedTests.test_future_in_window_session_born_in_reserved_room` |
| `scheduling.models.Session.declared_modality` | resolver/sweep effective-modality readers (MOD-06 coupling) | shared expression `declared_modality or schedule.modality` | ✓ WIRED | `EffectiveModalityCouplingTests` asserts the exact expression used by `ops/availability.py` and `verification/services.py` agrees post-apply |
| `regenerate_srs_docx` command | `FluxTrack_SRS.md` → `FluxTrack_SRS.docx` | `pypandoc.convert_file` | ✓ WIRED | `SrsV12DocTests.test_regenerate_srs_docx_writes_nonempty`; command run confirmed regenerating a 29265-byte docx during the full-suite run |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full project test suite (baseline regression) | `py -3.12 manage.py test` | 204 tests, OK | ✓ PASS |
| All Phase-4-specific suites (single run, not per-truth filtering) | `py -3.12 manage.py test scheduling.tests.<12 classes> ops.tests.RoomAvailabilityTests web.tests.FacultyModalityAuthzTests web.tests.DeanModalityAuthzTests scheduling.tests_srs -v2` | 77 tests, OK | ✓ PASS |
| `modality_shift_lead_days` policy resolves via `get_policy` (not a literal) | inline python assertion (plan Task 1 command, re-derived from source read) | `get_policy("modality_shift_lead_days")` reads `config/settings.py:211` | ✓ PASS (source-confirmed) |
| SRS v1.2 markers present, CHK-06 absent | grep on `FluxTrack_SRS.md` | MOD-01..06/DEAN-04/policy row present; zero `CHK-06` matches | ✓ PASS |
| No FAC-07 self-declare route survives | grep across `web/` and `scheduling/` for `declare_modality`/`self_declare` | only doc-comment references in `web/faculty.py` describing the retirement | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| MOD-01 | 04-01, 04-04, 04-07 | Lead-time-gated request submission | ✓ SATISFIED | Models + policy (04-01), gate/routing/scope (04-04), faculty submit surface (04-07); all backing tests pass |
| MOD-02 | 04-04, 04-08 | Dean routing + approve/reject with reason | ✓ SATISFIED | `route_to_dean`, `reject_modality_shift` (04-04), Dean queue/approve/reject views (04-08); tests pass |
| MOD-03 | 04-05, 04-06 | →Online release, born-released materialization | ✓ SATISFIED | `_apply_online` (04-05), `_apply_approved_shift` born-released branch (04-06); tests pass |
| MOD-04 | 04-03, 04-05, 04-06, 04-08 | →F2F auto-assign or clean fail, born-assigned | ✓ SATISFIED | `ops/availability.py` primitive (04-03), `_apply_f2f`/DENY (04-05), born-assigned hook (04-06), Dean-surfaced denial (04-08); tests pass |
| MOD-05 | 04-04, 04-05, 04-07 | IFO informational notify, withdraw-while-pending | ✓ SATISFIED | `notify()` calls in submit/apply (04-04/04-05), faculty withdraw surface (04-07); `ShiftNotifyTests` pass |
| MOD-06 | 04-02 (doc half), 04-05, 04-07 (code half) | Workflow replaces FAC-07 self-declare | ✓ SATISFIED | SRS FAC-07 superseded (04-02); `declared_modality` as the sole override (04-05); no self-declare route exists (04-07); `test_no_faculty_self_declare_route_exists` passes. REQUIREMENTS.md correctly shows MOD-06 Complete only after the code half landed (04-05/04-07), not prematurely at 04-02 — the 04-02 SUMMARY explicitly deferred this and it was later marked complete. |
| DOC-01 | 04-02 | SRS v1.2 revision, `.md` + `.docx` | ✓ SATISFIED | All 7 anchored edits present; `regenerate_srs_docx` command; `SrsV12DocTests` pass |

No orphaned requirements — every plan's `requirements:` frontmatter entry (MOD-01..06, DOC-01) is accounted for and traces to REQUIREMENTS.md, all marked Complete.

### Anti-Patterns Found

None. Grep for `TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|not yet implemented|coming soon` across all Phase-4-modified source files (`scheduling/models.py`, `scheduling/services.py`, `ops/availability.py`, `materialize_sessions.py`, `web/faculty.py`, `web/dean.py`, `web/urls.py`) returned zero matches.

### Human Verification Required

Three items — all visual/UX quality checks the executors themselves flagged as needing an in-browser check (not functional gaps; the underlying server-side behavior for all three is unit-proven):

### 1. SRS DOCX visual fidelity

**Test:** Open the regenerated `FluxTrack_SRS.docx` in Word/LibreOffice and confirm the MOD area (4.4), DEAN-04 row, the removed CHK-06 row, and the policy-register row render with tables/headings intact.
**Expected:** The DOCX visually matches the `.md` content — no broken tables, no missing sections, no encoding artifacts from the pandoc conversion.
**Why human:** Automated tests only assert the `.docx` is non-empty and regenerates without raising; pandoc's table/heading rendering fidelity is a visual property no grep/unit test can see.

### 2. Faculty availability-first picker UI

**Test:** As a faculty user, open `/faculty/modality/new`, pick a →F2F/Blended target, and exercise the picker (pick a specific room/time, pick "let the app decide," and trigger a time-move suggestion when the preferred slot is full).
**Expected:** The picker renders real room/time options, Franken-UI styling is consistent with other faculty pages, and the form is usable at mobile width.
**Why human:** Server-side validation/authz is unit-proven; visual layout and mobile-first usability require an in-browser check.

### 3. Dean approval queue UI

**Test:** As a Dean user, open `/dean/requests`, approve a pending →Online request and a pending →F2F request (one with a free room, one with none), and reject a request with a reason — observe the htmx in-place queue swap after each action.
**Expected:** The queue updates in place without a full page reload; success/denial/error messages are clearly distinguishable; layout is Franken-UI consistent.
**Why human:** Approve/reject consequences are unit-proven against persisted state and Notification rows, but htmx swap behavior and message clarity require an in-browser check.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria and all 7 requirement IDs (MOD-01..06, DOC-01) are backed by real, wired, tested code — verified by direct source inspection (not SUMMARY claims) and a live run of the full 204-test suite plus all 77 Phase-4-specific tests, all green. The only open items are three visual/UX spot-checks that the plan executors themselves flagged as out of automated-test reach; none of them indicate incomplete or stubbed functionality.

---

*Verified: 2026-07-04*
*Verifier: Claude (gsd-verifier)*

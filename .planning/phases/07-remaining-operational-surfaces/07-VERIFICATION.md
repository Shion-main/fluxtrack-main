---
phase: 07-remaining-operational-surfaces
verified: 2026-07-19T20:10:00Z
status: passed
score: 5/5 success criteria verified
---

# Phase 7: Remaining Operational Surfaces Verification Report

**Phase Goal:** Complete the remaining role surfaces - Guard monitoring/locator, IFO room
and booking operations, Faculty self-service, and scheduled-job monitoring.
**Verified:** 2026-07-19
**Status:** passed
**Re-verification:** No - initial verification

## Method

Goal-backward, not summary-forward. The five ROADMAP success criteria were taken as the
contract; each was traced into the actual routes, decorators, services and templates in
`web/`, `ops/`, `accounts/` and `templates/`. The twelve SUMMARY files were read only to
locate code, never accepted as evidence.

Two independent evidence streams back this report:

1. **Direct code inspection** of every view, decorator and service named below (this run).
2. **The browser-driven UAT** in `07-UAT.md` (2026-07-19, headless Chromium against the
   live MSSQL LocalDB, 13 of 14 tests pass, the one issue found and fixed in-session).
   The UAT is strong primary evidence because it exercised real forms, real file inputs
   and real DB state - not the Django test client.

Automated re-run this session (one run, not per-criterion):
`manage.py test web.tests web.tests_ifo_rooms web.tests_ifo_ops web.tests_ifo_import
web.tests_faculty_online web.tests_faculty_history web.tests_faculty_profile`
-> **235 tests, 3 failures**. The three are named and are the long-standing dev-login /
home-redirect failures (`DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`,
`DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`,
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`) - all three are Phase 03.1
auth-stub artifacts, none touches a Phase 07 surface.

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Guard: live polled floor monitor + per-room schedule for assigned floors, faculty locator (room/course/end time, or Online / Not-in-a-class + next class), debounced push alerts, and no write access anywhere | VERIFIED | All four views exist in `web/guard.py` and are routed (`guard/monitor`, `guard/monitor/rows`, `guard/locate`, `guard/rooms/<code>`). Every one carries `@guard_required` AND `@require_http_methods(["GET"])` - read-only by contract, not by absence of a write branch; `GuardReadOnlyTests` (web/tests.py:658) asserts it per URL, and UAT test 12 confirmed live 405s on all three monitor/locate URLs with a valid CSRF token. Floor scope is re-derived server-side per request in `_guard_floor_ids()` from active FLOOR-scoped GUARD assignments via `resolver.assignment_covers_now` - the client never supplies a floor. `room_detail` raises `Http404` (not 403) off-floor so room existence cannot leak; UAT test 11 confirmed R102 and nonexistent ZZZ999 return byte-identical 404s pre-posting, and 200 after posting. `locate` returns current session + `online_now` + next class. Push: `ops/guard_alerts.notify_floor_guards` emits exactly ONE coalesced `guard_floor_alert` per on-duty guard per sweep, called from both sweep entry points (`run_status_sweep.py`, `runscheduler.py`); UAT test 13 ran the real sweep with three seeded no-shows on one floor and the guard received exactly one notification, not three. See the Carried Caveat below on VAPID transport. |
| 2 | IFO: create/edit/delete rooms from a non-admin UI, rotate QR token + six-digit code (audit-logged, old posters dead), and import schedules by upload with validation and conflict reporting | VERIFIED | CRUD: `ifo.room_new` / `room_edit` / `room_delete`, all `@ifo_required` + method-gated. Code immutability is real, not cosmetic: `room_edit` never reads or writes `code`, `qr_token` or `manual_code`, and its `save(update_fields=["name","capacity","floor"])` makes that structural - UAT test 2 proved it by POSTing `code=HACKED101` and finding it ignored server-side. Delete refusal: `room_delete` re-runs `campus.services.room_delete_blockers` INSIDE `transaction.atomic()` (the GET-time probe is display only), with `ProtectedError` as backstop, and names each blocking relation with counts via `_BLOCKER_LABELS`; both outcomes audited (`room.deleted` / `room.delete_refused`). UAT test 3 saw R102 refuse with 67 schedules / 390 sessions / 47 validations and zero submit buttons. Rotation: `room_rotate` is POST-only, mints via `campus.codes.new_room_credentials()` and nowhere else, stamps `code_rotated_at`/`_by`, writes `AuditLog(room.code_rotated)` carrying NO credential value, and redirects to the poster; UAT test 4 saw both values actually change and land on the poster. Import: `import_page` / `import_preview` / `import_commit` / `import_discard` over `ops/import_staging.py`; preview writes only an `ImportStaging` row, commit calls `import_offerings` (get_or_create throughout, `reset_term` deliberately not importable from `web/`); UAT test 7 confirmed the four-bucket preview balanced, nothing written pre-commit, 2115 -> 2117 on commit, and idempotency on re-upload. |
| 3 | IFO: create/cancel conflict-checked ad-hoc bookings, and manually release a held room, resolving room-conflict notifications | VERIFIED | `booking_create` validates format/pk before touching the ORM, then asks `ops.availability.room_is_free` - the single occupancy oracle - and refuses with a named 400 re-render preserving input. `booking_cancel` flips status rather than deleting (so `room_is_free` frees the window and the PROTECT room-delete blocker survives), re-gated server-side against a stale row. Manual release: `session_release` re-reads the session, refuses at 400 if it has no room / is already released / is not in `_ROOM_HOLDING_STATUSES`, else calls `ops.occupancy.release_room(session, actor=request.user)` - which is what writes the single `session.room_released` AuditLog (deliberately no second row here). `conflicts` is GET-only and offers no manual dismiss; the flag closes on the next sweep because the cause is gone. UAT test 5 proved the whole chain live: `room_released_at` stamped, audit actor "Ivy Reyes (IFO Admin)" not None, flag auto-resolved 1 -> 0 on the next sweep. UAT test 6 proved the overlap refusal renders visibly (initially misreported, then retracted as a testing error). |
| 4 | Faculty: start an Online session via Verify & Start with a valid MS Teams link (no QR), view own attendance history including Checker flags, and manage profile photo + notification preferences | VERIFIED | `_teams_link_error` requires `https` and matches the host by exact-or-dot-boundary against `_TEAMS_HOSTS` (`host == d or host.endswith("." + d)`). Read directly: `teams.microsoft.com.evil.com` matches neither arm, so the lookalike is refused by construction - a substring check would have passed it. UAT test 9 confirmed all four refusals at 400 with the session left SCHEDULED, and a valid link starting the session with `checkin_method=online_self`. History: `faculty.history` is hard-scoped to `faculty=request.user` with no querystring faculty filter accepted at all, resolves verification/flags by `Exists()` annotations, one bounded extra query for flag reasons; UAT test 10 confirmed 25 rows, GET-only filters, zero hx-post/put/delete, no dispute control, flags rendered. Photo: `accounts/photos.py normalize_profile_photo` is pure bytes-in/bytes-out - size cap, decompression-bomb ceiling with the warning escalated to an exception, verify-then-reopen, format allow-list on the DECODED format, `ImageOps.exif_transpose` BEFORE the strip, then a JPEG save with no `exif=` keyword. UAT test 8 proved both halves on a real EXIF-bearing phone JPEG: 0 EXIF keys / no GPS on the stored file, AND the rotation baked in (200x400 -> 400x200, top edge landing right, i.e. Orientation=6 applied in the correct direction). Notification preferences shipped out-of-band and are linked from `faculty.profile`. |
| 5 | System Admin can monitor scheduled-job status (last run, success/failure, rows affected) | VERIFIED | `web/sys.py jobs` is routed at `sys/jobs`, gated by `sysadmin_required`, read-only. It reads the latest `ops.JobRun` per distinct `job_name` (Meta ordering `-started_at`, backed by a `(job_name, -started_at)` index) plus a PAGED run history, and computes duration. `JobRun` carries `job_name`, `status` (running/ok/failed), `started_at`, `finished_at`, `rows_affected` and `detail` - all three fields the criterion names. `templates/sys/jobs.html` exists. Rows are written by `ops/jobrun.run_job`, which wraps every scheduled job. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `web/guard.py` | Guard monitor, per-room schedule, locator; read-only by contract | VERIFIED | 195 lines, four views, all `@guard_required` + `@require_http_methods(["GET"])`. Server-side floor derivation. Off-floor -> 404. |
| `web/room_state.py` | Shared room-state extraction consumed by both IFO board and Guard room view | VERIFIED | 137 lines; `occupies`, `room_tile`, `room_timetable` imported by `web/guard.py` and `web/ifo.py` - the Guard view is literally the IFO board's code, so the online-occupancy and past-grace rules cannot drift. |
| `web/ifo.py` | Room CRUD, rotation, conflicts/release, bookings, import | VERIFIED | 1574 lines; every view carries `@ifo_required`, all mutating views are POST-only via `require_http_methods`. No stub returns, no static-return handlers. |
| `web/faculty.py` | Online Verify & Start, attendance history, profile photo | VERIFIED | 940 lines; Teams host allow-list, `Exists()`-annotated history, IDOR re-gate on both write paths (target is always `request.user`, never a posted id). |
| `web/sys.py` | SYS-04 job monitor | VERIFIED | 53 lines, read-only, paged. |
| `accounts/photos.py` | Validate + re-encode + EXIF strip, pure | VERIFIED | 183 lines, no ORM/storage/HTTP. Re-encode is the control; rotation applied before strip. |
| `ops/guard_alerts.py` | GRD-04 coalesced fan-out | VERIFIED | 164 lines; `summarize_floor_events` + `notify_floor_guards` emitting one `notify()` per on-duty guard, `is_active` checked explicitly (because `notify(users=[...])` does not filter inactive users). |
| `ops/import_staging.py` | IFO-03b staging model + service | VERIFIED | 193 lines; `resolve_staged` filters on `uploaded_by` AND `consumed_at IS NULL`, so cross-user and double-submit both resolve to None rather than raising. |
| `ops/models.py JobRun` | rows_affected + status + timestamps | VERIFIED | Fields present; indexed for the latest-per-job read. |
| `templates/` | 4 guard, 23 ifo, 13 faculty, 1 sys | VERIFIED | All named templates exist on disk; no placeholder bodies found. |
| `templates/base.html` + `templates/_console.html` | `{% block global_header %}` opt-out replacing the url_name allowlist | VERIFIED | `base.html:60` defines the block; `_console.html:15` overrides it to empty for every console page present and future; 15 faculty/guard templates override it individually. The old hardcoded allowlist is gone. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `web/guard.py` | `web/room_state.py` | `from web.room_state import occupies, room_timetable, room_tile` | WIRED | Same functions the IFO board calls. |
| `web/guard.py room_detail` | `verification.resolver.assignment_covers_now` | `_guard_floor_ids` | WIRED | Authorization derived server-side per request, not per session. |
| `web/ifo.py room_rotate` | `campus.codes.new_room_credentials` | direct call inside `transaction.atomic()` | WIRED | Single minter; the collision-safe one from 07-02. |
| `web/ifo.py room_delete` | `campus.services.room_delete_blockers` | re-probe inside the transaction + `ProtectedError` backstop | WIRED | Two independent controls, both proven live in UAT test 3. |
| `web/ifo.py booking_create` | `ops.availability.room_is_free` | direct call, single oracle | WIRED | No second overlap query exists in `web/`. |
| `web/ifo.py session_release` | `ops.occupancy.release_room` | `release_room(session, actor=request.user)` | WIRED | Second and last caller; `ReleaseRoomCallerGuardTests` enforces that. |
| `web/ifo.py import_commit` | `import_offerings` management command | `call_command(..., dry_run=False)` | WIRED | Same options as the preview, so preview and commit cannot describe different work. |
| `web/faculty.py profile_photo_upload` | `accounts.photos.normalize_profile_photo` | try/except `PhotoError` -> friendly status | WIRED | Stored bytes are always Pillow's output. |
| `ops/guard_alerts.notify_floor_guards` | `ops.notify.notify` | one call per on-duty guard | WIRED | Imported and called by `run_status_sweep.py` and `runscheduler.py`. |
| `web/sys.py jobs` | `ops.models.JobRun` | latest-per-name + paged history | WIRED | Rows written by `ops/jobrun.run_job`. |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| GRD-01 | Live polled read-only floor monitor | SATISFIED | `guard.monitor` + `monitor_rows`, poll interval from `get_policy` (honours SystemSetting override). Shipped out-of-band, audited 2026-07-18, label corrected by 07-01. |
| GRD-02 | Per-room schedule, guard-gated | SATISFIED | `guard.room_detail`; UAT test 11 (200 on-floor, identical 404 off-floor and for a nonexistent room). |
| GRD-03 | Faculty locator with Online / Not-in-a-class + next class | SATISFIED | `guard.locate` sets `current`, `online_now`, `next`. Shipped out-of-band, audited 2026-07-18. |
| GRD-04 | Debounced push alerts for floor activity | SATISFIED (fan-out); transport carried - see Caveat | `ops/guard_alerts.py`; UAT test 13 proved exactly ONE coalesced notification from three no-shows. |
| GRD-05 | No write access anywhere | SATISFIED | `require_http_methods(["GET"])` on all four Guard views + `GuardReadOnlyTests`; UAT test 12 confirmed live 405s. |
| IFO-01b | Room create/edit/delete from a non-admin UI | SATISFIED | Truth 2; code immutability proven server-side, delete refusal named with counts. |
| IFO-02 | Rotate QR token + six-digit code, audit-logged | SATISFIED | Truth 2; `AuditLog(room.code_rotated)` written, credentials never in the payload. |
| IFO-03b | Schedule import by upload with validation and reporting | SATISFIED | Truth 2; four-bucket reconciliation preview, nothing written pre-commit, idempotent re-commit. |
| IFO-05 | Create/cancel conflict-checked ad-hoc bookings | SATISFIED | Truth 3. Cancel was not clicked in the browser but is covered by six automated tests in `web/tests_ifo_ops.py` (flip+audit, frees the window, second cancel 400, not deleted, still listed, still blocks room delete). |
| IFO-08 | Manually release a held room, resolve conflict notifications | SATISFIED | Truth 3; release + auto-resolve proven end to end in UAT test 5. |
| FAC-08 | Online Verify & Start with a valid Teams link | SATISFIED | Truth 4; lookalike-host refusal is structural. |
| FAC-11 | Own attendance history with Checker flags, read-only | SATISFIED | Truth 4; hard-scoped, GET-only, no dispute control. |
| FAC-12 | Profile photo + notification preferences | SATISFIED | Truth 4; photo half built this phase, preferences half shipped out-of-band and audited 2026-07-18. |
| SYS-04 | Scheduled-job status: last run, success/failure, rows affected | SATISFIED | Truth 5; shipped out-of-band, audited 2026-07-18, re-verified here against the live code. |

No orphaned requirements. All fourteen IDs the ROADMAP maps to Phase 7 are accounted for;
the four that shipped out-of-band (SYS-04, GRD-01, GRD-03, FAC-12 preferences) were
re-checked in code during this verification rather than accepted on the 2026-07-18 audit.

### Anti-Patterns Found

None. Scanned `web/ifo.py`, `web/guard.py`, `web/faculty.py`, `web/sys.py`,
`web/room_state.py`, `ops/guard_alerts.py`, `ops/import_staging.py`, `accounts/photos.py`
and `templates/base.html` for `TODO`, `FIXME`, `XXX`, `HACK` and `PLACEHOLDER` - zero
matches. No empty handlers, no static-return stubs, no console-log-only implementations.
Every mutating view re-gates server-side against a stale client snapshot, and every one
writes an AuditLog (the single documented exception, `session_release`, is deliberate and
test-enforced so releases are not double-counted).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 07 surfaces behave under test | `manage.py test web.tests web.tests_ifo_rooms web.tests_ifo_ops web.tests_ifo_import web.tests_faculty_online web.tests_faculty_history web.tests_faculty_profile` | 235 tests, 3 failures | PASS (see below) |
| The 3 failures are pre-existing, not Phase 07 | `grep -E "^(FAIL\|ERROR):"` on the same run | `DevLoginCoexistTests`, `DevLoginCuratedDemoTests`, `HomeSurfaceNavTests` | PASS - all three are dev-login / home-redirect (Phase 03.1 auth stub); none touches a Guard, IFO, Faculty-self-service or Sys surface |
| Console chrome regression guarded | `grep "class ConsoleChromeTests" web/tests.py` | present at web/tests.py:884 | PASS |
| Guard read-only guarded | `grep "class GuardReadOnlyTests" web/tests.py` | present at web/tests.py:658 | PASS |

### Human Verification Required

None outstanding. The browser UAT (`07-UAT.md`) already discharged every item that needed
a human-equivalent driver: real forms, a real file input, a real EXIF-bearing JPEG, real
CSRF-bearing POSTs, and the real sweep. 14 of 14 tests now have a definitive result; the
one issue found (doubled page chrome) was fixed in-session and regression-tested.

### Carried Caveat (recorded, not a Phase 07 gap)

**VAPID push delivery to a real browser endpoint is unexercised.** UAT test 13 proved the
part GRD-04 owns - that the sweep produces exactly ONE coalesced `guard_floor_alert` per
on-duty guard rather than one per event - by running the real sweep. What it did not prove
is that the resulting notification reaches a subscribed browser over VAPID, because that
needs a registered push subscription and a live service worker. That transport is Phase
05's success criterion #2, not Phase 07's, and `ops/push.py` + the `push_outbox` job are
Phase 05 artifacts this phase only feeds. Recorded here so it is not lost: it should be
exercised end-to-end during the Phase 8 deployment, where a real HTTPS origin makes a real
subscription possible for the first time.

Two smaller items, both non-gaps: Import **Discard** and booking **Cancel** were never
clicked in the browser, but both are wired and both carry automated coverage
(`tests_ifo_import.py:220,327` and six tests in `tests_ifo_ops.py:375-484`), so the
un-clicked controls are proven by test rather than unproven.

### Known Follow-Ups Already On Record

Neither is a Phase 07 success criterion and neither is being papered over:

- **FAC-08:** merged online sibling sessions are not propagated on faculty self-start. The
  Phase 04.2 merge propagation covers the Checker path; the self-start seam does not yet
  call it.
- **IFO-05:** no booking override control exists. This is a deliberate reading of D-09
  recorded in 07-06-SUMMARY.md (threat T-07-27 accepted): building an override would let
  the console manufacture the exact contradictory occupancy that JOB-02c detects and
  IFO-08 cleans up.

### Gaps Summary

No gaps. All five ROADMAP success criteria are achieved in the actual codebase, verified
by direct inspection of the routes, decorators and services rather than from the SUMMARY
files, and corroborated by a live browser UAT that exercised the real forms and the real
database. All fourteen mapped requirements are satisfied. Debt-marker scan is clean. The
one defect surfaced during UAT (duplicate global header on newer console pages) was fixed
by replacing the fragile `url_name` allowlist in `base.html` with a `{% block
global_header %}` opt-out - a structural fix that covers future pages, not a re-listing -
and is regression-tested by `web.tests.ConsoleChromeTests`, which asserts both halves
(one header on console pages AND that `/notifications` still keeps the global one, so
"delete it everywhere" cannot pass).

The single unexercised behavior in the phase's neighbourhood - VAPID delivery to a real
browser endpoint - belongs to Phase 05's transport criterion, is explicitly recorded above,
and does not undercut GRD-04, whose coalescing requirement is proven.

---

*Verified: 2026-07-19*
*Verifier: Claude (gsd-verifier)*

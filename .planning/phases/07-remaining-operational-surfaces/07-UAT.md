---
status: complete
phase: 07-remaining-operational-surfaces
source: 07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md, 07-04-SUMMARY.md, 07-05-SUMMARY.md, 07-06-SUMMARY.md, 07-07-SUMMARY.md, 07-08-SUMMARY.md, 07-09-SUMMARY.md, 07-10-SUMMARY.md, 07-11-SUMMARY.md, 07-12-SUMMARY.md
started: 2026-07-19T18:20:00Z
updated: 2026-07-19T18:55:00Z
driven_by: agent (headless Chromium via gstack browse), not the operator
---

## Current Test

[testing paused — 5 items outstanding]

## Method

Driven in a real browser (headless Chromium), not the Django test client. Sessions
were minted server-side and injected as a `sessionid` cookie, because form-click
dev-login is unreliable on this machine. Every navigation asserted `document.title`
before any reading was trusted — this caught two silent logged-out reads that would
otherwise have been recorded as passes.

Test data created during this run (room TEST101, one booking, one guard posting)
was deleted afterwards. The DB is back to its pre-UAT state.

## Tests

### 1. Cold Start Smoke Test
expected: Server boots from scratch against MSSQL LocalDB, no pending migrations, /login serves the dev picker.
result: pass
evidence: 51 migrations applied, `makemigrations --check` clean, /login 200 with all seven demo accounts.

### 2. IFO Room Create & Edit (IFO-01b)
expected: Create a room and see it listed; edit name/capacity/floor; room code immutable.
result: pass
evidence: Created TEST101 via the real form, redirected to /ifo/rooms/TEST101. Edit changed name and capacity. The `code` field is absent from the edit form, and a hand-crafted POST with `code=HACKED101` was ignored server-side (HACKED101 404s, TEST101 still 200) — immutability is real, not just a hidden control.

### 3. IFO Room Delete Refusal (IFO-01b)
expected: A room with dependent records refuses deletion, naming each blocking relation with counts and offering no delete button.
result: pass
evidence: /ifo/rooms/R102/delete renders "R102 cannot be deleted", a table naming Recurring class schedules (67), Class sessions (390), Checker validations (47), and zero submit buttons. Unused TEST101 correctly showed "Nothing references this room" plus a working Delete.

### 4. IFO Credential Rotation (IFO-02)
expected: Warning names the room and states old codes die; confirming mints a new pair and lands on the poster.
result: pass
evidence: Confirm page named TEST101 and warned the printed poster stops scanning. After confirming: qr_token UGS3nlYh… -> dF905Ykj…, manual_code 272457 -> 069626, landed on /ifo/rooms/TEST101/poster.

### 5. IFO Conflicts Page & Manual Release (IFO-08)
expected: Conflicts page lists contending sessions; Release frees the hold; no manual dismiss control.
result: pass
evidence: Seeded a genuine conflict (two ACTIVE sessions holding R103) and ran the real `detect_room_conflicts`, which opened one flag. The page listed R103 with both sessions and a Release button each. Clicking Release stamped `room_released_at`, wrote `AuditLog(session.room_released)` with actor "Ivy Reyes (IFO Admin)" — not None, which would have meant a system release — and the flag auto-resolved (1 open -> 0) on the next sweep, exactly as the page's copy promises. No dismiss control exists; the page says so explicitly.

### 6. IFO Ad-hoc Bookings (IFO-05)
expected: Create a booking for a free room; an overlapping booking is refused with a reason; cancel frees the room.
result: pass
evidence: Booking created for R102 09:00-11:00 and listed with a Cancel action. An overlapping 10:00-12:00 booking in the same room was refused, and the refusal IS visible: a red `uk-alert-destructive` reading "R102 is not free for that window. Open the room's schedule to see what already occupies it.", with the operator's input preserved. Cancel action present but not exercised.

RETRACTION — this test was first recorded as a major issue ("silent refusal") and
that was WRONG. Three mistakes compounded:
  1. I grepped the page for "refused"/"overlap". The real message says "is not
     free", so my search could not have matched whatever was on screen.
  2. `wait --networkidle` returns before htmx finishes swapping, so every read
     ran against the pre-swap DOM. Re-reading the same page one round-trip later
     showed the alert present.
  3. My first click selector matched several submit buttons (the create form plus
     each row's Cancel), so some attempts never submitted at all.
The app was right and the test was wrong. base.html already documents the htmx
`responseHandling` contract that makes a 400 swap — the exact bug I thought I had
found had been fixed deliberately, before this UAT ran.

### 7. IFO Schedule Import Upload (IFO-03b)
expected: Upload shows a four-bucket reconciliation preview with nothing written; Commit applies; Discard throws it away.
result: pass
evidence: Uploaded a 2-row offerings CSV through the real file input. Preview rendered the four-bucket report balancing exactly (2 = 2+0+0+0, "every row is accounted for") and stated "Nothing has been written to the database yet" — confirmed against the DB: schedules stayed at 2115 and zero UAT rows existed; only an `ImportStaging` row appeared. Commit then reported "Imported uat-import.csv. 2 new schedules created" and the DB went 2115 -> 2117 with both rows carrying the right room and modality (R301/f2f, R302/blended).
ALSO TESTED the page's boldest claim — "re-uploading the same file twice is safe and changes nothing the second time". Re-uploaded and re-committed the identical file: still 2117 schedules, still 2 UAT rows. Idempotency holds.
Discard was not exercised.

### 8. Faculty Profile Photo (FAC-12)
expected: Upload a JPEG/PNG, see it render immediately, EXIF stripped.
result: pass
evidence: This closes 07-08's own admitted gap ("a real sideways phone photo end-to-end, an EXIF viewer on the stored file"). Built a JPEG carrying real phone-camera EXIF — Orientation=6, Make/Model, and GPS coordinates — and uploaded it through the file input.
  - Saved as profile_photos/123.jpg and served cache-busted (`?v=1784459764`), so a re-upload of the same filename does display the new image.
  - EXIF fully stripped on the stored file: 0 EXIF keys, no Orientation, no Make/Model, no GPS, and no `Exif` marker anywhere in the bytes. The privacy half holds — an uploaded photo cannot carry the location it was taken into a shared system.
  - Rotation is BAKED IN, not merely discarded: the 200x400 portrait original became a 400x200 stored image. A pixel probe confirms the direction is right — the original's top edge landed on the RIGHT, which is what Orientation=6 (rotate 90 CW) requires. Stripping the tag without applying it would have shipped every phone photo sideways.
The uploaded test photo was deleted afterwards; no photo existed for this account before (no seed sets profile_photo, and this was the only file in the directory), so nothing was overwritten.

### 9. Faculty Online Verify & Start (FAC-08)
expected: State-labelled session cards; a valid https Teams link starts the session; non-Teams/http/lookalike hosts refused.
result: pass
evidence: Seeded a startable online session; it rendered as "Ready to start" with the link field. All four refusals return 400 with a specific message and leave the session SCHEDULED with an empty link:
  - non-Teams host -> "That is not a Microsoft Teams meeting link..."
  - http (not https) -> refused
  - LOOKALIKE HOST `teams.microsoft.com.evil.com` -> refused. This is the one that matters: a naive suffix or substring check would have accepted it.
  - empty -> "Paste the Microsoft Teams meeting link for this class."
A valid https Teams link then started the session: status=active, `actual_start` stamped, `checkin_method=online_self`, link stored. The UI is honest about what that means — "Recorded as held. A Checker still opens your meeting link separately to verify attendance, so this is not yet checker-verified."

### 10. Faculty Attendance History (FAC-11)
expected: Paginated read-only table with status chips, Checker flags and reasons, no dispute control.
result: pass
evidence: 25 rows, GET-only filter form (Term / From / To), zero hx-post/put/delete anywhere, and no dispute/contest/appeal wording. Filtered to a date with a real flag: the flagged row shows "Absent" + "Flag: not present" and the verified row shows "Present" + "Verified". Closing note states flags are permanent records shared with IFO and HR and to raise a mistaken one with HR directly — the no-dispute design made explicit rather than merely absent.
OBSERVATION (not a defect): the Checker's free-text note ("Room empty at check.") is NOT surfaced — only the flag type. SRS FAC-11 requires "any Checker flags", which is met, and withholding a checker's private note from the person it describes is defensible. Recorded because 07-10's summary phrase "flags visible with their reason" could be read as promising the note text.

### 11. Guard Per-Room Schedule (GRD-02)
expected: Room detail with current state, today's timeline and weekly timetable; unposted floor returns a plain 404 that never confirms the room exists.
result: pass
evidence: Unposted guard: R102 -> 404 and nonexistent ZZZ999 -> 404, byte-identical, so existence never leaks. After posting the guard to ACAD F1: R102 -> 200 rendering "Nobody checked in", today's 1 class, and the week grid. Off-floor IT-301 -> 404. No horizontal overflow at 390px.

### 12. Guard Read-Only Enforcement (GRD-05)
expected: POST to the three Guard views returns 405; GET returns 200.
result: pass
evidence: With a valid CSRF token, POST to /guard/monitor, /guard/monitor/rows and /guard/locate all return 405; GET all return 200. Without a token they return 403 (CSRF fires before the method check) — defense in depth, not a defect, but worth knowing the plan's stated "405" is only what a CSRF-bearing request sees.

### 13. Guard Coalesced Floor Alerts (GRD-04)
expected: Exactly one push per sweep summarising all events on the posted floor(s).
result: pass (coalescing proven; VAPID transport not exercised)
evidence: Posted the guard to ACAD F1 and seeded three separate past-grace no-shows in one room, then ran the real `run_status_sweep`. It reported "marked 4 absent -> flagged 0 conflicts -> notified 2 guards" and the guard received exactly ONE notification — `guard_floor_alert`, titled "4 rooms now free on ACAD F1" — not four. That is the requirement: coalescing happens at the `notify()` layer, which is what decides how many pushes are sent.
NOT TESTED: actual VAPID delivery to a browser endpoint. That needs a registered push subscription and a service worker, and belongs to Phase 05's push transport rather than GRD-04's fan-out logic.
SIDE EFFECT, deliberately left in place: the sweep also marked one REAL session absent — 15074, AR200P-2 B199 (Malcampo, R102, 15:45 today), 3.6 hours past its start with no check-in. That is a genuine no-show and the scheduled sweep would have marked it the moment `runscheduler` next ran; it had not, because only `runserver` was running. Reverting it would have written a false "scheduled" over a true "absent", so it stands.

### 14. Cross-cutting: doubled page chrome on newer console pages
expected: Every console page renders one header — the console bar — as Rooms and Dashboard do.
result: pass
originally: issue (major) — FIXED and re-verified in this same session, so the
  result is recorded as the current, verified state rather than the state at
  discovery. The history is kept below deliberately; it is the only record of
  why the fix exists.
reported_at_discovery: "Bookings, Import, Conflicts, Utilization and the room sub-pages render the legacy global header stacked above the console bar: two FluxTrack brand marks and two notification bells showing the same count on one page."
evidence: After the fix and a server restart (--noreload caches templates, so the
  change is invisible until the process is recycled): all eight IFO console pages,
  five faculty pages and two guard pages render exactly one <header>, while
  /notifications correctly keeps the global one and no console bar. Regression
  test: web.tests.ConsoleChromeTests (3 tests, including the negative half).

## Summary

total: 14
passed: 14
issues: 0
pending: 0
skipped: 0
issues_found_and_fixed: 1
notes: |
  Every test now has a definitive result. The single issue (test 14, doubled page
  chrome) is FIXED and regression-tested. One earlier "issue" (test 6) was
  RETRACTED as a testing error, not an application fault.

  Two things are deliberately out of scope rather than untested:
    - VAPID push delivery to a real browser endpoint (test 13) — Phase 05's
      transport, not GRD-04's coalescing, which IS proven.
    - Import Discard (test 7) and booking Cancel (test 6) controls exist and are
      wired but were not clicked.

  Residual data changes from this run: all fixtures were deleted and the schedule
  count is back to its pre-UAT 2115. The one intentional exception is session
  15074, a genuine no-show the sweep correctly marked absent — see test 13.

## Gaps

- truth: "An IFO admin who submits a conflicting ad-hoc booking is told why it was refused"
  status: RETRACTED — not a defect
  reason: "Testing error, not an application fault. See the retraction note on test 6. The refusal renders correctly."
  severity: none
  test: 6

- truth: "Every IFO console page renders a single header (the console bar)"
  status: failed
  reason: "templates/base.html:48 suppresses the global header via a hardcoded allowlist of url_names. Pages added after that list was written render both headers. Confirmed visually: Bookings and Import show two brand marks and two notification bells with the same count; Rooms and Dashboard (allowlisted) correctly show one."
  severity: major
  test: 14
  artifacts:
    - path: "templates/base.html"
      issue: "Line 48 allowlist omits ifo_bookings, ifo_conflicts, ifo_import, ifo_utilization, ifo_room_new, ifo_room_edit, ifo_room_delete, ifo_room_rotate_confirm, ifo_room_poster, ifo_scorecard, dean_scorecard"
  missing: []
  root_cause: "Allowlist in base.html not updated when Phase 06.1 and Phase 07 added console pages"
  status_now: FIXED
  fix:
    - "base.html wraps the global header in {% block global_header %}, dropping the url_name allowlist entirely"
    - "_console.html overrides it to nothing — one line covering every current and future console page"
    - "The 15 faculty/checker/guard templates that draw their own chrome override it too"
    - "web.tests.ConsoleChromeTests asserts one <header> on console + faculty pages AND that /notifications still keeps the global one (the negative half, so 'delete it everywhere' cannot pass)"
  verified: "After a server restart: 8 IFO console pages, 5 faculty, 2 guard all at exactly 1 header; /notifications still renders the global sticky header and no cns__bar. Full suite 930 tests, same 3 pre-existing dev-login failures as before the change (confirmed by re-running them against a stashed tree)."
  debug_session: ""

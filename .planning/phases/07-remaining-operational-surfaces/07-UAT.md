---
status: partial
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
result: skipped
reason: The page renders correctly with its explanatory copy and no dismiss control, but the live DB had zero open conflicts, so the Release action itself was never exercised. Needs a seeded conflict to test properly.

### 6. IFO Ad-hoc Bookings (IFO-05)
expected: Create a booking for a free room; an overlapping booking is refused with a reason; cancel frees the room.
result: issue
reported: "Overlapping booking is refused silently — the form redisplays with the user's input, no error message anywhere, and the booking simply never appears."
severity: major
evidence: First booking created (id 2, active, listed with a Cancel action). Second booking overlapping 09:00-11:00 with 10:00-12:00 in the same room was correctly NOT created — but the page showed zero message elements, and the only occurrence of "refus"/"overlap" in the whole page text was the static helper paragraph that renders regardless. The conflict LOGIC is right; the user-facing refusal is missing. Cancel action present but not exercised.

### 7. IFO Schedule Import Upload (IFO-03b)
expected: Upload shows a four-bucket reconciliation preview with nothing written; Commit applies; Discard throws it away.
result: skipped
reason: Page renders correctly (clear "How this works", file input, "No file staged" empty state) but no file was actually uploaded, so preview/commit/discard were not exercised. This is the flow most worth a real operator run, against a real registrar export.

### 8. Faculty Profile Photo (FAC-12)
expected: Upload a JPEG/PNG, see it render immediately, EXIF stripped.
result: skipped
reason: Page renders with exactly one file input and a single header. No image was uploaded — the summary's own open item (a real sideways phone photo, EXIF viewer on the stored file) still stands and needs a real camera file.

### 9. Faculty Online Verify & Start (FAC-08)
expected: State-labelled session cards; a valid https Teams link starts the session; non-Teams/http/lookalike hosts refused.
result: [pending]

### 10. Faculty Attendance History (FAC-11)
expected: Paginated read-only table with status chips, Checker flags and reasons, no dispute control.
result: [pending]

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
result: [pending]
note: Needs a live push subscription plus a sweep run with multiple events. Not reachable from a headless browser without granting notification permission and registering a VAPID endpoint.

### 14. Cross-cutting: doubled page chrome on newer console pages
expected: Every console page renders one header — the console bar — as Rooms and Dashboard do.
result: issue
reported: "Bookings, Import, Conflicts, Utilization and the room sub-pages render the legacy global header stacked above the console bar: two FluxTrack brand marks and two notification bells showing the same count on one page."
severity: major

## Summary

total: 14
passed: 6
issues: 2
pending: 3
skipped: 3

## Gaps

- truth: "An IFO admin who submits a conflicting ad-hoc booking is told why it was refused"
  status: failed
  reason: "Refusal is silent — form redisplays with input intact, no message element, booking absent from list. Only 'refus'/'overlap' text on the page is the static helper paragraph shown regardless of outcome."
  severity: major
  test: 6
  artifacts:
    - path: "web/ifo.py"
      issue: "booking_create refusal path appears not to attach a message before re-rendering"
  missing:
    - "Surface the refusal reason to the user (Django message or inline form error) when room_is_free rejects the booking"
    - "Regression test asserting the refusal message is present in the response, not just that the Booking row was not created"
  root_cause: ""
  debug_session: ""

- truth: "Every IFO console page renders a single header (the console bar)"
  status: failed
  reason: "templates/base.html:48 suppresses the global header via a hardcoded allowlist of url_names. Pages added after that list was written render both headers. Confirmed visually: Bookings and Import show two brand marks and two notification bells with the same count; Rooms and Dashboard (allowlisted) correctly show one."
  severity: major
  test: 14
  artifacts:
    - path: "templates/base.html"
      issue: "Line 48 allowlist omits ifo_bookings, ifo_conflicts, ifo_import, ifo_utilization, ifo_room_new, ifo_room_edit, ifo_room_delete, ifo_room_rotate_confirm, ifo_room_poster, ifo_scorecard, dean_scorecard"
  missing:
    - "Invert the condition: suppress the global header whenever the template extends a console shell, rather than enumerating url_names — an allowlist fails silently every time a page is added"
    - "Regression test asserting each console page renders exactly one <header>"
  root_cause: "Allowlist in base.html not updated when Phase 06.1 and Phase 07 added console pages"
  debug_session: ""

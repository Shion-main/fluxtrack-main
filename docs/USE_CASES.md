# FluxTrack: Use Cases, Features & Scenes

**Last updated:** 2026-07-02
**Purpose:** the single reference for what FluxTrack does, per role — every scene
(screen) it needs, every user scenario that scene serves, and whether it's
built yet. This is the working build list. When a slice starts, its
requirement IDs and scenario numbers are what "done" is measured against.
Requirement IDs (`FAC-02`, `CHK-07`, etc.) trace back to `FluxTrack_SRS.md`
§4 — that document is the source of truth for exact wording; this document
is the source of truth for *build sequencing and current status*.

## Legend

- ✅ **Built** — implemented and verified (in-browser or by test)
- 🚧 **Partial** — model/backend exists but no dedicated UI, or UI exists but
  incomplete
- ⬜ **Not started**

## Status summary

| Role | Scenes built | Scenes partial | Scenes not started |
|---|---|---|---|
| Faculty | 2 | 1 | 2 |
| Checker | 0 | 0 | 3 |
| IFO Admin | 2 | 4 | 3 |
| HR Admin | 0 | 0 | 3 |
| Guard | 0 | 0 | 4 |
| Dean | 0 | 0 | 3 |
| System Admin | 0 | 2 | 2 |
| Cross-cutting (Auth, Scan Resolver, Reporting, Notifications, Jobs) | 1 | 4 | 4 |

The scan resolver and Faculty check-in are the only fully closed loop today.
Everything else is either scaffolding (models exist, no surface) or not
started.

---

## Cross-cutting: Authentication (AUTH-01–05)

Not a role — applies to every scene below.

- **AUTH-01/02 (Entra ID SSO)** — ⬜ Not started. Standing in for it: a
  DEBUG-only dev-login (`web/views.py:login_view`) that signs in as any
  seeded user by username, no password. This must be replaced before any
  real deployment; it is explicitly a stub, not a security boundary.
- **AUTH-03 (unprovisioned identities blocked)** — ✅ trivially true today
  (dev-login only accepts existing seeded usernames); will need real
  handling once Entra ID is wired (an authenticated-but-unprovisioned Entra
  identity must be rejected at the boundary, not just "no matching row").
- **AUTH-04 (server-side role/data scoping)** — 🚧 Partial. Implemented for
  the two built surfaces via decorators (`faculty_required`, `ifo_required`
  in `web/faculty.py` / `web/ifo.py`); every new surface needs its own
  equivalent decorator/check — this is not a framework-level guarantee, it's
  applied per view.
- **AUTH-05 (deactivation blocks access)** — 🚧 Partial. `User.is_active`
  already gates Django's auth backend and the dev-login query, so
  deactivation works today via the Django admin's `is_active` toggle. No
  dedicated "deactivate user" action exists yet (SYS-01).
- **Divergence to resolve before AUTH-01/02 work starts:** the SRS
  (§2.1, AUTH-02) specifies a backend-issued JWT for API calls. The current
  implementation uses Django's session-based auth throughout (`login()` /
  `request.user`), because the interface is server-rendered HTML, not a
  separate API-consuming frontend. Decide explicitly when SSO is built:
  keep session auth (simpler, matches the actual architecture) and treat
  the SRS's JWT language as describing the Entra ID exchange only, or
  introduce a real backend JWT layered on top of sessions. Don't let this
  get decided implicitly by whatever the SSO library defaults to.

---

## Faculty (FAC)

Mobile-first, camera-first, one-handed. Minimal training, minimal
interaction burden (SRS §2.3).

### Scenes

| Scene | Status | Requirement IDs | Files |
|---|---|---|---|
| My Schedule (day/week) | ✅ Built | FAC-01 | `templates/faculty/schedule.html`, `web/faculty.py:schedule` |
| Scan / Check-in | ✅ Built | FAC-02–06, 09, 10, SCAN-01–07 | `templates/faculty/scan.html`, `_outcome.html`, `web/scan.py` |
| Modality control + Online "Verify & Start" | ⬜ Not started | FAC-07, FAC-08 | — |
| Attendance history | ⬜ Not started | FAC-11 | — |
| Profile + notification preferences | ⬜ Not started | FAC-12 | — |

### Scenarios

**UC-FAC-1 — Sign in and land on schedule.** ✅ Built.
Faculty signs in → routed to `/` → role-routed home shows "My schedule" and
"Check in" cards → `/faculty/schedule` shows today's sessions + this week.

**UC-FAC-2 — Happy-path check-in.** ✅ Built (SCAN-01, 02, FAC-02, 03).
Faculty scans room QR (or types 6-digit code) within the grace window for a
session scheduled in that room → outcome `checked-in` → session becomes
`active`, `actual_start` stamped, `checkin_method` recorded.

**UC-FAC-3 — Check-out.** ✅ Built (FAC-05).
Faculty re-scans the same room while their session is active, at/after the
early-end threshold → outcome `checked-out` → session `completed`,
`actual_end` stamped.

**UC-FAC-4 — Early end requires a reason.** ✅ Built (FAC-06).
Faculty re-scans before the early-end threshold → outcome `early-end`,
`needs_confirm=true` → form asks for a reason → on confirm, session
`completed`, `ended_early=true`, reason recorded.

**UC-FAC-5 — Late arrival marks Absent.** ✅ Built (FAC-04).
Faculty scans after the grace window → outcome `absent` → session `absent`,
no active session starts. (Checker override to correct this is CHK-06,
not yet built — so today an Absent-by-lateness call is final in the UI even
though the SRS intends it to be correctable.)

**UC-FAC-6 — Wrong room, two-step confirm.** ✅ Built (FAC-10).
Faculty scans a room that isn't their scheduled one, but has a session due
now → outcome `wrong-room`, `needs_confirm=true` → confirm → session's room
updates, a `Notification` row is created per IFO Admin (`_notify_ifo`) —
but no surface displays it yet (see Notifications section): the data exists,
nobody can see it until NOTIF-01 ships.

**UC-FAC-7 — Room occupied, force handover.** ✅ Built (FAC-09).
Faculty scans a room with another active session in it → outcome
`room-occupied`, `needs_confirm=true` → confirm → prior session force-closed
(`completed`), new session `active`, handover recorded and audited, with no
faculty-to-faculty interaction required.

**UC-FAC-8 — Guard-rail outcomes.** ✅ Built (SCAN-02 remaining outcomes).
`too-early` (before the open window), `online-reject` (session is Online,
should use Verify & Start instead), `no-schedule` (nothing due in this
room), rate-limited manual codes (SCAN-05) — all return a discrete outcome
with no state change.

**UC-FAC-9 — Set session modality.** ⬜ Not started (FAC-07).
Faculty should be able to set a session's modality (F2F/Blended/Online),
defaulting to scheduled modality, with change timestamp + author visible to
IFO/HR. No UI exists; `Session.declared_modality` and
`modality_changed_at/by` fields exist on the model, unused.

**UC-FAC-10 — Start an Online session.** ⬜ Not started (FAC-08).
For Online (and Blended stays QR-based per F2F), faculty needs a
"Verify and Start" action requiring a valid MS Teams link — no QR scan
involved. `Session.teams_link` field exists, no view/template.

**UC-FAC-11 — View own attendance history.** ⬜ Not started (FAC-11).
Read-only, including any Checker flags against them, no dispute mechanism.

**UC-FAC-12 — Manage profile + notification prefs.** ⬜ Not started
(FAC-12). Profile photo (used for CHK-02 identity matching) and
notification mute preferences (NOTIF-03).

---

## Checker (CHK)

Mobile-first, intermittent connectivity, the system's source of truth for
presence (SRS §2.3). **Nothing in this section is built yet** — this is the
next slice.

### Scenes

| Scene | Status | Requirement IDs |
|---|---|---|
| Floor view (coverage + priority queue) | ⬜ Not started | CHK-07 |
| Room-state scan + verify actions | ⬜ Not started | CHK-01–06 |
| Offline scan queue | ⬜ Not started | CHK-08 |

### Scenarios

**UC-CHK-1 — On-duty gating.** ⬜ (CHK-01).
Checker's verification powers only activate while they have an active
`Assignment` (shift or standing) on the floor they're scanning. Off-duty or
wrong-floor scans should be rejected with a clear reason, not silently
denied.

**UC-CHK-2 — Scan a room, see state + photo.** ⬜ (CHK-02, CHK-03).
Checker scans a room QR on their assigned floor → sees the room's current
session state and the scheduled faculty member's profile photo → chooses
one of: Verify, Flag identity mismatch, Flag not present, Confirm absent,
Confirm empty / Verified empty.

**UC-CHK-3 — Verify marks the session checker-verified.** ⬜ (CHK-04).
A Verify finding sets `verified_by_checker` true (already a derived
property on `Session` reading `CheckerValidation`, per the model — the
verify action itself is what's missing).

**UC-CHK-4 — Identity mismatch flag.** ⬜ (CHK-05).
Recorded as a flag visible to IFO and HR, no dispute workflow (matches
FAC-11's "read-only, no dispute" from the faculty side).

**UC-CHK-5 — Override auto-Absent.** ⬜ (CHK-06).
Faculty is physically present despite an auto-Absent session (late scan or
missed scan entirely). Checker corrects it to Present. If the room was
already released (room-hold window elapsed), attendance is still corrected
but the room isn't reopened — a conflict notification goes to IFO instead.
This is the one case in the whole system where a Checker's action changes
a Faculty-recorded outcome after the fact; get the "room not reopened, IFO
notified" branch right, it's easy to accidentally reopen the room.

**UC-CHK-6 — Floor view.** ⬜ (CHK-07).
Coverage progress (how much of the floor's active sessions have been
checked), a priority queue sorted by oldest unverified active session,
color-coded room cards. This is the Checker's primary landing screen, not
a secondary one — most sessions should start here, not from a raw scan.

**UC-CHK-7 — Offline queue.** ⬜ (CHK-08).
Scans made while offline queue locally (IndexedDB — the pattern already
proven in `poc/app.py`), replay in batch on reconnect, each **re-validated
server-side before applying** (not blindly replayed — a room's state may
have changed while offline) or flagged for IFO if it can't be cleanly
applied.

---

## IFO Admin (IFO)

Desktop-first. Configures and monitors: rooms, codes, schedules, bookings,
assignments, live monitoring, reporting (SRS §2.3).

### Scenes

| Scene | Status | Requirement IDs | Files |
|---|---|---|---|
| Rooms list + detail (read) | ✅ Built | part of IFO-01, IFO-11 | `templates/ifo/rooms.html`, `_room_panel.html`, `room_detail.html` |
| QR poster + code image | ✅ Built | IFO-01 | `templates/ifo/poster.html`, `web/ifo.py:room_qr` |
| Live room board | ✅ Built | IFO-07 | `templates/ifo/rooms.html`, `_board.html`, `web/ifo.py:_room_board` |
| Room CRUD (create/edit/delete) | 🚧 Partial (Django admin only) | IFO-01 | — |
| Schedule import + CRUD | 🚧 Partial (CLI import only, no UI) | IFO-03 | `scheduling/management/commands/import_offerings.py` |
| Course offerings / terms / breaks mgmt | 🚧 Partial (models + admin only) | IFO-04 | — |
| Code rotation | ⬜ Not started | IFO-02 | — |
| Bookings | ⬜ Not started | IFO-05 | — |
| Checker/Guard floor assignments | ⬜ Not started | IFO-06 | — |
| Manual room release / conflict resolution | ⬜ Not started | IFO-08 | — |
| Dashboard (summary cards + scorecard drill-down) | ⬜ Not started | IFO-09 | — |
| Weekly report view/export | ⬜ Not started | IFO-10 (see Reporting section) | — |

### Scenarios

**UC-IFO-1 — Import a term's schedule.** ✅ Built, CLI only (IFO-03, IFO-04).
`manage.py import_offerings --file ... --building ... --floor ...` parses
the registrar CSV's `Schedule` column, creates/updates faculty (by
institutional email, unusable password), rooms (auto-creates building →
floor → room hierarchy), and `Schedule` rows; deactivates all other terms
so exactly one is active. **Gap**: this only runs from the command line —
IFO-03 calls for IFO to do this themselves, so a CSV-upload UI with
validation/conflict reporting is still needed even though the underlying
parser exists and is tested against real registrar data.

**UC-IFO-2 — Materialize sessions.** ✅ Built, CLI only (JOB-01).
`manage.py materialize_sessions --days N` creates dated `Session` rows from
active schedules, skipping academic breaks and out-of-term dates,
idempotently. **Gap**: JOB-01 specifies this runs *daily automatically* —
today it's a manual command, not wired to APScheduler (tracked under
Scheduled Jobs below, not duplicated here).

**UC-IFO-3 — Prepare a room and print its poster.** ✅ Built (IFO-01).
IFO opens a room's detail page → poster view renders room name, QR, and
6-digit code with print-only CSS (app chrome hidden via `@media print`) →
print produces a clean poster.

**UC-IFO-4 — View a room's per-term schedule.** ✅ Built (IFO-11).
Room detail page shows the room's recurring weekly schedule for the active
term plus its next 10 upcoming sessions — read-only, matches what GRD-02
and department-scoped Dean access will need to reuse.

**UC-IFO-5 — Live monitoring.** ✅ Built (IFO-07), merged into UC-IFO-4.
`/ifo/rooms` is now a **room board**: one tile per room, grouped by building
and floor, polling `/ifo/rooms/board` at the configured interval. `/ifo/live`
301s here and the separate nav item is gone.

The tile state is derived per room from today's sessions relative to `now`
(`web/room_state.py:room_tile`, shared with the Guard surfaces): **absent** (marked ABSENT, or still SCHEDULED past
the grace window — the board calls a no-show before the sweep job stamps it),
**starting** (inside grace, watch but not yet a problem), **in session**,
**online** (the class shifted to Online, so the room is legitimately empty —
D-05/MOD-01), **free**, **idle**. Problem states sort to the front of their
group and drive the "Needs attention" filter. Clicking a tile opens a
slide-over (`_room_panel.html`) with what is happening right now, today's
timeline, and the recurring week.

**Gap vs. spec**: SRS asks for a "live map" (spatial room layout). The board is
a sorted grid, not a floor plan — it needs no room geometry and stays readable
at 200+ rooms, where a map does not. Building a true spatial map is still an
open call, but the "live calendar" half of the intent is covered by the
slide-over's Today timeline.

**UC-IFO-6 — Room CRUD.** 🚧 Partial, Django admin only (IFO-01).
Creating/editing/deleting rooms currently requires `/admin/`. A dedicated
IFO-facing CRUD UI (with the poster/QR actions already built, this time
reachable without admin credentials) is the gap.

**UC-IFO-7 — Rotate a room's codes.** ⬜ Not started (IFO-02).
Regenerate `qr_token` + `manual_code`, audit-logged, immediately
invalidating old posters. Model already has `code_rotated_at`/`_by` fields
— the action itself doesn't exist.

**UC-IFO-8 — Ad-hoc bookings.** ⬜ Not started (IFO-05).
Create/cancel bookings conflict-checked against sessions and other
bookings. `Booking` model exists, unused.

**UC-IFO-9 — Assign Checkers/Guards to floors.** ⬜ Not started (IFO-06).
By shift or standing posting. `Assignment` model exists, unused — and this
is a hard blocker for the entire Checker slice (CHK-01 requires an active
Assignment to grant verification powers), so this needs to land before or
alongside Checker work, not after.

**UC-IFO-10 — Manual room release / resolve conflicts.** ⬜ Not started
(IFO-08).

**UC-IFO-11 — Dashboard.** ⬜ Not started (IFO-09). Summary cards (Faculty,
Room Occupancy in session-hours, Sessions, Absences) over a selectable
range, faculty-scorecard drill-down (shared logic with RPT-04).

---

## HR Admin (HR)

Consumes verified attendance for external payroll; performs no payroll
itself (SRS §2.3). **Nothing built.**

### Scenes

| Scene | Status | Requirement IDs |
|---|---|---|
| Attendance list (filter/search) | ⬜ Not started | HR-01, HR-02 |
| CSV export | ⬜ Not started | HR-03 |

### Scenarios

**UC-HR-1 — View verified attendance.** ⬜ Per faculty/session: present/
absent, actual times, check-in method, checker-verification status.

**UC-HR-2 — Filter and search.** ⬜ By faculty, department, date range, term.

**UC-HR-3 — Export CSV.** ⬜ Session-level detail for external payroll.

No payroll periods/locks/finalization exist or should exist (HR-04) — this
is a boundary, not a gap.

---

## Guard (GRD)

Read-only. Live floor status, per-room schedules, faculty locator (SRS
§2.3). **Nothing built.**

### Scenes

| Scene | Status | Requirement IDs |
|---|---|---|
| Floor monitor | ⬜ Not started | GRD-01 |
| Per-room schedule | ⬜ Not started (reuse IFO-11's view) | GRD-02 |
| Faculty locator | ⬜ Not started | GRD-03 |
| Push alerts | ⬜ Not started | GRD-04 |

### Scenarios

**UC-GRD-1 — Live floor status.** ⬜ Read-only, polled, scoped to assigned
floor(s) (depends on IFO-06 assignments existing).

**UC-GRD-2 — Room schedule.** ⬜ Should literally reuse the room-detail view
already built for IFO-11 — same data, same template shape, gated by a
`guard_required` decorator instead of `ifo_required`. Not a new build from
scratch.

**UC-GRD-3 — Faculty locator.** ⬜ Search by name → current location
(room/building/floor, course, end time), or "Online — not on campus", or
"Not in a class" + next class, plus today's schedule. This is a genuinely
new query (find a faculty member's *currently active* session across all
rooms), not a reuse of an existing view.

**UC-GRD-4 — Push alerts for floor activity.** ⬜ Debounced web-push
(depends on NOTIF-02's VAPID infrastructure existing first).

Guards get no write access anywhere (GRD-05) — enforced by simply never
adding write views to a `guard_required`-gated surface, not a special check.

---

## Dean (DEAN)

Read-only, department-scoped (SRS §2.3). **Nothing built.**

### Scenes

| Scene | Status | Requirement IDs |
|---|---|---|
| Department attendance reporting + scorecards | ⬜ Not started | DEAN-02 |
| Weekly report (department-scoped) | ⬜ Not started | DEAN-03 |

### Scenarios

**UC-DEAN-1 — Department-scoped access.** ⬜ Enforced via
`request.user.department` matching, set by System Admin (DEAN-01) — a data
filter on top of the same reporting views IFO and HR use, not a separate
implementation.

**UC-DEAN-2 — Attendance reporting + scorecards.** ⬜ Same underlying
aggregate functions as IFO-09/RPT-04, filtered to the Dean's department(s).

**UC-DEAN-3 — Weekly report.** ⬜ Same `WeeklyReport` records as IFO-10,
filtered to department.

---

## Reporting (RPT)

Cross-cutting — consumed by IFO (IFO-10), HR (HR-03), and Dean (DEAN-03).
**Nothing built.** This is the largest single remaining gap: every role
above except Faculty/Checker depends on some slice of this.

### Scenarios

**UC-RPT-1 — Weekly Consolidated Attendance Report.** ⬜ (RPT-01). Per
department: one row per faculty (scheduled, held/present, absent,
attendance %, checker-verified count) + itemized absence detail (date,
course/section, room, time).

**UC-RPT-2 — On-demand + auto-weekly generation.** ⬜ (RPT-02). Available
by week/department on demand; auto-generated weekly (depends on JOB-03),
stored, IFO notified.

**UC-RPT-3 — CSV + PDF export.** ⬜ (RPT-03). Both formats, per-department
or all.

**UC-RPT-4 — Faculty scorecard.** ⬜ (RPT-04). Scheduled vs. held,
attendance %, absences, early-ends, modality breakdown, selectable period.
Shared by IFO-09's drill-down and Dean's per-faculty view — build this once
as a reusable aggregate function, not three times.

**UC-RPT-5 — Graceful degradation.** ⬜ (RPT-05). Pure, independently
tested aggregate functions (matches the resolver's pattern in
`scheduling/resolver.py`); a single failed aggregate shows an error state
in its section, not a blank page. Build this as a constraint on *how*
RPT-01/04 get implemented, not a separate feature.

---

## Notifications (NOTIF)

Cross-cutting. **Write path partially exists, no read surface.**

- `Notification` and `PushSubscription` models exist (`ops/models.py`).
- `web/scan.py`'s `_notify_ifo()` (called on FAC-10 wrong-room confirmation)
  genuinely creates a `Notification` row per active IFO Admin — verified by
  reading the code, not assumed. So the write path for at least one event
  type already exists.
- What's actually missing: **any view that reads `Notification` back out.**
  Those rows are created and then sit unread — there's no in-app list
  (NOTIF-01) and no push delivery (NOTIF-02). Confirming a wrong-room change
  today produces a database row an IFO Admin has no way to see.

### Scenarios

**UC-NOTIF-1 — In-app notification list.** ⬜ (NOTIF-01). Polled list, all
roles.

**UC-NOTIF-2 — Web push.** ⬜ (NOTIF-02). VAPID, for floor activity
(Checker/Guard) and key events (wrong-room, force handover, room conflict,
weekly report ready). Blocks GRD-04.

**UC-NOTIF-3 — Mute preferences.** ⬜ (NOTIF-03). Per-user, feeds FAC-12.

---

## System Admin (SYS)

Desktop. Users, settings, audit, job monitoring (SRS §2.3).

### Scenes

| Scene | Status | Requirement IDs |
|---|---|---|
| User provisioning | 🚧 Partial (Django admin + `seed_demo` command) | SYS-01 |
| System settings | 🚧 Partial (Django admin on `SystemSetting`) | SYS-02 |
| Audit log | 🚧 Partial (Django admin link from home surface) | SYS-03 |
| Scheduled-job monitoring | ⬜ Not started | SYS-04 |

### Scenarios

**UC-SYS-1 — Provision users.** 🚧 Today: `seed_demo` management command
creates 7 fixed demo users; real provisioning (map an Entra identity to a
User, assign role/department, deactivate) happens through `/admin/`.
Whether this ever needs a dedicated non-admin UI depends on how comfortable
the actual system admin is with Django admin — worth deciding explicitly
rather than assuming a custom UI is required just because other roles have
one.

**UC-SYS-2 — Edit policy values.** 🚧 `SystemSetting` rows editable via
admin; `get_policy()` (`ops/policy.py`) already reads them with fallback to
`settings.FLUXTRACK_POLICY` defaults — the read path is solid, only the
"friendly UI to edit" part is missing, and (per UC-SYS-1) may not need to
be more than admin.

**UC-SYS-3 — Audit log.** 🚧 Viewable via `/admin/ops/auditlog/`, linked
from the System Admin home surface already (`web/views.py` SURFACES dict).

**UC-SYS-4 — Job monitoring.** ⬜ Last-run status, success/failure, rows
affected, for whatever job runner ends up wired (see Scheduled Jobs below).
No job-run tracking exists at all yet — this can't be built before the
scheduler itself is.

---

## Scheduled Jobs (JOB)

Cross-cutting infrastructure, not a role. Currently: **all three jobs exist
as manually-invoked management commands, none run automatically.**

**UC-JOB-1 — Daily materialization.** 🚧 Logic built (JOB-01, see UC-IFO-2)
as `materialize_sessions`; not scheduled.

**UC-JOB-2 — Status sweep.** ⬜ Not started (JOB-02). This is a real gap,
not just "not automated" — the logic itself doesn't exist yet. Today,
Absent is only detected *reactively*, at scan time, via the resolver
(`resolve_faculty_scan`'s grace-window check) — if a faculty member never
scans at all, nothing currently marks that session Absent, because there's
no scan to trigger the resolver. JOB-02 needs a proper sweep: mark
no-show sessions Absent after grace (independent of any scan happening),
release rooms after the room-hold window (unless a Checker-present override
applies — ties to CHK-06), raise room-conflict flags. Build this before
relying on "Absent" being trustworthy for any session nobody scanned into.

**UC-JOB-3 — Weekly report generation.** ⬜ Not started (JOB-03). Depends
on RPT-01 existing first.

**Process placement**: SRS §6.7 requires APScheduler run as a single
dedicated scheduler process, separate from web workers, to prevent
duplicate job execution. None of JOB-01/02/03 are wired into any scheduler
process yet — this is infrastructure work, not per-job work, and blocks all
three regardless of which job gets built first.

---

## Suggested build order

Not a commitment, a reasoned sequence based on what blocks what:

1. **JOB-02 (status sweep)** — makes Absent trustworthy without requiring
   every session to be scanned; several other scenarios (CHK-06, IFO-08)
   assume this exists.
2. **IFO-06 (Checker/Guard assignments)** — hard blocker for CHK-01; no
   Checker scenario works without it.
3. **Checker surface (CHK-01–08)** — closes the core attendance loop (this
   was already the agreed next slice before this document).
4. **NOTIF-01/02 infrastructure** — several already-built flows (FAC-10's
   IFO notification) are silently incomplete without it.
5. **Reporting (RPT-01–05)** — unblocks IFO-10, HR-03, DEAN-03 simultaneously
   since they share aggregates.
6. **Guard, Dean, HR surfaces** — mostly thin, read-only layers over
   reporting/assignment data that exists by this point.
7. **AUTH-01/02 (Entra ID), MSSQL migration, AWS deployment** — can run in
   parallel with the above once a working local dev-login stand-in exists
   (it already does); no reason to block feature work on this.

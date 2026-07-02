# FluxTrack: Modality Shift Approval + Reduced Checker Room-Release Scope

**Date:** 2026-07-02
**Status:** Approved, pending implementation plan

## Context

Two related rule changes, designed together because they share the same
goal: **a room's occupancy state should follow policy and schedule
mechanically, without requiring a Checker to physically confirm emptiness
before it can be released.**

1. A new formal workflow lets an instructor request a modality change
   (F2F/Blended ↔ Online), routed through their Dean for approval, that
   automatically releases the affected room the moment it's approved —
   instead of the room sitting "pending release" until the room-hold
   window elapses or a Checker manually confirms it's empty.
2. A Checker's existing planned ability to override an auto-Absent session
   back to Present (CHK-06) is removed. Once the scheduled status sweep
   marks a session Absent, that's final; the room releases on the normal
   `room_hold_minutes` timer with no human check required.

Both changes reduce the Checker's role in the room-release lifecycle to
zero for the cases they cover — Checkers verify *presence*, not the
*absence* side of the loop anymore.

This builds on the existing scan resolver and Session/Schedule models
(`scheduling/models.py`, `scheduling/resolver.py`) and the Checker
scenarios already documented in `docs/USE_CASES.md`'s CHK section, none of
which are built yet — so this is a specification change with no existing
code to migrate away from, only planned scenarios to correct before they're
built.

## 1. `ModalityShiftRequest`: what it is

An instructor-submitted request to change a session's or a recurring
schedule's modality between F2F/Blended and Online. New model in
`scheduling/`:

- `requested_by` (FK User, Faculty)
- `schedule` (FK Schedule)
- `scope`: `single_session` | `recurring`
- `session` (FK Session, nullable — set only when `scope=single_session`)
- `effective_date` — the date the change applies from (single date, or
  start date for recurring)
- `to_modality`
- `status`: `pending_dean` | `approved` | `dean_rejected`
- `dean` (FK User, nullable — who acted)
- `decided_at`, `decision_reason` (used on rejection; not disputable,
  matching the existing no-dispute pattern used for CHK-05/FAC-11)
- `assigned_room` (FK Room, nullable — populated only for an Online→F2F/
  Blended approval)

Faculty may cancel/withdraw a request while it's still `pending_dean`.

## 2. Lead time

New policy value `modality_shift_lead_days` (`SystemSetting`/
`get_policy()`, same pattern as `grace_minutes`/`room_hold_minutes`),
**default 2 days**. A request must be submitted at least this many days
before its earliest affected date to be eligible for Dean approval — this
isn't a soft warning, submission is rejected outright if it doesn't clear
the window, since a same-day approval couldn't deliver the room-release
benefit anyway.

**Accepted gap, explicitly not solved here:** a genuine same-day/emergency
modality change (e.g. an instructor is suddenly sick) has no formal
declare path. It falls back to existing scan-time behavior — for example,
scanning a room for what's now an online-only session returns the existing
`online-reject` outcome. This is a deliberate scope decision, not an
oversight: solving same-day emergency declaration is a different problem
(closer to the SRS's already-out-of-scope substitute-teacher flow) and
isn't required by this feature's goal.

## 3. Approval routing: Dean decides, IFO is informed

- **Dean** (of the instructor's department, via `User.department`) makes
  the real approve/reject decision — this is a judgment call, not a
  formality.
- **IFO is not a queue item.** On approval, a `Notification` row is
  created per active IFO Admin (reusing the exact `_notify_ifo` pattern
  already in `web/scan.py` for FAC-10's wrong-room case) — informational
  only. IFO cannot block or reverse an approved request. This is what
  actually delivers the "no longer pending on anyone" goal: the room
  releases the instant the Dean approves, full stop.
- On rejection: the request closes (`dean_rejected`), the instructor is
  notified with the Dean's reason, no further routing.

## 4. What "approved" actually does — room release mechanics

The `Session.room_released_at` field already exists on the model, unused
until now — this feature is its first writer.

- **F2F/Blended → Online, single session**: that Session's
  `declared_modality` → Online, `room_released_at` → the approval
  timestamp. The room is free immediately, not after `room_hold_minutes`
  elapses the way a no-show release works.
- **F2F/Blended → Online, recurring**: same treatment for every
  already-materialized future Session ≥ `effective_date`, plus
  `Schedule.modality` updates so anything materialized *after* approval is
  born already-Online. This requires a small patch to
  `materialize_sessions.py` (JOB-01, already built): when creating a
  Session from a Schedule whose modality is Online, stamp
  `room_released_at` at creation — otherwise a newly materialized online
  session would sit with an unset `room_released_at` and nothing would
  ever set it, since nothing "releases" a room that was never expected to
  be held.
- **Online → F2F/Blended** (either scope): the system auto-assigns a room
  — search for a free room in the same building as `schedule.room`
  (preferring `schedule.room` itself if still free at that day/time),
  checked against existing Sessions and Schedules for conflicts at
  approval time. **If no room is available, the approval fails outright**
  with a clear reason — no silent partial-apply, no manual IFO fallback
  invented to paper over it. This direction requires a minimal
  conflict-checking routine that doesn't exist anywhere in the codebase
  yet (IFO-03/IFO-05 aren't built either) — this feature has to implement
  its own, scoped narrowly to "is this room free at this day/time within
  the active term," not a general booking system.

## 5. Relationship to FAC-07

This fully replaces FAC-07 as originally sketched (immediate, no-approval
per-session modality declaration). There is no remaining self-declare path
— every modality change goes through this workflow or doesn't happen.

## 6. Checker scope reduction

- **CHK-06 is removed entirely.** Once the status sweep (JOB-02) marks a
  session Absent, no Checker action can reverse it. The room releases on
  the normal `room_hold_minutes` timer, same as before, but with zero
  Checker involvement — not "the Checker didn't get to it," but "there is
  no action for a Checker to take."
- **CHK-07's floor view never shows Absent sessions** in the coverage
  progress or priority queue — there's nothing to check.
- **CHK-03's action set drops "Confirm absent"** (it existed specifically
  to support the now-removed override) but **keeps "Confirm empty /
  Verified empty"** — that action serves a genuinely different case: a
  Checker discovers a room empty *during* its scheduled active window,
  before any Absent determination has fired at all. This is the SRS's
  ghost-booking detection (§1.2), not Absent correction, and stays in
  scope.

None of CHK-03/06/07 have any existing code — this is a specification
correction applied before the Checker slice is built, not a migration of
working behavior.

## 7. SRS revision

This changes formally specified requirements in the reviewed capstone SRS
(`FluxTrack_SRS.md`/`.docx`). Per the same process used for the v1.1 stack
revision, this needs a **v1.2 revision**:

- New requirement area (e.g. `MOD-01`..`MOD-0N`) covering the
  `ModalityShiftRequest` workflow, lead time, routing, and room-release
  mechanics.
- **FAC-07 amended** — no longer describes an immediate self-declare;
  reframed as "replaced by the modality shift approval workflow (§4.x)."
- **CHK-03 amended** — action list drops "Confirm absent."
- **CHK-06 removed**, replaced with a statement that Absent determinations
  are final and room release follows policy automatically.
- **§8 Policy Assumptions Register** gains `modality_shift_lead_days`
  (default 2 days) alongside the existing grace/hold/threshold values.
- Revision History table gains a v1.2 row.

This is implementation work (editing a real deliverable document, in both
`.md` and `.docx`, preserving `.docx` formatting as done for v1.1), so it's
a task in the implementation plan, not something performed during this
design step.

## Out of scope for this design

- Same-day/emergency modality declaration (Section 2's accepted gap).
- A general ad-hoc room booking/conflict system — only the narrow
  same-day-time-slot conflict check needed for Online→F2F/Blended
  auto-assignment is in scope.
- Actually building CHK-03/06/07 — this only specifies their corrected
  contract for whenever the Checker slice starts.
- IFO-side UI for the notification (depends on NOTIF-01, not built).

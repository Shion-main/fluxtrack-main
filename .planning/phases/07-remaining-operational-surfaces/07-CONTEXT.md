# Phase 07: Remaining Operational Surfaces - Context

**Gathered:** 2026-07-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete the remaining role surfaces so the app is feature-complete before the Phase 8 auth cutover:

- **Guard** (GRD-01..05): live polled room-status monitor + per-room schedule for assigned floor(s), a faculty locator, debounced push alerts, and NO write access anywhere.
- **IFO** (IFO-01b, IFO-02, IFO-03b, IFO-05, IFO-08): non-admin room CRUD, QR-token + six-digit-code rotation, schedule import by upload with validation/conflict reporting, conflict-checked ad-hoc bookings, and manual room release resolving conflict flags.
- **Faculty** (FAC-08, FAC-11, FAC-12): start an Online session via "Verify & Start" with a Teams link, view own attendance history including Checker flags (read-only), and manage profile photo + notification preferences.
- **System Admin** (SYS-04): monitor scheduled-job status (last run, success/failure, rows affected).

This phase SURFACES machinery that already exists (JobRun, release_room, Booking, availability, CheckerAssignment, push outbox) far more than it builds new domain logic. The scan resolver and the shared no-show predicate are OUT of scope — left untouched.
</domain>

<already_shipped>
## Already Shipped Before Planning (audited 2026-07-18)

Part of Phase 07 landed out-of-band during the UI-elevation work (see the
ui-elevation-plan step 6). Verified against code, not against docs:

- **SYS-04 — DONE.** `web/sys.py` `jobs` (`sysadmin_required`) + `templates/sys/jobs.html`;
  latest `JobRun` per `job_name` + paginated history. 3 tests green.
- **GRD-01 — DONE.** `web/guard.py` `monitor`/`monitor_rows` + navy templates;
  floor scoping server-derived from FLOOR-scoped GUARD assignments (D-04 honored).
- **GRD-03 locator — DONE**, but it is labeled **GRD-02** in `web/guard.py` and
  `web/urls.py`. Fix the labels; do not build it twice.
- **FAC-12 notification prefs — DONE** via `web/notifications.py` `settings_page`/
  `mute_toggle` (all-roles, not faculty-specific). Only the photo half remains.

**Still open:** GRD-02 (real per-room schedule for Guard), GRD-04, GRD-05
enforcement, IFO-01b, IFO-02, IFO-03b, IFO-05, IFO-08, FAC-08 write path,
FAC-11, FAC-12 photo upload.

**Planner note — the shape of the remaining work.** IFO-02, IFO-03b, IFO-05 and
IFO-08 each already have a complete, tested domain layer with ZERO web callers
(`campus.Room.code_rotated_at/by` never written; `import_offerings` CLI-only;
`ops.availability.room_is_free` called only by the modality service;
`ops.occupancy.release_room` called only by dean-approval + materialize). These
four are surface-and-URL work against existing services — plan them that way, not
as new domain logic. GRD-02, GRD-04, FAC-11 need new queries as well as surfaces.

**GRD-05 is currently unenforced.** `web/guard.py` is the only role module in
`web/` with zero `require_http_methods` decorators, so all three guard views
answer POST with a 200. Read-only in practice, not by contract — close it.

**UI/UX contract for every new surface here:** build it already-styled on the
existing system — navy `.ft-*` shell for Guard/Faculty, the shared
`templates/_console.html` for IFO, `.ft-form*` controls, `.ft-outcome*` result
cards, `.tbl`/`.data-grid` + `web/pagination.py` for any table, skeletons on
polled regions, WCAG-AA, no border-left accent stripes.
</already_shipped>

<decisions>
## Implementation Decisions

### FAC-08 — Online "Verify & Start" (resolves the CHK-02 ⇄ FAC-08 contradiction)
- **D-01:** Faculty self-start SURVIVES alongside Checker verification. Faculty paste the Teams link and click Start; that marks the online session started (status=ACTIVE, actual_start, an ONLINE self-start checkin_method). The Checker independently opens that SAME link to verify. Starting and verifying are two distinct acts by two people — not two competing claims about one fact. This closes the SRS/REQUIREMENTS "reconcile with FAC-08" note on CHK-02; FAC-08 is NOT retired (unlike FAC-07).
- **D-02:** A self-started online session that NO Checker ever verifies stays ACTIVE and counts as held, but `verified_by_checker` stays false so it reports as **unverified** on the Dean/IFO/HR scorecards — mirroring the 04.2 D-09 merged-sibling precedent (held-but-unverified). The JOB-02 sweep continues to skip ACTIVE sessions; self-start does not need to change the sweep. Nobody who taught is falsely marked absent; the unverified gap is visible, not hidden.
- **D-03:** Faculty supply the Teams link at start (pasted each time), and that pasted link IS `Session.teams_link` — the exact field the Checker's online verify surface reads. There is no competing "official" imported link to preserve; the faculty's link is the operative one for both roles, so they can never verify against different meetings. The write is audit-logged (domain-action audit convention — Claude discretion, not a user ruling). Validate it is a plausible Teams URL.

### Guard duty scope + alerts
- **D-04:** Guards reuse the Phase 3 `CheckerAssignment` table with FLOOR scope and the existing `_active_floor_ids` on-duty rule (standing assignment = always on; dated shift = on between start/end). One duty concept, one on-duty rule. IFO's existing `/ifo/assignments/create` UI extends to assign Guards. The table name saying "Checker" is cosmetic — leave or rename, do not fork a second model.
- **D-05:** GRD-04 alert triggers are EXACTLY TWO, both already-emitted events, scoped to the Guard's active floor(s): (1) a `RoomConflictFlag` opens — `detect_room_conflicts` already calls `notify()`; add floor-scoped Guards to that fan-out; and (2) a session is swept to ABSENT past grace (ghost booking → room now free). Explicitly NOT every check-in (spam), and NOT unscheduled-room-occupied (no detection exists for it — would be new work not in scope).
- **D-06:** "Debounced" = coalesce per sweep run: ONE push per job run per on-duty Guard, summarizing the batch (e.g. "3 rooms now free on Floor 3"). Both triggers fire from the same 5-minute sweep job (`sweep_no_shows` + `detect_room_conflicts` run together), so the debounce window falls out of the job cadence — NO new policy knob, NO per-room last-alerted state to persist.
- **D-07:** GRD-03 locator shows: current room/building/floor + course + end time, OR "Online — not on campus" / "Not in a class" + next class, PLUS the faculty member's schedule for TODAY (answers "when will they be free?"). Explicitly EXCLUDES attendance status and absence/flag history — that stays HR/Dean/IFO only (GRD-05 minimum-access).

### IFO booking + release
- **D-08:** IFO-05 "conflict-checked" = call the existing `ops.availability.room_is_free()` — the ONE canonical occupancy answer already used by the faculty room picker and Dean approval. Do NOT invent a second conflict definition. It already counts active Bookings, room-holding sessions, and approved modality-shift reservations with half-open overlap.
- **D-09:** A Booking never touches the scan resolver. Collisions are PREVENTED at booking-creation time (`room_is_free` refuses a booking that overlaps a scheduled class, absent an explicit override). A faculty member with a scheduled class always scans in normally — the scheduled class wins. Rationale: keep the most safety-critical, most-tested code path (scan resolver + shared no-show predicate) completely untouched.
- **D-10:** Booking cancellation is decided by existing code: `room_is_free` only counts `status="active"` bookings, so cancel = flip status away from "active"; the room frees itself. No new logic.
- **D-11:** IFO-08 manual release calls `ops.occupancy.release_room(session, actor=ifo_user)` (stamps `room_released_at` + `session.room_released` AuditLog). Releasing the contended session makes the conflict genuinely gone, so the NEXT sweep's `detect_room_conflicts` finds nothing and stamps `resolved_at` via the existing JOB-02c auto-resolve path. IFO does ONE thing; the flag closes because the cause is fixed. **Planner note:** `release_room` documents "INVOKED ONLY by MOD-03" and a Phase 2 grep-guard test asserts zero other callers — IFO-08 is the legitimate second caller; that invariant + its guard test must be updated (expected, not a regression).

### IFO-03b import surface
- **D-12:** The upload accepts BOTH `.xlsx` and `.csv` — `import_offerings` already dispatches by extension, and `.xlsx` is what IFO actually has (`.csv` is now only the synthetic test fixture). Flow is preview-then-commit: run `--dry-run` first, show the `reconcile()` report (four-bucket counts, typo rooms, email-less instructors), IFO reviews and clicks Commit to apply (or walks away). The file is held between the two steps.
- **D-13:** The web import is ADDITIVE ONLY — every write is `get_or_create`, no deletes; re-running the same file is idempotent. The destructive `reset_term` (clears 2000+ Schedule/Session rows, gated behind CLI `--yes`) is NOT reachable from the browser. Accepted cost: schedules from a superseded file that aren't in a re-upload stay behind (stale, not overwritten) — a full re-load is a rare, high-ceremony operator action, and the preview step catches bad files before they land. (RDS Express has no point-in-time restore configured yet — a Phase 8 concern — which reinforces keeping the destructive path off the web.)

### IFO-02 — QR/code rotation
- **D-14:** Rotation requires a confirmation step that explicitly states "this invalidates the current poster for room X," and on success lands IFO on the existing `/ifo/rooms/<code>/poster` surface so they immediately reprint and re-tape. Audit-logged (IFO-02 is audit-logged by requirement). Ties the destructive act to its remedy so a rotated room never silently has a dead poster on the door.

### FAC-11/FAC-12 — Faculty history + profile
- **D-15:** Faculty attendance history is READ-ONLY, Checker flags included and visible, with NO contest/dispute button. The same flag is already the system of record feeding Dean/HR/IFO scorecards; disputes happen out-of-band (talk to HR). A dispute state-machine + reviewer surface would be its own phase, not a Phase 7 clarification. Keeps the faculty surface a pure read like GRD/DEAN/HR.
- **D-16:** Profile photo upload does BASIC validation: file type (jpg/png), max size, real decodable image (Pillow already a dependency), and a server-side re-encode/resize to a standard dimension (consistent Checker view; strips a hostile payload). NO face detection, NO admin approval queue. Enough to keep the photo usable as identity evidence without inventing moderation.

### IFO-01b — Room CRUD
- **D-17:** Room delete REFUSES if the room is referenced by any Schedule, Session, or Booking — the UI blocks it and names what references it. Only a genuinely unused room (e.g. an import typo room with nothing on it) can be removed. Mirrors how `reset_term` treats PROTECTed schedules (report and skip, never half-delete). NOT soft-deactivate (would need an `is_active` field taught to every room query including the scan path we're leaving alone) and NOT cascade (destroys attendance history — catastrophic for an attendance-integrity app). Create/edit are straightforward.

### SYS-04 — Job monitoring
- **D-18:** Straight read of the `ops.JobRun` table (built in Phase 2 for exactly this, indexed `(job_name, -started_at)`): latest row per job_name with last run, status (running/ok/failed), started/finished, rows_affected, detail. Read-only, System-Admin-gated.

### Amendments after research (2026-07-19) — LOCKED

- **D-19 (amends D-17):** `ops.Booking.room` is `on_delete=CASCADE` while
  `Schedule.room`, `Session.room` and `CheckerValidation.room` are `PROTECT`.
  As written, D-17 was not enforceable — a room whose only references are
  bookings would delete cleanly and destroy them. **Migrate `Booking.room` to
  `on_delete=PROTECT`** and count **all** bookings (including cancelled) as
  blockers. The existing admin Booking surface is touched by this migration —
  expected.

  **CORRECTION (2026-07-19, after execution).** D-19 originally justified this
  as making the refusal "a database guarantee, not a view-level courtesy."
  **That rationale was factually wrong.** Django never encodes `on_delete` in
  DDL on any backend — it is a Python-level `Collector` concept, so deletion
  signals can fire. `sqlmigrate ops 0005` correctly emits `-- (no-op)` for the
  AlterField, and this is NOT the Phase-1 mssql-django `db_collation` defect;
  introspecting `sys.foreign_keys` shows EVERY FK to `campus_room` is
  `NO_ACTION`, including `scheduling_schedule`/`scheduling_session` which have
  always been PROTECT. The database was already refusing raw
  `DELETE FROM campus_room` before this change and still is.
  What the migration actually closed — verified empirically, created and rolled
  back against the real DB — is the **ORM path**: `room.delete()` from admin,
  shell or any Python caller previously CASCADEd and destroyed bookings, and
  now raises `ProtectedError` and deletes nothing. That is a real hole and it
  is genuinely closed. The net protective effect stands; the mechanism is the
  ORM layer, not the schema. Consequence: `room_delete_blockers` carries more
  of the guarantee than D-19 credited it with, which makes D-20's fifth
  relation more load-bearing, not less.
- **D-20 (amends D-17):** `CheckerValidation` is a **FOURTH blocker** D-17 never
  named. Unnamed, it surfaces as a `ProtectedError` 500 instead of a named
  refusal. The delete-blocker probe must cover Schedule, Session, Booking AND
  CheckerValidation, and the UI must name each one.
- **D-21 (GRD-04 alert type):** the new guard alert type is **pushable and
  mutable** — added to BOTH `PUSH_TYPES` and a `CATEGORY_TYPES` category in
  `ops/notifications.py`. A type in `PUSH_TYPES` but absent from
  `CATEGORY_TYPES` is structurally unmutable; a type in neither writes bell rows
  that never push with `pushed_at` stuck NULL (a symptom that misreads as a VAPID
  failure). Guards can mute guard alerts like any other category.

### Out of Scope — confirmed 2026-07-19

- **Room utilization / IFO-09** (SRS Room-Occupancy card, room-aware reporting
  aggregates) is unfinished **Phase 06** scope, deferred to a **06.1** insertion
  AFTER Phase 07 ships. Do not fold it into any Phase 07 plan.

### Claude's Discretion
- Audit-log wording/payloads for the new domain actions (link overwrite, QR rotation, manual release, room delete-refusal) follow the existing AuditLog convention.
- Exact template/URL layout of the new surfaces — reuse the navy app-shell and existing polled-monitor pattern (`ifo.live`/`live_rows`).
- Whether Guard duty keeps the `CheckerAssignment` name or gets a neutral rename (cosmetic).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — GRD-01..05, IFO-01b/02/03b/05/08, FAC-08/11/12, SYS-04 wording; CHK-02 note "reconcile with FAC-08" (line ~45) that D-01 closes.
- `.planning/ROADMAP.md` §"Phase 7: Remaining Operational Surfaces" — goal, depends-on (Phase 5 push, Phase 2 occupancy), 5 success criteria.
- `FluxTrack_SRS.docx` (generated — edit the `.md` source, regen via `manage.py regenerate_srs_docx`; never hand-edit the `.docx`) — CHK-02/CHK-03 online-Checker-verified wording; FAC-08 needs the same "starting ≠ verifying" clarification FAC-07 got.

### Occupancy / booking / release (IFO-05, IFO-08)
- `ops/availability.py` — `room_is_free()`, `free_rooms_in_building()`, half-open overlap semantics, HY010 materialize guard. THE conflict check.
- `ops/occupancy.py` — `release_room()`; note the "ONLY MOD-03 caller" invariant + Phase-2 grep-guard test to update for IFO-08.
- `ops/models.py` — `Booking` (status="active" semantics), `RoomConflictFlag` (filtered unique `uniq_open_conflict_per_key`, auto-resolve on clear).

### Guard duty + alerts (GRD-01..05)
- `web/ifo.py` `live`/`live_rows`/`room_detail` — the polled-monitor + per-room-schedule pattern the Guard monitor reuses.
- Phase 3 `CheckerAssignment` + `_active_floor_ids` (checker duty gating) — `.planning/phases/03-duty-assignments-checker-verification/` and the checker source; reused verbatim for Guards.
- `ops/notify.py` / `ops/notifications.py` — `notify()` single write path + NotificationCategory; add floor-Guards to the conflict/sweep fan-out.
- `ops/push.py` + `scheduling/jobs.py` (sweep job) — Phase 5 push outbox + the 5-min sweep both alert triggers fire from (D-06 coalescing).

### Faculty online start + verify (FAC-08)
- `scheduling/models.py` `Session.teams_link` (line ~110), `declared_modality`, status fields.
- `web/checker.py` `online_list`/`online_open` + Phase 3 03-05 online Verify — the Checker side that reads `teams_link` and sets ACTIVE; the faculty self-start is its counterpart.
- `web/scan.py` + `scheduling/resolver.py` — OUT of scope; do not modify (D-09).

### Import (IFO-03b)
- `scheduling/management/commands/import_offerings.py` — extension dispatch, `--dry-run`, get_or_create (additive) — wrap, don't rewrite.
- `scheduling/importing.py` — `reconcile()` four-bucket report, shared parse/classify helpers.
- `scheduling/management/commands/reset_term.py` — the destructive path deliberately KEPT off the web (D-13).

### Job monitoring + profile
- `ops/models.py` `JobRun` (SYS-04 read target, indexed `(job_name, -started_at)`).
- `accounts/models.py` `User.profile_photo` (ImageField, FAC-12), `Role.GUARD`/`SYSTEM_ADMIN`.
- `web/notifications.py` + Phase 5 `mute_toggle` — the notification-prefs half of FAC-12 may already exist; reuse, don't rebuild.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ops.JobRun` — purpose-built in Phase 2 for SYS-04; indexed for latest-per-job. SYS-04 is a read.
- `ops.occupancy.release_room()` — built + fully tested Phase 2, zero callers by design; IFO-08 is its first legitimate caller.
- `ops.availability.room_is_free()` — the single occupancy oracle; IFO-05 conflict-check for free.
- `ops.Booking` — model exists (admin-only today); IFO-05 gives it a real UI. `status="active"` drives availability.
- `RoomConflictFlag` auto-resolve on next sweep — IFO-08 rides it; no manual flag-close code needed.
- `web/ifo.py` `live`/`live_rows` — polled-monitor pattern → Guard monitor.
- Phase 3 `CheckerAssignment` + `_active_floor_ids` — Guard duty gating.
- `Session.teams_link`, `User.profile_photo` — fields already exist.
- Phase 5 push outbox + `notify()` + `mute_toggle` — alert delivery + FAC-12 prefs already built.
- `Pillow` — already a dependency (reporting) → profile-photo validation/re-encode.

### Established Patterns
- Every domain state-change writes an AuditLog (Conventions §2) — link overwrite, QR rotate, release, all audit.
- Read-only role surfaces use `@require_http_methods(['GET'])` so POST is 405 (DEAN/HR precedent) — Guard/faculty-history/SYS-04 follow it.
- MSSQL HY010: materialize querysets with `list()` before follow-up queries / inside `.iterator()` (availability + HR-export precedent).
- Server-side re-gating on every action; never trust client state (checker/scan precedent) — applies to faculty self-start.

### Integration Points
- Guard alerts hook the existing sweep-job `notify()` fan-out (add floor-scoped Guard recipients), not a new signal.
- Faculty self-start writes `Session.teams_link` + status ACTIVE — the same row the Checker online-verify reads.
- IFO manual release → `release_room` → next sweep auto-resolves the flag (no new resolve path).
- Web import wraps `import_offerings --dry-run`/apply; holds the uploaded file between preview and commit.
</code_context>

<specifics>
## Specific Ideas

- FAC-08 mental model the user stated verbatim: "the faculty will paste a link and when they click start it will be marked as its started and checkers can see that link to verify." Two acts, one link.
- Guard alerts should read like "3 rooms now free on Floor 3" — a batch summary, tap through to the monitor for detail.
- QR rotation should push IFO straight to the reprint page — the destructive act and its remedy in one flow.
</specifics>

<deferred>
## Deferred Ideas

- **Faculty flag dispute/contest workflow** — a state machine (disputed → reviewer notified → resolved) + reviewer surface. Real scope, no Phase 7 requirement; its own phase if wanted. (FAC-11 stays read-only.)
- **Profile-photo moderation/approval queue** — admin approval before a photo becomes Checker-visible. Not requested by any requirement; own phase if identity-photo abuse becomes a real concern.
- **Web-reachable term reset / replace-term import** — deliberately excluded (D-13). If stale-rows-after-reimport becomes a real pain, a double-confirmed replace-term flow (with PROTECT handling) is a future consideration — but not before Phase 8 real-SSO gating.
- **Unscheduled-room-occupied Guard alert** — would need new detection (the scan resolver refuses unscheduled check-ins, so no event exists). Out of scope; revisit if a detection source appears.

</deferred>

---

*Phase: 07-remaining-operational-surfaces*
*Context gathered: 2026-07-18*

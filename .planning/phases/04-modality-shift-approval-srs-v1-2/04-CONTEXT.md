# Phase 4: Modality Shift Approval & SRS v1.2 - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

A request → approval workflow for changing a session's modality (F2F/Blended ↔ Online),
with the room consequences applied automatically. Faculty submit a modality-shift request
(single session or a recurring, faculty-chosen date range); it routes to their department
Dean, who approves or rejects with a reason. Approval applies the consequence: a →Online
shift releases the room; a →F2F/Blended shift assigns a free room in the same building (or
fails cleanly if none is free). Phase 4 also revises the SRS to v1.2 (DOC-01).

**In scope:** the request model + lifecycle, the availability-first →F2F room picker,
Dean approval queue, faculty submit + "my requests" status list, the room release/assign
consequences, the notifications those events write, and the SRS v1.2 revision.
**Out of scope:** the notification read-surface/push (Phase 5), general IFO ad-hoc booking
& manual-release UI (Phase 7), broader faculty self-service (Phase 7).
</domain>

<decisions>
## Implementation Decisions

### Request submission & scope (MOD-01)
- **D-01:** A request covers F2F/Blended ↔ Online for a **single session OR a recurring,
  faculty-chosen date range** (e.g. "Thursday & Friday for the next 3 weeks"). Only sessions
  **inside the window** are affected; sessions outside keep the schedule's original modality
  and room, untouched — there is **no explicit "revert" event** (out-of-window sessions were
  simply never changed).
- **D-02:** The lead-time gate is measured in **whole calendar days in Asia/Manila**, cutoff =
  **start of the affected day** (default `modality_shift_lead_days` = 2 → a Wed session must be
  requested before Mon 00:00 Manila). For a windowed/recurring request the cutoff is checked
  against the **earliest affected session**. A too-late request is refused at submit.
- **D-03:** `modality_shift_lead_days` lives in the **policy register** (`get_policy()` /
  `SystemSetting`, SRS §8), default 2, overridable — never hardcoded.

### →Online approval (MOD-03)
- **D-04:** Approving a →Online shift flips the affected in-window session(s) to Online and
  calls the existing **`release_room()`** immediately (`room_released_at` stamped); the freed
  room becomes bookable by others. In-window Online sessions materialized later are **born
  released**. No timer-based release (Phase 2 decision, carried forward).

### →F2F/Blended approval — availability-first booking (MOD-04)
- **D-05:** The →F2F flow is **availability-first**. When requesting a →F2F/Blended shift, the
  faculty is shown the rooms/times **actually available** for the affected session(s). They
  either (a) pick a specific room/time, or (b) choose **"any room / anytime that day — let the
  app decide."** The concrete selection is what goes to the Dean.
- **D-06:** **Room is finalized at Dean approval, not at selection.** The faculty's pick is a
  *preference*; the room is committed when the Dean approves. If the picked room was taken
  meanwhile, or the faculty chose "let the app decide," the app auto-assigns: the session's
  **original room if still free, else the first free room** in the same building. It **fails
  only when no room is free at all**.
- **D-07:** On a no-room-free failure, the Dean's approve action is **blocked with a clear
  reason** ("no room free in {building} — can't apply") and the request **stays pending** (not
  terminal) so it can be approved later when a room frees. Nothing changes on the session — no
  silent partial apply (MOD-04).
- **D-08:** Room "free" is decided by the **same conflict-check used for bookings** (no other
  session/booking holds the room for that timeslot). Room lifecycle stays driven by explicit
  approved events.

### Dean routing & approval (MOD-02, MOD-05)
- **D-09:** **Exactly one Dean per department** (invariant, confirmed by user) → a request
  routes deterministically to the requesting faculty's **department Dean**. If the faculty has
  no department, or the Dean seat is vacant, the request is **refused at submit** with a clear
  message ("no Dean assigned — contact IFO") — a safety net that shouldn't trigger. No dispute
  path.
- **D-10:** Request states: **pending → approved / rejected (with reason) / withdrawn.** The
  faculty may **withdraw while pending** (MOD-05); a no-room →F2F approval keeps it pending (D-07).

### Notifications (MOD-05)
- **D-11:** All events fire via the existing **`notify()`** write path (Phase 2): request
  submitted → department Dean; decision (approved/rejected) → requesting faculty; →Online
  applied and →F2F room-assigned → **IFO informational** (not a gate). Phase 4 only writes the
  rows; the read surface is Phase 5.

### Surfaces built this phase
- **D-12:** Faculty — a **submit form** with the availability-first room picker + a **"my
  requests"** list (pending/approved/rejected/withdrawn). Dean — a **pending-approval queue**
  with approve/reject + reason. Nothing more (read-surface → Phase 5, self-service → Phase 7).

### FAC-07 replacement (MOD-06)
- **D-13:** This workflow **replaces the FAC-07 faculty self-declare** modality path — retire
  that entry point. Same-day changes have no formal path and fall back to existing scan-time
  behavior.

### SRS v1.2 (DOC-01)
- **D-14:** Revise `FluxTrack_SRS.md` to v1.2 (new MOD area, DEAN-04, amended FAC-07/CHK-03,
  removed CHK-06, RPT-02-notifies-Deans, `modality_shift_lead_days` in the policy register),
  then **regenerate `FluxTrack_SRS.docx` from the `.md` via pandoc** so the two never drift.
  ⚠ **pandoc is NOT currently on PATH** — the planner must install it (or define a fallback
  conversion) before DOC-01 can complete.

### Claude's Discretion
- Exact request model/schema and state names, notification message wording, and the precise
  layout of the picker/queue/status UIs — planner's discretion within the decisions above.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & scope
- `.planning/REQUIREMENTS.md` — MOD-01…MOD-06, DOC-01 (authoritative requirement text)
- `.planning/ROADMAP.md` — Phase 4 goal, success criteria, dependencies
- `.planning/phases/02-correctness-foundations/02-CONTEXT.md` — `release_room()` / `notify()`
  decisions and the timer-based-auto-release **cut** (room lifecycle = explicit events only)

### SRS (DOC-01 targets)
- `FluxTrack_SRS.md` — the SRS being revised to v1.2; §8 policy register
- `FluxTrack_SRS.docx` — binary counterpart, regenerated from the `.md`
- `SRS_frontend_revisions.md` — frontend revision notes to reconcile

### Code the phase builds on
- `ops/occupancy.py` — `release_room()` (MOD-03)
- `ops/policy.py` — `get_policy()` / `SystemSetting` (add `modality_shift_lead_days`)
- `scheduling/jobs.py` — `detect_room_conflicts` (post-hoc conflict analog; NOT a pre-booking
  availability query — see code_context)
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`ops/occupancy.py: release_room(session, *, actor, now)`** — stamps `room_released_at`;
  call directly for →Online (MOD-03). Ready to use.
- **`ops/policy.py: get_policy()` + `SystemSetting`** — add `modality_shift_lead_days` (default 2).
- **`notify()` (ops)** — the single notification write path for all Phase 4 events (MOD-05).
- **`accounts.models`: `Department`, `Role.DEAN`, `User.department`** — deterministic Dean
  routing (one Dean per department, D-09).
- **`scheduling.models`: `Modality` (F2F/Blended/Online), `Session.modality`, `Session.room`
  (nullable), `declared_modality` / `modality_changed_at` / `modality_changed_by`** — the
  last three are FAC-07 legacy self-declare fields; MOD-06 retires that entry point.
- **Phase 3 round-robin online-checker assignment** (scheduling) — nearby analog for the
  →F2F room auto-assign fallback.

### Established Patterns
- Room lifecycle is driven by **explicit approved events, never a timer** (Phase 2, locked).
- Policy values via `get_policy()` — never hardcoded (Conventions §3).
- `notify()` is the single notification write path (Phase 2 NOTIF-00).

### Integration Points / Gaps
- **No pre-booking room-availability query exists yet.** `detect_room_conflicts` is post-hoc
  detection, not "is room R free for this timeslot?". Phase 4 needs a **room-availability
  query** (reusing schedule/session data) to power both the availability-first picker (D-05)
  and the approval-time assignment/fallback (D-06). Researcher/planner to design.
- **Materialization must honor windowed shifts:** in-window future sessions born with the
  target modality (Online → released; F2F → assigned); out-of-window sessions unaffected (D-01).
- **pandoc not installed** — DOC-01 blocker (D-14).
</code_context>

<specifics>
## Specific Ideas

- The user's core →F2F vision: **"the faculty knows what to book, the app knows the schedule."**
  Show real availability, let them pick a specific room/time *or* delegate to the app, and have
  the app resolve conflicts by choosing for them — only failing when genuinely nothing is free.
- Recurrence example given by the user: **"Thursday & Friday in 3 weeks."**
</specifics>

<deferred>
## Deferred Ideas

- **General IFO ad-hoc room booking UI + manual release** → Phase 7 (IFO-02/03b). Phase 4
  reuses the conflict-check but does not build the IFO booking surface.
- **Notification read surface (in-app list, VAPID push)** → Phase 5.
- **Broader faculty self-service (attendance history, profile/photo)** → Phase 7.
- **Entra live D-09 proof (03.1-05)** — deferred earlier and tracked in
  `.planning/phases/03.1-authentication-entra-id-sso-local-dev-proof/03.1-UAT.md`. Unrelated
  to Phase 4; noted here only so it isn't lost.

None of the above are Phase 4 scope — discussion stayed within the modality-shift domain.
</deferred>

---

*Phase: 4-modality-shift-approval-srs-v1-2*
*Context gathered: 2026-07-03*

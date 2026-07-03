# Phase 4: Modality Shift Approval & SRS v1.2 - Research

**Researched:** 2026-07-03
**Domain:** Django request→approval workflow, room-availability querying, scheduled-session materialization, Markdown→DOCX doc generation
**Confidence:** HIGH (all findings grounded in files read this session; only DOC-01 toolchain and one materialization edge carry MEDIUM)

## Summary

Phase 4 is almost entirely an **in-repo composition** task, not a "pick a library" task. Every consequence primitive already exists and is tested: `release_room()` for →Online, `notify()` for all events, `get_policy()`/`SystemSetting` for the lead-time knob, `Role.DEAN` + `User.department` for routing, and the `declared_modality or schedule.modality` **effective-modality pattern** that six call sites already read. The single genuinely-missing primitive is a **pre-booking room-availability query** ("is room R free for timeslot [start,end)?"), which does not exist in any form — `detect_room_conflicts` is post-hoc, and the `Booking` conflict-check that D-08 references has **not been built yet** (it is Phase 7 / IFO-05). Phase 4 must create that primitive as the canonical one both this phase and Phase 7 reuse.

The cleanest architecture reuses the retired FAC-07 field: an approved shift sets `Session.declared_modality` to the target modality (plus stamps `modality_changed_at`/`_by`), which makes the entire existing effective-modality machinery (resolver, sweep, online round-robin, checker board) apply the shift with **zero changes to those readers**. →Online additionally calls `release_room()`; →F2F additionally writes `session.room`. The one non-trivial integration is that **`materialize_sessions` (JOB-01) must consult approved requests** so in-window FUTURE sessions are "born" with the target modality/room/release per D-04/MOD-03.

DOC-01 is a self-contained doc task blocked only by pandoc not being on PATH. `pypandoc_binary` (bundles the pandoc engine, no system install, no PATH dependency) is the recommended reproducible route for both dev and prod; `python-docx` 1.2.0 is already installed but is a poor fit for the table-heavy SRS.

**Primary recommendation:** Build one `ModalityShiftRequest` model + a new `ops/availability.py` room-free query; drive the shift consequence by setting `declared_modality` (+`release_room()` / room assign) inside a transaction that re-checks availability at write time; teach `materialize_sessions` to honor approved requests; regenerate the DOCX via `pypandoc_binary`.

## Post-Research Corrections (added 2026-07-03 during planning)

Two research-time positions were revised/resolved when planning with the user. **CONTEXT.md is authoritative**; this note keeps the research doc from contradicting it:

- **D-07 was REVISED.** This document's "no room free → block, **stays pending**" (Summary, Locked Decisions, Architecture Diagram, Requirements→Test Map) is superseded. The locked behavior is **terminal DENY** — no room that day → the request is denied (faculty resubmits later), never held. See CONTEXT.md D-07 (revised).
- **Open Questions are RESOLVED.** Q1 (multi-class recurrence) → CONTEXT.md **D-19** (one atomic ticket over multiple schedules). Q2 (no-free-room at future materialize) → **D-18** (reserve room at approval + request-aware availability → the case cannot occur in Phase 4 scope; defensive guard only). Q3 (one-Dean-per-department) → **D-09** (runtime invariant; `.first()` defensive).
- **New planning-time decisions** not in this research: **D-15** (picker resolution order), **D-16** (time-move bundled only with a →F2F shift, Dean can deny), **D-17** (faculty self-double-book guard). See CONTEXT.md.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** A request covers F2F/Blended ↔ Online for a **single session OR a recurring, faculty-chosen date range**. Only sessions **inside the window** are affected; out-of-window sessions keep their original modality/room, untouched — **no explicit "revert" event**.
- **D-02:** Lead-time gate = **whole calendar days in Asia/Manila**, cutoff = **start of the affected day** (default `modality_shift_lead_days`=2 → a Wed session must be requested before Mon 00:00 Manila). Windowed request → cutoff checked against the **earliest affected session**. Too-late is refused at submit.
- **D-03:** `modality_shift_lead_days` lives in the **policy register** (`get_policy()`/`SystemSetting`), default 2, overridable — never hardcoded.
- **D-04:** Approving a →Online shift flips affected in-window session(s) to Online and calls **`release_room()`** immediately; in-window Online sessions materialized later are **born released**. No timer-based release.
- **D-05:** →F2F flow is **availability-first** — faculty is shown rooms/times actually available and either (a) picks a specific room/time, or (b) chooses "any room / anytime that day — let the app decide." The concrete selection goes to the Dean.
- **D-06:** **Room finalized at Dean approval, not selection.** Faculty pick is a *preference*; if taken meanwhile or "let the app decide," the app auto-assigns the session's **original room if still free, else the first free room** in the same building. Fails **only when no room is free at all**.
- **D-07:** On no-room-free failure, the Dean's approve is **blocked with a clear reason** and the request **stays pending** (not terminal). Nothing changes on the session — no silent partial apply.
- **D-08:** Room "free" is decided by the **same conflict-check used for bookings** (no other session/booking holds the room for that timeslot). Room lifecycle stays driven by explicit approved events.
- **D-09:** **Exactly one Dean per department** → request routes deterministically to the faculty's **department Dean**. No department / vacant Dean seat → **refused at submit** ("no Dean assigned — contact IFO"). No dispute path.
- **D-10:** Request states: **pending → approved / rejected (with reason) / withdrawn.** Faculty may **withdraw while pending**; a no-room →F2F approval keeps it pending.
- **D-11:** All events fire via existing **`notify()`**: submitted → department Dean; decision → requesting faculty; →Online applied & →F2F assigned → **IFO informational** (not a gate). Phase 4 writes rows only; read surface is Phase 5.
- **D-12:** Faculty — a **submit form** with the availability-first picker + a **"my requests"** list. Dean — a **pending-approval queue** with approve/reject + reason. Nothing more.
- **D-13:** This workflow **replaces the FAC-07 faculty self-declare** modality path — retire that entry point. Same-day changes have no formal path and fall back to existing scan-time behavior.
- **D-14:** Revise `FluxTrack_SRS.md` to v1.2 (new MOD area, DEAN-04, amended FAC-07/CHK-03, removed CHK-06, RPT-02-notifies-Deans, `modality_shift_lead_days` in the policy register), then **regenerate `FluxTrack_SRS.docx` from the `.md`** so the two never drift. ⚠ pandoc NOT on PATH.

### Claude's Discretion
- Exact request model/schema and state names, notification message wording, and the precise layout of the picker/queue/status UIs — planner's discretion within the decisions above.

### Deferred Ideas (OUT OF SCOPE)
- General IFO ad-hoc room booking UI + manual release → Phase 7 (IFO-02/03b).
- Notification read surface (in-app list, VAPID push) → Phase 5.
- Broader faculty self-service (attendance history, profile/photo) → Phase 7.
- Entra live D-09 proof (03.1-05) — tracked in `03.1-UAT.md`; unrelated to Phase 4.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MOD-01 | Faculty submit modality-shift request (single/recurring), ≥ `modality_shift_lead_days` ahead; too-late refused | `ModalityShiftRequest` model + lead-time gate (§Request/Approval Lifecycle); `get_policy("modality_shift_lead_days")`; Manila whole-calendar-day math |
| MOD-02 | Routes to faculty's department Dean; approve/reject with reason (no dispute) | `Role.DEAN` + `User.department` deterministic routing (D-09); state machine |
| MOD-03 | →Online approval turns session(s) Online + releases room immediately; later-materialized born released | `release_room()` (ops/occupancy.py) + set `declared_modality=Online`; `materialize_sessions` hook |
| MOD-04 | →F2F approval auto-assigns free room in same building or fails cleanly (no partial apply) | New `ops/availability.py` room-free query, building-scoped; transactional approve; D-07 block-and-stay-pending |
| MOD-05 | IFO notified (informational) via `notify()`; faculty may withdraw while pending | `notify(role=IFO_ADMIN,...)`; withdraw guarded to requester+pending |
| MOD-06 | Replaces FAC-07 self-declare; same-day falls back to scan-time behavior | Retire FAC-07 entry point; repurpose `declared_modality` as approval-driven override (not self-declare) |
| DOC-01 | SRS revised to v1.2 in `.md` and `.docx` | `pypandoc_binary` conversion route (§DOC-01 Toolchain); exact SRS edit map |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Request submission + lead-time gate | Django view (web/faculty area) | Domain service (validation) | Server-side gate; never trust client date/time |
| Room-availability query | Domain service (`ops/availability.py`) | DB (Session/Booking overlap) | Reusable primitive for picker AND approval AND Phase-7 IFO-05 |
| Approval consequence (release/assign) | Domain service (transaction) | `ops/occupancy.release_room` | Explicit approved-event → state change, audited, atomic |
| Dean routing | Domain (accounts) | — | `User.department` + `Role.DEAN`, deterministic |
| "Born released/assigned" future sessions | JOB-01 `materialize_sessions` | approved-request lookup | Materializer is the only creator of future sessions |
| Notifications | `ops/notify.notify` | — | Single write path (NOTIF-00); read surface Phase 5 |
| SRS → DOCX | Build/doc task (`pypandoc_binary`) | — | Offline doc generation, no runtime tier |

## Standard Stack

This phase adds **no runtime web dependencies**. The only new package is for DOC-01 (offline doc generation).

### Core (already in the repo — reuse, do not re-add)
| Asset | Location | Purpose | Why Standard |
|-------|----------|---------|--------------|
| `release_room(session, *, actor, now)` | `ops/occupancy.py` | Stamp `room_released_at` + audit (→Online) | Built + tested Phase 2; MOD-03 is its designed sole caller [VERIFIED: ops/occupancy.py read] |
| `notify(*, type, title, body, link, role, users)` | `ops/notify.py` | Single Notification write path | NOTIF-00 invariant; role fan-out or explicit users [VERIFIED: ops/notify.py read] |
| `get_policy(key)` + `SystemSetting` | `ops/policy.py`, `ops/models.py` | Read `modality_shift_lead_days`; SystemSetting overrides settings default | Convention: policy never hardcoded [VERIFIED: ops/policy.py read] |
| `Role.DEAN`, `User.department` (FK→Department) | `accounts/models.py` | Deterministic Dean routing | seed_demo already seeds a CCIS Dean + faculty [VERIFIED: accounts/models.py, seed_demo.py] |
| `declared_modality`/`modality_changed_at`/`modality_changed_by` | `scheduling/models.py` Session | Per-session modality override — **repurpose** from FAC-07 self-declare to approval-driven (MOD-06) | 6 readers already use `declared_modality or schedule.modality` [VERIFIED: grep across scheduling/verification/web] |
| `assign_online_sessions` round-robin | `verification/services.py` | Nearest analog for the →F2F auto-assign fallback pattern (pure core + apply, materialize-before-write, notify-once) | Phase-3 pattern to mirror [VERIFIED: verification/services.py read] |

### Supporting (new code to write this phase)
| Component | Location (recommended) | Purpose |
|-----------|------------------------|---------|
| `ModalityShiftRequest` model | new app OR `scheduling/models.py` | Request lifecycle + window + preference + target modality |
| `ops/availability.py` | new module | `room_is_free()` / `free_rooms_in_building()` / `available_rooms_for(session)` |
| Modality-shift views | `web/faculty.py` (submit + my-requests), new `web/dean.py` (approval queue) | D-12 surfaces |
| `materialize_sessions` hook | `scheduling/management/commands/materialize_sessions.py` | Born-released / born-assigned for in-window future sessions |

### DOC-01 dependency (new)
| Package | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pypandoc_binary` | 1.17 | `.md`→`.docx` with bundled pandoc engine (no system install, no PATH) | The DOC-01 conversion task; dev + prod identical |

**Alternatives Considered:**
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pypandoc_binary` | System `pandoc` on PATH (`choco install pandoc` dev / apt prod) | Adds an out-of-repo install step to reproduce; the pinned wheel is more reproducible for a solo dev |
| `pypandoc_binary` | `python-docx` 1.2.0 (already installed) | python-docx has **no Markdown reader** — you'd hand-write a md→docx converter; the SRS is table-heavy (requirement/policy tables) and would lose fidelity. Not recommended. |
| new `ModalityShiftRequest` app | Put model in `scheduling/models.py` | scheduling is the natural home (Session/Schedule live there); avoids a new app + migration graph. Recommended: add to `scheduling`. |

**Installation:**
```bash
py -3.12 -m pip install pypandoc_binary==1.17
# add to requirements.txt under "Media / reports"
```

**Version verification:** `pypandoc_binary` 1.17 confirmed available via `pip index versions` (also 1.16.2, 1.15…). `python-docx` 1.2.0 already installed (`pip list`). pandoc confirmed NOT on PATH (`command -v pandoc` empty). [VERIFIED: pip index / pip list / command -v run this session]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `pypandoc_binary` | PyPI | published 2026-03-14 (1.17) | unknown (PyPI hides counts) | github.com/JessicaTegner/pypandoc | SUS (downloads-visibility only) | Approved — planner adds one `checkpoint:human-verify` before install |
| `pypandoc` | PyPI | 2026-03-14 (1.17) | unknown | github.com/JessicaTegner/pypandoc | SUS (downloads-visibility only) | Alternative to `_binary`; not needed if `_binary` chosen |
| `python-docx` | PyPI | 2025-06-16 (1.2.0) | unknown | github.com/python-openxml/python-docx | SUS (downloads-visibility only) | Already installed; not the recommended DOC-01 path |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** `pypandoc_binary` — the `SUS` verdict is a **PyPI artifact** (the legitimacy seam reports `unknown-downloads` because PyPI does not expose weekly download counts), NOT a genuine risk signal. All three packages `exists: true`, carry canonical maintained GitHub repos (`JessicaTegner/pypandoc`, `python-openxml/python-docx`), are not deprecated, and have `postinstall: null`. `pypandoc`/`pypandoc_binary` is the de-facto Python pandoc wrapper. Per protocol the planner should still gate the single new install behind one `checkpoint:human-verify` task.

## Architecture Patterns

### System Architecture Diagram

```
FACULTY                                    DEAN                        IFO
  │                                          │                          │
  │ 1. open submit form (D-12)               │                          │
  ▼                                          │                          │
[Availability-first picker]                  │                          │
  │  GET available rooms/times ──► ops/availability.available_rooms_for(session)
  │  (D-05: pick specific room OR "let app decide")                     │
  ▼                                          │                          │
[Submit request] ──► lead-time gate (D-02, get_policy, Manila days)     │
  │      │ too-late / no-Dean / no-dept ──► REFUSED at submit (D-09)    │
  │      ▼ ok                                                            │
  │  ModalityShiftRequest(status=PENDING, preferred_room?, target)      │
  │  notify(users=[dept Dean]) ─────────────► 2. approval queue (D-12)  │
  │                                             │                        │
  │                                             ▼                        │
  │                              [Approve / Reject+reason]               │
  │                                   │                                  │
  │        ┌──────────────────────────┼───────────────────────────┐     │
  │        ▼ REJECT                    ▼ APPROVE →Online            ▼ APPROVE →F2F
  │   status=REJECTED           set declared_modality=Online   ops/availability:
  │   notify(faculty)           release_room() each in-window  original room free?
  │                             session (D-04, MOD-03)          else 1st free in bldg
  │                             notify(faculty); notify(IFO)   (D-06)
  │                                   │                          │
  │                                   │              no room free (D-07)?
  │                                   │                ├─ YES ─► BLOCK approve,
  │                                   │                │         stay PENDING,
  │                                   │                │         no session change
  │                                   │                └─ NO ──► set declared_modality=F2F,
  │                                   │                          session.room=picked/free
  │                                   ▼                          notify(faculty); notify(IFO)
  │             ┌───────────────────────────────────────────────┘
  │             ▼  (both approved paths write to EXISTING in-window sessions)
  │   ── future in-window sessions not yet materialized ──►
  │      JOB-01 materialize_sessions consults approved requests:
  │        →Online: born declared_modality=Online + room_released_at set
  │        →F2F:    born declared_modality=F2F + room assigned (D-04)
  │
  │ 3. "my requests" list (pending/approved/rejected/withdrawn) — withdraw while PENDING (D-10)
  ▼
[Withdraw] ──► status=WITHDRAWN (requester-only, pending-only)
```

### Component Responsibilities
| File | Responsibility |
|------|----------------|
| `scheduling/models.py` (+migration) | `ModalityShiftRequest` model + status enum |
| `ops/availability.py` (new) | Pure-ish overlap predicate + DB query: room-free, free-rooms-in-building, available-for-session |
| `scheduling/services.py` (new) or `scheduling/modality.py` | submit (gate+route), apply-approval (transactional consequence), withdraw — the domain logic |
| `web/faculty.py` | Submit form view + "my requests" list (D-12) |
| `web/dean.py` (new) | Dean pending-approval queue + approve/reject POST (D-12) |
| `scheduling/management/commands/materialize_sessions.py` | Honor approved requests when creating future sessions |
| `config/settings.py` | Add `modality_shift_lead_days: 2` to `FLUXTRACK_POLICY` |

### Pattern 1: Repurpose `declared_modality` as the effective-modality override
**What:** An approved shift writes `session.declared_modality = target` (+ `modality_changed_at`, `modality_changed_by`). Every existing reader already computes `declared_modality or schedule.modality`.
**When to use:** Both →Online and →F2F approval, and materialization of future in-window sessions.
**Why:** Zero changes to the resolver, sweep, online round-robin, and checker board — they all pick up the new modality automatically. Session has **no own `modality` column**; this field IS the per-session override.
```python
# Source: scheduling/resolver.py:97, verification/services.py:47, web/checker.py:125/247/586/672 (read this session)
effective = session.declared_modality or session.schedule.modality
```

### Pattern 2: Room-availability query (the central missing primitive)
**What:** A reusable "is room R free for [start,end)?" query. Does NOT exist — build it. D-08's "same conflict-check used for bookings" is **aspirational**: no booking conflict-check exists yet (IFO-05 is Phase 7). Phase 4 builds the canonical one.
**Overlap semantics** (half-open intervals): R is busy in `[start,end)` iff any occupant O has `O.start < end AND start < O.end`. An occupant is:
- a `Session` with `room=R`, `status in (SCHEDULED, ACTIVE)`, `room_released_at IS NULL`, and effective modality **≠ Online** (online sessions don't hold a physical room), excluding the session being moved; OR
- a `Booking` (`ops.Booking`) with `room=R`, `status="active"`, overlapping `[start_datetime,end_datetime)`.
```python
# Source: derived from web/scan.py:144 (ACTIVE-holds-room), scheduling/jobs.py:88-91
#         (room_released_at IS NULL semantics), verification/services.py:47 (effective modality)
def room_is_free(room, start, end, *, exclude_session_id=None) -> bool: ...
def free_rooms_in_building(building, start, end) -> list[Room]:  # ordered, deterministic
def available_rooms_for(session) -> list[Room]:  # powers the D-05 picker
```
**Building scope (D-06):** `building = session.schedule.room.floor.building`; candidate rooms = `Room.objects.filter(floor__building=building)`; return first free (original `schedule.room` preferred).

### Pattern 3: Transactional approve with TOCTOU re-check
**What:** Availability is checked at picker time AND re-checked inside the approval transaction (rooms can be taken between selection and approval — this is exactly the D-06 case). Mirror the 03-02 checker re-gate ("never trust the earlier snapshot; re-run against current state before any write").
```python
# Source: STATE.md 03-02 re-gate decision; web/scan.py two-step confirm pattern
with transaction.atomic():
    # re-resolve the room against CURRENT availability, THEN write
```
**MSSQL guard:** materialize candidate sets with `list()` before the write loop — pyodbc allows one active result set (HY010 "Function sequence error"). Established in `scheduling/jobs.py:56` and `verification/services.py`. [VERIFIED: jobs.py comments read]

### Pattern 4: Lead-time gate math (D-02)
```python
# whole calendar days in Asia/Manila; cutoff = start of (earliest_affected_date - lead_days)
# TIME_ZONE="Asia/Manila", USE_TZ=True -> localdate()/localtime() are Manila-aware
lead = get_policy("modality_shift_lead_days")           # default 2
cutoff_date = earliest_affected_date - timedelta(days=lead)
cutoff = timezone.make_aware(datetime.combine(cutoff_date, time.min))  # Manila midnight
too_late = timezone.now() >= cutoff                     # Wed session, lead 2 -> refuse at/after Mon 00:00
```
[VERIFIED: TIME_ZONE/USE_TZ in config/settings.py:175-177; materialize_sessions.py uses the same make_aware(combine()) idiom]

### Pattern 5: Deterministic Dean routing (D-09)
```python
# Source: accounts/models.py (Role.DEAN, User.department); seed_demo.py seeds CCIS Dean+faculty
dept = requester.department
if dept is None:
    refuse("no department — contact IFO")
dean = User.objects.filter(role=Role.DEAN, department=dept, is_active=True).first()
if dean is None:
    refuse("no Dean assigned — contact IFO")   # D-09 safety net
```
**Data-integrity note:** "exactly one Dean per department" is a **runtime invariant, NOT a DB constraint** — no `UniqueConstraint` enforces it. `.first()` is defensive; the planner may add a `checkpoint` or a management-command guard, but do not silently assume uniqueness.

### Anti-Patterns to Avoid
- **Adding a new `Session.modality` column.** Redundant — `declared_modality` is the override and all readers use it. A new column would silently diverge from the resolver/sweep.
- **Nulling `session.room` on →Online.** `Session.room` is `PROTECT` and NOT-NULL; the established pattern (03-05) keeps `session.room` set and stamps `room_released_at`. Do the same. Online CheckerValidation reuses `session.room`.
- **Checking availability only at picker time.** TOCTOU — re-check inside the approval transaction (D-06 explicitly anticipates the picked room being taken meanwhile).
- **Calling `release_room()` from anywhere but the approval path.** The Phase-2 grep guard proves MOD-03 is its sole caller; keep it that way.
- **Applying a →F2F shift partially (some sessions assigned, one fails).** D-07/MOD-04: all-or-nothing per approval; block and stay pending, no silent partial apply.
- **Hardcoding lead days or building the DOCX with a hand-rolled md parser.**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Notify Dean/faculty/IFO | New Notification writer | `ops.notify.notify` | NOTIF-00 single write path; guarded by SingleWritePathTests |
| Release a room | Inline `room_released_at=now` | `ops.occupancy.release_room` | Single source of truth + audit contract |
| Read the lead-time value | `LEAD_DAYS = 2` constant | `get_policy("modality_shift_lead_days")` | SystemSetting override; Convention §3 |
| Effective modality | New modality column | `declared_modality or schedule.modality` | 6 existing readers already do this |
| Round-robin / choose-one distribution | Ad-hoc loop | Mirror `verification/services.assign_online_sessions` shape | Proven pattern (materialize-before-write, notify-once, audited) |
| Markdown→DOCX | python-docx hand converter | `pypandoc_binary` | Table fidelity; the SRS is table-heavy |

**Key insight:** Phase 4's risk is not "which library" — it's **correctly composing existing tested primitives** and adding the one missing availability query without breaking the effective-modality contract.

## Runtime State Inventory

Phase 4 is additive (new model + new views + one JOB-01 hook), not a rename/refactor. No stored-string migration is implied.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New `ModalityShiftRequest` rows + reuse of `declared_modality`/`room_released_at` on existing `Session` rows | New migration; no backfill of existing sessions |
| Live service config | `materialize_sessions` runs on the ENV-04 APScheduler (every 6h) — the JOB-01 change ships in code, no external re-registration | Redeploy scheduler process picks up new code |
| OS-registered state | None — scheduler is a `manage.py runscheduler` process, not an OS task | None |
| Secrets/env vars | None | None |
| Build artifacts | `FluxTrack_SRS.docx` is a generated artifact that will be regenerated (DOC-01); `requirements.txt` gains `pypandoc_binary` | Regenerate docx; `pip install -r requirements.txt` on deploy |

## Common Pitfalls

### Pitfall 1: The "born released/assigned" future-session gap
**What goes wrong:** A recurring request ("Thu & Fri in 3 weeks" = ~21 days) covers dates **beyond the 14-day materialization horizon**, so those sessions don't exist yet at approval time. Applying only to existing sessions silently drops the out-of-horizon ones.
**Why it happens:** `materialize_sessions` (JOB-01) creates future sessions later, unaware of approvals.
**How to avoid:** Persist the approved request with its window; in `materialize_sessions`, after `get_or_create` when `was_created`, look up an approved `ModalityShiftRequest` covering `(schedule, date)` and set `declared_modality` (+`room_released_at` for →Online, +resolved room for →F2F) on the new session. [VERIFIED: horizon default 14 in FLUXTRACK_POLICY; example window 21 days in CONTEXT specifics]
**Warning signs:** An approved 3-week request only changes the first ~2 weeks of sessions.

### Pitfall 2: →F2F born-assigned with no free room at materialize time
**What goes wrong:** At approval a room was free, but weeks later at materialize time the "first free room in same building" is occupied — and there is no Dean in the loop to block it.
**Why it happens:** D-07's block-and-stay-pending only covers the *approval* moment; materialization is unattended.
**How to avoid:** Prefer `schedule.room` (an Online schedule still has a room FK; it is usually free); if none free, materialize the session in its `schedule.room` but flag IFO via `notify()` (informational) rather than crashing the job. **Open question — confirm the desired fallback with the user** (see Assumptions Log A1).
**Warning signs:** A materialize run raises inside the shift hook, or a future F2F session appears with no usable room.

### Pitfall 3: Effective-modality readers vs a naive `session.modality`
**What goes wrong:** New code reads a non-existent `session.modality` and always sees the schedule default, ignoring the shift.
**Why it happens:** Session genuinely has no `modality` field — only `declared_modality`.
**How to avoid:** Always `declared_modality or schedule.modality`. Add a coupling test asserting the shift changes what the resolver/sweep sees. [VERIFIED: grep — no `Session.modality` field exists]

### Pitfall 4: MSSQL single-active-result-set (HY010)
**What goes wrong:** Iterating a queryset (open cursor) while `save()`-ing inside the loop raises HY010 on pyodbc/MSSQL.
**How to avoid:** `list(...)` the candidate sessions/rooms before the write loop — the established guard in `scheduling/jobs.py:56` and `verification/services.py`.
**Warning signs:** Tests pass on SQLite, fail only on MSSQL.

### Pitfall 5: Timezone drift in the lead-time gate
**What goes wrong:** Using naive `datetime.now()` or UTC dates makes the "whole calendar day" boundary off by up to 8h (Manila is UTC+8).
**How to avoid:** `timezone.localdate()` / `localtime()` (Manila-aware since `TIME_ZONE="Asia/Manila"`) and `make_aware(combine(date, time.min))` for the midnight cutoff. Test boundary cases at 23:59 and 00:00 Manila. [VERIFIED: settings.py:175-177]

### Pitfall 6: IDOR / privilege on approve & withdraw
**What goes wrong:** A faculty withdraws or a non-Dean approves someone else's request; a Dean approves outside their department.
**How to avoid:** Withdraw guarded to `request.requester == user AND status == PENDING`; approve guarded to `user.role == DEAN AND request.requester.department == user.department AND status == PENDING`. Re-check on the server for every POST (mirror the 03-02 re-gate). Write an AuditLog per decision (Convention §2).

## Code Examples

### Adding the policy default (D-03)
```python
# config/settings.py — FLUXTRACK_POLICY (Source: settings.py:202-211 read this session)
FLUXTRACK_POLICY = {
    "grace_minutes": 15,
    # ...
    "modality_shift_lead_days": 2,   # MOD-01/D-02: whole calendar days, Manila
}
# Optionally also seed a SystemSetting row so it is admin-overridable at runtime.
```

### Applying a →Online approval (D-04 / MOD-03)
```python
# Source: composed from ops/occupancy.release_room + declared_modality pattern
from ops.occupancy import release_room
from scheduling.models import Modality
with transaction.atomic():
    for s in list(affected_sessions):          # list() = MSSQL HY010 guard
        s.declared_modality = Modality.ONLINE
        s.modality_changed_at = now
        s.modality_changed_by = dean           # approving actor
        s.save(update_fields=["declared_modality", "modality_changed_at", "modality_changed_by"])
        release_room(s, actor=dean, now=now)   # stamps room_released_at + audit
    notify(users=[requester], type="modality_approved", title="Modality shift approved", ...)
    notify(role=Role.IFO_ADMIN, type="modality_online_applied", title="Session(s) moved online", ...)
```

### DOC-01 conversion (D-14)
```python
# One-off / management command. Source: pypandoc API (github.com/JessicaTegner/pypandoc)
import pypandoc
pypandoc.convert_file("FluxTrack_SRS.md", "docx", outputfile="FluxTrack_SRS.docx")
# pypandoc_binary bundles the pandoc engine; no system pandoc / no PATH entry needed.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| FAC-07 faculty self-declare modality | Dean-approved lead-time-gated shift (MOD) | This phase (D-13/MOD-06) | Retire the self-declare entry point; `declared_modality` field survives, now written by approval |
| Timer-based auto room release | Explicit approved-event release only | 2026-07-03 (Phase 2) | `release_room()` called only by MOD-03 |
| CHK-06 auto-Absent→Present override | Removed | This phase (D-14) | Absent is final; SRS edit |
| pandoc assumed on PATH | `pypandoc_binary` bundled wheel | This phase (D-14) | Reproducible md→docx without system install |

**Deprecated/outdated:**
- FAC-07 self-declare path: retire the UI entry point (field retained for the override).
- CHK-06 requirement: remove from SRS §4.4.

## DOC-01 Toolchain (detail)

**Blocker confirmed:** `command -v pandoc` returns nothing this session. `python-docx==1.2.0` is installed but has no Markdown reader.

**Recommended route (dev + prod, identical):**
1. `py -3.12 -m pip install pypandoc_binary==1.17` (add to `requirements.txt`).
2. Convert: `pypandoc.convert_file("FluxTrack_SRS.md", "docx", outputfile="FluxTrack_SRS.docx")`.
3. Wrap in a `manage.py` command or a `docs/` script so DOC-01 is one repeatable invocation and the two artifacts never drift.

**Fallback if the bundled binary is unwanted in prod:** install system pandoc (`choco install pandoc` on Windows dev, `apt-get install -y pandoc` on the EC2 Ubuntu prod) and use plain `pypandoc` (no `_binary`). The bundled wheel is preferred for solo-dev reproducibility.

**SRS v1.2 edit map (the `.md` changes before conversion):**
| Edit | Location in `FluxTrack_SRS.md` |
|------|-------------------------------|
| Add Revision History row v1.2 | §Revision History table (line ~25) |
| New MOD area (MOD-01..06) | new subsection under §4 (after §4.3 FAC or as §4.x) |
| Add DEAN-04 | §4.8 Dean (DEAN) table (line ~323) |
| Amend FAC-07 (self-declare → superseded by MOD) | §4.3 line ~268 |
| Amend CHK-03 (drop "Confirm absent"; VERIFIED_EMPTY; online applies) | §4.4 line ~281 |
| Remove CHK-06 | §4.4 line ~284 (delete the row) |
| RPT-02 notifies IFO **and Deans** | §4.9 line ~336 |
| Add `modality_shift_lead_days` (default 2) | §8 Policy Assumptions Register table (line ~461) |
[VERIFIED: all line anchors located via grep this session]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ | 3.12.10 | — |
| Django | all | ✓ | 6.0.6 (pinned) | — |
| MSSQL LocalDB | runtime data | ✓ (per Phase 1) | 2025 LocalDB | — |
| `python-docx` | (not recommended for DOC-01) | ✓ | 1.2.0 | — |
| pandoc (system) | DOC-01 | ✗ | — | `pypandoc_binary` bundled wheel (recommended) |
| `pypandoc_binary` | DOC-01 | ✗ (to install) | 1.17 avail | system pandoc + `pypandoc` |
| Network / PyPI | install step | ✓ | — | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** pandoc engine → `pypandoc_binary` (or system pandoc). This is the only DOC-01 blocker and it is resolvable in one `pip install`.

## Validation Architecture

Test framework: Django `TestCase`/`SimpleTestCase` (`manage.py test`). Existing suites: `scheduling/tests.py` (541 lines), `verification/tests.py` (868), `ops/tests.py` (298), `web/tests.py` (167). Add `scheduling/tests.py` (model/service) + `web/tests.py` (views) cases; a new `ops/tests.py` block for availability.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django test runner (unittest) |
| Config file | none — Django default; `config/settings.py` |
| Quick run command | `py -3.12 manage.py test scheduling.tests.ModalityShift -v2` |
| Full suite command | `py -3.12 manage.py test` |

### Phase Requirements → Test Map
| Req | Behavior | Test Type | Automated Command | File Exists? |
|-----|----------|-----------|-------------------|-------------|
| MOD-01 | Lead-time gate: request ≥ lead_days refuses at/after Manila-midnight cutoff (boundary 23:59 vs 00:00) | unit (pure gate fn) | `manage.py test scheduling.tests.LeadTimeGateTests` | ❌ Wave 0 |
| MOD-01 | Windowed request: cutoff checked against earliest affected session | unit | same | ❌ Wave 0 |
| MOD-01 | Single + recurring scope resolves the correct in-window session set; out-of-window untouched | integration | `manage.py test scheduling.tests.ShiftScopeTests` | ❌ Wave 0 |
| MOD-02 | Deterministic Dean routing; refuse-at-submit when no dept / vacant Dean | unit | `manage.py test scheduling.tests.DeanRoutingTests` | ❌ Wave 0 |
| MOD-03 | →Online approval sets effective modality Online + `room_released_at` stamped on each in-window session | integration | `manage.py test scheduling.tests.ApplyOnlineTests` | ❌ Wave 0 |
| MOD-03 | Future in-window session materialized later is born released (JOB-01 hook) | integration | `manage.py test scheduling.tests.BornReleasedTests` | ❌ Wave 0 |
| MOD-04 | →F2F approval assigns original-room-if-free else first-free-in-building | integration | `manage.py test scheduling.tests.ApplyF2FTests` | ❌ Wave 0 |
| MOD-04 | No free room → approval blocked, request STAYS pending, session unchanged (no partial apply) | integration | same | ❌ Wave 0 |
| MOD-04/D-08 | Availability query overlap semantics (half-open, released/absent/online excluded, Booking overlap) | unit (property-style over interval pairs) | `manage.py test ops.tests.RoomAvailabilityTests` | ❌ Wave 0 |
| MOD-04/D-06 | TOCTOU: picked room taken between select and approve → re-resolves to another free room | integration | `manage.py test scheduling.tests.ApproveRaceTests` | ❌ Wave 0 |
| MOD-05 | IFO notified informationally on apply; decision notifies faculty; submit notifies Dean | integration | `manage.py test scheduling.tests.ShiftNotifyTests` | ❌ Wave 0 |
| MOD-05 | Withdraw while pending (requester-only); non-pending/non-owner refused | unit/integration | `manage.py test scheduling.tests.WithdrawTests` | ❌ Wave 0 |
| MOD-06 | Effective modality after shift is read by resolver/sweep (coupling test) | integration | `manage.py test scheduling.tests.EffectiveModalityCouplingTests` | ❌ Wave 0 |
| MOD-02/06 | IDOR: non-Dean approve, cross-department approve, foreign withdraw all refused | integration (view) | `manage.py test web.tests.ModalityShiftAuthzTests` | ❌ Wave 0 |
| DOC-01 | `.md` contains v1.2 markers (MOD area, DEAN-04, no CHK-06, policy row); `.docx` regenerates without error | smoke | `manage.py test docs...` or a script assertion | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `py -3.12 manage.py test scheduling.tests.ModalityShift ops.tests.RoomAvailabilityTests -v2`
- **Per wave merge:** `py -3.12 manage.py test scheduling ops web`
- **Phase gate:** `py -3.12 manage.py test` fully green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `scheduling/tests.py` — LeadTimeGate, ShiftScope, DeanRouting, ApplyOnline, BornReleased, ApplyF2F, ApproveRace, ShiftNotify, Withdraw, EffectiveModalityCoupling
- [ ] `ops/tests.py` — RoomAvailabilityTests (overlap predicate, building scope, Booking + released/online exclusion)
- [ ] `web/tests.py` — ModalityShiftAuthzTests (IDOR / role gates)
- [ ] Fixtures: a Dean + faculty in one Department, a Schedule with Sessions, an Online schedule with a room, a competing Booking/Session for conflict cases (extend seed_demo pattern)
- [ ] DOC-01 smoke assertion + `pypandoc_binary` install

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json` → treated as enabled.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V4 Access Control | yes | Server-side role gates: faculty-only submit/withdraw-own; Dean-only approve within own department; re-check on every POST (03-02 re-gate pattern); AuditLog per decision |
| V5 Input Validation | yes | Validate target modality (enum), dates (`parse_date`, refuse invalid → 400 not 500, per `assignment_create` pattern), room selection (never trust client room pk — re-resolve against availability at approval) |
| V6 Cryptography | no | No new crypto |
| V2 Authentication | no (reuses) | `login_required` + role decorators (existing) |
| V3 Session Management | no (reuses) | Django sessions (existing) |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Approve/withdraw another user's request (IDOR) | Elevation/Tampering | Object-level ownership + department checks on every POST; AuditLog |
| Forge target room / session / modality in POST | Tampering | Re-resolve server-side from IDs; re-validate availability inside the approval transaction |
| Race: two approvals grab the same room (TOCTOU) | Tampering | `transaction.atomic()` + availability re-check at write; consider `select_for_update` on candidate rooms |
| Bypass lead-time gate via client clock | Tampering | Gate uses server `timezone.now()`, never client time |
| Late-materialized session escapes the shift | Repudiation/Tampering | JOB-01 hook consults approved requests (Pitfall 1) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | On →F2F future materialization with no free room, fall back to `schedule.room` + notify IFO (rather than fail the job) | Pitfall 2 | If user wants a hard stop/queue instead, the materialize hook logic changes — confirm before implementing |
| A2 | `ModalityShiftRequest` is scheduled-scoped over a date range (multi-class "Thu & Fri" = multiple requests OR multi-schedule select) | §Architecture (model) | If the user expects one request spanning multiple classes atomically, the model needs an M2M of schedules — discretion, but confirm |
| A3 | Repurpose `declared_modality` as the approval-driven per-session modality override | Pattern 1 / MOD-06 | If a distinct column is preferred, all effective-modality readers must be updated — larger blast radius |
| A4 | Availability query should also consider `ops.Booking` overlaps (forward-compat with Phase-7 IFO-05) | Pattern 2 / D-08 | If bookings are intentionally out of scope for Phase 4, drop the Booking clause (still safe to include) |
| A5 | `pypandoc_binary` (bundled) is the DOC-01 route | §DOC-01 Toolchain | If prod policy forbids bundled binaries, use system pandoc + `pypandoc` |

## Open Questions

1. **→F2F multi-class recurrence shape ("Thu & Fri for 3 weeks").**
   - What we know: a `Schedule` has a single `day_of_week`; a Thu class and a Fri class are two `Schedule` rows.
   - What's unclear: whether one request spans multiple schedules atomically or the faculty submits per-schedule requests.
   - Recommendation: model schedule-scoped + date-range as primary (A2); allow selecting multiple schedules in the form as a discretion enhancement.

2. **No-free-room at future materialize time (D-07 only covers approval).**
   - What we know: D-07 blocks the *Dean's* approve; materialization is unattended.
   - What's unclear: desired behavior when the born-assigned room is unavailable weeks later.
   - Recommendation: prefer `schedule.room`, else notify IFO informationally; confirm (A1).

3. **One-Dean-per-department is not DB-enforced.**
   - What we know: it is a stated invariant; `.first()` is defensive.
   - Recommendation: use `.first()`; optionally add a data-integrity checkpoint/management guard.

## Sources

### Primary (HIGH confidence — code read this session)
- `ops/occupancy.py`, `ops/notify.py`, `ops/policy.py`, `ops/models.py` — release_room, notify, get_policy, SystemSetting/Booking/AuditLog
- `scheduling/models.py`, `scheduling/jobs.py`, `scheduling/management/commands/materialize_sessions.py`, `assign_online.py` — Session/Schedule/Modality, effective-modality, JOB-01, MSSQL HY010 guard
- `verification/services.py` — round-robin assign pattern (→F2F analog)
- `accounts/models.py`, `accounts/management/commands/seed_demo.py` — Role.DEAN, User.department, Dean+faculty seed
- `web/scan.py`, `web/ifo.py`, `web/faculty.py`, `web/urls.py`, `ops/tests.py` — view/URL/test patterns, room-occupied semantics
- `config/settings.py` — TIME_ZONE=Asia/Manila, USE_TZ, FLUXTRACK_POLICY
- `FluxTrack_SRS.md` — §4/§8 structure and exact edit anchors

### Secondary (MEDIUM confidence)
- `pip index versions pypandoc_binary` → 1.17 available; `command -v pandoc` → absent; `pip list` → python-docx 1.2.0 (run this session)
- Package legitimacy seam (pypi) — pypandoc/pypandoc_binary/python-docx exist, canonical repos, no postinstall; SUS = downloads-visibility artifact

### Tertiary (LOW confidence)
- pypandoc API usage (`convert_file`) — from package repo knowledge [ASSUMED]; verify the exact call at implementation

## Metadata

**Confidence breakdown:**
- Standard stack (reuse map): HIGH — every asset read and signature confirmed this session
- Availability primitive design: HIGH — overlap semantics derived from actual scan/sweep/services code; note D-08's "booking conflict-check" does not yet exist
- Lifecycle & lead-time math: HIGH — TIME_ZONE and materialize idioms verified in code
- Materialization hook (born released/assigned): MEDIUM — the future-session edge (Pitfall 2 / A1) needs a user decision
- DOC-01 toolchain: MEDIUM — package availability verified; exact `pypandoc` invocation to confirm at build

**Research date:** 2026-07-03
**Valid until:** 2026-08-02 (stable in-repo domain; re-verify only if `scheduling`/`ops` models change)

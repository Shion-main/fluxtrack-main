# Phase 3: Duty Assignments & Checker Verification - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the on-duty Checker verification surface on top of the existing (scaffolded)
`Assignment` and `CheckerValidation` models. This phase delivers:

1. **IFO-06** — IFO assigns Checkers/Guards to floors (shift or standing posting);
   those assignments are what grant on-duty powers. **Extended this session:** IFO
   can also grant an **online-duty** assignment.
2. **CHK-01** — a Checker gains verification powers only while on duty on the
   scanned floor; off-duty / wrong-floor scans are refused with a clear reason.
3. **CHK-02/04/05** — scanning a room on the assigned floor returns the room's
   current session state + the scheduled faculty member's profile photo for
   identity matching; a Verify marks the session checker-verified; a flag is
   surfaced to IFO and HR.
4. **CHK-03** — the Checker records one of: Verify, Flag identity mismatch, Flag
   not present, Confirm/Verified empty. **No "Confirm absent"** (Absent is final).
5. **CHK-07** — a floor view with coverage progress, an oldest-unverified-first
   priority queue, and color-coded room cards, excluding Absent.
6. **CHK-08** — offline scans queue locally (IndexedDB) and replay on reconnect,
   each re-validated server-side before applying.
7. **Online verification (ROADMAP criterion #6)** — online sessions are verified by
   a Checker who opens the class's public MS Teams link. See the online model below.

Guard assignments (IFO-06) are created here too, but Guard *surfaces* are Phase 7.

</domain>

<decisions>
## Implementation Decisions

### Online verification model (the big one — reshaped this session)
- Online sessions are **not** scanned (no room) and are **not** on the floor board.
- **Online duty is a distinct assignment.** IFO assigns specific Checker(s) to
  online duty (a new assignment type/flag on `Assignment`, alongside the existing
  shift/standing floor assignments). Only online-duty Checkers handle online verification.
- **Each online session is pre-assigned to exactly one online-duty Checker** (by IFO
  or round-robin) — so there is NO shared-pool contention and no double-verification.
  Each online-duty Checker sees their own "Online to verify" list.
- The assigned Checker opens the session's **public MS Teams link** to confirm the
  faculty is conducting the class, then records the result with the same verification
  actions (Verify / Flag not present). A **Verify** flips the online session so the
  JOB-02 sweep no longer marks it Absent; a **Flag not present** leads to Absent.
- This is what lets **online sessions join the Phase-2 JOB-02 sweep** (Phase 2
  currently excludes online). Removing that exclusion is part of this phase.
- **Claude's discretion / research:** exact assignment mechanism (round-robin at
  materialize time vs IFO manual assign, with IFO reassign), and where the Teams
  link lives (`Session.teams_link` already exists on the model).

### On-duty gating (CHK-01)
- On-duty = an active `Assignment`. A room scan requires an active FLOOR assignment
  covering the scanned room's floor; off-duty or wrong-floor scans are refused with a
  clear, specific reason ("You are not on duty on floor X").
- Online verification requires an active **online-duty** assignment (floor-agnostic),
  and the session must be pre-assigned to that Checker.

### Floor view (CHK-07)
- **Color-coded room cards by verification state:** e.g. grey = no active session,
  amber = active-unverified, green = checker-verified, red = flagged, blue =
  confirmed/verified empty. **Absent sessions are excluded** from the board.
- **Priority queue** lists oldest unverified ACTIVE sessions first (longest-waiting
  on top) so the Checker works the most overdue rooms first.
- **Coverage progress** indicator (verified vs total active on the floor).
- The floor board is **F2F/Blended only**. Online sessions live in the separate
  "Online to verify" list (per the online model above), not on the floor board.
- Mobile-first (Checker is on the move); desktop-responsive.

### Verification actions & flags (CHK-03/04/05)
- **Verify** and **Confirm/Verified empty** are **one tap** (no friction on the
  common case).
- **Flag identity mismatch** and **Flag not present** **require a short note** before
  submit — these go to IFO **and** HR permanently with no dispute/appeal, so a reason
  is mandatory for accountability.
- Flags fire **`notify()`** (Phase 2 write path) to IFO + HR **immediately**, no
  second confirmation step.
- **Retire the dead `CONFIRMED_ABSENT` action** from `ValidationAction` — "Confirm
  absent" was removed with CHK-06; Absent is final via the sweep. (Migration to
  remove/deprecate the choice; ensure no code path emits it.)
- A Verify sets the session checker-verified (the existing `Session.verified_by_checker`
  property already keys off `validations.filter(action="verified")`).

### Offline queue (CHK-08)
- Offline scans queue in **IndexedDB** (vanilla JS, per project constraint); a visible
  **"offline / N queued"** banner shows state.
- On reconnect, each queued scan **replays and is re-validated server-side** against
  current state — **never blindly trusted**.
- **Apply if still valid; if stale/contradictory** (session already ended, already
  Absent, handed over), **do not apply — record it and raise an IFO flag via
  `notify()`** so a human resolves it. The Checker sees which items applied vs flagged.

### Claude's Discretion
- Exact card colors/iconography and queue visual design (defer to `/gsd:ui-phase 3`).
- IFO assignment UI layout (how IFO picks Checker + floors + shift window).
- Round-robin vs manual online-session→Checker assignment (research to recommend).
- Offline replay conflict-resolution copy and IFO flag payload shape.

</decisions>

<specifics>
## Specific Ideas

- Online is *assigned work with one owner*, not a free-for-all — the user explicitly
  rejected a shared first-come pool in favor of pre-assignment (accountability).
- Flags are consequential (reach HR, no appeal) → a note is mandatory on flags.
- "Confirm absent" must be gone from the Checker's options — Absent is the sweep's job.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing models & code to reuse / extend (source of truth)
- `verification/models.py` — `Assignment` (user/role/floors M2M/type/date/times/term/
  status) and `CheckerValidation` (session/room/checker/action/identity_match/note/
  scanned_at/validated_at/offline_queued). EXTEND, don't recreate. Add the online-duty
  assignment concept and remove `ValidationAction.CONFIRMED_ABSENT`.
- `verification/views.py` — currently an empty stub; the Checker surface is built here.
- `scheduling/models.py` — `Session` (`room`, `status`, `declared_modality`,
  `teams_link`, `verified_by_checker` property, `room_released_at`), `Modality`,
  `SessionStatus`.
- `scheduling/jobs.py` — the JOB-02 sweep; its **online exclusion is removed** in this
  phase once online verification exists (Phase-2 hook cited in `sweep_no_shows`).
- `web/scan.py` + `scheduling/resolver.py` — the Faculty scan pattern (pure-core +
  thin-apply, two-step signed confirm, idempotency, AuditLog) to mirror for the
  Checker scan.
- `ops/notify.py` — `notify(role=..., users=...)` for flags to IFO/HR and IFO
  offline-conflict flags.
- `accounts/models.py` — `Role` (CHECKER, GUARD, IFO_ADMIN); user profile photo for
  identity matching (confirm field exists / add in FAC-12 territory — check).

### Requirements & design
- `.planning/ROADMAP.md` Phase 3 — success criteria incl. criterion #6 (online via
  Teams) and the 2026-07-03 captured note.
- `.planning/REQUIREMENTS.md` — IFO-06, CHK-01..05/07/08; amended CHK-02/CHK-03 (online).
- `FluxTrack_SRS.md` §5 (verification/duty), §6.6 (pure resolver pattern).
- `.planning/codebase/CONVENTIONS.md` — per-view role decorators; every write logs
  AuditLog; htmx partials `_name.html`; signed tokens for two-step confirms.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Assignment` model — already models floors (M2M), shift/standing, times, term. Needs
  an online-duty variant (new `AssignmentType` or a role/flag) — small extension.
- `CheckerValidation` model — already has every field the actions need
  (`action`, `identity_match`, `note`, `offline_queued`, `scanned_at`). Retire the
  `CONFIRMED_ABSENT` choice.
- `Session.verified_by_checker` property + `Session.teams_link` field already exist.
- The Faculty scan stack (`web/scan.py`, `resolver.py`) is the template for the
  Checker scan: pure decision core + thin apply layer + signed two-step confirm.
- `notify()` (Phase 2) for all IFO/HR flag routing.

### Established Patterns
- Pure-core-decides / thin-apply-mutates-and-audits split.
- Per-view role decorators for access control; server-side scoping.
- htmx partials for interactive swaps; PWA shell already present.
- Offline: IndexedDB queue + server re-validation (never trust the client).

### Integration Points
- Removing the sweep's online exclusion (`scheduling/jobs.py`) once online verify exists.
- Checker flags → `notify()` → IFO + HR notification rows (read surface is Phase 5).
- Online-duty assignment + per-session online-Checker assignment are new; Phase 4
  (modality shift → Online) will also need to assign a Checker to newly-online sessions.

</code_context>

<scope_additions>
## New Scope Introduced This Session (flag for planner + requirements)

These refine the online-verification criterion and IFO-06; they are within Phase 3's
domain but add concrete surface area the roadmap didn't spell out:

1. **Online-duty assignment type** — extends IFO-06 assignments beyond floors.
2. **Per-session online-Checker pre-assignment** — each online session owned by one
   online-duty Checker (by IFO or round-robin); prevents double-verification.
3. **Retire `ValidationAction.CONFIRMED_ABSENT`** — align the model with "Absent is
   final" (CHK-06 removal).
4. **Remove the sweep's online exclusion** (Phase-2 hook) once online verify ships.

Planner should reflect #1–#4 in tasks and requirement coverage; consider whether
REQUIREMENTS.md IFO-06 / CHK-02 wording needs a light amendment to name online duty.

</scope_additions>

<deferred>
## Deferred Ideas

- **Guard surfaces** (floor monitor, locator) — IFO-06 creates Guard assignments here,
  but Guard-facing screens are Phase 7 (GRD-01..05).
- **Modality-shift → Online Checker assignment** — when Phase 4 approves a →Online
  shift, the newly-online session needs an online-duty Checker assigned; wire that in
  Phase 4 using this phase's assignment mechanism.
- **Notification read surface / push** for the flags raised here — Phase 5 (NOTIF-01/02).

</deferred>

---

*Phase: 03-duty-assignments-checker-verification*
*Context gathered: 2026-07-03*

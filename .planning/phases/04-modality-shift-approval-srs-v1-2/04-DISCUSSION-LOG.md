# Phase 4: Modality Shift Approval & SRS v1.2 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-03
**Phase:** 4-modality-shift-approval-srs-v1-2
**Areas discussed:** →F2F room pick, Recurring shift scope, Dean routing, Lead-time cutoff, Range room behavior, Approval-failure handling, Surfaces, SRS .docx, Room finalization timing, Room-choice granularity

---

## →F2F room pick rule (MOD-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Original, else first-free | Prefer the session's original room if free, else first free in building | ✓ |
| First free in building | Grab any free room, ignore original | |
| Smallest that fits | Capacity-aware smallest free room | |

**User's choice:** Original, else first-free.
**Notes:** Later refined by the availability-first flow — this is the app's fallback when the faculty delegates or their pick is taken.

---

## Recurring shift scope (MOD-01)

| Option | Description | Selected |
|--------|-------------|----------|
| All future from that date | Schedule modality changes going forward for the term | |
| Faculty-chosen date range | Apply only within a start/end window the faculty picks | ✓ |
| Only unmaterialized ones | Leave already-created future sessions alone | |

**User's choice:** Faculty-chosen date range (e.g. "Thursday & Friday in 3 weeks").
**Notes:** In-window sessions affected; out-of-window untouched (implicit revert).

---

## Range room behavior

| Option | Description | Selected |
|--------|-------------|----------|
| In-window only, rooms freed | Released rooms are bookable by others; outside window untouched | ✓ |
| Hold original room through window | Keep original room reserved through the window | |

**User's choice:** In-window only, rooms freed.
**Notes:** Consistent with MOD-03 "release immediately."

---

## Dean routing edges (MOD-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Refuse if unroutable | Block at submit when no/vacant Dean; multiple → all, first acts | |
| Fall back to admin/IFO | Admin approves when no Dean | |
| Any Dean in department | Route to all Deans in dept | |

**User's choice:** Free text — "there is only one dean per department."
**Notes:** Invariant confirmed → deterministic routing to the department's single Dean. Adopted "refuse at submit if faculty has no department / vacant Dean seat" as a safety net (shouldn't trigger).

---

## Lead-time cutoff (MOD-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Calendar days, Manila | Whole calendar days, cutoff = start of affected day | ✓ |
| Rolling 48 hours | lead_days × 24h before session start | |

**User's choice:** Calendar days, Asia/Manila; recurring checked against earliest affected session.

---

## Approval-failure handling → Availability-first booking (MOD-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Block, keep pending | Approve blocked if no room; request stays pending | (folded) |
| Fail terminal, resubmit | Request goes terminal-failed | |
| Apply room-less + flag IFO | Flip with no room, flag IFO | |

**User's choice:** Free text — reframed the flow: faculty selects from *available* rooms/times up front (specific, or "any / anytime that day"), the concrete pick routes to the Dean, and the app auto-resolves conflicts ("let the app choose for them, since the app knows the schedule, the faculty knows what to book"). "lets chat more about this."
**Notes:** Resolved via the two follow-ups below. Net rule: fail (block, stay pending) only when *nothing* is free; otherwise auto-fallback (original → first-free).

## Room finalization timing

| Option | Description | Selected |
|--------|-------------|----------|
| Finalize at approval | Pick is a preference; room committed at Dean approval, fallback if taken | ✓ |
| Reserve on selection | Selecting holds the room through pending | |
| I meant something else | — | |

**User's choice:** Finalize at approval.

## Room-choice granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Specific OR let-app-decide | Faculty picks exact room+time, or delegates to the app within a window | ✓ |
| Must pick specific | Always an explicit room+time | |

**User's choice:** Specific OR let-app-decide.

---

## Surfaces

| Option | Description | Selected |
|--------|-------------|----------|
| Forms + queue + status | Faculty submit + "my requests"; Dean approval queue | ✓ |
| Actions only, status via notifs | Endpoints only, no status list | |

**User's choice:** Forms + queue + status.

---

## SRS .docx (DOC-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Regenerate from .md (pandoc) | Edit .md, regenerate .docx via pandoc | ✓ |
| Hand-edit both | Manually edit .md and .docx | |
| .md now, .docx later | Defer the binary | |

**User's choice:** Regenerate from .md (pandoc).
**Notes:** pandoc is not currently on PATH — flagged as a planner prerequisite.

---

## Claude's Discretion

- Exact request model/schema and state names, notification message wording, and the precise UI
  layout of the picker/queue/status views.

## Deferred Ideas

- General IFO ad-hoc room booking UI + manual release → Phase 7.
- Notification read surface / push → Phase 5.
- Broader faculty self-service → Phase 7.
- Entra live D-09 proof (03.1-05) → tracked in 03.1-UAT.md (unrelated to Phase 4).

---

## Planning-time refinements (2026-07-03, during /gsd-plan-phase)

Follow-up discussion after research surfaced two open questions. Decisions recorded in CONTEXT.md as D-07 (revised) and D-15…D-19.

| Topic | Options weighed | User's choice |
|-------|-----------------|---------------|
| No-room-that-day handling (revisits "keep pending", line 78) | (a) keep pending until a room frees · (b) **deny outright, resubmit later** · (c) roomless + IFO action | **(b) Deny outright** — reverses the earlier "stay pending". |
| Time-move / reschedule | (a) room-finding only, keep the class's scheduled time · (b) **also allow moving the class to a free time slot** | **(b) Allow** — but only bundled with a →F2F shift (never standalone), and the Dean can deny it. |
| Self-conflict on a time-move | (a) allow · (b) **block double-booking the same faculty** | **(b) Block** — never offer / server-reject a slot where the faculty already has a class. |
| Multi-class request shape ("Thu & Fri") | (a) per-schedule = multiple requests · (b) **one atomic ticket spanning both class-days** | **(b) One ticket** approved as a block. |
| Future-session room race (researcher A1/Pitfall 2) | (a) unattended re-resolve at materialize · (b) **reserve room at approval + request-aware availability** | **(b)** — closes the race; the "no room weeks later" case cannot occur in Phase 4 scope. Non-issue, no product decision needed. |

**Notes:** Time-move is an intentional scope extension (adjacent to Phase-7 booking) confirmed explicitly by the user. Model framed as a "ticket": teacher opens → Dean approves/rejects → IFO informed.

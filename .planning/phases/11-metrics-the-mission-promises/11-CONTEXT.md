# Phase 11: Metrics the Mission Promises - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning
**Source:** Inline discussion (orchestrator-captured; two decisions confirmed by the developer)

<domain>
## Phase Boundary

The numbers the product exists to produce become visible and trustworthy:
**lateness** (redeeming the PROJECT.md core-value promise that lateness is
captured at the room level), **verification coverage** (redeeming the premise
that a Checker's physical verification is the authoritative presence signal),
and **utilization depth** deep enough for a facilities office to act.

This phase is an **aggregate-layer + surface** phase. It reuses
`scheduling/reporting.py` (the honest held/absent/verified/room-hours aggregates
that shipped in earlier phases) and adds new computed columns + surfaces on top.
It does NOT change how attendance is captured, how sessions are resolved, or how
room-hours are counted — only what is summarised and shown.

Closes audit items **A3** (lateness), **A6** (verification coverage), and
**A8 partially** (utilization depth — ghost-room list + CSV; capacity-fit
deferred, see `<deferred>`). Finishes the deliberately-dropped **06.1-07** CSV
export.
</domain>

<decisions>
## Implementation Decisions

### D-01 — Minutes-late is continuous, grace-independent
Per-session minutes late = `max(0, actual_start − scheduled_start)`, computed in
the aggregate layer (`scheduling/reporting.py`), matching the audit A3 fix
verbatim. It is **NOT** gated on `grace_minutes`. Grace exists for the
absent/no-show machinery; reusing it here would hide the most common real
lateness — the faculty member who habitually starts a few minutes late but
inside grace, so never falls Absent. Only sessions with a non-null `actual_start`
(i.e. actually held) contribute; ABSENT / CANCELLED sessions have no start and
are excluded.

### D-02 — Chronic-late flag = frequency ≥30%, reported next to magnitude
A faculty member is flagged **chronically late** when they are late
(`minutes_late > 0`) in **≥ 30% of their held sessions** over the selected
range, with a floor of **≥ 5 held sessions** in range to qualify (so one late
class in a light week never trips it). Frequency alone is not the whole story,
so the chronic flag is always shown alongside **average minutes late** over held
sessions — a dean can then tell "chronic and averages 14 min" (a real problem)
from "chronic but averages 2 min" (noise). A raw count threshold ("≥3 late") was
rejected because it punishes faculty who simply teach more sections.

### D-03 — Lateness surfaced in all three places A3 names
The lateness figures (minutes-late aggregate + chronic flag) appear on: the
**faculty scorecard**, the **weekly report**, and the **HR CSV export**. The HR
export today emits raw `actual_start` with no derived lateness — this phase adds
a derived lateness column, it does not remove the timestamp.

### D-04 — Verification coverage = verified ÷ held, by building & day
A coverage aggregate answering "what % of held sessions were physically
checker-verified, and which floors/buildings had zero coverage?" Denominator is
**held** sessions (not scheduled); numerator is checker-verified. Grouped by
**building & day**. **Zero-coverage floors are listed explicitly** (a floor with
held sessions but no verification must be visible, not merely a low percentage).
Surfaced on the **IFO dashboard**. This is a historical/management view, distinct
from the live per-floor board the on-duty checker already sees.

### D-05 — Ghost-room list = booked-but-never-used
An actionable list of physical rooms with `booked_hours > 0` AND
`used_hours = 0` over the range — bookings that produced no actual occupancy at
all. This is the "act on it" companion to the existing heat grid, derived from
the `RoomLoad` aggregate already computed per room.

### D-06 — Per-room utilization CSV export
Finish 06.1-07: a per-room CSV export of the utilization breakdown
(`room_breakdown` / `RoomLoad` rows). This was planned and deliberately dropped
in Phase 06.1; Phase 11 ships it.

### Claude's Discretion
- Exact placement/labels of the new scorecard and dashboard columns/cards, as
  long as they honour the existing IFO/faculty shell and token system.
- Whether to carry a per-session `past_grace` boolean for context on drill-down
  views. Allowed as a display nicety, but it is NOT the definition of "late"
  (D-01 governs) and must never gate the minutes-late number.
- CSV column set/order, filename, and streaming vs in-memory, as long as it
  matches the on-screen breakdown and scopes to the same range/term.
- Whether chronic-late lives as a computed property on the scorecard dataclass
  or a helper — implementation detail, as long as D-02's definition holds.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The mission promises being redeemed
- `docs/AUDIT-2026-07-19.md` §A3 (lines ~472-481) — lateness fix, incl. the
  `max(0, actual_start − scheduled_start)` formula and the three surfaces.
- `docs/AUDIT-2026-07-19.md` §A6 (lines ~498-507) — verification-coverage metric.
- `docs/AUDIT-2026-07-19.md` §A8 (lines ~515-522) — utilization depth; note
  capacity-fit is called out here but is DEFERRED this phase (see `<deferred>`).
- `PROJECT.md` core value — "lateness captured at the room level" is the promise
  D-01/D-02/D-03 redeem.

### The aggregate layer this phase extends
- `scheduling/reporting.py` — the aggregate module. Key anchors: `faculty_scorecard`
  (~464), `Scorecard`/`FacultyRow` dataclasses (~60-97), `RoomLoad` (~942, carries
  the T3/enrolled_count deferral note at ~947), `room_breakdown` (~1005),
  `building_floor_rollup` (~1089), `safe_card` (~1154).
- `scheduling/models.py` — `Session.actual_start` / `scheduled_start` (lateness
  basis), `SessionStatus` (held vs ABSENT vs CANCELLED), `Schedule.enrolled_count`.
- `web/hr.py` (~51, ~237) — HR CSV export; add the derived lateness column here.
- Weekly report surface + IFO dashboard/utilization views (`web/ifo.py`) — where
  coverage and ghost-room list render.

### Load-bearing prior facts (do not re-derive)
- Utilization "used" comes from ACTUAL timestamps, clamped to the scheduled
  window; ABSENT contributes booked hours and zero used hours; in-flight ACTIVE
  sessions are excluded from both numerator and denominator. (See the
  06.1 utilization definitions — the ghost-room list must not contradict them.)
</canonical_refs>

<specifics>
## Specific Ideas

- Lateness formula is fixed by the audit: `max(0, actual_start − scheduled_start)`.
- Chronic threshold is 30% of held sessions, min 5 held sessions in range.
- Coverage denominator is HELD (consistent with every other reporting.py rate),
  never scheduled.
- Ghost-room = `booked_hours > 0 AND used_hours = 0` (stricter than "wasted
  hours > 0", which the heat grid already shows).
</specifics>

<deferred>
## Deferred Ideas

- **Capacity-vs-enrollment "fit" (A8) — DESCOPED from Phase 11 by developer
  decision.** Reopening it means reversing the documented T3 deferral at
  `scheduling/reporting.py:947`: seat utilization (`enrolled/capacity`) was
  deliberately deferred because `Schedule.enrolled_count` trustworthiness across
  the imported term is unproven, and `seed_term` does not populate it at all
  (it is 0 on the dev dataset; only the real `import_offerings` importer fills
  it). A seat figure nobody can check is worse than no figure. **Reopen only
  after `enrolled_count` is validated on a real imported term**, as its own
  small follow-up — do not fold it into this phase.
- **Week-over-week utilization trend (A8)** — also out of scope this phase;
  Phase 11's utilization work is limited to the ghost-room list + CSV. Candidate
  for the same follow-up as capacity-fit.
- The two 06.1 open questions (physical vs physical-teaching denominator; a
  utilization target band) remain deliberately open and are NOT decided here.
</deferred>

---

*Phase: 11-metrics-the-mission-promises*
*Context gathered: 2026-07-20 via inline discussion*

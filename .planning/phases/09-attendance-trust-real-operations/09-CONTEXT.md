# Phase 09 — Attendance Trust Under Real Operations — CONTEXT

**Milestone:** v1.3 "Operational Trust". **Priority:** CRITICAL (lands before any deploy).
**Source:** docs/AUDIT-2026-07-19.md addendum A1/A2/A5.

## Why this phase exists
The attendance record is the product. Three real-world operations currently poison it:
- **A1 (typhoon/suspension):** the sweep has no break/suspension awareness for
  already-materialized sessions, and there is no `CANCELLED` status. A class-suspension
  day (frequent in Davao) mass-marks the campus Absent.
- **A2 (correction):** `web/faculty.py:671` tells faculty "a Checker can correct it,"
  but no code path lets anyone reinstate an Absent session (checker gates ABSENT out:
  `web/checker.py:558-559`, floor board excludes it `:688`). The promise is false.
- **A5 (holiday entry):** `AcademicBreak` is respected by materialize but creatable
  only in Django admin, which IFO (no `is_staff` by role) cannot reach.

## Grounding (verified in code)
- `SessionStatus` (scheduling/models.py:70-74) = SCHEDULED/ACTIVE/COMPLETED/ABSENT.
  `Session.status` is `max_length=10` — "cancelled" (9) fits.
- `AcademicBreak` (scheduling/models.py:32-40): term FK + start/end date + reason.
  Consulted by materialize (`materialize_sessions.py:128-137`), NOT by the sweep.
- Sweep (`scheduling/jobs.py:77-100`) filters SCHEDULED past-grace; now uses a
  status-guarded `.update()` (M7 fix). No break/suspension guard.
- Precedent for a "flip only SCHEDULED siblings, audited, atomic" operation:
  `scheduling/merge.py` propagate helpers — reuse that shape for bulk suspension flips.

## Design decisions

**D1 — Suspension model (DECIDED: new `ClassSuspension`).** A planned semester break
(`AcademicBreak`) and an emergency day-suspension are different: the suspension is
ad-hoc, often single-day, may be building-scoped, must flip *already-materialized*
sessions, and must be reversible if called off. New model:
`ClassSuspension(date_start, date_end, building=nullable FK, reason, declared_by, created_at, lifted_at=nullable)`.
Sweep and materialize consult BOTH AcademicBreak and active ClassSuspension.

**D2 — CANCELLED provenance (DECIDED).** Add `Session.cancelled_reason` (short
CharField, blank) for display ("Cancelled — typhoon"); full actor/why in AuditLog.
CANCELLED is terminal and excluded from held/absent/booked everywhere.

**D3 — Correction authority (NEEDS OWNER DECISION — see below).** Who can reinstate a
wrongly-Absent session?

**D4 — Notify faculty on suspension (NEEDS OWNER DECISION — see below).**

**D5 — Reversibility (DECIDED, should-have).** Lifting a `ClassSuspension` reinstates
the sessions it cancelled that are still CANCELLED+unchanged, back to SCHEDULED. The
per-session correction action (D3) covers individual cases.

**D6 — Sweep/materialize precedence (DECIDED).** A date covered by AcademicBreak OR an
active ClassSuspension: materialize never creates a session there; the sweep never
marks Absent there; on suspension creation, existing SCHEDULED sessions on covered
dates flip to CANCELLED (atomic, audited, faculty-scoped batches to respect the MSSQL
2100-param cap — same discipline as sweep/merge).

## Success criteria (from ROADMAP Phase 9)
1. CANCELLED status; excluded from Absent/held/booked in all reports + utilization.
2. IFO suspend-classes action (date/range, optional building) flips existing SCHEDULED
   sessions to CANCELLED; future materialization skips them.
3. Sweep honors AcademicBreak AND suspensions — no covered-date session goes Absent.
4. IFO academic-break/holiday CRUD from the console; sweep + materialize respect it.
5. Absent-correction action (per D3), audited; faculty message becomes true.

## Open decisions for the owner
- **D3 correction authority:** IFO-only (recommended), checker-only, or both?
- **D4 faculty notification on suspension:** yes (recommended) or defer?

## Rough plan shape (to formalize in 09-*-PLAN.md after D3/D4)
1. Foundation: `CANCELLED` status + `cancelled_reason` + `ClassSuspension` model +
   migration; report/utilization exclusions + tests.
2. Sweep/materialize break+suspension guard (D6) + tests (the core A1 fix).
3. IFO suspend-classes action (create/lift) + faculty notify (D4) + tests.
4. IFO AcademicBreak/holiday CRUD (A5) + tests.
5. Absent-correction action (D3) + faculty message fix (A2) + tests.

*Context written 2026-07-20 against code at `3acff75`.*

# Phase 09 — Verification

**Status: COMPLETE (5/5 criteria). 2026-07-20.**
Suite: 965 tests, 0 failures, 2 skips. 30 new tests (16 service + 14 console).

| # | Success criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | CANCELLED status; excluded from Absent/held/booked everywhere | PASS | `SessionStatus.CANCELLED` + `reporting._session_contribution` returns (0,0,False) for CANCELLED; `CancelledUtilizationTests` (0 booked, ABSENT control still booked). Attendance %: CANCELLED is neither in `HELD_STATUSES` nor `ABSENT`, so excluded from numerator and denominator automatically. |
| 2 | IFO suspend action flips existing SCHEDULED → CANCELLED; future materialization skips | PASS | `suspend_classes()` + `/ifo/suspensions/create`; `SuspendClassesServiceTests`, `SuspensionConsoleTests.test_create_suspends_and_cancels_sessions`; materialize consults `excused_checker`. |
| 3 | Sweep honors AcademicBreak AND suspensions — no covered-date Absent | PASS | `sweep_no_shows` calls `session_is_calendar_excused`; `SweepExcusalTests` (break skip, suspension skip, building-scoped only-other-building Absent, unexcused control still Absent). **The core A1 fix.** |
| 4 | IFO break/holiday CRUD from console; sweep+materialize respect | PASS | `/ifo/breaks` create/delete; `BreakConsoleTests`; `ExcusalCheckerTests.test_academic_break_excuses_campus_wide`. |
| 5 | Absent-correction (IFO-only, D3) audited; faculty message true | PASS | `/ifo/sessions/<pk>/reinstate` (ABSENT→COMPLETED, reason required, audited); `CorrectionConsoleTests` (reinstate, reason required, non-absent refused, IFO-only 403); faculty message rewritten to point to IFO. |

## Design decisions (locked)
- **D3 corrections = IFO-only.** Reinstatement is an IFO action; checkers do not
  retroactively edit records. Faculty message points to IFO.
- **D4 notify faculty on suspension = yes** (one coalesced notify per faculty).
- Correction lands COMPLETED with the scheduled window as a *documented best-effort*
  (audit payload marks it estimated, manual, not a scan) so it reads as held without
  fabricating a scan.

## Deliberately deferred / follow-ups
- **Browser UAT** not yet run for the three new console pages (templates are
  exercised by the test client via redirect-follow, but no human/browser pass).
  Fold into the milestone's UI review or Phase 13.
- **Term-scoped suspensions on materialize horizon:** a suspension declared for a
  date beyond the 14-day materialize horizon is honored when materialize later runs
  (it consults active suspensions), and already-materialized sessions are flipped on
  declaration — both paths covered. A suspension entirely in the past is a no-op flip.
- **Lift precision:** `lift_suspension` reinstates only rows still CANCELLED with the
  suspension's exact reason, so a session independently changed after the suspension
  is never resurrected (tested).

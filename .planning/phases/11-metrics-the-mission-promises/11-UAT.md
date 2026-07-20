---
status: passed
phase: 11-metrics-the-mission-promises
source: [11-VERIFICATION.md]
started: 2026-07-20T19:15:00Z
updated: 2026-07-20T20:05:00Z
---

## Current Test

number: 4
name: All human-verification items confirmed
expected: |
  All 4 items passed — verified in a headless browser (gstack /browse) against the
  running dev app as IFO admin, over the data-rich window from=2026-06-23 to
  to=2026-07-18 (the default page window is the current week, which is empty of
  held sessions — the from/to params drive the range).
awaiting: none — complete

## Tests

### 1. IFO dashboard verification-coverage section + explicit zero-coverage floors
expected: Coverage table (verified/held by building × weekday, physical-only) renders with pill colours; zero-coverage floors listed by name or a calm empty state.
result: pass — /ifo/dashboard renders the "Verification coverage" table: Academic Building ACAD by weekday, e.g. Mon 823 held / 161 verified / 20%, Tue 1051/139/13% … Sat 864/241/28%, Sun 1/1/100% (coverage pills red at low %). "Zero-coverage floors" shows the calm empty state ("Every floor with held sessions had at least one checker verification") because this window is fully covered. Honest low coverage (13–28%) surfaced — exactly A6's purpose.

### 2. Ghost-room section + per-room CSV opens cleanly in a spreadsheet
expected: "Booked but never used" section renders; Export CSV downloads one row per physical room, columns match, no cell interpreted as a formula.
result: pass — /ifo/utilization renders "Booked but never used" as a named list (R102, R103, R104 … with booked-hours). Export CSV downloaded = 125 physical rooms (126 lines incl. header), 12 columns (Room,Name,Building,Floor,Seats,Sessions,Absent sessions,Used h,Booked h,Available h,Reclaimable h,Utilization %). Full-file scan found NO formula-injectable cell (no cell starts with = + - @). csv_safe neutralization also unit-tested.

### 3. Faculty scorecard lateness KPI card + chronic pill gating
expected: avg-minutes-late figure shows; chronic pill appears only at ≥5 held sessions; legible beside other KPI cards.
result: pass — /ifo/scorecard/106 (Zyrah Gwen Suaybaguio, 112/114 held) shows the "Avg min late" card reading 4.3 with an amber "Chronic" pill, sitting cleanly beside Sessions / Attendance % / Absences / Early ends. A faculty with 0.0 min / <5 held correctly shows no pill.

### 4. Date-range re-scoping across all three surfaces
expected: coverage grid, ghost list, and CSV export all rescope to the new range.
result: pass — the reporting range uses ?from=&to= params. Total Used h over the current-week default = 0.0 (empty window) vs 10,364.6 over 2026-06-23→07-18; coverage %, ghost list, and CSV values all track the applied window. Confirmed by comparing downloaded CSVs across two ranges.

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None — all human-verification items passed. Note for future demos: the default page
window is the current reporting week; use the From/To pickers (or ?from=&to=) to land
on a window with held sessions (the seed term's held data runs 2026-06-23 to 2026-07-18).

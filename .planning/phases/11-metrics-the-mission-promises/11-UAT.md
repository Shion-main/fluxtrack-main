---
status: testing
phase: 11-metrics-the-mission-promises
source: [11-VERIFICATION.md]
started: 2026-07-20T19:15:00Z
updated: 2026-07-20T19:15:00Z
---

## Current Test

number: 1
name: IFO dashboard verification-coverage section + explicit zero-coverage floors
expected: |
  Coverage table renders (verified/held by building x weekday) with pill colours
  (ok/warn/bad); any floor with held sessions but zero verification appears as a
  named building+floor row in the zero-coverage-floors list (not merely a low %),
  or a calm empty state when none exist.
awaiting: user response

## Tests

### 1. IFO dashboard verification-coverage section + explicit zero-coverage floors
expected: Visit /ifo/dashboard as an IFO admin. Coverage table renders with pill colours; zero-coverage floors (held>0, verified==0) show as named building+floor rows, or a calm empty state.
result: [pending]

### 2. Ghost-room section + per-room CSV opens cleanly in a spreadsheet
expected: Visit /ifo/utilization. The "Booked but never used" ghost-room section renders; clicking Export CSV downloads utilization-*.csv; opening it in Excel/Sheets/LibreOffice shows one row per physical room, columns match the on-screen table, and NO cell (esp. room code/name/building) is interpreted as a live formula.
result: [pending]

### 3. Faculty scorecard lateness KPI card + chronic pill gating
expected: Visit /ifo/scorecard/<id> for a faculty with late sessions. The avg-minutes-late figure shows; the chronic pill appears only when there are >= 5 held sessions in range; the card is legible and correctly placed beside the other KPI cards.
result: [pending]

### 4. Date-range re-scoping across all three surfaces
expected: Change the From/To window on /ifo/dashboard and /ifo/utilization and Apply. The coverage grid, ghost-room list, and CSV export all rescope consistently to the new range.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

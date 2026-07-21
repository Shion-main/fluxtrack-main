---
phase: 12-term-lifecycle
plan: 12
subsystem: reporting
tags: [ifo, term-scope, exports, weekly-reports]
requires: [12-08, 12-09]
provides:
  - "ReportScope-backed IFO dashboard, scorecard, utilization, and exports"
  - "Selected-term weekly report lists and cross-term-safe downloads"
  - "Normalized scope propagation through IFO report links and pagination"
requirements-completed: [A4, IFO-04]
status: complete
completed: 2026-07-22
---

# Phase 12 Plan 12: IFO Selected-Term Reporting Summary

**Every IFO reporting surface and export now resolves one explicit bounded term scope and preserves it across navigation.**

## Accomplishments

- Replaced legacy dashboard, scorecard, utilization, and CSV range handling with the shared `ReportScope` contract.
- Passed the selected term explicitly to every reporting aggregate and rendered friendly non-widening invalid/no-active states.
- Propagated normalized scope through dashboard drill-downs, pagers, reset/back links, scorecard and utilization exports.
- Scoped stored WeeklyReport lists and downloads by selected term; a real report ID from another term now returns 404.
- Added selected-term identity to generated CSV filenames and retained week identity on stored download links.

## Commits

- `5362722` test(12-12): add IFO report term scope contracts
- `5d41042` feat(12-12): scope IFO reports and exports by term

## Verification

- Python compilation and `git diff --check` passed.
- Source contracts confirm shared scope selection, explicit aggregate term arguments, normalized link propagation, and pk-plus-term download lookup.
- Django runtime tests remain blocked by the missing local Django environment.

## Self-Check: PASSED

All planned IFO report/controller/template seams are term-scoped and committed with regression contracts.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-22*

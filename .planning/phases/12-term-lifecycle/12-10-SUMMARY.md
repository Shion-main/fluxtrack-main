---
phase: 12-term-lifecycle
plan: 10
subsystem: reporting-and-verification
tags: [dean, term-scope, idor, coupling-guards]
requires: [12-11, 12-12]
provides:
  - "Term-and-department-scoped Dean reports, exports, and stored downloads"
  - "Phase-wide implicit-term and archived-writer coupling guards"
  - "Final local compile/source verification record"
requirements-completed: [A4, IFO-04]
status: complete
completed: 2026-07-22
---

# Phase 12 Plan 10: Dean Reporting and Final Coupling Gate Summary

**Dean reporting now composes one bounded selected term with the mandatory department boundary, and executable source guards close the remaining implicit-term and writer seams.**

## Accomplishments

- Applied shared ReportScope handling to Dean dashboard, reports, scorecards, CSV/PDF exports, latest report cards, and stored downloads.
- Preserved the independent department/IDOR predicate; stored downloads now require PK, selected term, and the Dean's department.
- Propagated normalized scope through filters, pagination, reset/back links, drill-downs, exports, and latest-report downloads.
- Added explicit production seam inventories for legacy term selection, management-report scope, lifecycle UI coupling, and archived writer enforcement.

## Commits

- `61c07a2` test(12-10): add Dean scope and phase coupling guards
- `d52cd65` feat(12-10): scope Dean reports by term and department

## Verification

- `python -m compileall -q scheduling verification ops web` passed.
- `git diff --check` passed.
- Source audit found no production `DEFAULT_TERM`, AcademicTerm boolean filter/order, or `AcademicTerm.objects.first()` fallback.
- Lifecycle source inventory confirms create/activate/close/reopen service wiring and no reset/clone UI path.
- The configured Django/MSSQL gate could not start: `py -3.12` reports no installed interpreter, while available Python raises `ModuleNotFoundError: django`.

## Required Follow-up in Hydrated Environment

Run the Phase 12 quick suites, full configured MSSQL suite, `manage.py check`, migration drift check, SQL migration inspection, and the production-shaped migration rehearsal specified by 12-VALIDATION.md.

## Self-Check: PASSED WITH RUNTIME GATE PENDING

All plan-owned code, templates, tests, and source guards are committed; the external Django/MSSQL runtime gate remains pending rather than falsely marked passed.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-22*

---
phase: 12-term-lifecycle
plan: 09
subsystem: reporting
tags: [django, term-lifecycle, hr, reporting, csv]
requires:
  - phase: 12-06
    provides: "ACTIVE-term live surface scoping"
  - phase: 12-08
    provides: "Required-term reporting aggregates and term-keyed reports"
provides:
  - "Immutable, bounded, linkable ReportScope shared by management reports"
  - "HR list and streaming CSV constrained to exactly one selected term"
  - "Normalized term/date propagation through filters, pagination, reset, and export links"
affects: [reporting, hr, ifo, phase-12-verification]
key-files:
  created:
    - templates/reports/_term_filter.html
    - web/tests_term_reporting.py
  modified:
    - web/reporting_common.py
    - web/hr.py
    - templates/hr/attendance.html
    - web/tests_hr.py
requirements-completed: [A4]
status: complete
completed: 2026-07-22
---

# Phase 12 Plan 09: Explicit HR Report Term Scope Summary

**HR report pages and CSV exports now share one bounded, URL-addressable term scope and cannot silently widen to another term.**

## Accomplishments

- Added immutable `ReportScope` selection with ACTIVE defaults, friendly invalid/no-active states, archived full-span defaults, bounded dates, normalized query parameters, and no session state.
- Applied the same scope and `schedule__term` predicate to HR HTML and streaming CSV while preserving department, faculty, search, `Exists`, and CSV-safety behavior.
- Added same-date cross-term exclusion and propagation tests for filters, reset, pagination, and export links.

## Task Commits

1. `6961f76` test(12-09): add failing report scope contract tests
2. `6379361` feat(12-09): add bounded report scope contract
3. `68cc5c2` test(12-09): add failing HR term scope tests
4. `f5b5386` feat(12-09): scope HR reports to one term

## Verification

- `python -m compileall -q web/reporting_common.py web/hr.py web/tests_term_reporting.py web/tests_hr.py` passed.
- `git diff --check 6961f76^..f5b5386` passed.
- Source inventory confirmed the shared selector, mandatory `schedule__term` predicate, shared filter partial, and normalized `scope_query` propagation.
- Django runtime tests remain environment-blocked: `py -3.12` has no installed interpreter and the available Python environment lacks Django.

## Deviations and Issues

No implementation deviation. The required Django suite must be rerun in the hydrated project environment.

## Self-Check: PASSED

All plan-owned files and four task commits are present; the checkout contains no uncommitted plan code.

---
*Phase: 12-term-lifecycle*
*Completed: 2026-07-22*

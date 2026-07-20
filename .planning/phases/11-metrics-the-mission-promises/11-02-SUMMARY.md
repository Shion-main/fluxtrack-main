---
phase: 11-metrics-the-mission-promises
plan: 02
subsystem: reporting
tags: [reporting, lateness, csv, pdf, django, decimal, scorecard, hr-export]

# Dependency graph
requires:
  - phase: 11-01
    provides: session_minutes_late helper + FacultyRow/Scorecard minutes_late_avg/late_sessions/chronic_late fields
provides:
  - report_render.HEADER 8-column contract + build_csv/build_pdf lateness cells (weekly report + Dean/IFO scorecard CSV)
  - web.hr.CSV_HEADER derived Minutes-late column (raw Actual-start retained) computed via the shared session_minutes_late helper
  - reports/scorecard.html lateness card (avg minutes late + chronic verdict gated at >=5 held)
affects: [11-03 (verification coverage surfaces reuse the same render/scorecard patterns), HR payroll consumers]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two DISTINCT CSV header contracts kept separate (report_render.HEADER weekly/scorecard vs web.hr.CSV_HEADER payroll) — each surface edited independently (Pitfall 5)"
    - "HR per-session lateness cell imports the SHARED session_minutes_late helper (seconds//60) so the payroll export cannot drift from the faculty aggregate"
    - "Chronic verdict template-gated at held>=5 (D-02 floor) AND always paired with the numeric average so colour is never the only signal"

key-files:
  created: []
  modified:
    - scheduling/report_render.py
    - scheduling/tests_report_render.py
    - web/hr.py
    - web/tests_hr.py
    - templates/reports/scorecard.html

key-decisions:
  - "The two lateness cells are numeric/short text so csv_safe is unnecessary on them (only the faculty name keeps csv_safe); chronic cell stays terse Yes/'' for landscape-A4 column budget (Pitfall 4)"
  - "HR derived cell computed as session_minutes_late(scheduled_start, actual_start)//60 inline in the streaming rows() generator with NO DB access, preserving the open-cursor HY010 contract"
  - "Scorecard chronic pill gated in the template at card.0.held >= 5 (D-02), never solely on chronic_late, so a statistically-insufficient faculty never shows a chronic verdict"

patterns-established:
  - "Pattern: surface-only plan consumes prior-wave aggregate fields additively — no schema change, no re-derivation of the lateness formula"

requirements-completed: [A3]

coverage:
  - id: D1
    description: "report_render.HEADER carries Avg min late + Chronic late (8 cols); build_csv/build_pdf emit them from every FacultyRow; empty rows still yield header-only CSV"
    requirement: A3
    verification:
      - kind: unit
        ref: "scheduling/tests_report_render.py#LatenessColumnTests (test_header_has_lateness / test_csv_row_has_lateness / test_pdf_has_lateness_header / test_empty_rows_header_only)"
        status: pass
    human_judgment: false
  - id: D2
    description: "web.hr.CSV_HEADER gains a derived Minutes-late column while retaining the raw Actual-start cell (D-03 add, don't remove); ABSENT -> 0"
    requirement: A3
    verification:
      - kind: integration
        ref: "web/tests_hr.py#HrLatenessCsvTests (test_hr_csv_keeps_actual_start_and_adds_lateness / test_hr_late_session_shows_minutes / test_hr_absent_zero_minutes)"
        status: pass
    human_judgment: false
  - id: D3
    description: "The HR per-session Minutes-late cell is computed via the shared session_minutes_late helper (imported, not re-derived) — a session late by N minutes shows N"
    requirement: A3
    verification:
      - kind: integration
        ref: "web/tests_hr.py#HrLatenessCsvTests.test_hr_late_session_shows_minutes"
        status: pass
    human_judgment: false
  - id: D4
    description: "The faculty scorecard renders avg-minutes-late alongside the chronic-late flag; the chronic verdict shows only when held >= 5 (D-02 floor)"
    requirement: A3
    verification:
      - kind: integration
        ref: "web/tests_hr.py#ScorecardLatenessSurfaceTests (test_scorecard_page_shows_lateness / test_scorecard_suppresses_chronic_below_floor)"
        status: pass
    human_judgment: false

# Metrics
duration: 12min
completed: 2026-07-20
status: complete
---

# Phase 11 Plan 02: Lateness Surfaces Summary

**Surfaced the Plan-01 lateness aggregates in all three A3/D-03 places — the weekly report render layer (`report_render.HEADER` + CSV/PDF builders), the HR payroll CSV (a derived per-session Minutes-late column beside the retained raw Actual-start, computed via the SHARED `session_minutes_late` helper), and the faculty scorecard (avg-minutes-late card with a chronic verdict gated at the >=5-held floor) — with no schema change and no re-derivation of the lateness formula.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-20T16:47Z
- **Completed:** 2026-07-20T16:59Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- **Weekly report / scorecard CSV+PDF (Task 1):** `report_render.HEADER` extended from 6 to 8 columns ("Avg min late", "Chronic late"); `build_csv` and `build_pdf` emit `r.minutes_late_avg` and a terse `"Yes"/""` chronic cell from every `FacultyRow`. `web.hr.CSV_HEADER` left untouched — the two CSV contracts are deliberately separate (Pitfall 5).
- **HR payroll CSV (Task 2):** `web.hr` imports `session_minutes_late`; `CSV_HEADER` gains a "Minutes late" column immediately after the retained raw "Actual start" (D-03: add the derived figure, do not remove the timestamp). The derived cell = `session_minutes_late(s.scheduled_start, s.actual_start) // 60`, computed inline in the streaming `rows()` generator with zero DB access, so the open server-side cursor / HY010 contract holds. ABSENT (NULL start) -> 0.
- **Scorecard card (Task 3):** a lateness KPI card renders `card.0.minutes_late_avg`; the "Chronic" amber pill shows only when `card.0.held >= 5` (D-02 floor) and `card.0.chronic_late`, always paired with the numeric average so colour is never the only signal.
- Named tests for each surface, including the HR/aggregate parity via the shared helper and the below-floor chronic suppression.

## Task Commits

Each task was committed atomically (TDD tasks carry a RED test commit then a GREEN feat commit):

1. **Task 1 (RED): failing lateness-column tests for the render layer** - `43a140f` (test)
2. **Task 1 (GREEN): lateness columns in report_render HEADER/build_csv/build_pdf** - `b2a2ed8` (feat)
3. **Task 2 (RED): failing HR payroll derived-lateness-column tests** - `c614d95` (test)
4. **Task 2 (GREEN): derived Minutes-late column in the HR payroll CSV** - `ce98e50` (feat)
5. **Task 3: avg-minutes-late + chronic flag on the faculty scorecard (card + view tests)** - `1448ca6` (feat)

**Plan metadata:** committed separately with STATE.md/ROADMAP.md updates (docs: complete plan).

## Files Created/Modified
- `scheduling/report_render.py` - `HEADER` extended to 8 columns; `build_csv`/`build_pdf` emit the two lateness cells.
- `scheduling/tests_report_render.py` - `_row` helper + `CSV_HEADER` constant carry the lateness fields; new `LatenessColumnTests` (4 named tests).
- `web/hr.py` - imports `session_minutes_late`; `CSV_HEADER` gains "Minutes late"; `attendance_csv` row generator inserts the derived cell after the raw actual_start.
- `web/tests_hr.py` - `HrLatenessCsvTests` (3 named tests) + `ScorecardLatenessSurfaceTests` (2 view tests).
- `templates/reports/scorecard.html` - lateness KPI card (avg minutes late + held>=5-gated chronic pill).

## Decisions Made
- None beyond what the plan and D-01/D-02/D-03 specify. The two-distinct-CSV-contracts split, the shared-helper HR cell, the terse chronic cell, and the >=5-held template gate were all pre-specified and honored exactly.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Each module run was green on first execution after the intended RED->GREEN cycle; no auto-fixes required.

## TDD Gate Compliance
Tasks 1 and 2 carry `tdd="true"` and followed proper RED->GREEN gates: a `test(...)` commit with confirmed-failing tests (`43a140f`: 5 failures; `c614d95`: 3 failing) precedes each `feat(...)` implementation commit (`b2a2ed8`, `ce98e50`) that turns them green. Task 3 is `type="auto"` (no TDD) — template + view tests committed together.

## Verification
- `manage.py test scheduling.tests_report_render web.tests_hr scheduling.tests_reporting` — 60 tests, all green (the `RuntimeError: raw-internal-detail-should-not-leak` in output is an intentional leak-isolation test assertion, captured, not a failure).
- Weekly report CSV/PDF and HR CSV both carry lateness (neither surface omits it — Pitfall 5); HR keeps the raw `actual_start`.
- Targeted module runs only (not the full suite), so `FluxTrack_SRS.docx` was NOT regenerated — confirmed untouched in git status.
- No re-derivation of the lateness delta anywhere: HR imports and calls `session_minutes_late`.

## User Setup Required
None - no external service configuration required. No schema change, no migration.

## Next Phase Readiness
- Plan 03 (verification coverage on the IFO dashboard) and Plan 04 (ghost-room list + per-room CSV) are unblocked; both reuse the same aggregate/render/scorecard surfacing patterns established here.
- A3 lateness is now fully surfaced across all three D-03 places; the "lateness captured at the room level" PROJECT.md promise is visible end-to-end (aggregate -> weekly report + HR payroll + scorecard).

## Self-Check: PASSED

All modified files exist on disk; all five task commits (`43a140f`, `b2a2ed8`, `c614d95`, `ce98e50`, `1448ca6`) present in git history.

---
*Phase: 11-metrics-the-mission-promises*
*Completed: 2026-07-20*

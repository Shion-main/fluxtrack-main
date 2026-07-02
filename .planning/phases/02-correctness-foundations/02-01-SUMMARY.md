---
phase: 02-correctness-foundations
plan: 01
subsystem: scheduling
tags: [predicate, resolver, no-show, grace, tdd, pure-function, coupling-integrity]

# Dependency graph
requires:
  - phase: 01-mssql-foundation
    provides: pure scan resolver (resolve_faculty_scan) with inline no-show comparison
provides:
  - "is_no_show_past_grace(scheduled_start, now, grace_min) — the single shared no-show predicate (JOB-02a)"
  - "resolve_faculty_scan ABSENT branch delegates to the shared predicate"
  - "NoShowPredicateTests (boundary math) + CouplingIntegrityTests (scan<->predicate agreement)"
affects: [02-03-sweep, status-sweep, JOB-02, no-show, absent-rule]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure predicate extraction: lift an inline business comparison into a named module-level pure function shared by multiple call paths"
    - "Coupling-integrity test: assert path-A outcome iff predicate is True across a boundary sweep, to block future drift between two paths"

key-files:
  created: []
  modified:
    - scheduling/resolver.py
    - scheduling/tests.py

key-decisions:
  - "Only the atomic no-show comparison is shared, not the whole resolver — the sweep imports is_no_show_past_grace, keeping resolver purity (SRS 6.6) intact"
  - "Boundary semantics are strictly `>`: at exactly scheduled_start + grace_min the predicate is False (mirrors the original inline `now > start + grace`)"
  - "Removed the now-dead `grace = timedelta(...)` local in resolve_faculty_scan since the predicate owns that arithmetic"

patterns-established:
  - "Pure predicate extraction with a docstring citing the requirement ID (JOB-02a)"
  - "Coupling-integrity SimpleTestCase ties one code path's decision to a shared predicate across a delta sweep"

requirements-completed: [JOB-02a]

coverage:
  - id: D1
    description: "is_no_show_past_grace pure predicate exists in scheduling/resolver.py with strictly-past-grace boundary semantics (14 False, 15 False, 16 True)"
    requirement: "JOB-02a"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#NoShowPredicateTests"
        status: pass
    human_judgment: false
  - id: D2
    description: "resolve_faculty_scan ABSENT decision is True if-and-only-if is_no_show_past_grace is True for identical inputs (scan/sweep never disagree — Phase-2 criterion #1)"
    requirement: "JOB-02a"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#CouplingIntegrityTests.test_resolver_absent_iff_predicate_true"
        status: pass
    human_judgment: false
  - id: D3
    description: "All 16 existing FacultyResolverTests still pass — no behaviour drift in resolve_faculty_scan; resolver stays pure"
    verification:
      - kind: unit
        ref: "scheduling/tests.py#FacultyResolverTests"
        status: pass
    human_judgment: false

# Metrics
duration: 2min
completed: 2026-07-02
status: complete
---

# Phase 02 Plan 01: Shared No-Show Predicate (JOB-02a) Summary

**Extracted the scan resolver's inline `now > scheduled_start + grace` comparison into one pure `is_no_show_past_grace(scheduled_start, now, grace_min)` predicate that `resolve_faculty_scan` now calls, locking Phase-2 criterion #1 (scan and sweep can never disagree) behind a shared atom plus a coupling-integrity test — with all 16 legacy resolver tests still green.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-07-02T21:38:04Z
- **Completed:** 2026-07-02T21:39:29Z
- **Tasks:** 2 (both TDD)
- **Files modified:** 2

## Accomplishments
- Added `is_no_show_past_grace(scheduled_start, now, grace_min)` to `scheduling/resolver.py` — a pure bool returning `now > scheduled_start + timedelta(minutes=grace_min)`, no ORM, no `timezone.now()`, no side effects (SRS 6.6). Docstring cites JOB-02a and names it the single predicate shared by scan-time and the upcoming sweep-time path.
- Wired `resolve_faculty_scan`'s ABSENT branch to call the predicate (replacing exactly one inline comparison at what was L89) and removed the now-dead `grace` local.
- Added `NoShowPredicateTests` (boundary math: 14 False, exactly-15 False, 16 True, +120 True, pre-start False) and `CouplingIntegrityTests` (resolver ABSENT iff predicate across deltas -1/0/14/15/16/30) — both pure `SimpleTestCase`, placed above the DB-backed divider.
- Confirmed byte-for-byte behaviour preservation: all 16 `FacultyResolverTests` still pass (22/22 pure tests green).

## Task Commits

Each task was committed atomically (TDD RED -> GREEN):

1. **Task 1: Add NoShowPredicateTests + CouplingIntegrityTests (RED)** - `b4ad3ac` (test)
2. **Task 2: Extract is_no_show_past_grace() and wire resolve_faculty_scan (GREEN)** - `c307806` (feat)

**Plan metadata:** (docs commit — this SUMMARY + STATE + ROADMAP)

## Files Created/Modified
- `scheduling/resolver.py` - Added the `is_no_show_past_grace` pure predicate after the `Resolution` dataclass; ABSENT branch now delegates to it; removed the dead `grace` local.
- `scheduling/tests.py` - Added `is_no_show_past_grace` import and two pure `SimpleTestCase` classes (`NoShowPredicateTests`, `CouplingIntegrityTests`) above the `# DB-backed MSSQL foundation tests` divider.

## Decisions Made
- **Share only the atom, not the resolver.** The Phase-2 sweep (Plan 02-03) will `from scheduling.resolver import is_no_show_past_grace` rather than call the whole resolver, so purity is preserved and the two paths share exactly the one rule that must never diverge.
- **Strictly `>` boundary.** At exactly `scheduled_start + grace_min` the predicate returns False, mirroring the original semantics; the boundary test pins 15 min as False and 16 min as True.
- **Removed the dead `grace` local** in `resolve_faculty_scan` — the predicate owns the `timedelta(minutes=grace_min)` arithmetic now, avoiding an unused variable.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Git reported the expected LF->CRLF conversion warnings on Windows (cosmetic, no impact).

## TDD Gate Compliance
RED gate (`test(02-01)` commit `b4ad3ac`) preceded GREEN gate (`feat(02-01)` commit `c307806`). RED was confirmed by an ImportError on `is_no_show_past_grace` before Task 2 landed. No REFACTOR gate needed — the GREEN implementation was already minimal and clean.

## Verification Notes
Ran only the pure `SimpleTestCase` classes (`FacultyResolverTests`, `NoShowPredicateTests`, `CouplingIntegrityTests`) — 22/22 green. The full `scheduling.tests` suite additionally contains MSSQL `TestCase`/`TransactionTestCase` classes that build a test database; that run was deliberately skipped to avoid colliding with Plan 02-02's parallel DB-backed Wave-1 test run. This plan's new tests build no test DB, so scan/sweep coupling is proven without touching the database.

## Next Phase Readiness
- Plan 02-03's status sweep can now `from scheduling.resolver import is_no_show_past_grace` to make its no-show decision, guaranteeing scan-time and sweep-time agreement (Phase-2 success criterion #1) at the predicate level.
- `CouplingIntegrityTests` will fail if any future change makes the resolver's ABSENT decision diverge from the shared predicate — drift protection is in place.

## Self-Check: PASSED

- FOUND: scheduling/resolver.py
- FOUND: scheduling/tests.py
- FOUND: .planning/phases/02-correctness-foundations/02-01-SUMMARY.md
- FOUND commit: b4ad3ac (test RED)
- FOUND commit: c307806 (feat GREEN)

---
*Phase: 02-correctness-foundations*
*Completed: 2026-07-02*

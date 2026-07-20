---
phase: 11-metrics-the-mission-promises
verified: 2026-07-20T19:15:00Z
status: human_needed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Visit /ifo/dashboard as an IFO admin. Confirm the verification-coverage section renders (verified/held by building x weekday) and that any floor with held sessions but no verification is listed explicitly in the zero-coverage-floors list (not merely a low percentage)."
    expected: "Coverage table renders with pill colours (ok/warn/bad) and the zero-coverage-floors list shows named building+floor rows, or the calm empty state when none exist."
    why_human: "Visual rendering and legibility of a Franken-UI table/list cannot be confirmed by grep or unit assertions — only that the template renders 200 with the expected strings."
  - test: "Visit /ifo/utilization. Confirm the 'Booked but never used' ghost-room section renders, then click Export CSV and open utilization-*.csv in a real spreadsheet."
    expected: "One row per physical room, columns match the on-screen table, and no cell (especially room code/name/building) is interpreted as a live formula by the spreadsheet application."
    why_human: "csv_safe neutralization is unit-tested (leading-quote check), but whether Excel/Sheets/LibreOffice actually renders the CSV cleanly and legibly is a real-application behavior no automated test exercises."
  - test: "Visit /ifo/scorecard/<id> for a faculty with late sessions. Confirm the avg-minutes-late figure shows and the chronic pill appears only when there are >= 5 held sessions in range."
    expected: "The lateness KPI card is visually legible, correctly placed beside the other KPI cards, and the chronic pill (colour + text) reads clearly."
    why_human: "Visual placement/legibility inside the existing Franken shell is a design judgment, not a grep-checkable fact."
  - test: "Change the From/To window on /ifo/dashboard and /ifo/utilization and Apply. Confirm the coverage grid, ghost list, and CSV export all rescope to the new range."
    expected: "All three surfaces reflect the newly applied date range consistently."
    why_human: "End-to-end range-application through the browser form is a live interaction path distinct from the unit tests that pass explicit start/end kwargs directly to the aggregate functions."
---

# Phase 11: Metrics the Mission Promises Verification Report

**Phase Goal:** The numbers the product exists to produce are visible — lateness, verification coverage, and utilization deep enough for facilities to act.
**Verified:** 2026-07-20T19:15:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A3 — `session_minutes_late` + `_lateness_map` compute grace-independent, seconds-based lateness in the aggregate layer, with the D-02 chronic definition (>=30% of held, >=5-held floor, >=1-whole-minute frequency gate) | VERIFIED | `scheduling/reporting.py:428-473, 710-733` — read in full; matches must_haves verbatim. 12 named tests in `scheduling/tests_reporting_lateness.py`, all pass. |
| 2 | A3 — Minutes-late + chronic flag populate both `FacultyRow` and `Scorecard` from the shared `_lateness_map`, with no drift between builders | VERIFIED | `scheduling/reporting.py:518-537` (`faculty_attendance`) and `:692-706` (`faculty_scorecard`) both call `_lateness_map(qs)` and compute the identical `chronic_late = held_ws >= 5 and late_ct/held_ws >= 0.30` expression. `LatenessParityTests` in `tests_reporting.py` pins agreement. |
| 3 | A3/D-03 — Lateness surfaced on all three named places: weekly report (CSV+PDF), HR payroll CSV (via the shared helper, not re-derived), and the faculty scorecard | VERIFIED | `scheduling/report_render.py` HEADER extended to 8 cols emitting `r.minutes_late_avg`/chronic; `web/hr.py:38` imports `session_minutes_late` and computes the derived cell inline (`web/hr.py:249`) — confirmed by grep, not a re-derivation; `templates/reports/scorecard.html:51-62` renders the lateness card gated at `held>=5`. |
| 4 | A6/D-04 — `coverage_by_building_day` computes verified/HELD by (building, weekday), physical-only, verified via a SEPARATE distinct-count query (no reverse-join inflation) | VERIFIED | `scheduling/reporting.py:561-611` read in full — held query and verified query are two distinct grouped querysets folded by Python dict, exactly as specified. 7 named tests in `scheduling/tests_reporting_coverage.py`, all pass. |
| 5 | A6/D-04 — `zero_coverage_floors` lists every (building, floor) with held>0 AND verified==0 explicitly; a fully-covered floor never appears | VERIFIED | `scheduling/reporting.py:614-655` — floor-granular held/verified fold, `held>0 and key not in verified_keys` predicate exactly as must_have specifies. |
| 6 | A6/D-04 — Coverage renders on the IFO dashboard, each section independently `safe_card`-isolated | VERIFIED | `web/ifo.py:1338-1391` wires `_coverage_card` + `zero_coverage_floors` through `safe_card`; `templates/ifo/_coverage.html` guards `coverage.1` and `zero_floors.1` independently, each including `reports/_error_card.html` on failure. |
| 7 | A8(partial)/D-05 — `ghost_rooms` returns physical rooms with `booked_seconds>0 AND used_seconds==0` (unrounded), a pure reduction of `room_breakdown` | VERIFIED | `scheduling/reporting.py:1313-1344` — exact one-line reduction on unrounded seconds fields as specified. 4 named tests in `scheduling/tests_reporting_rooms.py` including the rounding-guard case, all pass. |
| 8 | A8(partial)/D-06/IFO-09 — `utilization_csv` emits one row per physical room, `csv_safe`-neutralized text cells, `@ifo_required` GET-only, server-built filename; finishes the 06.1-07 CSV export | VERIFIED | `web/ifo.py:1585-1631` read in full — `@ifo_required`+`@require_http_methods(["GET"])`, `csv_safe(r.code)/csv_safe(r.name)/csv_safe(r.building_name...)`, filename `f'attachment; filename="utilization-{start}.csv"'` (server-built from range, not request). Route registered at `web/urls.py:142-143` as `ifo_utilization_csv`. 5 named tests in `web/tests_ifo_utilization.py`, all pass. |

**Score:** 8/8 truths verified (0 present, behavior-unverified)

### Capacity-vs-enrollment fit (A8 deferral) — confirmed absent as intended

`scheduling/reporting.py:1166-1205` (`RoomLoad`) carries only the pre-existing `capacity` field; no seat/enrolment field was added and nothing is computed from `capacity`. The docstring explicitly reasserts the T3 deferral. This matches `11-CONTEXT.md`'s `<deferred>` section — a correctly-scoped non-delivery, not a gap.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scheduling/reporting.py::session_minutes_late` | Pure seconds formula, grace-independent | VERIFIED | Lines 710-733; no `grace_minutes`/`past_grace`/DurationField reference. |
| `scheduling/reporting.py::_lateness_map` | Per-faculty fold | VERIFIED | Lines 444-473; in-flight ACTIVE included, sub-minute excluded from frequency count only. |
| `FacultyRow`/`Scorecard` lateness fields | `minutes_late_avg`/`late_sessions`/`chronic_late` | VERIFIED | Lines 75-77, 104-106; defaulted, safe construction. |
| `scheduling/reporting.py::coverage_by_building_day` / `zero_coverage_floors` | Coverage aggregates | VERIFIED | Lines 561-655; `CoverageRow`/`ZeroCoverageFloor` dataclasses at 110/128. |
| `scheduling/reporting.py::ghost_rooms` | Ghost-room reduction | VERIFIED | Lines 1313-1344. |
| `web/hr.py` CSV_HEADER + derived cell | Minutes-late column, Actual-start retained | VERIFIED | Lines 58-60 (`CSV_HEADER`), 249 (derived cell via imported helper). |
| `web/ifo.py::utilization_csv` + `UTILIZATION_CSV_HEADER` | Per-room CSV export | VERIFIED | Lines 1578-1631; distinct 3rd header contract (12 columns, superset of on-screen 8). |
| `templates/ifo/_coverage.html` | Coverage + zero-floor sections | VERIFIED | Two independently-guarded sections, read in full. |
| `templates/ifo/utilization.html` ghost section + Export CSV link | Ghost list + CSV link | VERIFIED | Lines 149-150 (Export CSV), 205-225 (ghost section, own `ghosts.1` guard). |
| `web/urls.py` route | `ifo/utilization.csv` -> `ifo_utilization_csv` | VERIFIED | Lines 142-143. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_lateness_map` | `FacultyRow`/`Scorecard` fields | direct call in both builders | WIRED | Confirmed identical unpacking/formula in both `faculty_attendance` and `faculty_scorecard`. |
| `session_minutes_late` | `web/hr.py` HR CSV cell | `from scheduling.reporting import session_minutes_late` (hr.py:38), called at hr.py:249 | WIRED | Import confirmed — not re-derived. |
| `FacultyRow.minutes_late_avg`/`chronic_late` | `report_render.py` HEADER/build_csv/build_pdf | direct attribute access | WIRED | `r.minutes_late_avg`, `"Yes" if r.chronic_late else ""` at report_render.py:81-82, 132-134. |
| `coverage_by_building_day`/`zero_coverage_floors` | `web/ifo.py` dashboard `safe_card` | direct call | WIRED | web/ifo.py:1338-1391. |
| `ghost_rooms` | `web/ifo.py` utilization `safe_card` | direct call | WIRED | web/ifo.py:1512 `ghosts = safe_card(ghost_rooms, **scope)`. |
| `room_breakdown` | `utilization_csv` | direct call, same aggregate as on-screen table | WIRED | web/ifo.py:1608. |

### Behavioral Spot-Checks / Test Execution

Ran the full set of Phase-11 targeted test modules directly (not the whole suite, per the authoritative baseline already established):

```
manage.py test scheduling.tests_reporting_lateness scheduling.tests_reporting_coverage \
  web.tests_ifo_coverage web.tests_ifo_utilization web.tests_hr \
  scheduling.tests_reporting_rooms scheduling.tests_report_render -v1
```

Result: **Ran 222 tests — OK.** (The `RuntimeError: aggregate exploded` traceback in the output is the intentional captured exception from a card-isolation test, per both 11-03-SUMMARY.md and 11-04-SUMMARY.md — not a failure.)

All 27 must_have-named tests across the four plans were located by name and confirmed present:
- Lateness (12): `test_formula_max_zero`, `test_none_start_zero`, `test_early_arrival_not_negative`, `test_within_grace_but_late_counts`, `test_sub_minute_not_a_late_session`, `test_absent_zero_lateness`, `test_cancelled_excluded_from_lateness`, `test_inflight_active_contributes_to_lateness`, `test_chronic_threshold_boundary`, `test_chronic_floor_below_five_never_flagged`, `test_facultyrow_lateness_fields`, `test_scorecard_lateness_fields`.
- Coverage (6): `test_coverage_pct_verified_over_held`, `test_coverage_excludes_virtual_rooms`, `test_merged_sibling_lowers_coverage`, `test_absent_and_cancelled_excluded_from_coverage`, `test_zero_coverage_floor_listed`, `test_covered_floor_absent`.
- Ghost rooms (4): `test_ghost_room_booked_never_used_listed`, `test_used_room_not_ghost`, `test_ghost_rounding_guard_tiny_use_not_flagged`, `test_cancelled_room_not_ghost`.
- Utilization CSV / isolation (5): `test_ghost_card_isolation`, `test_utilization_csv_row_per_physical_room`, `test_utilization_csv_formula_neutralized`, `test_utilization_csv_gate`, `test_utilization_csv_post_405`.

`git status` confirms `FluxTrack_SRS.docx` is not in the modified/untracked set — the targeted runs did not regenerate it (MEMORY guard honored).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| A3 (audit item) | 11-01, 11-02 | Lateness captured + surfaced on scorecard, weekly report, HR CSV | SATISFIED | See truths 1-3 above. |
| A6 (audit item) | 11-03 | Verification coverage on IFO dashboard | SATISFIED | See truths 4-6 above. |
| A8 (audit item, partial) | 11-04 | Ghost-room list + per-room CSV; capacity-fit deferred by design | SATISFIED (scoped) | See truths 7-8; deferral confirmed intentional and undisturbed. |
| IFO-09 | 11-04 (finishes 06.1-07) | Per-room CSV export | SATISFIED | Already marked Complete pre-phase (REQUIREMENTS.md:103/179, closed by Phase 06.1); this phase adds the CSV export that 06.1 deliberately dropped — confirmed delivered. No REQUIREMENTS.md status conflict; this is additive, not a re-open. |

No orphaned requirements found — A3/A6/A8 are audit-addendum items (docs/AUDIT-2026-07-19.md), not SRS REQ-IDs, and are not expected to appear in REQUIREMENTS.md's Phase-mapping table.

### Anti-Patterns Found

None. Scanned all phase-modified files (`scheduling/reporting.py`, `scheduling/report_render.py`, `web/hr.py`, `web/ifo.py`, `web/urls.py`, `templates/reports/scorecard.html`, `templates/ifo/_coverage.html`, `templates/ifo/dashboard.html`, `templates/ifo/utilization.html`) for TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER/"not yet implemented" markers and stub-shaped empty-return patterns — none found. This corroborates 11-REVIEW.md's independent "clean" verdict (0 blocker/major/minor, 1 doc-wording nit that requires no fix).

### Human Verification Required

Plan 11-04 Task 3 is a `checkpoint:human-verify` gate that was recorded under autonomous/yolo mode as a Manual-Verification item (D8, `status: unknown`, `human_judgment: true`) rather than actually confirmed by a person in a browser. All four items below restate that checkpoint's `how-to-verify` steps as discrete verification items:

1. **Coverage dashboard render** — Visit `/ifo/dashboard`, confirm the coverage table and zero-coverage-floors list render legibly with real data.
2. **Ghost-room CSV export** — Visit `/ifo/utilization`, click Export CSV, open `utilization-*.csv` in a real spreadsheet and confirm no cell resolves as a formula and the layout is legible.
3. **Scorecard lateness card** — Visit `/ifo/scorecard/<id>`, confirm the avg-minutes-late figure and gated chronic pill render correctly in the existing KPI grid.
4. **Range re-scoping** — Change From/To and Apply on both dashboard and utilization pages; confirm all three surfaces (coverage, ghost list, CSV) rescope together.

### Gaps Summary

No gaps. Every must_have truth across all four plans was independently confirmed against the actual source (not SUMMARY.md claims): the lateness formula and fold, the FacultyRow/Scorecard/report_render/HR wiring, the coverage aggregates and dashboard template, and the ghost-room reduction plus CSV export all exist, are substantive (no stubs), are wired end-to-end, and pass their named tests under a live targeted run (222/222 green). The A8 capacity-fit deferral was checked and confirmed intentionally absent, matching the locked CONTEXT decision. The only open item is the human-verify checkpoint that Plan 04 deliberately deferred to a person — it was not silently dropped, it is surfaced here as required.

---

_Verified: 2026-07-20T19:15:00Z_
_Verifier: Claude (gsd-verifier)_

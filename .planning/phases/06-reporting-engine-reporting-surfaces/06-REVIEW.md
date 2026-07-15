---
phase: 06-reporting-engine-reporting-surfaces
reviewed: 2026-07-16T00:00:00Z
depth: deep
files_reviewed: 19
files_reviewed_list:
  - ops/reports.py
  - ops/tests_reports.py
  - requirements.txt
  - scheduling/management/commands/generate_weekly_report.py
  - scheduling/management/commands/runscheduler.py
  - scheduling/report_render.py
  - scheduling/reporting.py
  - scheduling/test_support.py
  - scheduling/tests_report_render.py
  - scheduling/tests_reporting.py
  - templates/dean/dashboard.html
  - templates/dean/reports.html
  - templates/hr/_rows.html
  - templates/hr/attendance.html
  - templates/ifo/_cards.html
  - templates/ifo/dashboard.html
  - templates/reports/_error_card.html
  - templates/reports/scorecard.html
  - web/dean.py
  - web/hr.py
  - web/ifo.py
  - web/tests_dean_reporting.py
  - web/tests_hr.py
  - web/tests_reporting.py
  - web/urls.py
  - web/views.py
findings:
  critical: 1
  high: 1
  medium: 1
  low: 4
  total: 7
status: issues-found
---

# Phase 06: Code Review Report — Reporting Engine & Reporting Surfaces

**Reviewed:** 2026-07-16
**Depth:** deep (cross-file, aggregate → render → view → template chains traced; MSSQL/N+1/authz focus per scope brief)
**Files Reviewed:** 26 (19 source, 7 test — test files inspected only where they confirm/refute a source-level gap)
**Status:** issues_found

## Summary

The reporting aggregate layer (`scheduling/reporting.py`) is genuinely well-built: one shared scoped queryset, DB-side conditional aggregation, a separate grouped query for the verified count (no join-inflation), local-date filtering (no UTC week drift), and `safe_card` per-card isolation that never leaks exception text. The CSV/PDF render layer correctly reuses one `csv_safe` neutralizer everywhere text is user-controlled, and the HR CSV export is a genuinely correct MSSQL-safe streaming implementation (annotation-resolved `is_verified`, no per-row subquery, no write inside the generator). The scheduler still registers exactly 4 jobs. No hardcoded secrets, no `eval`/`exec`, no `|safe` template usage, no unescaped user text.

However, a **CRITICAL** authorization gap was found in the Dean surface: `weekly_download` and `scorecard` in `web/dean.py` do NOT replicate the `department is None` guard that `dashboard()` and `reports()`/`report_export()` in the SAME file explicitly implement. A Dean account with `department=None` (a reachable DB state — `accounts.models.User.department` is `null=True` with no non-null constraint for the DEAN role) can retrieve the org-wide "ALL departments" `WeeklyReport` (the IFO-facing roll-up) via `/dean/reports/weekly/<pk>/csv|pdf`, because Django translates `department=None` into `department__isnull=True` — matching the roll-up row that itself has `department=None`. The phase's own `06-SECURITY.md` marks the related threat (T-06-01) "closed," but the test suite (`DeanScopeTests`) only exercises a *foreign non-null* department, never the *NULL*-department case — so this gap passed a prior security audit undetected.

A **HIGH** severity logic bug was found in the HR attendance list: with no filters applied, the base queryset is ordered `date, scheduled_start` (ascending / oldest-first) and sliced to the first 200 rows — meaning the unfiltered default view of `/hr/attendance` shows the OLDEST 200 sessions in the system's entire history, not the most recent ones, once the term/session volume exceeds the page size (which will happen within weeks of `materialize_sessions` running).

Remaining findings are MEDIUM/LOW quality and defensive-robustness items (PDF title mislabeling for non-weekly ranges, verified-count not defensively scoped to held sessions, banker's-rounding in the percentage helper, duplicated range-parsing logic, and an IFO notification fan-out that sends one notice per department plus one for the roll-up).

## Critical Issues

### CR-01: Dean `weekly_download` / `scorecard` miss the `department is None` guard that sibling views in the same file already apply — cross-department (BOLA) report exposure

**File:** `web/dean.py:304-329` (primarily lines 314-315), and the related `web/dean.py:246-271` (line 257-258)

**Issue:**
`dashboard()` (line 206-220) and `reports()`/`report_export()` (lines 233-243, 285-289) each explicitly special-case a Dean whose `department` is `None`:

```python
if dept is None:
    # NULL-department Dean: nothing is scoped in -> a zeroed, no-crash card.
    # NEVER dept_summary(department=None), which would leak ALL departments.
    summary = (DeptSummary(0, 0, 0, 0, 0), None)
```

`weekly_download` has no equivalent guard:

```python
report = get_object_or_404(
    WeeklyReport, pk=pk, department=request.user.department)
```

When `request.user.department` is `None`, Django's ORM translates the keyword `department=None` into `department_id IS NULL` — which is exactly the filter that matches the IFO-facing **ALL-departments roll-up** `WeeklyReport` row (`ops/reports.py` creates it with `department=None` for every week). A Dean account that is provisioned without a department (a reachable state — `accounts/models.py:33-35` has `department = models.ForeignKey(Department, null=True, blank=True, ...)` with no DB or model-level constraint forcing `Role.DEAN` to carry a non-null department) can therefore fetch the pk of the org-wide roll-up report and download every department's consolidated attendance data via `GET /dean/reports/weekly/<pk>/csv` or `.../pdf` — a direct violation of the phase's own T-06-01 control ("a Dean may read only their own department").

`scorecard()` (line 257-258) has the same shape of gap: `get_object_or_404(get_user_model(), pk=faculty_id, department=request.user.department)` with `department=None` matches ANY faculty who ALSO has a NULL department — a narrower but still out-of-scope disclosure (a NULL-department Dean can view the scorecard of any similarly-unscoped faculty, which is not necessarily "their own department" because they have none).

This is exactly the scenario the code author was clearly aware of and guarded against in the two sibling views in this same file — the fix was simply not applied consistently across all 4 reporting endpoints. `web/tests_dean_reporting.py::DeanScopeTests` only tests a *foreign, non-null* department (`dept_b`), never the `department=None` case, so this gap is untested and was not caught by the "verified" `06-SECURITY.md` audit (T-06-01 disposition: mitigate / closed).

**Fix:**
```python
@dean_required
@require_http_methods(["GET"])
def weekly_download(request, pk, fmt):
    dept = request.user.department
    if dept is None:
        # A Dean with no department scope must never resolve ANY report,
        # including the department=None IFO roll-up (T-06-01).
        raise Http404("Report file not found.")
    report = get_object_or_404(WeeklyReport, pk=pk, department=dept)
    ...


@dean_required
@require_http_methods(["GET"])
def scorecard(request, faculty_id):
    dept = request.user.department
    if dept is None:
        raise Http404("No department scope.")
    faculty = get_object_or_404(get_user_model(), pk=faculty_id, department=dept)
    ...
```
Add a regression test mirroring `test_foreign_department_weekly_download_404s` but for a Dean created with `department=None`, asserting 404 against the ALL roll-up report's pk.

## High Issues

### HI-01: HR attendance list's unfiltered default view shows the OLDEST 200 sessions, not the most recent

**File:** `web/hr.py:101-105` (queryset ordering) and `web/hr.py:182` (page slice)

**Issue:**
```python
qs = (Session.objects
      .select_related(...)
      .annotate(is_verified=Exists(verified_sq))
      .order_by("date", "scheduled_start"))     # ASCENDING (oldest first)
...
sessions = list(qs[:HR_PAGE_SIZE])               # first 200 = oldest 200
```
`_filtered_sessions` applies no default date range — an HR admin who opens `/hr/attendance` with no filters gets every `Session` row ever materialized, ordered oldest-first, capped to the first 200. Because `materialize_sessions` continuously extends the session horizon and terms accumulate over time, the unfiltered page will very quickly (within weeks, once total session count exceeds 200) show only records from the very first term/week the system was seeded with — never anything current. This is the primary landing view of the HR-01 surface and its default behavior is effectively non-functional for any installation with more than a couple hundred historical sessions. No test exercises the no-filter case at scale (`web/tests_hr.py` fixtures are small), so this was not caught.

**Fix:** Either reverse the default ordering to most-recent-first and slice the tail, or (more consistent with the Dean/IFO dashboards, which default to "current reporting week") apply a default date-range scope when neither `from` nor `to` is supplied:
```python
if not (from_raw or to_raw):
    # No explicit range: default to the active term / a recent window so the
    # unfiltered page shows current data, not the oldest 200 sessions ever.
    qs = qs.order_by("-date", "-scheduled_start")
else:
    qs = qs.order_by("date", "scheduled_start")
```
or scope to `AcademicTerm.objects.filter(is_active=True)` by default. Either way, `HR_PAGE_SIZE` should cap the MOST RECENT rows by default, not the earliest.

## Medium Issues

### ME-01: `build_pdf`'s hardcoded "week of {start}" title mislabels Dean's ad-hoc exports, which can span an arbitrary (non-weekly) range

**File:** `scheduling/report_render.py:94-98`, called from `web/dean.py:294`

**Issue:** `build_pdf`'s docstring and title assume a single-week scope:
```python
story = [
    Paragraph(
        f"Weekly Attendance - {dept_label} - week of {week_start}",
        styles["Title"],
    ),
```
But `dean.report_export` passes whatever `start`/`end` the Dean chose via the `from`/`to` GET filters (`web/dean.py:158-191`, `_reporting_range`), which is NOT clamped to 7 days — a Dean can select a month or a full term. The generated PDF's title will still read "week of 2026-07-06" even though the table underneath covers, say, 8 weeks of data, misleading anyone who archives or forwards the PDF as a record.

**Fix:** Either pass both bounds and render an accurate label, or rename/generalize the title:
```python
def build_pdf(rows, period_start, period_end, department):
    ...
    Paragraph(f"Attendance Report - {dept_label} - {period_start} to {period_end}", styles["Title"])
```
and update both call sites (`ops/reports.py:98` passes `week_start`/`week_end` already available; `web/dean.py:294` needs `end` threaded through, which `report_export` already has in scope as `end`).

## Low Issues

### LO-01: `_verified_map` counts VERIFIED validations across the full scoped queryset, not scoped to HELD sessions

**File:** `scheduling/reporting.py:123-135`, consumed at `scheduling/reporting.py:178`

**Issue:** `_verified_map` is built from the same `qs` passed to `faculty_attendance`, which includes ABSENT/SCHEDULED sessions, not just HELD ones:
```python
verified = (
    qs.filter(validations__action=ValidationAction.VERIFIED)
    .values("faculty_id")
    .annotate(n=Count("id", distinct=True))
)
```
Nothing in this layer defensively constrains "verified" to be a subset of "held." If any upstream bug or data anomaly ever attaches a VERIFIED `CheckerValidation` to a non-held session, the reported `verified` count could exceed `held`, producing a nonsensical row in the HR/report CSV export (the only place `verified` is surfaced — confirmed via grep, no HTML template references `.verified`). No test exercises this (only the ACTIVE + verified and MERGED + unverified cases are covered in `scheduling/tests_reporting.py`).

**Fix:** Add `status__in=HELD_STATUSES` to the `_verified_map` filter to make the invariant self-enforcing rather than relying on upstream discipline:
```python
verified = (
    qs.filter(status__in=HELD_STATUSES, validations__action=ValidationAction.VERIFIED)
    .values("faculty_id")
    .annotate(n=Count("id", distinct=True))
)
```

### LO-02: `_pct` uses Python's banker's-rounding, which can silently produce an off-by-one-percent tie value

**File:** `scheduling/reporting.py:87-95`

**Issue:** `round(100 * held / scheduled)` uses Python 3's round-half-to-even. For an exact `.5` tie (e.g. `held=1, scheduled=8` → `12.5`), `round(12.5)` returns `12`, not the conventionally expected `13`. This is a minor, rare-in-practice discrepancy but can make an attendance percentage look one point lower than a stakeholder manually computing it would expect.

**Fix:** Use conventional half-up rounding if a deterministic, human-expected tie-break matters here:
```python
from decimal import Decimal, ROUND_HALF_UP
def _pct(held, scheduled):
    if not scheduled:
        return 0
    return int(Decimal(100 * held / scheduled).quantize(0, rounding=ROUND_HALF_UP))
```

### LO-03: `_reporting_range` is duplicated verbatim between `web/ifo.py:222-255` and `web/dean.py:158-191` (plus the `_WEEKDAY_INDEX` dict duplicated a third time)

**File:** `web/ifo.py:218-255`, `web/dean.py:154-191`

**Issue:** The docstring in `dean.py` explains the duplication is deliberate ("mirroring `web.ifo._reporting_range` (deliberately NOT imported across role modules)"), but the duplicated block is 30+ lines including the `_WEEKDAY_INDEX` mapping — a change to the range-resolution logic (e.g. a new edge case, a different note wording) now has to be made identically in two places, and there is no test asserting the two stay in sync. This is a maintainability risk more than a functional bug today.

**Fix:** If cross-role importing is intentionally avoided, at minimum extract the shared, role-agnostic pure logic (weekday resolution + note construction) into `scheduling/reporting.py` or a small `web/_reporting_range.py` helper that both `ifo.py` and `dean.py` import — pure functions have no role-coupling concern, only view functions do.

### LO-04: `generate_week_reports` sends the IFO admin role one notification PER department plus one for the ALL roll-up, every week

**File:** `ops/reports.py:128-165`

**Issue:** `notify_report_ready(dept, ...)` is called once per department inside the loop, then once more for `department=None`. Every notification call to `notify(role=Role.IFO_ADMIN, ...)` fans out to every active IFO admin. For an institution with, say, 10 departments, every IFO admin receives 11 near-identical "Weekly attendance report ready" notifications every Monday morning. This matches the literal docstring ("IFO gets every report") but may be unwanted notification noise; worth confirming with product intent since it's easy to collapse to a single "reports ready" notice per week.

**Fix (if noise is undesired):** send IFO a single notification per week after the loop completes, rather than once per department:
```python
count = 0
for dept in departments:
    generate_weekly_report(week_start=week_start, week_end=week_end, department=dept)
    _notify_dept_deans_only(dept, week_start, link=link)   # deans only, per iteration
    count += 1
generate_weekly_report(week_start=week_start, week_end=week_end, department=None)
notify(role=Role.IFO_ADMIN, type=WEEKLY_REPORT_READY,
       title="Weekly attendance reports ready", body=f"{count} department reports + the All roll-up - week of {week_start}", link=link)
count += 1
```

---

_Reviewed: 2026-07-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_

---
phase: 06
slug: reporting-engine-reporting-surfaces
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
block_on: high
created: 2026-07-16
---

# Phase 06 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
>
> Retroactive audit. Verified against the REAL implemented source (not documentation or
> SUMMARY.md claims): `scheduling/reporting.py`, `scheduling/report_render.py`,
> `ops/reports.py`, `scheduling/management/commands/runscheduler.py` +
> `generate_weekly_report.py`, `web/ifo.py`, `web/dean.py`, `web/hr.py`, `web/urls.py`,
> `web/views.py`, `templates/reports/_error_card.html`, `accounts/models.py`,
> `ops/models.py`. The full phase-06 test suite (77 tests across
> `scheduling.tests_reporting`, `scheduling.tests_report_render`, `ops.tests_reports`,
> `web.tests_reporting`, `web.tests_dean_reporting`, `web.tests_hr`,
> `scheduling.tests.SchedulerWiringTests`) was RE-RUN during this audit (not merely
> read from a prior SUMMARY) and is green.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| aggregate -> view/template | An aggregate that raises must not leak internal exception detail to the rendered page | exception text / generic message |
| PyPI -> dev/prod environment | An installed package runs with full process privilege | reportlab package bytes |
| server data -> exported CSV opened in Excel | A faculty display name is user-controlled text Excel will evaluate as a formula if it starts with `= + - @` | CSV cell text |
| generated report bytes -> storage | Report file paths must be server-controlled, not derived from any request input | filesystem path string |
| generation event -> notification recipients | A Dean must be notified about only their own department's report | Notification row / push payload |
| client -> IFO dashboard/scorecard | Any authenticated user could try to reach a reporting URL; only IFO_ADMIN (or superuser) may | HTTP request |
| client -> Dean reporting surface | Any authenticated user could try a Dean URL; only Role.DEAN (or superuser) may | HTTP request |
| Dean -> department data | A Dean may read only their own department; a crafted faculty_id / report pk / department param must not cross the boundary | ORM queryset scope |
| client -> HR surface | Any authenticated user could try `/hr/*`; only Role.HR_ADMIN (or superuser) may | HTTP request |
| filtered queryset -> streamed response | A large export must not exhaust memory; a streamed cursor must not run concurrently with a write | DB cursor / HTTP stream |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-06-01 | Elevation of Privilege (IDOR/BOLA) | `web/dean.py` scorecard / reports / report_export / weekly_download | high | mitigate | `get_object_or_404(User, pk=faculty_id, department=request.user.department)` (dean.py:257-258) and `get_object_or_404(WeeklyReport, pk=pk, department=request.user.department)` (dean.py:314-315); `reports()`/`report_export()` scope `faculty_attendance(department=dept)` (dean.py:238-239, 288-289). Verified by re-running `web.tests_dean_reporting::DeanScopeTests` (5 tests, incl. `test_foreign_department_scorecard_404s`, `test_foreign_department_weekly_download_404s`, `test_report_excludes_foreign_faculty`, `test_export_excludes_foreign_faculty`) — pass. | closed |
| T-06-02 | Tampering (CSV injection) | `scheduling/report_render.py::csv_safe` reused by `web/dean.py` (build_csv/build_pdf) + `web/hr.py` (direct import) | high | mitigate | Single neutralizer `csv_safe()` (report_render.py:40-52) prefixes a leading quote to any cell starting with `= + - @ \t \r`. `build_csv` (report_render.py:68) applies it; `web/hr.py` imports the SAME function (hr.py:37) at every text cell (hr.py:234-243) — no reimplementation found (grepped for a second `_FORMULA_TRIGGERS`/quote-prefix pattern; none exists). Verified by `scheduling.tests_report_render::CsvInjectionTests`, `web.tests_dean_reporting::DeanExportTests`, `web.tests_hr::HrExportTests` — all pass. | closed |
| T-06-03 | Denial of Service (full-term CSV export) | `web/hr.py::attendance_csv` | medium | mitigate | `StreamingHttpResponse(rows(), ...)` (hr.py:247) + `qs.iterator()` (hr.py:231); on-screen list capped at `HR_PAGE_SIZE=200` (hr.py:42, 182) — the CSV is the only uncapped surface, by design. Verified by `web.tests_hr::HrExportTests` — pass. | closed |
| T-06-04 | Information Disclosure | `scheduling/reporting.py::safe_card` + `templates/reports/_error_card.html` | medium | mitigate | `safe_card` (reporting.py:266-281) logs the real exception via `logger.exception` and returns `(None, "This section could not be loaded.")` — never the exception string. `_error_card.html` renders fixed generic copy only (no template variable carries exception text). Verified by re-running `scheduling.tests_reporting::CardIsolationTests` and `web.tests_reporting::CardIsolationViewTests` (patches an aggregate to raise with a secret marker `KABOOM_SECRET_TRACE_12345` / `raw-internal-detail-should-not-leak` and asserts it is ABSENT from the HTTP response) — pass; the marker appears only in the server-side stderr traceback, never in response content. | closed |
| T-06-05 | Tampering (storage path traversal) | `ops/reports.py::generate_weekly_report` | medium | mitigate | Storage names built ONLY from `department.code` (or `"ALL"`) + `week_start` (reports.py:93-98); the function signature takes no request object and is reachable only from `generate_week_reports()` (JOB-03 scheduler / on-demand CLI), never a web view. `Department.code` is admin-managed (accounts/models.py), not request-derived. No `request.*` reference anywhere in `ops/reports.py` (grepped). | closed |
| T-06-06 | Information Disclosure (notify targeting) | `ops/reports.py::notify_report_ready` | medium | mitigate | IFO notified via `role=Role.IFO_ADMIN`; Deans notified via `users=<Dean queryset filtered to department=department>` (reports.py:117-125) — never the raw department-None ALL roll-up sent to a Dean. Verified by re-running `ops.tests_reports::NotifyTargetingTests::test_dept_report_notifies_ifo_and_that_dept_dean_only`, which asserts the OTHER department's Dean receives ZERO notifications — pass. | closed |
| T-06-07 | Tampering (Dean read-only) | `web/dean.py` all reporting views | high | mitigate | `@require_http_methods(["GET"])` on `dashboard`, `reports`, `scorecard`, `report_export`, `weekly_download` (dean.py:194-329, all 5 confirmed via grep); no write/mutation endpoint exists on the reporting surface. Verified by re-running `web.tests_dean_reporting::ReadOnlyTests` — pass. | closed |
| T-06-08 | Tampering (aggregate truth source) | `scheduling/reporting.py` | low | accept | Aggregates are read-only pure functions reading `Session.status`; grepped `scheduling/reporting.py` for `.save(`, `.create(`, `notify(` — zero matches (the only occurrences of "notify()"/"timezone.now()" are in the module docstring's PROHIBITION text, not actual calls). No write path exists in this module. | closed (accepted) |
| T-06-09 | Denial of Service (build_pdf memory) | `scheduling/report_render.py::build_pdf` | low | accept | In-memory `io.BytesIO` PDF is bounded to one department / one week (the weekly report scope); the unbounded full-term case (HR) uses streaming CSV instead of PDF (see T-06-03). No PDF export exists on the HR surface (grepped `web/hr.py` for `build_pdf` — none). | closed (accepted) |
| T-06-10 | Elevation of Privilege | `web/ifo.py::dashboard`, `::scorecard` | high | mitigate | Both wrapped in `@ifo_required` (ifo.py:258, 277) — `login_required` + `Role.IFO_ADMIN` check, superuser bypass, else `PermissionDenied` (403). Verified by re-running `web.tests_reporting::IfoDashboardTests`, `::ScorecardDrilldownTests` (non-IFO refused 403) — pass. | closed |
| T-06-11 | Input Validation | `web/ifo.py::_reporting_range` (from/to GET params) | low | mitigate | `parse_date`-validated; invalid or reversed input degrades to the default reporting week with a friendly note, never raises (ifo.py:222-255). Verified by `web.tests_reporting::FilterValidationTests` — pass. | closed |
| T-06-12 | Denial of Service (JOB-03 double-fire) | `scheduling/management/commands/runscheduler.py` | medium | mitigate | `build_scheduler()` registers exactly 4 jobs (materialize/sweep/weekly_report/push_outbox, confirmed by reading `runscheduler.py` directly — no 5th job); `weekly_report` job has `max_instances=1, coalesce=True`. `WeeklyReport.unique_together(week_start, department)` (ops/models.py:184) + `get_or_create` (ops/reports.py:90-91) makes re-runs idempotent. Verified by re-running `ops.tests_reports::JobFillTests` + `scheduling.tests::SchedulerWiringTests` — both pass. | closed |
| T-06-13 | Access Control | `/dean/*` reporting | high | mitigate | `dean_required` (dean.py:50-57: `login_required` + `Role.DEAN` check, superuser bypass) wraps all 5 reporting views. Verified by `web.tests_dean_reporting::DeanDashboardTests::test_non_dean_refused` — pass. | closed |
| T-06-14 | Elevation of Privilege | `/hr/attendance`, `/hr/attendance.csv` | high | mitigate | `hr_required` (hr.py:52-66: `login_required` + `Role.HR_ADMIN` check, superuser bypass) wraps `attendance()` and `attendance_csv()`. Verified by `web.tests_hr::HrGateTests` (non-HR user 403 on both routes) — pass. | closed |
| T-06-15 | Tampering (MSSQL cursor safety) | `web/hr.py::attendance_csv` streaming generator | medium | mitigate | Checker-verified status is an `Exists(OuterRef(...))` ANNOTATION resolved in the main query (hr.py:99-104), not a per-row property/subquery; the `rows()` generator (hr.py:229-244) performs no `.save()/.create()/.delete()` — read-only string formatting only (grepped, confirmed no ORM write inside the generator). Verified by `web.tests_hr::HrExportTests` — pass. | closed |
| T-06-16 | Input Validation | HR filter GET params | low | mitigate | Date filters `parse_date`-validated, invalid input drops the bound with a friendly note (hr.py:127-135); FK filters (`faculty`, `department`, `term`) gated by `.isdigit()` (hr.py:118-123) before hitting the ORM — never a raw/non-numeric lookup, never `pk__in` on a large list. Verified by `web.tests_hr::HrFilterTests::test_invalid_date_is_friendly_not_500` — pass. | closed |
| T-06-SC | Tampering (reportlab supply-chain) | `reportlab` pip install | high | mitigate | Blocking human legitimacy checkpoint (06-02-PLAN Task 1) presented before any pip command ran; operator approved after pypi.org verification (official reportlab.com maintainers, multi-year version history, SUS verdict confirmed a download-telemetry false positive per 06-02-SUMMARY.md). Pin `reportlab>=4.2,<5` confirmed present in `requirements.txt:13` (grep). Installed version 4.5.1, within the pinned range. | closed |
| T-06-SC2 | Tampering (transitive deps) | reportlab's Pillow dependency | low | accept | ReportLab's only image dependency is Pillow, already vetted/installed in a prior phase; the `<5` pin excludes the brand-new 5.0.0 major. No WeasyPrint/GTK/Pango/Cairo entry found in `requirements.txt` (grep). | closed (accepted) |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Unregistered Flags (new attack surface not in any plan's threat model)

None found. Grepped all 7 `06-0X-SUMMARY.md` files for `Threat Flag` / new-attack-surface markers — no matches; no SUMMARY.md in this phase records an unmapped flag.

**Informational note (broad ASVS L1 pass, not a registered threat, non-blocking):** `web/ifo.py::scorecard` resolves `faculty_id` via `get_object_or_404(get_user_model(), pk=faculty_id)` with no `role=Role.FACULTY` filter — an IFO admin can pass the pk of a non-faculty User (e.g. another Dean or HR account) and receive a zeroed scorecard (no Session rows match a non-faculty user). This is consistent with IFO-09's documented "unscoped dashboard, any faculty reachable" design (IFO is already the most-privileged reporting role platform-wide) and does not cross a privilege boundary or leak data beyond what IFO already has unscoped access to. No action required; noted for completeness.

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|--------------|------|
| AR-06-01 | T-06-08 | Aggregate layer (`scheduling/reporting.py`) is read-only by construction — no `.save()`/`.create()`/`notify()` calls exist in the module; tampering with attendance truth from this layer is architecturally impossible, so no additional control is needed. | Phase 06 plan (06-01-PLAN.md) | 2026-07-15 |
| AR-06-02 | T-06-09 | `build_pdf` renders in-memory (`io.BytesIO`), acceptable because it is bounded to one department / one week (the weekly-report and Dean ad-hoc export scope). The unbounded full-term case (HR payroll) deliberately uses streaming CSV instead of PDF, so no in-memory PDF is ever built at unbounded scale. | Phase 06 plan (06-03-PLAN.md) | 2026-07-15 |
| AR-06-03 | T-06-SC2 | ReportLab's only image dependency (Pillow) was already vetted and installed in a prior phase; the `reportlab>=4.2,<5` pin excludes the brand-new, less-vetted 5.0.0 major. No new system-library (GTK/Pango/Cairo) surface introduced. | Phase 06 plan (06-02-PLAN.md), operator-approved checkpoint | 2026-07-15 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|----------------|--------|------|--------|
| 2026-07-16 | 18 | 18 | 0 | gsd-secure-phase (retroactive audit) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-16

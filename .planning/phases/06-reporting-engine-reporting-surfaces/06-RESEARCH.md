# Phase 6: Reporting Engine & Reporting Surfaces - Research

**Researched:** 2026-07-15
**Domain:** Django ORM aggregation on MSSQL, server-rendered dashboards (htmx), CSV/PDF export, scheduled report generation
**Confidence:** HIGH (codebase-grounded; PDF library choice verified against PyPI + official docs)

> **No CONTEXT.md exists for this phase** (discuss-phase intentionally skipped). There is therefore no `## User Constraints` section. Design intent is drawn from REQUIREMENTS.md, ROADMAP.md Phase 6, the SRS, and the approved `docs/superpowers/specs/2026-07-02-dean-dashboard-design.md`. Every unresolved judgment call is surfaced in **Open Questions** and **Assumptions Log** for the planner (and a possible late discuss-phase) to lock.

## Summary

Phase 6 builds **one shared, side-effect-free aggregate layer** and then hangs five surfaces off it: the Weekly Consolidated Report (RPT-01/02/03), the faculty scorecard (RPT-04), the IFO-09 dashboard, the Dean dashboard (DEAN-04), and the HR session-level list (HR-01/02/03). The entire phase is **read-only reporting over data that Phases 2/3/4/04.2 already made trustworthy** — there is no new attendance truth to invent. The single most important architectural rule is: **the aggregates MUST consume the existing `Session.status` truth (`ABSENT` set by the sweep/scan via `is_no_show_past_grace`, `ACTIVE`/`COMPLETED` = held) and `Session.verified_by_checker`, never re-derive "held/absent" from timestamps.** Re-deriving would fork the truth the whole milestone spent four phases unifying.

The highest-risk decision is **PDF generation (RPT-03)**. WeasyPrint — the usual "best fidelity" pick — is **rejected** here: it is not pure Python (requires Pango/Cairo/GObject/HarfBuzz system libraries), needs an MSYS2 `pacman` install on the Windows dev box, and is routinely false-flagged as malware by antivirus — three ways to break a capstone demo. The recommendation is **ReportLab (Platypus `Table`/`TableStyle`)**: pure-Python wheels, zero system dependencies, identical behavior on Windows dev and Linux EC2, and a table-first API that is a perfect fit for a one-row-per-faculty consolidated report. `xhtml2pdf` (built on ReportLab) is the fallback if template reuse with the on-screen HTML report is judged worth the lower CSS fidelity.

The aggregate layer follows the established **pure-resolver discipline** (`scheduling/resolver.py`): read-only, deterministic given `(scope, date-range)` and the DB, no writes, no `notify()`, no `timezone.now()` baked in (range passed as args), independently unit-testable under the Django test runner. Efficiency on MSSQL comes from **DB-side conditional aggregation** (`Count('id', filter=Q(status=...))` in one `GROUP BY`), never Python loops over large querysets, and from **filtering by the `Session.date` DateField** (local class date) rather than the UTC `scheduled_start` to keep weekly boundaries timezone-correct. The 2100-parameter MSSQL limit that bit `reset_term` is avoidable by construction: reporting filters on `date__range` + `faculty__department`, never a giant `pk__in` list.

**Primary recommendation:** Build `scheduling/reporting.py` (or `ops/reporting.py`) as pure, side-effect-free aggregate functions returning dataclasses; compute every surface from them; render each dashboard card through a `safe_card()` wrapper for RPT-05 isolation; generate CSV with the stdlib `csv` module into an `HttpResponse`, PDF with ReportLab Platypus; store `WeeklyReport` files via `default_storage` (FileSystemStorage now, S3-swappable in Phase 8); land JOB-03 in the existing `_job_weekly_report` stub in `runscheduler.py`, made idempotent by the `WeeklyReport` `unique_together(week_start, department)`; notify IFO + Deans through `notify()` with the pre-defined `WEEKLY_REPORT_READY` type.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RPT-01 | Weekly consolidated report per department, one row/faculty (scheduled, held, absent, attendance %, checker-verified) + itemized absences, from pure aggregates | Aggregate layer §Architecture Pattern 1; conditional-aggregation query §Pattern 2; "held/absent" truth reuse §Don't Hand-Roll |
| RPT-02 | Weekly report generates on demand + auto-weekly (JOB-03), stored, notifies IFO + Dean(s) | JOB-03 lands in existing `_job_weekly_report` stub §Pattern 5; idempotency via `unique_together`; `notify()` + `WEEKLY_REPORT_READY` already wired §Pattern 6 |
| RPT-03 | Export as CSV and printable PDF, per department or all | ReportLab recommendation §Standard Stack; stdlib `csv` §Pattern 3 |
| RPT-04 | Faculty scorecard (scheduled vs held, %, absences, early-ends, modality breakdown, selectable period) from same aggregates | Scorecard = per-faculty slice of the same aggregate + `ended_early` + effective-modality breakdown §Pattern 2 |
| RPT-05 | Single failed aggregate degrades gracefully (its card errors, page still renders) | `safe_card()` isolation wrapper §Pattern 4 |
| IFO-09 | IFO dashboard: summary cards over selectable range + faculty-scorecard drill-down (shared aggregates) | Same aggregates, unscoped; `ifo_required` gate §Pattern 7 |
| DEAN-01 | Dean access read-only, scoped to their department(s) | `dean_required` + `department`-scoped querysets §Security Domain; server-side scoping §Pattern 7 |
| DEAN-02 | Dean views department-scoped reporting + per-faculty scorecards | Same aggregates filtered by `faculty__department=dean.department` |
| DEAN-03 | Dean views + exports weekly report for their department(s) | Reuse RPT-03 export, department-scoped; `WeeklyReport` filtered by department |
| DEAN-04 | Dean dashboard: dept-scoped summary cards + latest-weekly-report card, reusing RPT aggregates | Approved design spec `2026-07-02-dean-dashboard-design.md`; mirrors IFO-09 shape |
| HR-01 | HR views verified session-level attendance (present/absent, actual times, method, checker-verification) | Session-level list view (not aggregate); reads `Session` + `verified_by_checker` |
| HR-02 | HR filters/searches by faculty, department, date range, term | GET-param filter form over `Session` queryset; `AcademicTerm` for term filter |
| HR-03 | HR exports session-level attendance as CSV for external payroll | stdlib `csv` streaming §Pattern 3 |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Attendance aggregation (counts, %) | API/Backend (Django ORM, DB-side `GROUP BY`) | Database | MSSQL computes counts far faster than Python; keep the loop out of Python |
| "Held/absent" truth | Database (`Session.status`) | — | Already decided by sweep/scan in Phases 2/3/04.2; reporting only *reads* it |
| Report rendering (dashboards) | Frontend Server (Django templates + htmx) | — | Server-rendered per project constraint (no React/Node); htmx polling idioms established |
| CSV/PDF generation | API/Backend (Python: stdlib `csv`, ReportLab) | — | Server generates files; browser only downloads |
| Report storage | Database (`WeeklyReport` row) + Storage (`default_storage`) | — | Row is metadata/idempotency key; file bytes go to MEDIA_ROOT now, S3 in Phase 8 |
| Weekly generation trigger | API/Backend (existing `runscheduler` process) | — | ENV-04 one-scheduler rule; JOB-03 slot already reserved |
| Report-ready notification | API/Backend (`notify()` write path) | — | NOTIF-00 single write path; `WEEKLY_REPORT_READY` type pre-defined |
| Department scoping / read-only | API/Backend (per-view role decorators) | — | Authorization is server-side decorators (Convention #5), never client-trusted |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django ORM (in-stack) | 6.0.6 | Conditional aggregation (`Count(..., filter=Q(...))`, `Case`/`When`) for all counts | Already the stack; DB-side aggregation is the correct MSSQL-efficient path [VERIFIED: requirements.txt] |
| Python stdlib `csv` | 3.12 | CSV export for RPT-03 + HR-03 | Zero new dependency; correct quoting/escaping; already used in `import_offerings.py` [VERIFIED: repo grep] |
| **ReportLab** | 4.4.x (latest 5.0.0) | Printable PDF (RPT-03) via Platypus `Table`/`TableStyle` | Pure-Python wheels, no system libs, identical Win/Linux, table-first — best demo reliability [VERIFIED: PyPI; CITED: doc.courtbouillon WeasyPrint deps] |

> **ReportLab version note:** PyPI shows `5.0.0` (2026-06-18) as latest and `4.4.x` as the mature 4-series. Pin conservatively (e.g. `reportlab>=4.2,<5` or test `5.0.0` explicitly) — `5.0.0` is new (~1 month old at research time). The planner should add a `checkpoint:human-verify` before the install per the legitimacy protocol. ReportLab depends on Pillow, which is **already installed** (`Pillow>=10.0` in requirements.txt) [VERIFIED: requirements.txt].

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `django.core.files.storage.default_storage` | in-stack | Read/write report files backend-agnostically | Store `WeeklyReport.csv_path`/`pdf_path`; FileSystemStorage now, S3 in Phase 8 without code change |
| `django.db.models` `Q`, `Count`, `Case`, `When`, `Avg` | in-stack | Conditional aggregation building blocks | The aggregate query core |
| `django.http.HttpResponse` / `StreamingHttpResponse` | in-stack | CSV/PDF download responses with `Content-Disposition` | In-memory for weekly report; streaming for full-term HR export |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ReportLab (build PDF via Platypus) | **xhtml2pdf** (`0.2.17`) | Renders a Django HTML template → PDF (reuse the on-screen report template, DRY). Built on ReportLab so still pure-Python/no system libs. **Lower CSS fidelity** (no flexbox/grid, basic table/CSS2 only); silent layout quirks are a demo risk. Acceptable for a purely tabular report if template reuse is prioritized. |
| ReportLab | **WeasyPrint** (`69.0`) | **REJECTED.** Best HTML/CSS fidelity but NOT pure Python: needs Pango/Cairo/GObject/HarfBuzz/Fontconfig; Windows install requires MSYS2 `pacman -S mingw-w64-x86_64-pango`; frequently false-flagged as malware by AV. Contradicts "simplest AWS surface" and endangers a Windows-dev demo. [CITED: doc.courtbouillon.org/weasyprint/stable/first_steps.html] |
| ReportLab | **Headless Chromium** (Playwright print-to-PDF) | **REJECTED.** Highest fidelity but Chromium is a massive dependency (`playwright install chromium`), heavy on a single EC2, and pulls a browser toolchain — squarely against the Node-free/simplest-surface ethos (DEPLOY-02). Overkill for capstone scale. |
| DB-side aggregation | Python loop over `.iterator()` | REJECTED. At full-term scale (~4,226 sessions materialized for 14 days; a full term is much larger) Python-side counting is slow and, on MSSQL/pyodbc, the open SELECT cursor + per-row work risks the same HY010 class of issues the sweep guards against. Aggregate in the DB. |

**Installation:**
```bash
pip install "reportlab>=4.2,<5"     # add to requirements.txt under "Media / reports"
# (Pillow already present; no system libraries required)
```

**Version verification:** `pip index versions reportlab` → latest `5.0.0`, mature series `4.4.x` (verified 2026-07-15). No `postinstall`/native-build step for pure-Python wheels.

## Package Legitimacy Audit

> Run before install. Verdicts below are from `gsd-tools query package-legitimacy check --ecosystem pypi`.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| reportlab | PyPI | series since 2.3 (2008); 5.0.0 published 2026-06-18 | seam: unknown (telemetry gap) | reportlab.com (official) | **SUS** (`too-new`, `unknown-downloads`) | **Keep — flag.** False positive: SUS reasons are (a) the seam can't read PyPI weekly downloads and (b) `5.0.0` is recent. ReportLab is a ~18-year-established library (versions back to 2.3). Planner MUST add `checkpoint:human-verify` before install; pin `>=4.2,<5` to avoid the brand-new 5.0.0 if preferred. |
| xhtml2pdf | PyPI | since 0.0.1; 0.2.17 published 2025-02-24 | seam: unknown | none detected by seam (actually github.com/xhtml2pdf/xhtml2pdf) | **SUS** (`unknown-downloads`, `no-repository`) | **Fallback only.** Same telemetry gap. Established library. Use only if xhtml2pdf path is chosen over ReportLab. |
| weasyprint | PyPI | since 0.1; 69.0 published 2026-06-02 | seam: unknown | weasyprint.org (official) | **SUS** (`unknown-downloads`) | **REMOVED from recommendation** (not for legitimacy reasons — for the system-dependency/Windows/AV risks above). Legitimate package; simply not chosen. |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** reportlab, xhtml2pdf, weasyprint — all SUS **solely** because the seam could not fetch PyPI download telemetry (`unknown-downloads`), not because of any real risk signal. All three are long-established (decade-plus) libraries with official project sites and full version histories. The planner MUST still gate the chosen install (ReportLab) behind a `checkpoint:human-verify` task per protocol, but the SUS verdict here is a telemetry false-positive, not evidence of slopsquatting.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌─────────────────────────────────────────────┐
                          │  scheduling/reporting.py  (PURE aggregates)  │
   Session.status  ─────▶ │  faculty_attendance(dept, start, end) ->     │
   (ABSENT/ACTIVE/        │      [FacultyRow(scheduled, held, absent,    │
    COMPLETED = truth     │       attendance_pct, verified, early_ends,  │
    from Ph2/3/04.2)      │       modality_breakdown, absences[])]       │
   Session.verified_by_   │  dept_summary(dept, start, end) -> Summary   │
    checker  ───────────▶ │  NO writes · NO notify() · NO now() inside   │
   ended_early ─────────▶ │  DB-side Count(filter=Q(...)) GROUP BY       │
                          └───────────────┬─────────────────────────────┘
                                          │ (read-only, deterministic)
        ┌─────────────────┬───────────────┼───────────────┬──────────────────┐
        ▼                 ▼               ▼               ▼                  ▼
  ┌───────────┐    ┌────────────┐  ┌────────────┐  ┌────────────┐   ┌──────────────┐
  │ IFO-09    │    │ Dean       │  │ Faculty    │  │ Weekly     │   │ HR list      │
  │ dashboard │    │ dashboard  │  │ scorecard  │  │ report gen │   │ (session-    │
  │ (all dept)│    │(DEAN-04,   │  │ (RPT-04,   │  │ (RPT-01/02)│   │  level, not  │
  │ ifo_req'd │    │ dept-scope,│  │ drill-down)│  │            │   │  aggregate)  │
  │           │    │ dean_req'd)│  │            │  │            │   │ hr_required  │
  └─────┬─────┘    └─────┬──────┘  └─────┬──────┘  └─────┬──────┘   └──────┬───────┘
        │ each card via safe_card()      │               │                 │
        ▼ (RPT-05 isolation)             ▼               ▼                 ▼
  server-rendered htmx-polled cards            ┌──────────────────┐  CSV (stdlib csv)
                                               │ CSV: stdlib csv  │  Content-Disposition
                                               │ PDF: ReportLab   │
                                               │ default_storage  │
                                               │ WeeklyReport row │
                                               │ (unique_together │
                                               │  = idempotency)  │
                                               └────────┬─────────┘
                                                        ▼
                          runscheduler _job_weekly_report (JOB-03, Mon 06:00)
                          + on-demand view  ──▶ notify(IFO + Dean(s),
                                                  type=WEEKLY_REPORT_READY)
                                                  ──▶ 05-03 push outbox delivers
```

### Component Responsibilities

| File (new/edit) | Responsibility |
|------|----------------|
| `scheduling/reporting.py` (new) | Pure aggregate functions + dataclasses. NO ORM writes, NO `now()` baked in (range passed as args), NO `notify()`. The single source every surface computes from. Docstring cites RPT-01/04/05. |
| `scheduling/report_render.py` or in reporting service (new) | CSV builder (stdlib `csv`) + PDF builder (ReportLab Platypus). Takes aggregate dataclasses → bytes. |
| `scheduling/services.py` (edit) or new `ops/reports.py` | `generate_weekly_report(week_start, department)` — orchestrates aggregate → render → `default_storage` write → `WeeklyReport` get_or_create (idempotent) → `notify()`. Reused by JOB-03 and the on-demand view. |
| `web/ifo.py` (edit) | IFO-09 dashboard view (unscoped), scorecard drill-down. |
| `web/dean.py` (edit) | DEAN-04 dashboard + DEAN-02/03 department-scoped report/scorecard/export views. |
| `web/hr.py` (new) | HR-01/02/03 session-level list + filter + CSV export. New `hr_required` decorator. |
| `web/urls.py` (edit) | Wire `/ifo/dashboard`, `/dean/dashboard`, `/dean/reports/...`, `/hr/attendance`, export endpoints. |
| `scheduling/management/commands/runscheduler.py` (edit) | Replace `_job_weekly_report` stub body with a call into `generate_weekly_report` for every department for last week. |
| `templates/{ifo,dean,hr}/*.html` (new) | Server-rendered dashboards/cards, htmx-polled, Franken UI shell; `safe_card` error partials. |

### Pattern 1: Pure aggregate functions (resolver discipline) — RPT-01/04/05

**What:** Aggregates live in `scheduling/reporting.py`, mirror the `scheduling/resolver.py` purity contract: read-only, deterministic, no `save()`, no `notify()`, no `timezone.now()` inside (the date range is passed in), returning dataclasses. Independently unit-testable under the Django test runner with DB fixtures.
**When to use:** Every count/percentage the five surfaces need.
**Example:**
```python
# scheduling/reporting.py  — Source: pattern of scheduling/resolver.py + CONVENTIONS.md rule #1
from dataclasses import dataclass, field
from django.db.models import Count, Q
from scheduling.models import Session, SessionStatus, Modality

HELD_STATUSES = (SessionStatus.ACTIVE, SessionStatus.COMPLETED)  # Phase-2/3 truth: held = checked-in/verified

@dataclass
class FacultyRow:
    faculty_id: int
    name: str
    scheduled: int
    held: int
    absent: int
    verified: int
    attendance_pct: float
    absences: list = field(default_factory=list)  # itemized (RPT-01)

def faculty_attendance(*, start, end, department=None):
    """Pure RPT-01 aggregate: one FacultyRow per faculty over [start, end] (Session.date).

    Reuses Session.status truth (never re-derives no-show). department=None -> all
    (IFO-09); a Department -> DEAN/RPT scoping. Filters on Session.date (local class
    date) so weekly boundaries are timezone-correct (no UTC scheduled_start drift).
    One GROUP BY on MSSQL via conditional Count(filter=Q(...)) — no Python loop.
    """
    qs = Session.objects.filter(date__range=(start, end))
    if department is not None:
        qs = qs.filter(faculty__department=department)
    rows = (qs.values("faculty_id", "faculty__first_name", "faculty__last_name")
              .annotate(
                  scheduled=Count("id"),
                  held=Count("id", filter=Q(status__in=HELD_STATUSES)),
                  absent=Count("id", filter=Q(status=SessionStatus.ABSENT)),
                  # verified reuses the 'verified' CheckerValidation (MERGED siblings
                  # get NO validation, so this stays honest — 04.2 D-09)
                  verified=Count("id", filter=Q(validations__action="verified"), distinct=True),
              ).order_by("faculty__last_name"))
    # attendance_pct computed in Python from returned ints (pure arithmetic) to avoid
    # MSSQL integer-division surprises; guard scheduled==0.
    ...
```
> **Purity nuance:** these functions DO touch the ORM (attendance is fundamentally a DB count). "Pure" here means *side-effect-free and deterministic given inputs + DB state* — the resolver's discipline (no writes, no `now()` inside, no notify), independently testable — NOT "no ORM." This is the honest reading of RPT-01's "pure, independently tested aggregate functions" for a data-aggregation layer. [ASSUMED — see Assumptions Log A1]

### Pattern 2: DB-side conditional aggregation (MSSQL-efficient) — RPT-01/04/IFO-09/DEAN-04

**What:** All counts computed in ONE `GROUP BY` query using `Count("id", filter=Q(...))`. Attendance % and modality breakdown derived from the returned integers in Python (cheap, avoids MSSQL integer-division / `Avg` rounding surprises). Django 6 supports `filter=` on aggregates natively (compiles to `COUNT(CASE WHEN ... END)` on MSSQL).
**When to use:** Every summary card and every report row.
**Modality breakdown (RPT-04):** effective modality = `declared_modality or schedule.modality` (mirrors `scheduling/merge.py:_effective_is_online` and the resolver). Because `declared_modality` overrides, the breakdown needs a `Case/When(declared_modality='', then=schedule__modality, default=declared_modality)` annotation, or a second grouped query — do NOT count `schedule.modality` alone (it ignores approved modality shifts).
**Early-ends (RPT-04):** `Count("id", filter=Q(ended_early=True))` — the `Session.ended_early` boolean is already set by the early-end scan flow.

### Pattern 3: CSV export (RPT-03 / HR-03) — stdlib, correct headers

**What:** stdlib `csv` writing into an `HttpResponse` with `Content-Type: text/csv` and `Content-Disposition: attachment; filename="..."`. For the **weekly report** (bounded: one dept, one week) build in-memory. For the **HR full-term payroll export** (potentially tens of thousands of session rows), use `StreamingHttpResponse` with a generator + `.iterator()` to bound memory.
**Example:**
```python
# Source: Django docs "Outputting CSV with Django" pattern
import csv
from django.http import StreamingHttpResponse

class _Echo:
    def write(self, value): return value

def hr_attendance_csv(rows_iter):  # rows_iter: qs.iterator()
    writer = csv.writer(_Echo())
    def stream():
        yield writer.writerow(["Faculty","Department","Course","Section","Date",
                               "Scheduled start","Actual start","Status","Method","Checker-verified"])
        for s in rows_iter:
            yield writer.writerow([...])
    resp = StreamingHttpResponse(stream(), content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="attendance.csv"'
    return resp
```
> **MSSQL cursor caution:** streaming with `.iterator()` keeps a SELECT cursor open. For a **read-only export with no writes during iteration** this is safe (the HY010 trap in `sweep_no_shows`/`merge.py` only occurs when you INSERT/UPDATE *while* the cursor is open). Do not perform any write inside the streaming generator. [VERIFIED: scheduling/jobs.py comment + merge.py comment]

### Pattern 4: RPT-05 per-card error isolation

**What:** Each dashboard card is computed through a small wrapper so one raising aggregate shows an error in its own card while the rest of the page renders. Composes over the pure aggregates without coupling them.
**Example:**
```python
def safe_card(fn, *args, **kwargs):
    """Return (value, None) or (None, error_message). RPT-05: one failing aggregate
    must not blank the page — the view passes a per-card (value, error) pair and the
    template renders an error state for that card only."""
    try:
        return fn(*args, **kwargs), None
    except Exception as exc:            # deliberately broad: isolation is the point
        return None, str(exc)
```
The view builds `ctx = {"attendance": safe_card(faculty_attendance, ...), "summary": safe_card(dept_summary, ...)}`; each template card is `{% if card.1 %}<error state>{% else %}<render card.0>{% endif %}`. Log the exception to `AuditLog`? No — a read failure is not a domain state change; prefer surfacing it in the card + optionally a `logging` line. [ASSUMED A2]

### Pattern 5: Weekly report generation + JOB-03 (RPT-02) — reuse the existing stub

**What:** The scheduler slot **already exists** — `runscheduler.py:_job_weekly_report()` is a registered stub returning 0, wired as a `CronTrigger(day_of_week="mon", hour=6)` job wrapped in `run_job`. Phase 6 replaces its body; **do NOT create a second scheduler or a second job** (ENV-04 / `NoImplicitSchedulerTests` forbids it).
**Idempotency:** `WeeklyReport` has `unique_together=[("week_start", "department")]`. Generation uses `get_or_create(week_start=..., department=...)` then (re)writes the files, so JOB-03 re-running the same Monday (misfire coalesce, manual re-run) never duplicates rows. On-demand regeneration updates the existing row's `csv_path`/`pdf_path`.
**Week boundary:** `reporting_week_start` policy = `"monday"` (`get_policy` / `FLUXTRACK_POLICY`); JOB-03 fires Mon 06:00 for the **prior** Mon–Sun. Compute `week_start` in Asia/Manila local date, filter sessions by `Session.date` (DateField), never by UTC `scheduled_start`.
**Storage:** write bytes via `default_storage.save(path, ContentFile(bytes))`; store the returned name in `csv_path`/`pdf_path`. FileSystemStorage → `MEDIA_ROOT` in dev; Phase 8 swaps `STORAGES["default"]` to S3 with no report-code change (the model docstring already says "files in S3").
**Return value:** the job returns the count of reports generated so `JobRun.rows_affected` is meaningful (Convention: prefer a JobRun row).

### Pattern 6: Notify IFO + Dean(s) through `notify()` (RPT-02, NOTIF-00)

**What:** The Phase 5↔6 contract is **already defined**: `ops/notifications.py` declares `WEEKLY_REPORT_READY = "weekly_report_ready"`, maps it into the `REPORTS` mute category, and lists it in `PUSH_TYPES` — so a report-ready push already has 05-03 delivery. Phase 6 only needs to **emit** rows of this type via the single `notify()` write path.
**Example:**
```python
from ops.notify import notify
from ops.notifications import WEEKLY_REPORT_READY
from accounts.models import Role, User

def notify_report_ready(department, week_start, link):
    # IFO gets all reports; each Dean gets ONLY their department's report (spec §2)
    notify(role=Role.IFO_ADMIN, type=WEEKLY_REPORT_READY,
           title="Weekly attendance report ready",
           body=f"{department.code if department else 'All'} · week of {week_start}",
           link=link)
    deans = User.objects.filter(role=Role.DEAN, is_active=True, department=department)
    notify(users=deans, type=WEEKLY_REPORT_READY, title="...", body="...", link=link)
```
> `notify()` takes `role=` OR `users=`. For per-department Dean targeting use `users=` with a department-filtered queryset (there is no per-department role fan-out). [VERIFIED: ops/notify.py]

### Pattern 7: Role gating + department scoping (DEAN-01/read-only, IFO-09, HR)

**What:** Authorization is a stacked per-view decorator (Convention #5), never middleware, never client-trusted. Add `hr_required` in `web/hr.py` mirroring `ifo_required`/`dean_required`. Dean read-only scoping = filter every queryset by `faculty__department=request.user.department` (and `WeeklyReport.department=request.user.department`); there are NO write endpoints on the Dean reporting surface (DEAN-01). A Dean requesting another department's report/scorecard/export is refused server-side (filter to their department, `get_object_or_404` scoped), never merely hidden — mirrors the `web/dean.py` approval-queue scoping already in place.

### Recommended Project Structure
```
scheduling/
├── reporting.py          # NEW: pure aggregate functions + dataclasses (RPT-01/04/05)
├── report_render.py      # NEW: CSV (stdlib) + PDF (ReportLab) builders from dataclasses
├── services.py           # EDIT: generate_weekly_report() orchestration (or new ops/reports.py)
└── management/commands/
    └── runscheduler.py    # EDIT: fill _job_weekly_report stub -> generate_weekly_report
web/
├── ifo.py                # EDIT: IFO-09 dashboard + scorecard drill-down
├── dean.py               # EDIT: DEAN-04 dashboard + DEAN-02/03 report/scorecard/export
├── hr.py                 # NEW: hr_required + HR-01/02/03 list/filter/CSV
└── urls.py               # EDIT: wire dashboard/report/export/hr routes
templates/
├── ifo/dashboard.html + _cards.html
├── dean/dashboard.html + reports.html + scorecard.html
└── hr/attendance.html + _rows.html
```

### Anti-Patterns to Avoid
- **Re-deriving held/absent from timestamps in the aggregate.** Use `Session.status` (ABSENT/ACTIVE/COMPLETED). Re-computing no-show from `scheduled_start + grace` forks the truth the sweep owns. [VERIFIED: scheduling/jobs.py, resolver.py]
- **Filtering weekly ranges by `scheduled_start` (UTC datetime).** Use `Session.date` (local DateField) to avoid an 8h Asia/Manila boundary drift at week edges.
- **`filter(pk__in=[large list])`** — the 2100-param MSSQL limit that broke `reset_term`. Reporting filters on `date__range` + FK; never materialize a giant id list.
- **Python loops over large querysets to count.** Aggregate in the DB.
- **Counting `schedule.modality` for the modality breakdown** — ignores approved per-session `declared_modality` shifts (MOD). Use effective modality.
- **A second scheduler / new APScheduler job for JOB-03.** Fill the existing stub. ENV-04 one-scheduler invariant is test-guarded.
- **Writing report files to a hardcoded path.** Use `default_storage` so Phase 8 S3 swap is config-only.
- **Trusting a Dean-supplied department id in a GET param.** Scope to `request.user.department` server-side.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Held/absent determination | A new "was this session attended" function | Existing `Session.status` (ACTIVE/COMPLETED = held, ABSENT = absent) set by sweep/scan/merge | Four phases unified this truth; re-deriving forks it |
| No-show grace math | Re-implement grace in reporting | It's already baked into `status` before reporting runs | `is_no_show_past_grace` is the single predicate; reporting reads the *result* |
| Checker-verified count | Query validations ad hoc | `Session.verified_by_checker` / `Count(filter=Q(validations__action="verified"))` | MERGED siblings intentionally get no validation (honest count) — 04.2 D-09 |
| Co-scheduled double-count | Special-case merged siblings in reports | Nothing — count sessions as distinct rows | 04.2 fix is attendance-only; reports SEE sections as distinct (criterion #5) — this is correct, each section is a real scheduled obligation |
| CSV writing/quoting | Manual string join with commas | stdlib `csv.writer` | Correct quoting/escaping of names with commas/quotes |
| PDF layout | Hand-drawn coordinates | ReportLab Platypus `Table`/`TableStyle` | Auto pagination, row/col styling, repeat headers |
| Report idempotency | Dedup logic in the job | `WeeklyReport.unique_together` + `get_or_create` | DB constraint is the idempotency key |
| Report-ready push | New push type/category | `WEEKLY_REPORT_READY` (already defined, mapped, in PUSH_TYPES) | Phase 5↔6 contract pre-wired |
| Notification write | Inline `Notification.objects.create` | `notify()` | NOTIF-00 single write path |
| Report file storage swap | Env branch for S3 vs local | `default_storage` + `STORAGES` setting | Phase 8 changes config only |

**Key insight:** Phase 6 is a *reading* phase. Almost every "how do I compute X" question resolves to "read a field Phases 2–04.2 already populated." The only genuinely new engineering is the aggregate query shape, the PDF renderer, and the four surfaces.

## Common Pitfalls

### Pitfall 1: Timezone-wrong weekly boundaries
**What goes wrong:** Filtering `scheduled_start__range=(monday_00:00, sunday_23:59)` in UTC pulls the wrong sessions at week edges (an 8h Asia/Manila offset moves late-Sunday/early-Monday classes into the wrong week).
**Why:** `scheduled_start` is datetime2 stored UTC; the "class date" is `Session.date` (local).
**How to avoid:** Filter by `Session.date__range=(week_start_date, week_end_date)` using Asia/Manila local dates. `Session.date` is exactly the local class date.
**Warning signs:** Session counts that shift when run at different times of day; a Sunday-night class appearing in next week's report.

### Pitfall 2: MSSQL 2100-parameter limit
**What goes wrong:** `Session.objects.filter(pk__in=[...thousands...])` raises pyodbc `07002 COUNT field incorrect` at full-term scale (exactly what broke `reset_term` per STATE.md blocker).
**Why:** SQL Server caps a statement at 2100 parameters; a big `IN` list exceeds it.
**How to avoid:** Reporting never needs an id list — filter on `date__range` + `faculty__department` FK + `status`. If you ever must pass many ids, chunk them.
**Warning signs:** Works on a small dev slice, fails at full-term scale.

### Pitfall 3: Forking the "held/absent" truth
**What goes wrong:** The report's absent count disagrees with the sweep/scan.
**Why:** Reporting re-derived no-show from timestamps instead of reading `status`.
**How to avoid:** `absent = Count(filter=Q(status=ABSENT))`, `held = Count(filter=Q(status__in=(ACTIVE, COMPLETED)))`. Nothing else.
**Warning signs:** A session marked ABSENT by the sweep counts as held (or vice-versa) in a report.

### Pitfall 4: PDF library detonates on the demo machine
**What goes wrong:** WeasyPrint import fails (`cannot load library 'libgobject-2.0-0'`) or AV quarantines it on the Windows dev box mid-demo.
**Why:** WeasyPrint needs native GTK/Pango libs; Windows needs MSYS2; AV false-flags it.
**How to avoid:** Use ReportLab (pure Python, no system libs). [CITED: doc.courtbouillon.org]
**Warning signs:** PDF works on one machine, `OSError`/`ImportError` on another.

### Pitfall 5: Modality breakdown ignores approved shifts
**What goes wrong:** A session shifted to Online by a Dean-approved MOD request still counts as F2F.
**Why:** Counting `schedule.modality` instead of effective (`declared_modality or schedule.modality`).
**How to avoid:** Use the effective-modality expression (mirror `merge._effective_is_online`).
**Warning signs:** Online counts lower than the approved-shift count.

### Pitfall 6: MERGED siblings and verified counts
**What goes wrong:** Trying to "fix" the checker-verified count to include merge-filled siblings.
**Why:** Misreading the design — merge-filled siblings deliberately get NO `CheckerValidation` (04.2 D-09) so `verified_by_checker` stays honest. They ARE counted as *held* (status ACTIVE via MERGED) but NOT as *checker-verified*.
**How to avoid:** Count held via `status`, verified via `validations__action="verified"`. Do not conflate them.
**Warning signs:** Verified count == held count on co-scheduled days.

## Runtime State Inventory

> Greenfield reporting phase (adds read surfaces + one scheduler-stub body). Not a rename/refactor/migration. No stored-string renames, no OS-registered state changes, no secret renames. The one new dependency (ReportLab) is a normal pip add. **Section omitted** — no runtime state to migrate.

## Code Examples

### Weekly report generation (idempotent, storage-agnostic) — RPT-02
```python
# scheduling/services.py (or ops/reports.py) — Source: WeeklyReport model + default_storage pattern
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from ops.models import WeeklyReport
from scheduling.reporting import faculty_attendance
from scheduling.report_render import build_csv, build_pdf

def generate_weekly_report(week_start, week_end, department):
    rows = faculty_attendance(start=week_start, end=week_end, department=department)
    report, _ = WeeklyReport.objects.get_or_create(   # idempotent via unique_together
        week_start=week_start, department=department)
    csv_name = f"reports/{week_start}/{department.code if department else 'ALL'}.csv"
    pdf_name = f"reports/{week_start}/{department.code if department else 'ALL'}.pdf"
    report.csv_path = default_storage.save(csv_name, ContentFile(build_csv(rows)))
    report.pdf_path = default_storage.save(pdf_name, ContentFile(build_pdf(rows, week_start, department)))
    report.save(update_fields=["csv_path", "pdf_path"])
    return report
```

### PDF via ReportLab Platypus (tabular) — RPT-03
```python
# scheduling/report_render.py — Source: ReportLab Platypus Table/TableStyle
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet

def build_pdf(rows, week_start, department) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    title = Paragraph(f"Weekly Attendance — {department.code if department else 'All'} "
                      f"— week of {week_start}", styles["Title"])
    header = ["Faculty", "Scheduled", "Held", "Absent", "Attendance %", "Checker-verified"]
    data = [header] + [[r.name, r.scheduled, r.held, r.absent,
                        f"{r.attendance_pct:.0f}%", r.verified] for r in rows]
    table = Table(data, repeatRows=1)          # repeat header across pages
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#001c43")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6fa")]),
    ]))
    doc.build([title, table])
    return buf.getvalue()
```

### Conditional aggregation with attendance % (MSSQL-safe) — RPT-01
```python
rows = (Session.objects.filter(date__range=(start, end), faculty__department=dept)
        .values("faculty_id", "faculty__first_name", "faculty__last_name")
        .annotate(scheduled=Count("id"),
                  held=Count("id", filter=Q(status__in=HELD_STATUSES)),
                  absent=Count("id", filter=Q(status=SessionStatus.ABSENT)),
                  verified=Count("validations", filter=Q(validations__action="verified"), distinct=True),
                  early_ends=Count("id", filter=Q(ended_early=True)))
        .order_by("faculty__last_name"))
# attendance_pct in Python: round(100*held/scheduled) if scheduled else 0  (avoid MSSQL int div)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `.extra()` / raw SQL for conditional counts | `Count("id", filter=Q(...))` aggregate filtering | Django 2.0+ | Portable to MSSQL; compiles to `COUNT(CASE WHEN)`; use this, not raw SQL |
| WeasyPrint as default HTML→PDF | Pure-Python ReportLab for constrained/Node-free deploys | Ongoing | Avoids system-lib + AV friction on Windows/EC2 |
| Hardcoded MEDIA path writes | `default_storage` + `STORAGES` setting | Django 4.2 `STORAGES` | S3 swap is config-only (Phase 8) |

**Deprecated/outdated:**
- `DEFAULT_FILE_STORAGE`/`STATICFILES_STORAGE` settings → replaced by the `STORAGES` dict (already used in `config/settings.py`). Use `default_storage`, not the old setting names.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "Pure aggregate functions" (RPT-01) means side-effect-free/deterministic-given-DB (resolver discipline), NOT literally ORM-free | Pattern 1 | If the user intended a fully DB-free pure core (counts passed in), the module needs a two-layer split (fetch layer + pure compute). Low risk — attendance is inherently a DB count; but confirm the intended "purity" boundary. |
| A2 | RPT-05 card failures are surfaced in-card + optional `logging`, NOT written to AuditLog | Pattern 4 | If audit of report failures is required, add an AuditLog write. Convention #2 says writes get AuditLog, but a read failure isn't a state change (like the read-surface exception in `ops/notifications._mark_read`). |
| A3 | ReportLab chosen over xhtml2pdf/WeasyPrint | Standard Stack | If the user wants template reuse (one HTML template → screen + PDF), xhtml2pdf may be preferred despite lower fidelity. This is the one call most worth a quick user confirm. |
| A4 | Report files stored via `default_storage` to MEDIA_ROOT now; S3 is Phase 8 | Pattern 5 | If S3 is wanted in Phase 6, needs `django-storages`+boto3 now. Model docstring says "S3" but STORAGES is FileSystemStorage — treating S3 as Phase 8 is consistent with the roadmap. |
| A5 | "held" = status ACTIVE or COMPLETED; "scheduled" = all Session rows in range regardless of status | Pattern 1/2 | If "scheduled" should exclude cancelled/archived schedules, add `schedule__status=ACTIVE` filter. Verify whether archived-schedule sessions should count. |
| A6 | HR "term" filter maps to `AcademicTerm` via `session.schedule.term`; date-range and term are independent filters | Phase Requirements HR-02 | If term should override date-range or map differently, adjust. `AcademicTerm` has `is_active`; only one active at a time. |
| A7 | Weekly report generated **per department** (one WeeklyReport row per department per week), plus possibly an ALL (department=NULL) roll-up | Pattern 5 | `unique_together(week_start, department)` with nullable department allows both. Confirm whether an all-departments report is generated in addition to per-department. |
| A8 | Faculty scorecard drill-down is reachable from IFO-09 and Dean dashboards (a per-faculty detail view) reusing the same aggregate sliced to one faculty | Pattern 2 | Confirm the drill-down UX (modal vs page). |

**These 8 assumptions are the strongest candidates for a short discuss-phase or a planner checkpoint before locking the plan.**

## Open Questions

1. **PDF library final call (A3).**
   - What we know: ReportLab is the safe, pure-Python, demo-reliable choice; xhtml2pdf enables HTML-template reuse at lower fidelity; WeasyPrint is rejected for system-lib/AV/Windows friction.
   - What's unclear: whether template reuse (DRY between on-screen report and PDF) outweighs ReportLab's fidelity/reliability.
   - Recommendation: **ReportLab.** Revisit only if the on-screen report HTML is complex enough that maintaining two renderers is costly.

2. **All-departments roll-up report (A7).**
   - What we know: `WeeklyReport.department` is nullable (NULL = ALL); IFO sees all.
   - What's unclear: does JOB-03 generate per-department rows only, or also one ALL row?
   - Recommendation: generate per-department rows (Deans need theirs); add an ALL row for IFO if the IFO weekly view wants a single consolidated file. Cheap to add.

3. **"Scheduled" denominator scope (A5).**
   - What we know: attendance % = held / scheduled.
   - What's unclear: whether sessions from ARCHIVED schedules or future-dated sessions in the range count toward "scheduled."
   - Recommendation: count only sessions whose `date <= today` and whose schedule is ACTIVE; a future session isn't yet a missed obligation. Confirm.

4. **HR export scale / term size.**
   - What we know: full-term materialized ~4,226 sessions for 14 days; a whole term is larger.
   - What's unclear: exact full-term session row count for the CSV.
   - Recommendation: use `StreamingHttpResponse` + `.iterator()` for the HR export regardless; it costs nothing and removes the memory ceiling.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All | ✓ | 3.12 (`py -3.12`) | — |
| Django | Aggregation, views | ✓ | 6.0.6 | — |
| Pillow | ReportLab image support | ✓ | >=10.0 (installed) | — |
| ReportLab | PDF (RPT-03) | ✗ (to add) | 4.4.x / 5.0.0 | xhtml2pdf (also pip, pure-Python) |
| stdlib `csv` | CSV (RPT-03/HR-03) | ✓ | 3.12 | — |
| MSSQL (LocalDB dev / RDS prod) | All queries | ✓ | SQL Server 2025 LocalDB | — |
| APScheduler + `runscheduler` | JOB-03 | ✓ | >=3.10,<4 | — (job slot already exists) |
| `notify()` + `WEEKLY_REPORT_READY` | RPT-02 notify | ✓ | in-repo | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** ReportLab (fallback xhtml2pdf) — both are pip installs, no system libraries. WeasyPrint's system libs are NOT required by the recommended path.

## Validation Architecture

> `nyquist_validation` is enabled (`.planning/config.json` → `workflow.nyquist_validation: true`). FluxTrack uses the **Django test runner**, NOT pytest (per MEMORY + verified: no pytest.ini/tox.ini/conftest; tests live in `<app>/tests*.py`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django `unittest`-based test runner (`manage.py test`) |
| Config file | none — test discovery via `<app>/tests*.py`; test DB `test_fluxtrack` on MSSQL (`config/settings.py` TEST NAME) |
| Quick run command | `py -3.12 manage.py test scheduling.tests_reporting -v2` |
| Full suite command | `py -3.12 manage.py test -v1` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RPT-01 | Aggregate produces correct scheduled/held/absent/%/verified per faculty | unit | `py -3.12 manage.py test scheduling.tests_reporting.AggregateTests -v2` | ❌ Wave 0 |
| RPT-01 | Held/absent read from `status`, never re-derived (coupling test vs a fixture with mixed statuses) | unit | `...tests_reporting.TruthReuseTests` | ❌ Wave 0 |
| RPT-04 | Scorecard early-ends + effective-modality breakdown honor `declared_modality` | unit | `...tests_reporting.ScorecardTests` | ❌ Wave 0 |
| RPT-05 | One raising aggregate → its card errors, others render (`safe_card`) | unit | `...tests_reporting.CardIsolationTests` | ❌ Wave 0 |
| RPT-03 | CSV has correct header/rows + `Content-Disposition`; PDF builds non-empty bytes | integration | `web.tests_reporting.ExportTests` | ❌ Wave 0 |
| RPT-02 | JOB-03 idempotent (re-run same week → one WeeklyReport row); notifies IFO + only that dept's Dean | integration | `scheduling.tests_reporting.WeeklyJobTests` | ❌ Wave 0 |
| RPT-02 | Weekly boundary uses `Session.date` (timezone-correct at week edges) | unit | `...tests_reporting.WeekBoundaryTests` | ❌ Wave 0 |
| IFO-09 | Dashboard renders unscoped; scorecard drill-down works | integration | `web.tests_reporting.IfoDashboardTests` | ❌ Wave 0 |
| DEAN-01 | Dean queryset scoped to own department; cross-dept report/export refused server-side | integration | `web.tests_reporting.DeanScopeTests` | ❌ Wave 0 |
| DEAN-04 | Dean dashboard cards + latest-weekly-report card | integration | `web.tests_reporting.DeanDashboardTests` | ❌ Wave 0 |
| HR-01/02/03 | Session-level list; filter by faculty/dept/date/term; CSV export streams | integration | `web.tests_reporting.HrTests` | ❌ Wave 0 |
| DEAN-01/HR | No write endpoints on Dean/HR reporting surfaces (read-only negative test) | integration | `web.tests_reporting.ReadOnlyTests` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `py -3.12 manage.py test scheduling.tests_reporting -v2` (the pure aggregates — fastest, DB-light).
- **Per wave merge:** `py -3.12 manage.py test scheduling.tests_reporting web.tests_reporting -v1`.
- **Phase gate:** `py -3.12 manage.py test -v1` full suite green before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] `scheduling/tests_reporting.py` — pure aggregate + week-boundary + truth-reuse + card-isolation tests (RPT-01/04/05/02).
- [ ] `web/tests_reporting.py` — dashboard/export/scope/HR integration tests (IFO-09, DEAN-*, HR-*, RPT-03).
- [ ] Shared fixture: a small term with faculty across ≥2 departments, sessions spanning statuses (ACTIVE/COMPLETED/ABSENT/SCHEDULED), a MERGED sibling, an `ended_early` session, and a `declared_modality`-shifted session — so aggregates are exercised against every code path. Reuse `scheduling/test_support.py` / the GARAY merge fixture where possible.
- [ ] Framework install: none (Django runner present).

## Security Domain

> `security_enforcement` not disabled in config (absent = enabled).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Read-only reporting tier; scoping enforced server-side in views |
| V2 Authentication | no (this phase) | Handled by existing dev-login/Entra; all views `@login_required` via `_required` decorators |
| V4 Access Control | **yes (central)** | Per-view role decorators (`ifo_required`, `dean_required`, new `hr_required`); Dean department-scoping filters every queryset; cross-department/IDOR refused server-side, not hidden (DEAN-01) |
| V5 Input Validation | yes | HR filter GET params (faculty/dept/date/term) parsed with `parse_date`/validated; invalid input → friendly empty result, never a 500 (mirror `ifo.assignment_create` validation) |
| V7 Error Handling & Logging | yes | RPT-05 `safe_card` isolates failures; export/report writes are read-derived (no new secrets) |
| V12 Files & Resources | yes | Report files written via `default_storage` under MEDIA_ROOT; download responses set `Content-Disposition: attachment` (no inline HTML injection); path built from `department.code`/date, not user input |

### Known Threat Patterns for Django reporting/export

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dean reads another department's report/scorecard (BOLA/IDOR) | Elevation of Privilege | Filter every queryset by `request.user.department`; scope `get_object_or_404`; never trust a department id in GET/POST |
| CSV formula injection (payroll CSV opened in Excel) | Tampering | Prefix cells beginning with `= + - @` with a `'` or space when writing user-derived text fields (faculty names) to the CSV |
| Large export exhausts memory / DoS | Denial of Service | `StreamingHttpResponse` + `.iterator()` for the HR full-term export |
| Report file path traversal | Tampering | Build storage paths from server-controlled `department.code` + date only; never from request input |
| Read endpoint used to mutate | Tampering | Reporting views are GET-only reads; no state change (DEAN-01 read-only); export endpoints GET, no side effects |
| Information disclosure via broad card exception text | Information Disclosure | `safe_card` should surface a generic "This section failed to load", not raw exception internals, in production |

> **CSV formula injection** is the one net-new security control this phase introduces (payroll CSV is opened in Excel downstream). Sanitize leading `= + - @ \t \r` in text cells. [CITED: OWASP CSV Injection guidance]

## Sources

### Primary (HIGH confidence)
- FluxTrack codebase (read this session): `scheduling/models.py` (Session/WeeklyReport-adjacent), `ops/models.py:171` (WeeklyReport), `scheduling/jobs.py` (sweep truth + MSSQL cursor notes), `scheduling/management/commands/runscheduler.py` (JOB-03 stub), `ops/notify.py`, `ops/notifications.py` (WEEKLY_REPORT_READY contract), `scheduling/resolver.py` (purity discipline), `scheduling/merge.py` (held/verified truth, `_effective_is_online`), `web/dean.py`/`web/ifo.py`/`web/faculty.py` (role-gate + scoping patterns), `config/settings.py` (TIME_ZONE, STORAGES, policy), `.planning/codebase/CONVENTIONS.md`.
- PyPI (`pip index versions`, 2026-07-15): reportlab 5.0.0/4.4.x, weasyprint 69.0, xhtml2pdf 0.2.17 — [VERIFIED].
- `doc.courtbouillon.org/weasyprint/stable/first_steps.html` — WeasyPrint native deps + Windows/MSYS2 + AV false-positive — [CITED].

### Secondary (MEDIUM confidence)
- `docs/superpowers/specs/2026-07-02-dean-dashboard-design.md` (approved) — DEAN-04 shape + RPT-02 notify-Deans amendment.
- Django docs pattern "Outputting CSV with Django" (StreamingHttpResponse + Echo buffer) — [CITED, training + standard].

### Tertiary (LOW confidence)
- Deployment/AV characteristics of PDF libraries beyond the cited WeasyPrint page — training knowledge, cross-checked against the official deps page.

## Metadata

**Confidence breakdown:**
- Standard stack (ReportLab, stdlib csv, Django aggregation): HIGH — versions verified on PyPI, WeasyPrint rejection grounded in official docs, aggregation is in-stack.
- Architecture (aggregate layer, JOB-03 reuse, notify contract): HIGH — every integration point read in the actual source; JOB-03 stub, WeeklyReport model, and WEEKLY_REPORT_READY contract all confirmed present.
- Pitfalls (MSSQL 2100, timezone, truth reuse): HIGH — each is a documented, code-confirmed reality in this repo (reset_term blocker, datetime2 UTC round-trip, sweep status truth).
- Design intent (per-dept vs ALL, purity boundary, PDF-vs-xhtml2pdf): MEDIUM — no CONTEXT.md; 8 assumptions logged for confirmation.

**Research date:** 2026-07-15
**Valid until:** 2026-08-14 (stable stack; ReportLab 5.0.0 newness is the only fast-moving element — re-verify the pin at plan time).

**Graph note:** knowledge graph is STALE (237h old, built at commit b04375a) and returned zero nodes for "reporting" (reporting is unbuilt). Semantic relationships treated as absent; all findings grounded in direct source reads instead.

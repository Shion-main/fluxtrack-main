# Phase 12: Term Lifecycle - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 31 implementation and test seams
**Analogs found:** 31 / 31

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scheduling/models.py` | model | CRUD | `ops/models.py:185-208` | exact constraint analog |
| `scheduling/migrations/<next>_term_lifecycle.py` | migration | transform | `ops/migrations/0002_roomconflictflag.py` | role-match |
| `scheduling/term_lifecycle.py` (new) | service | event-driven/CRUD | `scheduling/services.py:492-555` | exact transaction analog |
| `scheduling/term_scope.py` (new) | utility/service | request-response | `web/reporting_common.py:41-78` | role-match |
| `scheduling/materialization.py` (new or extracted core) | service | batch | `scheduling/management/commands/materialize_sessions.py:118-164` | exact logic source |
| `scheduling/management/commands/materialize_sessions.py` | command | batch | same file, `118-164` | exact |
| `scheduling/management/commands/import_offerings.py` | command | file-I/O/batch | same file, `80-126` | exact |
| `scheduling/management/commands/reset_term.py` | command | destructive batch | same file, `49-103` | exact seam; guard/retire |
| `scheduling/management/commands/runscheduler.py` | command | event-driven | same file, `43-93` | exact |
| `scheduling/jobs.py` | service | batch | same file, `85-107` | exact |
| `scheduling/importing.py` | service | transform | `web/ifo.py:1072-1200` | role-match |
| `scheduling/schedule_ops.py` | service | CRUD | same file, `38-104` | exact |
| `scheduling/services.py`, `scheduling/suspensions.py` | service | CRUD/batch | `scheduling/services.py:492-555` | exact |
| `scheduling/admin.py` | config/admin | CRUD | `ops/admin.py:8-43` | role-match |
| `web/ifo.py` | controller | request-response/CRUD | `web/ifo.py:570-638` | exact preflight/action analog |
| `web/urls.py` | route | request-response | `web/urls.py:69-150` | exact |
| `templates/ifo/terms*.html` (new) | component | request-response | `templates/ifo/room_delete.html` | exact confirmation analog |
| `templates/ifo/import.html`, `templates/ifo/_import_panel.html` | component | file-I/O | existing files + `web/ifo.py:1072-1200` | exact |
| `web/reporting_common.py` | utility | request-response/transform | same file, `41-78` | exact extension point |
| `scheduling/reporting.py` | service | batch/transform | same file, `388-406`, `842-866` | exact |
| `web/dean.py` | controller | request-response | same file, `147-325` | exact scope analog |
| `web/hr.py` | controller | request-response | same file, `109-250` | exact selector/export analog |
| `templates/dean/*.html`, `templates/hr/attendance.html`, `templates/ifo/{dashboard,utilization,scorecard,reports}.html`, `templates/reports/scorecard.html` | component | request-response | current GET range forms and links | exact extension points |
| `ops/models.py` | model | CRUD | `WeeklyReport`, `250-267` | exact |
| `ops/migrations/<next>_weeklyreport_term.py` | migration | transform | staged migrations in `ops/migrations/` | role-match |
| `ops/reports.py` | service | batch/file-I/O | same file, `79-156` | exact |
| `ops/admin.py` | config/admin | CRUD | same file, `39-43` | exact |
| `scheduling/tests_term_lifecycle.py` (new) | test | CRUD/batch | `scheduling/tests_suspensions.py` | role/data-flow match |
| `web/tests_term_lifecycle.py` (new) | test | request-response | `web/tests_ifo_rooms.py` | exact IFO action analog |
| `web/tests_term_reporting.py` (new) | test | request-response | `web/tests_dean_reporting.py` | exact report-scope analog |
| `ops/tests_reports.py` plus existing affected suites | test | batch/file-I/O | `ops/tests_reports.py:35-200` | exact |

The planner should treat names marked “new” as recommended boundaries, not locked public APIs. Existing large modules should remain controllers; lifecycle invariants belong in a focused service.

## Pattern Assignments

### `scheduling/models.py` and lifecycle migration (model, CRUD/transform)

**Analog:** `ops/models.py:185-208` proves filtered `UniqueConstraint` support on this project's SQL Server backend.

**Constraint pattern** (`ops/models.py:203-208`):

```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["conflict_key"], condition=Q(resolved_at__isnull=True),
            name="uniq_open_conflict_per_key")
    ]
```

Apply the same database-backed shape to `AcademicTerm.status`: a `TextChoices` enum, a date-order `CheckConstraint`, a filtered unique constraint for `status="active"`, and a unique term name. Do not retain `is_active` as a second source of truth. Use a staged data migration: add status, map the one true `is_active` row to ACTIVE and other rows to ARCHIVED, validate legacy dates/names, add constraints, then remove the boolean. Date-overlap remains service/model validation with a locked overlap query because SQL Server has no PostgreSQL exclusion constraint.

For `WeeklyReport`, follow its current identity pattern (`ops/models.py:250-267`) but add a required `term` FK and replace `(week_start, department)` with `(term, week_start, department)`. Backfill only when each legacy report maps unambiguously to one term; fail loudly rather than assigning current ACTIVE.

### `scheduling/term_lifecycle.py` (service, event-driven CRUD)

**Analog:** `scheduling/services.py:492-555`.

**Atomic re-gate and audit pattern** (`scheduling/services.py:504-555`):

```python
with transaction.atomic():
    req = ModalityShiftRequest.objects.get(pk=request.pk)
    if dean.role != Role.DEAN or req.department_id != dean.department_id:
        raise ModalityShiftError("only the routed department Dean may approve")
    if req.status != ModalityShiftStatus.PENDING:
        raise ModalityShiftError("only a pending request may be approved")
    sessions = list(affected_sessions(req))
    # domain writes ...
    AuditLog.objects.create(
        actor=dean, event_type="modality_shift.approved",
        target_type="modality_shift_request", target_id=str(req.pk),
        payload={"target_modality": req.target_modality},
    )
```

Implement create/preflight/activate/close/reopen through this service. Re-fetch the term with `select_for_update()` inside `transaction.atomic()`, re-check actor authority and typed confirmation, recompute blockers/warnings, list-materialize querysets before nested writes (MSSQL HY010 discipline), then write state and `AuditLog` together. Audit payloads must contain reason, before/after status and relevant counts, never secrets. Activation calls the explicit-term materializer inside the same outer transaction so a materialization exception rolls back sessions, status, and audit. Translate database uniqueness races into a controlled “another term is active” blocker.

### `scheduling/term_scope.py` and archive-write gates (utility/service)

**Analogs:** `web/ifo.py:57-64` for centralized guards and `scheduling/schedule_ops.py:38-104` for mutation services.

```python
def ifo_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.IFO_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```

Create one authoritative `get_active_term()` resolver (error on none; DB invariant prevents many) and one `require_writable_term(term)` guard. Apply the guard at service/command/admin boundaries, not just templates. Known mutation seams include attendance/checker/scan actions, schedule CRUD, breaks/suspensions, modality shifts, imports, materialization, scheduler jobs, Django Admin, and legacy reset. Live boards/jobs must add `schedule__term=active_term`, not rely on date coincidence.

### Materialization, import, and command seams (service/command, batch/file-I/O)

**Analog:** `scheduling/management/commands/materialize_sessions.py:118-164`.

```python
term = AcademicTerm.objects.filter(is_active=True).first()
start = (datetime.strptime(o["start"], "%Y-%m-%d").date()
         if o["start"] else timezone.localdate())
end = start + timedelta(days=o["days"])
excused = excused_checker(term)
schedules = (term.schedules.filter(status=ScheduleStatus.ACTIVE)
             .select_related("faculty", "room", "room__floor"))
# iterate dates; Session.objects.get_or_create(...)
```

Extract the recurrence loop into an explicit `materialize_term(term=..., start=..., days=..., allow_draft=False)` function. Preserve `excused_checker`, `get_or_create` idempotency, approved-shift hooks and list-before-write behavior. The command resolves ACTIVE and delegates; activation passes its locked DRAFT term and enables the narrowly scoped draft exception.

**Staged import pattern:** `web/ifo.py:1105-1200` stages bytes, previews without domain writes, commits using the same options, keeps a failed staging row retryable, consumes only after success, and writes `schedule.imported`. Add a selected Draft term id to the staged/preview/commit contract and pass it explicitly to `import_offerings`; the importer must never create/activate a term or deactivate others. Draft import creates recurring `Schedule` only and must not call materialization. `reset_term` must not be a rollover path; make any retained command explicit-target, high-friction and archive-guarded, or retire it if the plan confirms no required operational use.

### `web/ifo.py`, `web/urls.py`, and term templates (controller/component)

**Analogs:** `web/ifo.py:57-64`, `570-638`; `web/urls.py:69-150`; `templates/ifo/room_delete.html`.

**Display-only preflight plus authoritative POST re-check** (`web/ifo.py:595-632`):

```python
if request.method == "GET":
    blockers = room_delete_blockers(room)
    return render(request, "ifo/room_delete.html", {
        "room": room, "blockers": _blocker_rows(blockers),
        "can_delete": not blockers})

with transaction.atomic():
    blockers = room_delete_blockers(room)
    if blockers:
        refused = blockers
    else:
        room.delete()
```

Term list/detail/create and action-confirm views use `@ifo_required`; Deans and HR get report selection only. GET presents fresh blockers/warnings and the exact-name/reason form. POST passes raw inputs to the lifecycle service, which is the authority and rechecks everything. Use separate POST routes for activate, close and reopen. Preserve validation errors with HTTP 400 and render the same confirmation surface. Empty schedules are an acknowledgeable warning; invalid dates, overlap, another ACTIVE term, active sessions on close, or failed materialization are blockers.

### `web/reporting_common.py`, report controllers, templates, and aggregates (request-response/transform)

**Analogs:** `web/reporting_common.py:41-78`; `scheduling/reporting.py:388-406`; existing term-aware room functions such as `room_utilization(..., term, ...)` at `842`.

**Existing aggregate seam** (`scheduling/reporting.py:388-406`):

```python
def _scoped_sessions(*, start, end, department=None, as_of=None, faculty=None):
    qs = Session.objects.filter(
        schedule__status=ScheduleStatus.ACTIVE,
        date__range=(start, end),
    )
    if department is not None:
        qs = qs.filter(faculty__department=department)
    if faculty is not None:
        qs = qs.filter(faculty=faculty)
    return qs
```

Make `term` mandatory and add `schedule__term=term`; retain department/faculty authorization as a separate predicate. Add one shared parser returning selected term, clamped dates, term choices and a normalized query string/dict. A missing term GET defaults to the single ACTIVE term. Archived defaults to full term dates; ACTIVE keeps each report's existing useful default. Clamp explicit dates to `[term.start_date, term.end_date]`.

Every report link, scorecard drill-down, pagination link, reset link, CSV/PDF link and stored-report list/download must carry `term=<pk>` plus the normalized range. Build query parameters server-side; do not store report term in session. Controllers must pass the same normalized scope to HTML and export functions. Preserve Dean department/IDOR filtering (`web/tests_dean_reporting.py:75-146`) and CSV formula protection through existing `build_csv` rather than adding renderers.

### `ops/models.py`, migration, `ops/reports.py`, and stored-report views (model/service/file-I/O)

**Analog:** `ops/reports.py:79-99`.

```python
report, _ = WeeklyReport.objects.get_or_create(
    week_start=week_start, department=department)
code = department.code if department else "ALL"
csv_name = f"reports/{week_start}/{code}.csv"
pdf_name = f"reports/{week_start}/{code}.pdf"
```

Require `term` in `generate_weekly_report(s)`, filter all source sessions by that term, use `(term, week_start, department)` for idempotency, and include a stable term id in storage paths (for example `reports/term-<pk>/<week>/<code>`). The scheduler resolves the applicable term explicitly and must never create an artifact spanning terms. IFO lists/downloads filter by selected term; Dean downloads additionally keep the current department-scoped `get_object_or_404` pattern.

### Django Admin and every non-view writer (config/service)

**Analogs:** `scheduling/admin.py`, `ops/admin.py`, and the service guard pattern above.

Admin `save_model`, `delete_model`, and queryset/action paths must refuse archived term-owned mutations unless the request user is a superuser using a deliberately documented break-glass path. Normal IFO authority goes through lifecycle services. Commands must take explicit term identifiers where preparation/history is relevant, call the same guard/service functions, and return non-zero/friendly errors for archived targets. Avoid signals for lifecycle auditing because actor/reason are explicit inputs.

### Tests (test, CRUD/request-response/batch)

**Analogs:** `web/tests_dean_reporting.py:36-146`, `ops/tests_reports.py:35-200`, `web/tests_ifo_rooms.py`, and `scheduling/tests_suspensions.py`.

```python
class _DeanBase(TestCase):
    def setUp(self):
        self.fx = make_reporting_fixture()
        self.client.force_login(self.dean)

def test_foreign_department_weekly_download_404s(self):
    rep_b = generate_weekly_report(..., self.fx.dept_b)
    resp = self.client.get(reverse("dean_weekly_download", args=[rep_b.pk, "csv"]))
    self.assertEqual(resp.status_code, 404)
```

Use focused new modules (`scheduling/tests_term_lifecycle.py`, `web/tests_term_lifecycle.py`, `web/tests_term_reporting.py`) and extend existing suites where signatures change. Reuse `scheduling.test_support` fixtures, adding two same-date terms to expose leakage. Use `TransactionTestCase` for database constraint/race behavior; `TestCase` for service/views; `override_settings(MEDIA_ROOT=tempfile...)` for report files. Required adversarial coverage: second ACTIVE rejected, invalid/overlapping term refused, activation rollback after injected materializer failure, close with ACTIVE sessions refused, reopen becomes DRAFT, every archived writer fails, Dean/HR cannot transition, every link/export preserves term, date clamp, same-date other-term rows excluded, stored reports never collide across terms, and no surviving production `DEFAULT_TERM`/`AcademicTerm...is_active` lookup.

## Shared Patterns

### Authorization

**Source:** `web/ifo.py:57-64`. Apply `ifo_required` to lifecycle controllers and independently authorize in the transition service. Preserve existing Dean department and HR role decorators; a selector never broadens their data scope.

### Atomicity and TOCTOU

**Source:** `web/ifo.py:582-605` and `scheduling/services.py:504-518`. GET preflight is presentation only. POST/service re-fetches and recomputes under `transaction.atomic()`; activation materialization is inside that transaction.

### Audit Logging

**Source:** `ops/models.py:165-179`, `web/ifo.py:317-330`. State and audit commit together. Use explicit event types such as `term.created`, `term.activated`, `term.archived`, `term.reopened`, with actor, target, reason, before/after state and counts.

### MSSQL Safety

**Source:** `scheduling/management/commands/materialize_sessions.py:52-61`, `scheduling/services.py:512`. Convert candidate querysets to `list()` before nested writes; chunk large primary-key lists (the legacy reset uses a bounded chunk helper). Do not introduce PostgreSQL-only constraints.

### Error Handling

Use domain exceptions carrying blocker/warning information. Views translate expected lifecycle/input failures to a friendly HTTP 400 confirmation page; commands translate them to `CommandError`. Let unexpected materialization failures escape the atomic block so rollback occurs, then present a generic failure without claiming activation.

### Query Propagation

Use one normalized GET scope from `web/reporting_common.py`; HTML, pagination, drill-down and exports receive the same values. Explicit `term` is mandatory below the controller layer so omission is a type/signature error rather than silent cross-term aggregation.

## No Analog Found

No Phase 12 file lacks a usable local pattern. There is no existing full academic-term lifecycle service, so the planner must compose the proven transaction/audit, filtered-constraint, preflight-confirmation and explicit-scope patterns above rather than copy one file wholesale.

## Metadata

**Analog search scope:** `scheduling/`, `web/`, `ops/`, `templates/`, `config/`, migrations and tests
**Files scanned:** 50+ candidate source/test/template files; 10 primary analogs inspected in detail
**Pattern extraction date:** 2026-07-21
**Primary implementation rule:** make term identity impossible to omit at mutation and management-report boundaries.

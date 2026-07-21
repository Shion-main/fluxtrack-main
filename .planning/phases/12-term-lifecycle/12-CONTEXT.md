# Phase 12: Term Lifecycle - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 12 adds a non-destructive academic-term lifecycle for IFO: create and
prepare a Draft term, activate exactly one term for live operations, close and
archive a finished term without deleting its schedules, sessions, attendance,
or reports, and deliberately reopen an archive when correction is necessary.

It also makes IFO, Dean, and HR reporting/export surfaces explicitly selectable
by term. Live attendance, Checker, Guard, room-state, and scheduler surfaces
remain active-term-only. This phase replaces hardcoded/default-term assumptions;
it does not redesign attendance capture, scheduling rules, imports, or reporting
metrics.

</domain>

<decisions>
## Implementation Decisions

### Term states and transitions

- **D-01 — Explicit lifecycle:** Terms move through `DRAFT -> ACTIVE -> ARCHIVED`.
  Exactly one term may be ACTIVE at a time. Draft terms are preparable; archived
  terms are read-only.
- **D-02 — IFO-controlled reopen:** An IFO Admin may reopen an archived term only
  through a confirmed, reason-required, fully audited action. Reopening returns
  the term to DRAFT; it never makes the old term ACTIVE automatically.
- **D-03 — Strict close eligibility:** A term may close only on or after its
  `end_date` and only when it has no ACTIVE sessions. Early close and implicit
  cancellation of future sessions are out of scope.
- **D-04 — Application-wide archive freeze:** Archived term-owned data rejects
  writes through normal UI views, services, imports, materialization, management
  commands, and Django Admin. The term must be explicitly reopened before any
  such write can occur.

### Preparing and activating the next term

- **D-05 — Prepare safely in Draft:** IFO may import recurring schedules into a
  Draft term while the current term stays active. Dated `Session` rows are not
  materialized for the Draft term.
- **D-06 — Separate close and activate:** Activating a Draft term refuses while
  another term is ACTIVE. IFO must close/archive the old term first; activation
  is a separate, explicit action. Overlapping active terms are forbidden.
- **D-07 — Blank, validated creation:** A new Draft term starts blank with a
  required unique name, start date, and end date. Dates must be ordered and must
  not overlap another term. Prior schedules are not cloned automatically.
- **D-08 — Activation includes readiness:** Activation is successful only after
  the configured initial session horizon materializes successfully and the term
  is ready for normal scheduler and attendance surfaces. If this setup fails,
  the term remains DRAFT.

### Historical reporting and exports

- **D-09 — Management reports are term-selectable:** Every IFO, Dean, and HR
  report and export accepts an explicit term selection. Live operational boards
  remain scoped to the ACTIVE term.
- **D-10 — Explicit, linkable selection:** A fresh report request defaults to the
  ACTIVE term. The selected term is carried by query parameters and propagated
  into filters, drill-downs, pagination, and export links; it is not hidden in
  session state.
- **D-11 — Term-bounded date ranges:** Report ranges are clamped to the selected
  term. Archived terms default to their full date span; the active term preserves
  each report's existing useful default window.
- **D-12 — No silent cross-term aggregation:** One report or export is scoped to
  exactly one selected term. Multi-term comparison and unbounded ranges across
  terms are not part of Phase 12.

### Rollover safeguards and recovery

- **D-13 — Authority:** IFO Admins own the normal lifecycle workflow. A Django
  superuser remains the break-glass override; Deans and other roles cannot
  transition terms.
- **D-14 — High-friction confirmation:** Lifecycle actions show a preflight
  summary and require typing the exact term name. Close and reopen additionally
  require a reason. Audit records capture actor, reason, and before/after state.
- **D-15 — Blockers versus warnings:** Invalid dates, another active term, ACTIVE
  sessions during close, or failed initial materialization are hard blockers.
  Noncritical conditions such as an empty schedule set appear as explicit
  warnings that IFO must acknowledge.
- **D-16 — Atomic transitions:** Each close, archive, activate, or reopen action
  is atomic and audited. A failed transition leaves that transition unapplied;
  no partial lifecycle state or partial activation is reported as success.

### Claude's Discretion

- Exact model/migration representation of the lifecycle state, provided the
  explicit three-state contract and single-ACTIVE invariant are enforceable on
  SQL Server.
- Service/module boundaries, URL names, page layout, confirmation wording, and
  audit event names, following existing IFO and `AuditLog` conventions.
- Exact query-parameter names and reusable term-selector component, provided
  selected-term state remains explicit and every related link/export preserves it.
- Exact warning copy and presentation order in the preflight summary.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase mandate and audit finding

- `.planning/ROADMAP.md` §Phase 12 — phase goal, A4 mapping, and the three
  required success criteria.
- `docs/AUDIT-2026-07-19.md` §A4 — the destructive rollover time-bomb and the
  requirement to preserve attendance history.
- `docs/PLAN-2026-07-20-post-audit-milestone.md` §Phase 12 — sequencing and
  operational acceptance criteria.
- `.planning/PROJECT.md` — product core value, SQL Server constraint, role model,
  and server-authoritative attendance requirements.
- `.planning/REQUIREMENTS.md` — IFO-04 and existing role/report requirements.

### Current term, import, and materialization seams

- `scheduling/models.py` — `AcademicTerm`, recurring `Schedule`, dated `Session`,
  modality items, and historical relations that must be preserved.
- `scheduling/management/commands/reset_term.py` — destructive legacy path that
  must not become the rollover implementation.
- `scheduling/management/commands/import_offerings.py` — additive importer that
  must accept an explicit Draft target.
- `scheduling/management/commands/materialize_sessions.py` — active-term session
  creation and initial activation horizon.
- `scheduling/management/commands/runscheduler.py` — recurring jobs that must
  derive their target from the single ACTIVE term.
- `config/settings.py` — current `DEFAULT_TERM` assumptions to remove.
- `.planning/phases/07-remaining-operational-surfaces/07-CONTEXT.md` D-12/D-13 —
  preview/commit import and the locked rule that destructive reset is not web-accessible.

### Reporting and IFO integration

- `web/ifo.py` — IFO import, reporting, utilization, and management surfaces.
- `web/dean.py`, `web/hr.py`, `web/reporting_common.py` — management report scopes,
  filters, drill-downs, and exports that must carry the selected term.
- `scheduling/reporting.py` — shared aggregates; metrics stay unchanged while
  query scope becomes explicitly term-bound.
- `ops/models.py` and `ops/notify.py` — `AuditLog` and the single notification
  path used by lifecycle actions if notifications are needed.

### Current architecture and known risks

- `.planning/codebase/ARCHITECTURE.md` — Schedule-versus-Session boundary,
  transactional service pattern, role gates, audit convention, and SQL Server constraints.
- `.planning/codebase/CONCERNS.md` — destructive reset risk, archived history,
  large-module seams, and production correctness constraints.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `scheduling.models.AcademicTerm`: existing term identity, date bounds, and
  `is_active` concept provide the migration anchor for explicit lifecycle state.
- `ImportStaging` plus the IFO preview/commit flow in `web/ifo.py`: reusable safe
  upload pattern for targeting a Draft term without exposing reset.
- `materialize_sessions`: reusable session-generation engine for activation's
  initial horizon; do not duplicate its recurrence logic.
- Existing report scope/filter/export helpers in `web/reporting_common.py` and
  the IFO/Dean/HR modules: extend with one shared term-selection contract.
- Existing IFO confirmation flows and `AuditLog`: reuse the server-side
  confirmation and explicit-domain-audit patterns.

### Established Patterns

- `Schedule` is recurring registrar intent; `Session` is the dated official
  attendance and room-occupancy record. Archival preserves both.
- Multi-row state transitions belong in transactional services and re-check
  mutable state inside `transaction.atomic()`.
- Every domain write is explicitly audited; authorization is enforced by
  per-view role decorators and query scoping.
- Imports are additive and previewed before commit. SQL Server cursor behavior
  requires materializing querysets before nested writes.
- Live UI state is server-derived; management reports may use explicit GET
  filters and must preserve them through exports and pagination.

### Integration Points

- Replace `DEFAULT_TERM`/first-active lookups in settings, commands, scheduler,
  views, and reports with one authoritative active-term resolver.
- Add IFO term-list/create/detail/close/activate/reopen routes under `web/urls.py`
  and focused service functions rather than adding lifecycle rules to templates.
- Add archive-write gates to every term-owned mutation seam, including Django
  Admin and management commands, not only the new IFO pages.
- Thread an explicit selected term through IFO/Dean/HR report scopes, drill-down
  URLs, pagination, CSV/PDF exports, and stored weekly-report generation.

</code_context>

<specifics>
## Specific Ideas

- Archived means an application-wide write freeze, not merely hidden edit buttons.
- Reopen is intentionally available to IFO, but it returns the old term to DRAFT
  and requires a reason; it never steals ACTIVE status from the current term.
- Preparing a future term must be possible without creating live sessions early.
- A term cannot become ACTIVE until its first materialization succeeds.
- Historical reports are always explicit, linkable, single-term views.

</specifics>

<deferred>
## Deferred Ideas

- Timed/scheduled activation, one-click archive-and-activate, automatic cloning
  of prior schedules, multi-term comparison reports, and two-person lifecycle
  approval are not part of Phase 12.

### Reviewed Todos (not folded)

- `.planning/todos/pending/entra-auth-backend-decision.md` — belongs to Phase 15
  production Entra cutover; local PKCE wiring already exists and is unrelated to
  term lifecycle.
- `.planning/todos/pending/phase1-localdb-env-deviations.md` — completed Phase 1
  SQL Server LocalDB context; remaining deployment-parity checks belong to Phase 15.

</deferred>

---

*Phase: 12-term-lifecycle*
*Context gathered: 2026-07-21*

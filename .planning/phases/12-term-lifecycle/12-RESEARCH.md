# Phase 12: Term Lifecycle - Research

**Researched:** 2026-07-21
**Domain:** Django/SQL Server lifecycle state, non-destructive academic rollover, and explicit historical report scoping
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

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

### Codex's Discretion

- Exact model/migration representation of the lifecycle state, provided the
  explicit three-state contract and single-ACTIVE invariant are enforceable on
  SQL Server.
- Service/module boundaries, URL names, page layout, confirmation wording, and
  audit event names, following existing IFO and `AuditLog` conventions.
- Exact query-parameter names and reusable term-selector component, provided
  selected-term state remains explicit and every related link/export preserves it.
- Exact warning copy and presentation order in the preflight summary.

### Deferred Ideas (OUT OF SCOPE)

- Timed/scheduled activation, one-click archive-and-activate, automatic cloning
  of prior schedules, multi-term comparison reports, and two-person lifecycle
  approval are not part of Phase 12.

### Reviewed Todos (not folded)

- `.planning/todos/pending/entra-auth-backend-decision.md` — belongs to Phase 15
  production Entra cutover; local PKCE wiring already exists and is unrelated to
  term lifecycle.
- `.planning/todos/pending/phase1-localdb-env-deviations.md` — completed Phase 1
  SQL Server LocalDB context; remaining deployment-parity checks belong to Phase 15.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| A4 | The only current rollover tool deletes `Schedule`/`Session` history; provide close/archive plus create/activate without deletion and remove the hardcoded default term. | The lifecycle schema, transition service, import/materialization split, archive-guard matrix, and migration/test strategy below close this audit finding. [VERIFIED: `docs/AUDIT-2026-07-19.md:483-490`] |
| IFO-04 (partial) | IFO manages academic terms, the active term, offerings, and academic breaks. | The recommended IFO term console owns create/preflight/activate/close/reopen; Draft import and existing break/schedule surfaces are bound to the chosen writable term. [VERIFIED: `FluxTrack_SRS.md:309`] |
</phase_requirements>

## Summary

Phase 12 must be implemented as a domain invariant, not a collection of view flags. Add an explicit `AcademicTerm.Status`, enforce unique names, ordered dates, and at-most-one ACTIVE term in SQL Server, and put every transition in one transactional service that re-fetches mutable rows, recomputes blockers/warnings, writes state and `AuditLog` together, and rolls activation back if initial materialization fails. [VERIFIED: D-01/D-07/D-14/D-16; `.planning/codebase/ARCHITECTURE.md:164-169`]

The codebase has three immediate rollover hazards. `import_offerings` creates/activates a hardcoded term and deactivates every other term; `reset_term` deletes historical schedules/sessions; and most operational reads/writes select sessions only by date, not by active term. [VERIFIED: `scheduling/management/commands/import_offerings.py:80,115-126`; `scheduling/management/commands/reset_term.py:34,93-103`; `scheduling/jobs.py:85-107`; `web/faculty.py:120-128`; `web/checker.py:239-243`] The fix must thread term identity through lifecycle, importer, materializer, scheduler/jobs, live role surfaces, and all mutation services rather than only adding an IFO page. [VERIFIED: D-04/D-09]

Reporting needs an equally explicit contract. Room-utilization aggregates already accept `term`, but faculty/dean aggregates do not; HR visually defaults its selector to ACTIVE while its base queryset remains unfiltered when `?term=` is absent; and stored `WeeklyReport` rows have no term foreign key. [VERIFIED: `scheduling/reporting.py:388-406,495-706,842`; `web/hr.py:109-125,155-169`; `ops/models.py:250-263`] Add one selected-term parser, require term in aggregate/report-generation services, clamp ranges centrally, propagate `?term=<pk>` in every link, and include term in stored report identity. [VERIFIED: D-09..D-12]

**Primary recommendation:** use a database-backed three-state lifecycle, one active-term resolver, one transactional lifecycle/materialization service, explicit archive guards at every write boundary, and one reusable GET-based report term scope. [VERIFIED: D-01..D-16]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Lifecycle state and single-ACTIVE invariant | Database / Storage | API / Backend | SQL Server must reject a second ACTIVE row even if a caller bypasses IFO UI; backend owns transition eligibility and audit. [VERIFIED: D-01/D-16; `ops/models.py:185-208`] |
| Create/close/activate/reopen | API / Backend | Database / Storage | Multi-row transition, materialization, blocker re-check, and audit belong in a transaction service. [VERIFIED: `.planning/codebase/ARCHITECTURE.md:164-169,203-208`] |
| Draft import and materialization | API / Backend | Database / Storage | Existing commands are entry points, but reusable functions must accept explicit term and refuse archives. [VERIFIED: `import_offerings.py`; `materialize_sessions.py`] |
| IFO lifecycle console | Frontend Server (SSR) | API / Backend | Existing IFO screens are server-rendered; templates display preflight while service revalidates POST. [VERIFIED: `web/ifo.py:552-638`; `templates/ifo/_console.html`] |
| Live board scope | API / Backend | Frontend Server (SSR) | Querysets must include authoritative ACTIVE term; client cannot choose live term. [VERIFIED: D-09] |
| Historical report selection | API / Backend | Frontend Server (SSR) | GET term is parsed server-side and preserved through filters, links, pagination, and exports. [VERIFIED: D-09/D-10; `web/pagination.py:28-55`] |
| Archive write freeze | API / Backend | Database / Storage | Service/command/admin guards cover normal mutation seams; DB constraints remain lifecycle backstop. [VERIFIED: D-04/D-16] |

## Project Constraints (from AGENTS.md)

- All browsing must use gstack `/browse`; no browsing was needed because this phase uses the existing pinned stack and local domain logic. [VERIFIED: provided AGENTS.md]
- `mcp__claude-in-chrome__*` is forbidden and was not used. [VERIFIED: provided AGENTS.md]
- Project `.agents/skills/` entries are command routers and add no Phase 12 coding convention. [VERIFIED: `.agents/skills/*/SKILL.md`]
- No repository `CLAUDE.md` or `.claude/CLAUDE.md` exists. [VERIFIED: filesystem scan 2026-07-21]

## Standard Stack

### Core

| Library / facility | Version | Purpose | Why Standard Here |
|--------------------|---------|---------|-------------------|
| Django | 6.0.6 | Models, constraints, transactions, views/Admin/tests | Existing pinned monolith; no new framework required. [VERIFIED: `requirements.txt`; `.planning/codebase/ARCHITECTURE.md:38`] |
| mssql-django | 1.7.3 | SQL Server ORM backend | SQL Server is the only configured DB and filtered unique constraints are already proven. [VERIFIED: `requirements.txt`; `config/settings.py:99-126`; `ops/models.py:194-207`] |
| SQL Server / ODBC Driver 18 | project environment | Durable constraints and transactions | Configuration explicitly targets Microsoft backend and Driver 18. [VERIFIED: `config/settings.py:99-126`] |
| `transaction.atomic()` | Django 6.0.6 | Transition + materialization + audit rollback | Established service-owned multi-row write pattern. [VERIFIED: `scheduling/schedule_ops.py`; `scheduling/services.py`] |
| `ops.models.AuditLog` | project model | Actor/reason/before/after trail | Every domain write is explicitly audited. [VERIFIED: `ops/models.py:165-182`; `.planning/codebase/ARCHITECTURE.md:62,207`] |
| APScheduler | `>=3.10,<4` | Active-term scheduled jobs | Existing dedicated scheduler remains sole job owner. [VERIFIED: `requirements.txt`; `runscheduler.py`] |

### Supporting Existing Components

| Component | Purpose | Reuse |
|-----------|---------|-------|
| `ops.policy.get_policy` | `materialization_horizon_days` | Activation/default materialization should use configured 14 days, not current command literal 7. [VERIFIED: `config/settings.py:250`; `materialize_sessions.py:115`] |
| `web.pagination.paginate` | Preserves non-page GET params | It already carries term/from/to once they exist. [VERIFIED: `web/pagination.py:41-55`] |
| `scheduling.report_render` | CSV/PDF and injection protection | Scope rows before unchanged render layer. [VERIFIED: `web/dean.py:248-301`; `web/hr.py:214-250`] |
| `ImportStaging` preview/commit | Owned single-use upload | Bind upload to explicit Draft term so preview/commit target cannot drift. [VERIFIED: `ops/models.py:51-99`; `web/ifo.py:1150-1200`] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Explicit status enum | `is_active` plus archived boolean | Multiple booleans admit contradictory states and do not express locked transition contract. [VERIFIED: D-01] |
| Filtered unique ACTIVE constraint | Application-only `exists()` | Application check races during concurrent activation. [VERIFIED: D-01/D-16] |
| GET report term | Session state | Hidden state breaks linkability/export parity and D-10 forbids it. [VERIFIED: D-10] |
| Cross-layer archive guards | Hide UI buttons | Commands, services, scheduler, Admin, and direct POST remain writable. [VERIFIED: D-04] |

**Installation:** No external package is required. [VERIFIED: local stack inspection]

## Package Legitimacy Audit

Not applicable: Phase 12 adds no package. It uses Django ORM/transactions, the current SQL Server backend, current renderers, and current scheduler. [VERIFIED: `requirements.txt` and codebase architecture]

## Current Codebase Inventory

| Seam | Current behavior | Planning consequence |
|------|------------------|----------------------|
| `AcademicTerm` | `name`, dates, and unconstrained `is_active`; no unique name, date-order, or single-active constraint. [VERIFIED: `scheduling/models.py:22-29`] | Add status, data migration, unique/check/filtered-unique constraints. |
| Import command | Defaults to `"2nd Term SY 2025-2026"`, creates it active, and deactivates every other term. [VERIFIED: `import_offerings.py:80,115-126`] | Target explicit Draft/writable term; importer never transitions lifecycle. |
| Staged import | Preview/commit stores only upload token; commit calls importer without term and counts schedules globally. [VERIFIED: `web/ifo.py:1144-1196`] | Persist target term with staging; recheck Draft/writable on commit; count target only. |
| Materializer | Resolves first active boolean, defaults 7 days, and contains reusable recurrence/shift logic inline. [VERIFIED: `materialize_sessions.py:111-164`] | Extract `materialize_term(term, start, days)`; activation calls Draft internally with policy horizon. |
| Reset | Deletes sessions/schedules in chunks and owns the only `DEFAULT_TERM`. [VERIFIED: `reset_term.py:34-105`] | Never use for rollover; require explicit target and reject ARCHIVED. |
| Sweep | Scans every old SCHEDULED and every ACTIVE session without active-term predicate. [VERIFIED: `scheduling/jobs.py:85-107,138-165`] | Resolve active once per job; filter `schedule__term=active`; no active is clean no-op. |
| Suspension | Receives term, but flip/lift session queries omit `schedule__term=term`. [VERIFIED: `scheduling/suspensions.py:63-104,125-153`] | Fix predicate while adding archived guard; otherwise same-date other-term rows can change. |
| Online assignment | Candidate sessions and assignments are date/status scoped but not term scoped; `Assignment.term` already exists. [VERIFIED: `verification/services.py:36-64`; `verification/models.py:21-45`] | Bind candidates/duty grants to ACTIVE term. |
| Live surfaces | Faculty, Checker, Guard, IFO board, and scan mostly query today by date/room/user without term. [VERIFIED: `web/faculty.py:120-128,567-580`; `web/checker.py:239-243,602-607,686-691`; `web/guard.py`; `web/ifo.py:79-95`; `web/scan.py:167-176`] | Thread ACTIVE predicates through all live reads and mutation re-gates. |
| Attendance aggregates | `_scoped_sessions` has no term; faculty/dept/coverage/scorecard inherit omission. [VERIFIED: `scheduling/reporting.py:388-406,495-706`] | Make term required throughout; never rely on date non-overlap as implicit scope. |
| Room utilization | Already accepts/uses explicit term. [VERIFIED: `scheduling/reporting.py:313-385,842-980`] | Keep API; views resolve selected report term instead of active-only. |
| HR report | Applies term only when numeric param exists; fresh request reads all terms while template visually selects ACTIVE. [VERIFIED: `web/hr.py:109-125,155-169`; `templates/hr/attendance.html:42`] | Default actual queryset to ACTIVE and clamp through shared selector. |
| Stored weekly reports | Identity is `(week_start, department)` and row/path contain no term. [VERIFIED: `ops/models.py:250-263`; `ops/reports.py:79-102`] | Add required term FK and include it in uniqueness/path/generation/list/latest/download. |
| Admin / term deletion | Term/Schedule/Session/Break/Assignment/Validation/WeeklyReport are editable without archive guard, and deleting `AcademicTerm` cascades to Schedule/Session through current FKs. [VERIFIED: `scheduling/admin.py`; `verification/admin.py`; `ops/admin.py:39-42`; `scheduling/models.py:35,101,150`] | Add reusable term-aware permission/save/delete guards; expose no lifecycle delete action. |

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | Canonical runtime data is in SQL Server: `AcademicTerm.is_active`, all term-owned rows, `Assignment.term`, and `WeeklyReport` rows without term identity. The live database could not be queried from this shell. [VERIFIED: `config/settings.py:99-126`; model inventory; local Python unavailable] | Run a pre-migration inventory: term ids/names/states/date overlaps/duplicate names, active count, term-owned row counts, and legacy report-to-term mapping. Data-migrate active -> ACTIVE, inactive -> ARCHIVED, and backfill report term before constraints. Do not infer production state from the checked-in `db.sqlite3`. [RECOMMENDED: migration gate] |
| Live service config | APScheduler uses an in-memory job store and job callables resolve database state when invoked; no persistent scheduler configuration stores a term id/name. [VERIFIED: `scheduling/management/commands/runscheduler.py`; `.planning/codebase/CONCERNS.md:255-264`] | Deploy changed code to the existing scheduler process and restart it normally; no external scheduler data migration. Test that all four existing jobs remain registered and term-aware. |
| OS-registered state | The documented target is one systemd unit invoking `manage.py runscheduler`; no systemd unit or IaC artifact is checked in, and no OS registration contains the hardcoded term string in repository evidence. [VERIFIED: `.planning/codebase/INTEGRATIONS.md:76-77`; repository term-string scan] | No rename/re-registration task. Normal application deployment/restart only; Phase 15 still owns production unit files. |
| Secrets / env vars | No `DEFAULT_TERM`, `TERM_NAME`, `ACADEMIC_TERM`, or hardcoded live term value appears in `.env` or `.env.example`; current defaults live in Python commands. [VERIFIED: scoped repository search 2026-07-21] | No secret/env key migration. Remove command constants/defaults and keep term identity database-driven. |
| Build artifacts / installed packages | Existing stored report bytes use `media/reports/{week}/{code}` and DB path fields; staged imports use opaque token filenames. No installed package or compiled artifact embeds the term name. [VERIFIED: `ops/reports.py:94-99`; `ops/import_staging.py:25,92`; `config/settings.py:222`] | Preserve existing report paths during DB backfill; use term-qualified paths for new reports. No file rewrite is required for old artifacts, and no package reinstall is required. |

**Canonical question:** after source edits, the remaining old lifecycle state is the SQL Server data (`is_active`, unscoped legacy reports, and possibly invalid/overlapping term rows), not an OS/env registration. The executor must audit and migrate that data before adding non-null/unique constraints. [RECOMMENDED: runtime-state review]

## Architecture Patterns

### System Architecture Diagram

```text
IFO GET term detail
        |
        v
preflight(term, action) --------------------> blockers + warnings + row counts
        |                                                   |
        | POST exact name / reason / warning acknowledgments|
        v                                                   v
lifecycle service -- authorize + lock + recompute ----------+
        |
        +-- close: ACTIVE --eligible--> ARCHIVED
        +-- reopen: ARCHIVED --reason--> DRAFT
        +-- activate: DRAFT --no ACTIVE--> materialize_term(term, policy horizon)
        |                                      |
        |                                      +-- failure: transaction rollback
        |                                      +-- success: ACTIVE
        v
AuditLog(actor, reason, before, after, counts) in same transaction

active_term() ----------------> live boards / scans / sweep / scheduler / duty
selected_report_term(?term=) -> bounded range -> aggregates -> pages/CSV/PDF
                                      |
                                      +-> WeeklyReport(term, week, department)
```

### Recommended Project Structure

```text
scheduling/
├── models.py                         # AcademicTerm.Status + SQL constraints
├── terms.py                          # active resolver, writable guard, transitions
├── materialization.py                # explicit-term reusable materializer
├── reporting.py                      # required term in attendance aggregates
├── schedule_ops.py / services.py     # archived-term guard calls
├── suspensions.py / jobs.py          # explicit active/selected term filters
├── migrations/0008_*.py              # status/data/constraint migration
└── tests_term_lifecycle.py            # constraints, rollback, freeze, jobs
ops/
├── models.py / reports.py            # WeeklyReport.term + scoped generation
└── migrations/0006_*.py              # report-term backfill + uniqueness
web/
├── reporting_common.py               # selected term + clamped range contract
├── ifo.py / dean.py / hr.py           # selected term + IFO lifecycle endpoints
├── urls.py
└── tests_term_lifecycle.py / tests_term_reporting.py
templates/
├── ifo/terms*.html                    # list/detail/create/preflight/actions
└── reports/_term_filter.html           # reusable explicit selector
```

### Pattern 1: Explicit State Plus Database Backstops

Use nested `TextChoices` with exactly `draft`, `active`, and `archived`. Make `name` unique, add `CheckConstraint(end_date__gte=F("start_date"))`, and add `UniqueConstraint(fields=["status"], condition=Q(status="active"))`. [VERIFIED: D-01/D-07; filtered unique constraints are proven on MSSQL at `ops/models.py:185-208`]

Date non-overlap is a cross-row invariant and cannot use the same row-level check. Validate inclusive overlap (`start <= other.end_date` and `end >= other.start_date`) in model/service and recheck inside the create transaction. [VERIFIED: D-07; current model has no range/exclusion facility]

Migration order: add status, map `is_active=True` to ACTIVE and existing inactive rows to ARCHIVED, verify duplicate names/date corruption, add constraints, switch callers, then remove `is_active`. [VERIFIED: current schema; D-01] Existing inactive pre-lifecycle terms have no Draft semantics, so ARCHIVED is the history-preserving backfill. [RECOMMENDED: migration interpretation]

### Pattern 2: Service-Owned Transactional Transitions

Each service accepts persisted term and actor, opens `transaction.atomic()`, re-fetches/locks term, re-authorizes actor, recomputes blockers/warnings, validates exact-name confirmation/reason/acknowledgments, then mutates and audits. [VERIFIED: D-13..D-16; `scheduling/services.py:495-551`; `web/ifo.py:582-638`]

| Action | From | Hard blockers | Warnings | Atomic result |
|--------|------|---------------|----------|---------------|
| Create | n/a | missing/duplicate name, invalid dates, overlap | none required | Blank DRAFT; no cloned schedules/sessions. [VERIFIED: D-07] |
| Activate | DRAFT | another ACTIVE, invalid dates, materialization error | empty schedules and other noncritical readiness observations | Materialize configured horizon, set ACTIVE, audit; exceptions roll all back. [VERIFIED: D-06/D-08/D-15/D-16] |
| Close | ACTIVE | local date before end; any term Session ACTIVE | noncritical readiness/report observations | Set ARCHIVED and audit; never delete/cancel rows. [VERIFIED: D-03/D-16] |
| Reopen | ARCHIVED | invalid state/date integrity | consequences of making history writable | Set DRAFT and audit; never activate. [VERIFIED: D-02/D-16] |

Superuser is a break-glass authorization bypass, not an invariant bypass: it uses the same workflow and cannot bypass single-ACTIVE/date/atomicity controls. [RECOMMENDED: safest reading of D-13 with D-15/D-16]

### Pattern 3: Extract Explicit-Term Materialization

Move recurrence/session creation from `BaseCommand.handle()` into a function taking term/start/days; retain approved-shift behavior and MSSQL list-before-write discipline. [VERIFIED: `materialize_sessions.py:25-108,118-164`; `.planning/codebase/CONCERNS.md:222-231`]

- Public command resolves ACTIVE (or explicit ACTIVE) and refuses DRAFT/ARCHIVED. [RECOMMENDED: D-04/D-05]
- Activation is the only internal caller allowed to materialize a locked DRAFT, inside its transaction, using `get_policy("materialization_horizon_days")`. [VERIFIED: D-08; `config/settings.py:250`]
- Draft import writes only recurring Schedule rows and never invokes materialization. [VERIFIED: D-05]
- Acknowledged empty schedules may yield zero sessions and still activate because D-15 explicitly makes empty schedule noncritical. [VERIFIED: D-15]

### Pattern 4: Central Archive Guard With Explicit Coverage

Create `ArchivedTermError` and `ensure_term_writable(term)`. Call it at every public mutator and again after the relevant term is locked/re-fetched. [RECOMMENDED: D-04/D-16]

A guard placed only in templates/views or one save path is insufficient because the current writer inventory also contains direct queryset `.update()` and `bulk_create()` paths. [VERIFIED: `scheduling/suspensions.py:99-101`; `scheduling/merge.py:133-139`; `seed_term.py:332-424`]

| Boundary | Required guard/filter |
|----------|-----------------------|
| Faculty scan / online start | Re-fetch session with `schedule__term=active`; refuse stale archive before save/merge. [VERIFIED: `web/scan.py:70-133`; `web/faculty.py:626-706`] |
| Checker action / replay | Re-fetch session in ACTIVE; refuse before CheckerValidation/status propagation. [VERIFIED: `web/checker.py:258-309,491-589`] |
| IFO correction/release/schedule CRUD | Derive term and call writable guard inside transaction/service. [VERIFIED: `web/ifo.py:706-766,1897-1927,2131-2242`] |
| Break/suspension create/lift/delete | Guard explicit/derived term and add `schedule__term=term` to affected-session queries. [VERIFIED: `scheduling/suspensions.py`; `web/ifo.py:1739-1861`] |
| Modality submit/withdraw/approve/reject | Derive affected term via items and require one writable term. [VERIFIED: `scheduling/services.py:169-360,495-558`] |
| Merge helpers | Guard anchor term or require authorized active caller; keep status-guarded updates. [VERIFIED: `scheduling/merge.py:98-191`] |
| Sweep/conflict/online assignment | Resolve ACTIVE once and scope candidates/assignments; no active is no-op. [VERIFIED: D-09; `scheduling/jobs.py`; `verification/services.py`] |
| Import/materialize/reset/seed commands | Explicit valid target, archived `CommandError`, importer never toggles state, reset no default. [VERIFIED: D-04/D-05; current commands] |
| Django Admin | Term-aware change/delete plus guarded save/delete/delete_queryset and no archive bulk mutations; deny AcademicTerm deletion so rollover cannot enter the cascading delete path. [VERIFIED: D-04; current admin modules/FKs] |

### Pattern 5: One Active-Term Resolver

Provide `get_active_term()` returning unique ACTIVE or None and `require_active_term()` raising a friendly domain/command error. [RECOMMENDED: D-01/D-09]

Replace every `.filter(is_active=True).first()` and implicit date-only live query. Key call sites: IFO, Faculty, Guard, Checker, scan, room_state, jobs, suspensions, materialize, audit_merge_coverage, assign_online, and seed_term. [VERIFIED: repository search 2026-07-21]

Live querysets should explicitly include `schedule__term=active` (or `term=active` for Schedule/Assignment), even with non-overlapping ranges, to protect against stale/out-of-bound legacy rows. [VERIFIED: D-09/D-12]

### Pattern 6: One Management-Report Scope

Extend `web/reporting_common.py` with a parser returning selected term, choices, bounded start/end, as_of, note, and preserved query value. [RECOMMENDED: D-09..D-12]

1. Parse numeric `?term=<pk>` server-side. A missing param defaults to ACTIVE; a supplied invalid/missing id returns a friendly 400/empty error rather than silently widening or switching scope. If no ACTIVE exists, show an explicit no-active empty state. [VERIFIED: D-10; current friendly-invalid pattern in `web/reporting_common.py:40-74`]
2. Fresh ACTIVE retains current week-to-today default; fresh ARCHIVED uses full term range. [VERIFIED: D-11]
3. Explicit from/to clamp to term bounds; as_of is no later than selected end/today. [VERIFIED: D-11]
4. Require term in `_scoped_sessions`, faculty/dept/coverage/scorecard aggregates, and report generation. [VERIFIED: D-12; current omission in `scheduling/reporting.py:388-706`]
5. Propagate term through IFO dashboard/utilization/scorecards/CSV, Dean dashboard/reports/scorecards/CSV/PDF/latest report, HR list/CSV, pager, reset, and weekly links. [VERIFIED: D-09/D-10]
6. Keep Dean department authorization independent of term. [VERIFIED: `web/dean.py:147-325`]

### Pattern 7: Stored Reports Need Term Identity

Add `WeeklyReport.term`; change uniqueness to `(term, week_start, department)` and include stable term id in storage path. [VERIFIED: D-12; current key/path at `ops/models.py:261-263`, `ops/reports.py:90-99`]

Use staged migration: nullable FK, infer each existing report from the unique term whose dates contain/intersect its week, fail on ambiguous/unmatched production rows, then require FK and replace uniqueness. Never silently assign legacy reports to current active. [RECOMMENDED: history-preserving migration safety]

`generate_weekly_report(s)` must take term and filter sessions explicitly. Scheduled generation must resolve applicable term and never aggregate two terms into one artifact. [VERIFIED: D-12; current unscoped `ops/reports.py:79-156`]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Single active term | Process cache or view check | SQL filtered `UniqueConstraint` plus service preflight | Multiple workers/commands can race. [VERIFIED: D-01/D-16] |
| Lifecycle audit | Signal guessing actor/reason | Explicit `AuditLog` inside transition service | Signals lack request actor/reason and obscure transaction ownership. [VERIFIED: `.planning/codebase/ARCHITECTURE.md:62,207`] |
| Activation recurrence | Duplicate loop in lifecycle code | Extract/reuse materializer core | It already handles breaks, suspensions, shifts, timezone, and idempotency. [VERIFIED: `materialize_sessions.py:25-164`] |
| Report term memory | Server session | GET param and shared parser | Hidden state violates D-10 and breaks link/export parity. [VERIFIED: D-10] |
| Archive protection | Disabled buttons | Service/command/admin guards + active filters | Non-UI writers otherwise mutate history. [VERIFIED: D-04] |
| Cross-row overlap DB magic | PostgreSQL exclusion/range constraint | Validation plus locked overlap query on SQL Server | Project is SQL Server-only and has no PostgreSQL range types. [VERIFIED: `config/settings.py:99-126`] |
| New report engine | Custom CSV/PDF | Existing `build_csv`, `build_pdf`, `csv_safe` | Existing exports already protect formula cells. [VERIFIED: `scheduling/report_render.py`; `web/hr.py:214-250`] |

**Key insight:** the feature is making term identity impossible to omit at mutation/report boundaries; a lifecycle page alone leaves destructive and cross-term failures intact. [VERIFIED: D-04/D-09/D-12]

## Common Pitfalls

### Pitfall 1: Keeping `is_active` beside an archive flag

**What goes wrong:** contradictory states remain possible and callers keep using/sorting the old boolean. [VERIFIED: current caller inventory]

**How to avoid:** fully migrate to status and update all `-is_active` orderings, templates, seeds, commands, and tests in this phase. [RECOMMENDED: D-01]

**Warning sign:** search still finds `AcademicTerm.objects.filter(is_active=True)`, `order_by("-is_active")`, or production `DEFAULT_TERM`. [VERIFIED: current search]

### Pitfall 2: Application-only single-ACTIVE validation

**What goes wrong:** concurrent activations both observe no active term. [VERIFIED: race implied by D-16]

**How to avoid:** transaction re-check plus filtered unique constraint; translate `IntegrityError` to friendly blocker. [RECOMMENDED: D-01/D-16]

### Pitfall 3: Calling current management command from activation

**What goes wrong:** it only resolves ACTIVE, has a 7-day default versus policy 14, and cannot safely own the outer rollback. [VERIFIED: `materialize_sessions.py:114-126`; `config/settings.py:250`]

**How to avoid:** extract explicit-term function and call inside lifecycle transaction. [RECOMMENDED: D-08/D-16]

### Pitfall 4: Treating date non-overlap as term scope

**What goes wrong:** stale/out-of-bound rows, reopened Draft, or legacy data can leak into live/report querysets. [VERIFIED: live/query inventory]

**How to avoid:** explicit `schedule__term=...` everywhere and adversarial same-date other-term fixtures. [RECOMMENDED: D-09/D-12]

### Pitfall 5: Visually selected HR term with unfiltered backend

**What goes wrong:** fresh list/export spans all terms although ACTIVE option appears selected. [VERIFIED: `web/hr.py:109-125`; `templates/hr/attendance.html:42`]

**How to avoid:** resolve default term before queryset and share normalized scope between list/CSV. [RECOMMENDED: D-10/D-12]

### Pitfall 6: View-only archive freeze

**What goes wrong:** commands, Admin, scheduler, modality services, and `.update()` still write archived rows. [VERIFIED: writer inventory]

**How to avoid:** maintain/test a writer matrix and add coupling tests requiring guard or ACTIVE filter at all known entry points. [RECOMMENDED: D-04]

### Pitfall 7: Stored reports overwrite across terms

**What goes wrong:** `(week_start, department)` and `reports/{week}/{code}` cannot distinguish term. [VERIFIED: `ops/models.py:261-263`; `ops/reports.py:90-99`]

**How to avoid:** include term in DB uniqueness and path. [RECOMMENDED: D-12]

### Pitfall 8: Closing by cancelling future sessions

**What goes wrong:** close mutates history and hides errors; D-03 forbids implicit cancellation. [VERIFIED: D-03]

**How to avoid:** block on ACTIVE sessions, leave Schedule/Session unchanged, transition only term. [VERIFIED: D-03/D-16]

### Pitfall 9: Missing MSSQL cursor/parameter discipline

**What goes wrong:** nested writes while cursor open cause HY010; large id lists cross 2100-parameter limit. [VERIFIED: `.planning/codebase/CONCERNS.md:222-231`; `reset_term.py:36-45`]

**How to avoid:** preserve list-before-write and <=900 chunk patterns. [VERIFIED: `scheduling/suspensions.py:24-25,89-104`; `reset_term.py:42-46`]

### Pitfall 10: Dropping term on drill-down/export/reset

**What goes wrong:** selecting archive then following a scorecard/back/export link jumps to ACTIVE/default. [VERIFIED: current links in `templates/dean/reports.html`, `templates/reports/scorecard.html`, `templates/ifo/utilization.html`]

**How to avoid:** central query construction or normalized `scope_query`; response tests for each link family. [RECOMMENDED: D-10]

## Code Examples

Implementation shapes below derive from project patterns; final names are discretionary.

### SQL-Backed Lifecycle Constraints

```python
class Status(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"

class Meta:
    constraints = [
        models.CheckConstraint(
            condition=models.Q(end_date__gte=models.F("start_date")),
            name="term_dates_ordered",
        ),
        models.UniqueConstraint(
            fields=["status"],
            condition=models.Q(status="active"),
            name="uniq_active_academic_term",
        ),
    ]
```

Source pattern: existing filtered unique constraint on SQL Server. [VERIFIED: `ops/models.py:203-208`]

### Explicit Report Query Scope

```python
def scoped_sessions(*, term, start, end, department=None, faculty=None, as_of=None):
    qs = Session.objects.filter(
        schedule__term=term,
        schedule__status=ScheduleStatus.ACTIVE,
        date__range=(start, end),
    )
    return qs  # existing department/faculty/as_of narrowing follows
```

Source: current `_scoped_sessions` with mandatory missing term predicate. [VERIFIED: `scheduling/reporting.py:388-406`; D-12]

### Activation Rollback Shape

```python
@transaction.atomic
def activate_term(term_id, *, actor, confirmation, acknowledge_warnings=False):
    term = AcademicTerm.objects.select_for_update().get(pk=term_id)
    # authorize, validate exact name, recompute blockers/warnings
    result = materialize_term(
        term=term,
        start=max(timezone.localdate(), term.start_date),
        days=get_policy("materialization_horizon_days"),
        allow_draft=True,
    )
    term.status = AcademicTerm.Status.ACTIVE
    term.save(update_fields=["status"])
    AuditLog.objects.create(
        actor=actor, event_type="term.activated",
        target_type="term", target_id=str(term.pk),
        payload={"before": "draft", "after": "active",
                 "sessions_created": result.created},
    )
    return term
```

Source pattern: service atomic writes and explicit AuditLog. [VERIFIED: `scheduling/services.py:272-289,504-558`; D-08/D-16]

## State of the Art

| Current | Phase 12 | Impact |
|---------|----------|--------|
| Boolean `is_active` plus `.first()` | State enum + SQL single-ACTIVE + resolver | Multiple active becomes DB-rejected. [VERIFIED: current model; D-01] |
| Import implicitly activates hardcoded term | Explicit writable Draft; lifecycle alone activates | Preparation cannot disrupt current operations. [VERIFIED: importer; D-05/D-06] |
| Materializer discovers active internally | Reusable explicit-term core; command active-only | Atomic activation without duplicate recurrence. [VERIFIED: materializer; D-08] |
| Reset/delete rollover | Close changes only term state | History stays intact. [VERIFIED: A4; D-03/D-04] |
| Date-only live and partial reports | Explicit ACTIVE live + selected single-term reports | No cross-term write/aggregate. [VERIFIED: D-09..D-12] |
| Weekly key lacks term | Term/week/department identity | Stored export attribution/collision safety. [VERIFIED: current model; D-12] |

**Deprecated/outdated:**

- `reset_term.DEFAULT_TERM` and importer default target must not remain implicit. [VERIFIED: `reset_term.py:34,54`; `import_offerings.py:80`]
- `order_by("-is_active")` must become status-aware/presentation ordering. [VERIFIED: `web/hr.py:166`; `web/faculty.py:836-837`]
- `.filter(is_active=True).first()` must be replaced by authoritative resolver. [VERIFIED: repository search]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | None. Recommendations derive from locked decisions and verified source. | — | — |

## Open Questions

No user decision is required before planning. Make stored-report backfill an explicit pre-migration verification: every legacy `WeeklyReport` must map to exactly one term before `term_id` becomes non-null. [RECOMMENDED: history-preserving migration gate]

The knowledge graph exists but is 377 hours stale and returned no nodes for three Phase 12 capability queries; all findings use live source/planning docs. [VERIFIED: `gsd-tools graphify status/query`, 2026-07-21]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | GSD tooling | Yes | v22.14.0 | — [VERIFIED: local probe] |
| Python 3.12 / `py -3.12` | Django migration/tests | No in this shell | — | Use established project Python 3.12 environment before verification claims. [VERIFIED: local probe returned `No installed Python found!`] |
| SQL Server + Driver 18 | Constraint/full tests | Not probeable without runtime connection | configured, runtime unknown | Use established MSSQL test environment; do not substitute SQLite for acceptance. [VERIFIED: `config/settings.py:99-126`] |
| New package | None | Not required | — | Existing stack covers phase. [VERIFIED: stack analysis] |

**Missing dependencies with no fallback:** Python 3.12 is unavailable here, so research could not execute Django tests or live migrations. Plan an environment preflight. [VERIFIED: local probe]

**Missing dependencies with fallback:** None; source/migration planning is complete. [VERIFIED: task scope]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Django `TestCase`, `TransactionTestCase`, `SimpleTestCase` from Django 6.0.6. [VERIFIED: `scheduling/tests.py:174-175`; `requirements.txt`] |
| Config | `config/settings.py`, SQL Server test DB with `DB_TEST_NAME`. [VERIFIED: `config/settings.py:99-126`] |
| Quick run | `py -3.12 manage.py test scheduling.tests_term_lifecycle web.tests_term_lifecycle web.tests_term_reporting -v 2` |
| Full suite | `py -3.12 manage.py test` in established Python/MSSQL environment; STATE records 994 green before Phase 12. [VERIFIED: `.planning/STATE.md`] |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| A4 / D-01 | Migration maps active/inactive; DB rejects second ACTIVE and invalid date order. | migration/constraint | `py -3.12 manage.py test scheduling.tests_term_lifecycle.TermConstraintTests -v 2` | No - Wave 0 |
| A4 / D-02/D-03 | Close eligibility, reopen-to-Draft, reason and exact confirmation. | service integration | `py -3.12 manage.py test scheduling.tests_term_lifecycle.TermTransitionTests -v 2` | No - Wave 0 |
| A4 / D-05/D-08/D-16 | Draft import creates schedules only; activation uses horizon; injected failure rolls sessions/state/audit back. | command/transaction | `py -3.12 manage.py test scheduling.tests_term_lifecycle.ActivationMaterializationTests -v 2` | No - Wave 0 |
| A4 / D-04 | Archived writes reject across attendance, IFO services, commands, Admin. | integration/coupling | `py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeTests web.tests_term_lifecycle -v 2` | No - Wave 0 |
| A4 / D-06 | Activation refuses another ACTIVE; DB race backstop gives controlled error. | transaction/constraint | `py -3.12 manage.py test scheduling.tests_term_lifecycle.SingleActiveTests -v 2` | No - Wave 0 |
| A4 / D-07 | Create validates unique/order/non-overlap and makes blank Draft. | service/view | `py -3.12 manage.py test scheduling.tests_term_lifecycle.TermCreateTests web.tests_term_lifecycle.TermCreateViewTests -v 2` | No - Wave 0 |
| A4 / D-09 | Live surfaces, sweep, and assignment ignore same-date archived fixtures. | view/job | `py -3.12 manage.py test web.tests_term_lifecycle.ActiveTermOperationalScopeTests scheduling.tests_term_lifecycle.ActiveTermJobScopeTests -v 2` | No - Wave 0 |
| A4 / D-10..D-12 | IFO/Dean/HR list, drilldown, pagination, CSV/PDF preserve term; ranges clamp; aggregates do not cross. | view/aggregate/export | `py -3.12 manage.py test web.tests_term_reporting scheduling.tests_reporting -v 2` | No - Wave 0; existing suites extend |
| IFO-04 / D-13..D-15 | IFO/superuser access, Dean denial, preflight blockers/warnings/ack, audit payload. | security/view | `py -3.12 manage.py test web.tests_term_lifecycle.TermAuthorityAndPreflightTests -v 2` | No - Wave 0 |
| D-12 stored reports | Backfill, term/week/dept idempotency, path/latest/list/download. | migration/model/service/view | `py -3.12 manage.py test ops.tests_reports web.tests_term_reporting.WeeklyReportTermTests -v 2` | Existing files extend |

### Sampling Rate

- **Per task commit:** narrow touched test classes plus `py -3.12 manage.py check`. [RECOMMENDED: existing test organization]
- **Per wave merge:** term lifecycle/report files plus `ops.tests_reports`, `verification.tests`, and modified job/report/import suites. [RECOMMENDED: coupling breadth]
- **Phase gate:** full MSSQL suite, `makemigrations --check --dry-run`, `sqlmigrate`, and live constraint smoke before `/gsd-verify-work`. [VERIFIED: SQL Server-only constraint]

### Wave 0 Gaps

- [ ] `scheduling/tests_term_lifecycle.py` - state constraints, transitions, activation rollback, commands, freeze matrix, jobs.
- [ ] `web/tests_term_lifecycle.py` - IFO authority, create/preflight/actions, confirmation, warnings, live scope, archived POST refusal.
- [ ] `web/tests_term_reporting.py` - selector/range/link/export contracts for IFO/Dean/HR and stored reports.
- [ ] Extend `ops/tests_reports.py` - term identity, generation, paths, notification, latest/list.
- [ ] Extend `scheduling/tests.py`, `verification/tests.py`, `web/tests_hr.py`, `web/tests_dean_reporting.py`, `web/tests_ifo_utilization.py`, and import tests where signatures change.
- [ ] Add source/coupling guard inventorying direct active lookups and known session-write entry points so future bypasses fail tests. [RECOMMENDED: analogous project coupling tests]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes | Existing Django login/session auth. [VERIFIED: role decorator in `web/ifo.py:57-76`] |
| V3 Session Management | Yes, unchanged | Keep Django CSRF/session; report term remains GET, not session. [VERIFIED: D-10] |
| V4 Access Control | Yes | IFO/superuser auth in view and transition service; Dean/others denied; Dean department scope retained. [VERIFIED: D-13; `web/dean.py:147-325`] |
| V5 Input Validation | Yes | Validate term ids, names, inclusive overlap/order, exact confirmation, reasons, warning acknowledgment, state, bounded ranges. [VERIFIED: D-07/D-14/D-15] |
| V6 Cryptography | No new crypto | Confirmation is friction, not secret; Python equality plus existing CSRF, no custom signing. [RECOMMENDED: threat model] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Forged lifecycle POST by non-IFO | Elevation | `ifo_required` plus service actor authorization; explicit superuser. [VERIFIED: D-13] |
| Stale preflight then changed DB state | Tampering / TOCTOU | Re-fetch/lock/recompute in atomic; display preflight is never authority. [VERIFIED: `web/ifo.py:582-605`; D-16] |
| Simultaneous activation | Tampering | Transaction check plus filtered unique constraint; friendly `IntegrityError`. [VERIFIED: D-01/D-16] |
| Direct archived session id to mutation endpoint | Tampering | Resolve through ACTIVE/writable predicate before validation/audit/status write. [VERIFIED: D-04] |
| Term dropped on report/export | Information Disclosure | Mandatory term in aggregate service and GET propagation; Dean department scope independent. [VERIFIED: D-09..D-12] |
| Consequential action repudiated | Repudiation | Required reason where locked, exact confirmation, actor/before/after AuditLog inside transaction. [VERIFIED: D-14/D-16] |
| Legacy destructive command against archive | Tampering / Data Loss | Remove default, explicit target, archive guard, keep out of rollover/UI. [VERIFIED: A4/D-04] |
| Large mutation hits SQL limits | DoS / partial failure | Materialize querysets, small batches, atomic transition. [VERIFIED: MSSQL discipline] |

## Sources

### Primary (HIGH confidence)

- `.planning/phases/12-term-lifecycle/12-CONTEXT.md` - locked D-01..D-16.
- `.planning/ROADMAP.md` Phase 12 - goal, A4 mapping, success criteria.
- `docs/AUDIT-2026-07-19.md` A4 - destructive rollover finding.
- `docs/PLAN-2026-07-20-post-audit-milestone.md` Phase 12 - sequencing/acceptance.
- `scheduling/models.py`, `scheduling/management/commands/*.py`, `scheduling/jobs.py`, `scheduling/services.py`, `scheduling/suspensions.py` - domain/mutation seams.
- `web/ifo.py`, `web/dean.py`, `web/hr.py`, `web/faculty.py`, `web/checker.py`, `web/guard.py`, `web/scan.py`, `web/reporting_common.py` - role/report/live behavior.
- `scheduling/reporting.py`, `ops/models.py`, `ops/reports.py` - aggregate/stored report identity.
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md` - service, audit, MSSQL, risks.
- `requirements.txt`, `config/settings.py` - pinned stack and policy.

### Secondary (MEDIUM confidence)

- `.planning/STATE.md` - prior decisions and last suite result.
- Knowledge graph status only; stale/no results, so no graph finding was used.

### Tertiary (LOW confidence)

- None. No web or training-only claim was used.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - exact pins/config in repo; no new dependency.
- Architecture: HIGH - follows locked D-01..D-16 and current transaction/audit conventions.
- Pitfalls: HIGH - each tied to current symbol/query or locked invariant.
- Runtime verification: MEDIUM - source is current, but Python/SQL Server unavailable here, so tests/migrations were not run.

**Research date:** 2026-07-21
**Valid until:** 2026-08-20 (re-scan if other scheduling/reporting changes land first)

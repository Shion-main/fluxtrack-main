# Session Workflow Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce unnecessary operator and faculty actions from schedule import through session completion while preserving server authority, independent verification, auditability, and accurate attendance history.

**Architecture:** Keep the existing pure-decision/service/apply separation, but introduce one canonical operational lifecycle around term readiness, session start, and session completion. Make routine setup a single guided operation with a dry-run checkpoint, make online-duty assignment idempotently follow materialization, and treat exceptional corrections and room conflicts as separate paths rather than normal meet steps.

**Tech Stack:** Django 6, Django ORM, Microsoft SQL Server, server-rendered templates, HTMX, APScheduler, existing `AuditLog`, `Session`, `Schedule`, and `Assignment` models.

---

## Audit baseline — read-only, 2026-08-24

### Scope and terminology

This repository does not contain `Player`, `Athlete`, or `Meet` entities. The equivalent lifecycle is:

`faculty/schedule` -> recurring `Schedule` -> dated `Session` -> faculty/checker attendance events -> reporting/term archive.

Enrollment is represented only by `Schedule.enrolled_count`; there is no per-student participant roster. If “players” and “meets” refer to a different product workflow, this plan must be re-scoped before implementation.

### Current process traced in code

1. IFO creates a blank Draft term with a preflight screen and exact-name confirmation (`web/ifo_terms.py:82-126`, `scheduling/term_lifecycle.py:98-152`).
2. IFO uploads a registrar file, selects the Draft term, reviews reconciliation, then separately commits the staged file (`web/ifo.py:1415-1531`, `ops/import_staging.py`, `scheduling/management/commands/import_offerings.py:124-222`).
3. IFO activates the Draft with another preflight, exact-name confirmation, warning acknowledgement, and an activation transaction that materializes the configured horizon (`web/ifo_terms.py:173-225`, `scheduling/term_lifecycle.py:341-396`).
4. IFO posts floor duty and/or online duty assignments. Creating online duty immediately invokes round-robin assignment across dates (`web/ifo.py:1572-1666`, `verification/services.py:76-153`).
5. A scheduled job independently materializes sessions every six hours; an explicit management command and the single-schedule UI can also materialize them (`scheduling/management/commands/runscheduler.py:44-47`, `:120-155`, `web/ifo.py:2676-2735`).
6. F2F/Blended faculty scan once to start and re-scan to finish. Wrong-room, occupied-room, and early-end outcomes add a signed confirmation step (`web/scan.py:115-234`, `scheduling/resolver.py:55-116`).
7. A Checker separately scans/verifies the room. Offline scans add a later replay step, although that is justified by unreliable connectivity (`web/checker.py:304-366`, `:492-647`).
8. Online sessions have two competing start paths: Faculty pastes and verifies a Teams link, or a Checker’s online Verify activates the scheduled session. Faculty then explicitly checks out (`web/faculty.py:697-879`, `web/checker.py:649-696`).
9. A five-minute sweep marks still-scheduled sessions Absent after grace; it does not normally complete active sessions or release rooms (`scheduling/jobs.py:48-122`, `ops/occupancy.py:19-22`).
10. IFO manually releases a room only for an active occupancy conflict; this is an exception path, not normal session completion (`web/ifo.py:907-1022`, `ops/occupancy.py:33-60`).
11. Term closure requires the term end date, no active sessions, and another confirmation/reason flow (`scheduling/term_lifecycle.py:168-181`, `:269-302`).

### Findings

| ID | Severity | Finding | Assessment |
|---|---|---|---|
| F1 | High | Setup is split across Draft creation, import preview, import commit, activation preflight, activation confirmation, duty posting, and background materialization. | The safety checkpoints are individually defensible, but the operator must understand several internal phases before the system is ready. Consolidate the routine path into one “Prepare term” workflow while retaining one meaningful dry-run review. |
| F2 | High | The same session materialization capability is reached through activation, the six-hour scheduler, the explicit command, and single-schedule creation. | The service is idempotent, so this is not necessarily a data-corruption defect; it is duplicated operational knowledge and creates ambiguity about which action is required. Keep one canonical service and make the other callers internal/recovery paths. |
| F3 | High | Online-duty assignment is a separate operational concern and is not wired into the scheduler’s materialization job. Creating an assignment assigns existing horizon sessions, but later newly materialized online sessions can remain unassigned until another assignment/command path runs. | This is both friction and a workflow gap. Assignment should be reconciled automatically after materialization; the IFO should handle exceptions rather than remember a second command. |
| F4 | High | Online sessions have two start semantics: Faculty self-start (`ONLINE_SELF`) and Checker Verify (`ONLINE_MANUAL`), both able to move `SCHEDULED` to `ACTIVE`. | This is not automatically wrong, but it makes the canonical process unclear and duplicates state-transition logic. Choose one primary path and retain the other only as an explicitly labelled recovery/exception path. |
| F5 | Medium | Normal completion depends on a human end action: F2F/Blended re-scan or Online checkout. If forgotten, the session can stay `ACTIVE`, which also blocks term closure. | Decide whether actual end must always be manually captured. A lower-friction policy is scheduled-end fallback plus an explicit early-end action; retain manual completion for cases where exact actual end is required. |
| F6 | Medium | The Checker step is an additional human action after faculty check-in. | This is not proven redundant: independent Checker verification is the stated trust model and supports coverage metrics. Do not remove it without changing the product promise and reporting semantics. Optimize the Checker queue/assignment instead. |
| F7 | Medium | There are multiple schedule-entry paths: browser bulk import, CLI import, individual schedule creation/edit, and a development-only `seed_term` reshaper. | Keep bulk import as the production source of truth; label individual schedule operations as exceptions and keep `seed_term` development-only. Do not make operators choose among equivalent paths for routine setup. |
| F8 | Low | `docs/USER_FLOWS.md` explicitly says it is superseded and still describes old stubbed surfaces, while `docs/PROGRESS.md` describes the later completed system. | Documentation drift makes the process look less coherent than the current implementation. Refresh the canonical workflow documentation after the process decision. |

### What is already efficient and should be preserved

- Pure resolvers keep decisions separate from writes and are shared by live scans and the sweep (`scheduling/resolver.py:39-52`, `scheduling/jobs.py:89-116`).
- Transaction boundaries protect anchor/sibling updates and attendance writes (`web/scan.py:144-154`, `:163-186`, `web/checker.py:340-356`).
- Signed confirmation tokens, server-side re-gating, cache idempotency, durable offline replay receipts, and audit logs are backend safeguards, not unnecessary user workflow steps.
- The import reconciliation report is valuable; the change should remove repeated navigation/confirmation, not remove the dry-run evidence that proves rows were not silently dropped.

## Target operating model

The recommended routine path is:

1. IFO opens **Prepare term**, enters term dates, uploads the registrar file, reviews one reconciliation/readiness summary, and confirms activation once.
2. The system commits schedules, materializes the configured horizon, and reconciles online-duty ownership in one idempotent orchestration boundary.
3. IFO posts or edits duty coverage only when the readiness summary reports missing floor or online coverage.
4. F2F/Blended: Faculty starts with one scan; Checker verifies once; completion follows the agreed end policy.
5. Online: one primary start/verification path is shown. The alternate path is retained only as a named recovery path if the product owner confirms it is needed.
6. The sweep handles only unstarted no-shows and operational alerts. It must not be presented as a normal “end meet” action.
7. IFO corrections, room release, suspension, and term closure remain exceptional/admin paths with their current audit and authorization requirements.

## Implementation plan

### Task 1: Lock the lifecycle contract before changing behavior

**Files:**
- Modify: `PRODUCT.md`
- Modify: `FluxTrack_SRS.md`
- Modify: `docs/FACULTY_USER_FLOW.md`
- Modify: `docs/ARCHITECTURE.md`
- Create: `docs/SESSION_WORKFLOW_CONTRACT.md`
- Test: `scheduling/tests_e2e.py` (scenario names and acceptance notes only in this task)

- [ ] **Step 1: Record the domain vocabulary.** State that the current system tracks faculty/class sessions, not individual players or meets, and define `Schedule`, `Session`, `ACTIVE`, `COMPLETED`, `ABSENT`, and `CANCELLED`.
- [ ] **Step 2: Choose the end policy.** Recommended default: a session may be explicitly completed early, but an active session receives a scheduled-end fallback so forgotten checkout does not block term closure; preserve actual user-entered end time when available and record the fallback method.
- [ ] **Step 3: Choose the online primary path.** Recommended default: Faculty starts the Teams session and Checker verifies it; keep Checker “verify and start if needed” only as a recovery path with explicit copy.
- [ ] **Step 4: Define the normal versus exception paths.** Normal: prepare term, coverage readiness, start, verify, complete. Exception: room conflict, wrong room, early end, suspension, correction, online recovery, and manual room release.
- [ ] **Step 5: Add acceptance scenarios to `scheduling/tests_e2e.py` without changing production code.** Scenarios must cover one imported term becoming ready, one F2F session, one online session, a forgotten checkout fallback, an online recovery start, and term closure after all active sessions are resolved.
- [ ] **Step 6: Run `py -3.12 manage.py test scheduling.tests_e2e --verbosity 2`.** Expected: existing tests pass; new contract scenarios are initially marked as pending only if the project’s test convention allows that, otherwise defer executable assertions to the implementation tasks.

### Task 2: Add a baseline measurement and readiness report

**Files:**
- Modify: `ops/models.py` only if a durable workflow-run record is required after the measurement design is approved
- Modify: `ops/jobrun.py` if orchestration runs need to reuse existing job telemetry
- Create: `docs/WORKFLOW_BASELINE-2026-08-24.md`
- Test: `ops/tests.py` or a new `ops/tests_workflow_baseline.py`

- [ ] **Step 1: Use existing `AuditLog` events to measure the current path.** Count `term.created`, `schedule.imported`, `term.activated`, `assignment.created`, `session.checked_in`, `checker.verified`, `session.checked_out`, `session.online_checked_out`, `session.marked_absent`, and `session.room_released` over a representative period.
- [ ] **Step 2: Record operator touchpoints, not just database writes.** Capture clicks/requests required for term preparation, the number of unassigned online sessions after materialization, active sessions remaining after scheduled end, and median time from scheduled start to completion.
- [ ] **Step 3: Keep this read-only at first.** Do not add a new model if the current audit data can answer the baseline; add durable telemetry only when a missing metric is demonstrated.
- [ ] **Step 4: Add a regression check for the readiness summary.** It must identify missing schedules, unassigned online sessions, uncovered Checker floors, and active sessions past scheduled end without mutating attendance rows.
- [ ] **Step 5: Run `py -3.12 manage.py test ops --verbosity 2`.** Expected: existing ops tests pass and the baseline/readiness query has no write side effects.

### Task 3: Consolidate routine term setup behind one orchestration boundary

**Files:**
- Modify: `scheduling/term_lifecycle.py`
- Modify: `web/ifo_terms.py`
- Modify: `web/ifo.py`
- Modify: `ops/import_staging.py` only for lifecycle cleanup if needed
- Modify: `scheduling/management/commands/import_offerings.py` only to keep the CLI as a thin adapter
- Modify: `templates/ifo/term_form.html`
- Modify: `templates/ifo/term_action.html`
- Modify: `templates/ifo/import.html`
- Modify: `templates/ifo/_import_panel.html`
- Create: `scheduling/term_setup.py`
- Test: `scheduling/tests_term_lifecycle.py`
- Test: `scheduling/tests_import.py`
- Test: relevant `web/tests_*.py` for IFO term/import routes

- [ ] **Step 1: Define `prepare_term(...)` as the single routine orchestration service.** It must validate the term, stage and reconcile the file, commit schedules, materialize the configured horizon, and return a readiness result. It must remain transactional for database writes and preserve the current staged-file safety boundary.
- [ ] **Step 2: Preserve one human review checkpoint.** The operator must still see reconciliation totals, typo/unassigned rooms, email-less faculty, schedule count, materialized-session count, and missing duty coverage before activation is confirmed.
- [ ] **Step 3: Reduce repeated confirmations.** Keep one explicit activation confirmation for the combined routine flow. Preserve separate term creation/import screens only for recovery or advanced operators, not as the default route.
- [ ] **Step 4: Keep CLI imports as an adapter.** `import_offerings` should call the same service/reconciliation contract rather than becoming a second implementation of readiness behavior.
- [ ] **Step 5: Make the post-import state obvious.** After success, show “ready for operations” or specific blockers; do not require the operator to infer whether activation, materialization, or assignment still needs another action.
- [ ] **Step 6: Run `py -3.12 manage.py test scheduling.tests_term_lifecycle scheduling.tests_import web.tests_term_lifecycle web.tests_schedule_ops --verbosity 2`.** Expected: the combined flow is atomic on failure, idempotent on retry, and does not delete existing term data.

### Task 4: Make materialization and online-duty assignment self-reconciling

**Files:**
- Modify: `scheduling/materialization.py`
- Modify: `verification/services.py`
- Modify: `scheduling/management/commands/runscheduler.py`
- Modify: `scheduling/management/commands/materialize_sessions.py`
- Modify: `web/ifo.py`
- Test: `verification/tests.py`
- Test: `scheduling/tests_term_lifecycle.py`
- Test: scheduler wiring tests under `scheduling/`

- [ ] **Step 1: Keep `materialize_term` as the only session-creation authority.** Activation, manual schedule creation, the CLI, and the scheduler may call it, but none should duplicate its rules.
- [ ] **Step 2: Reconcile online ownership immediately after successful materialization.** For each newly materialized date, call the idempotent assignment service using the active online-duty roster; leave sessions unassigned and notify IFO when no eligible Checker exists.
- [ ] **Step 3: Make retries safe.** Existing owned sessions must not reshuffle, duplicate notifications, or create duplicate audit records.
- [ ] **Step 4: Remove the need for a routine manual `assign_online` command.** Keep the command for repair/recovery and diagnostics, but document it as non-routine.
- [ ] **Step 5: Run `py -3.12 manage.py test verification.tests scheduling.tests_term_lifecycle --verbosity 2`.** Expected: materialization after duty creation assigns eligible sessions; materialization after duty creation does not disturb existing ownership; no-duty cases remain visible as unassigned.

### Task 5: Unify session start and completion writes

**Files:**
- Create: `scheduling/session_lifecycle.py`
- Modify: `web/scan.py`
- Modify: `web/faculty.py`
- Modify: `web/checker.py`
- Modify: `web/ifo.py`
- Modify: `scheduling/merge.py`
- Modify: `scheduling/models.py` only if the approved end-policy requires an explicit completion method field
- Create: migration under `scheduling/migrations/` only if the model change is approved
- Test: `web/tests_merge_scan.py`
- Test: `web/tests_merge_checker.py`
- Test: `web/tests_faculty_online.py`
- Test: `verification/tests.py`
- Test: `scheduling/tests_merge_sweep.py`

- [ ] **Step 1: Define canonical service operations.** Use explicit operations such as `start_session`, `verify_session`, `complete_session`, `mark_no_show`, and `recover_online_start`; each operation must re-fetch and re-gate the current row before writing.
- [ ] **Step 2: Move duplicated status/audit/merge behavior into the service.** Faculty scan, Faculty online start, Checker online Verify, and Checker room actions should become thin adapters that pass evidence and actor context.
- [ ] **Step 3: Preserve evidence distinctions.** Keep the real check-in method (`QR_SCAN`, `MANUAL_CODE`, `ONLINE_SELF`, `ONLINE_MANUAL`, `FORCE_HANDOVER`, `MERGED`) and do not mark a session Checker-verified merely because Faculty started it.
- [ ] **Step 4: Preserve transaction boundaries.** Anchor state changes, merged siblings, and their audit events must still commit or roll back together.
- [ ] **Step 5: Implement the approved completion policy.** If scheduled-end fallback is selected, make it explicit, idempotent, auditable, excluded from early-end calculations, and safe for term closure. Do not make room release timer-driven; room occupancy and attendance completion remain separate concerns.
- [ ] **Step 6: Run `py -3.12 manage.py test web.tests_merge_scan web.tests_merge_checker web.tests_faculty_online verification.tests scheduling.tests_merge_sweep --verbosity 2`.** Expected: every existing state-transition invariant remains green, including no false verification, no sibling half-flips, no late start after Absent, and no unauthorized completion.

### Task 6: Simplify the operator and faculty surfaces around the canonical lifecycle

**Files:**
- Modify: `templates/ifo/term_form.html`
- Modify: `templates/ifo/term_action.html`
- Modify: `templates/ifo/import.html`
- Modify: `templates/ifo/_import_panel.html`
- Modify: `templates/ifo/assignments.html`
- Modify: `templates/faculty/online.html`
- Modify: `templates/faculty/_online_start.html`
- Modify: `templates/checker/online_list.html`
- Modify: `templates/checker/online_open.html`
- Modify: `templates/faculty/schedule.html` and/or current completion partials as needed
- Modify: `docs/FACULTY_USER_FLOW.md`
- Create: `docs/SESSION_OPERATING_PROCEDURE.md`
- Test: route/UI tests covering IFO setup, Faculty scan/online, Checker floor/online, and term close

- [ ] **Step 1: Make routine setup a single visible journey.** Hide internal recovery commands from the primary IFO navigation and surface readiness blockers in the same screen as the activation result.
- [ ] **Step 2: Make the primary online path unambiguous.** Show one primary action; label the alternate path as recovery only if Task 1 approves keeping it.
- [ ] **Step 3: Explain completion semantics.** Tell Faculty whether the session ends automatically at scheduled end, requires a final scan, or needs an explicit early-end action.
- [ ] **Step 4: Keep exceptions discoverable but separate.** Wrong room, occupied room, suspension, correction, and manual release should not appear as routine steps in the happy path.
- [ ] **Step 5: Run the focused web tests and a manual browser pass.** Expected: a first-time IFO can prepare a term without consulting management-command documentation; Faculty and Checker can identify the next required action from the page itself.

### Task 7: Verify efficiency and remove stale process documentation

**Files:**
- Modify: `docs/PROGRESS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `README.md`
- Modify: `docs/FACULTY_USER_FLOW.md`
- Mark as superseded or replace: `docs/USER_FLOWS.md`
- Create: `docs/WORKFLOW_REVIEW-2026-08-24.md`

- [ ] **Step 1: Re-run the baseline metrics from Task 2 after implementation.** Compare setup requests, unassigned online sessions, active-past-end sessions, and median completion latency.
- [ ] **Step 2: Verify no safety regression.** Run `py -3.12 manage.py check`, the focused workflow tests, and then `py -3.12 manage.py test --verbosity 1` against the configured SQL Server test database.
- [ ] **Step 3: Verify migrations and deployment artifacts.** Run `py -3.12 manage.py makemigrations --check`, `py -3.12 manage.py migrate --check`, and the documented production checks without changing production data.
- [ ] **Step 4: Record the before/after process.** The review must list the number of routine human actions removed, which actions remain intentionally, and which exception paths are unchanged.
- [ ] **Step 5: Stop for product review if the measured result does not reduce operator effort.** Do not merge a refactor that only moves complexity between screens or services.

## Self-review checklist

- [ ] The plan treats the absence of individual player/meet entities as an explicit scope condition.
- [ ] The import reconciliation checkpoint remains; only repeated setup friction is removed.
- [ ] Independent Checker verification remains unless the product promise and reporting model are deliberately changed.
- [ ] Room release is not silently converted into timer-based release.
- [ ] Online self-start and Checker verification have one documented primary path and one documented fallback, if both remain.
- [ ] Session completion and no-show marking are separate, auditable transitions.
- [ ] Existing idempotency, audit, authorization, SQL Server cursor safeguards, and merged-sibling invariants remain test-covered.
- [ ] No source-code implementation was performed during this audit.


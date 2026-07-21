---
phase: 12
slug: term-lifecycle
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-21
---

# Phase 12 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django 6.0.6 `TestCase`, `TransactionTestCase`, and `SimpleTestCase` |
| **Config file** | `config/settings.py` with the SQL Server test database selected by `DB_TEST_NAME` |
| **Quick run command** | `py -3.12 manage.py test scheduling.tests_term_lifecycle web.tests_term_lifecycle web.tests_term_reporting -v 2` |
| **Full suite command** | `py -3.12 manage.py test` |
| **Estimated runtime** | Establish during Wave 0 in the configured Python/MSSQL environment |

---

## Sampling Rate

- **After every task commit:** Run the narrow test class or module named by the task plus `py -3.12 manage.py check`.
- **After every plan wave:** Run the Phase 12 modules plus `ops.tests_reports`, `verification.tests`, and every modified import/job/report suite.
- **Before `/gsd-verify-work`:** Run the full MSSQL suite, `py -3.12 manage.py makemigrations --check --dry-run`, review `sqlmigrate` output, and smoke-test the live constraints.
- **Max feedback latency:** Record the baseline during Wave 0; keep task-level checks narrow enough for immediate iteration.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 12-W0-01 | TBD | 0 | A4 / D-01 | T-12-01 | Invalid date order and a second ACTIVE term are rejected | migration/constraint | `py -3.12 manage.py test scheduling.tests_term_lifecycle.TermConstraintTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-02 | TBD | 0 | A4 / D-02–D-03 | T-12-02 | Close and reopen re-check locked state, exact confirmation, reason, and eligibility | service integration | `py -3.12 manage.py test scheduling.tests_term_lifecycle.TermTransitionTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-03 | TBD | 0 | A4 / D-05, D-08, D-16 | T-12-03 | Failed activation rolls back materialized sessions, state, and audit together | command/transaction | `py -3.12 manage.py test scheduling.tests_term_lifecycle.ActivationMaterializationTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-04 | TBD | 0 | A4 / D-04 | T-12-04 | Archived-term writes are refused across services, commands, attendance, and Admin | integration/coupling | `py -3.12 manage.py test scheduling.tests_term_lifecycle.ArchiveFreezeTests web.tests_term_lifecycle -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-05 | TBD | 0 | A4 / D-06–D-07 | T-12-01 | Draft creation validates uniqueness/order/non-overlap and activation cannot race a current ACTIVE term | transaction/view | `py -3.12 manage.py test scheduling.tests_term_lifecycle.SingleActiveTests scheduling.tests_term_lifecycle.TermCreateTests web.tests_term_lifecycle.TermCreateViewTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-06 | TBD | 0 | A4 / D-09 | T-12-05 | Live surfaces and jobs select only the ACTIVE term even with same-date archived fixtures | view/job | `py -3.12 manage.py test web.tests_term_lifecycle.ActiveTermOperationalScopeTests scheduling.tests_term_lifecycle.ActiveTermJobScopeTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-07 | TBD | 0 | A4 / D-10–D-12 | T-12-06 | Report selection, drilldown, pagination, CSV/PDF, ranges, and aggregates preserve exactly one term | reporting/export | `py -3.12 manage.py test web.tests_term_reporting scheduling.tests_reporting -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-08 | TBD | 0 | IFO-04 / D-13–D-15 | T-12-02, T-12-07 | IFO/superuser authority, Dean denial, preflight, acknowledgements, and audit payloads are enforced | security/view | `py -3.12 manage.py test web.tests_term_lifecycle.TermAuthorityAndPreflightTests -v 2` | ❌ W0 | ⬜ pending |
| 12-W0-09 | TBD | 0 | A4 / D-12 | T-12-06 | Stored reports are idempotent by term/week/department and retain term-aware paths and downloads | migration/model/service/view | `py -3.12 manage.py test ops.tests_reports web.tests_term_reporting.WeeklyReportTermTests -v 2` | ⚠ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scheduling/tests_term_lifecycle.py` — constraints, transitions, activation rollback, command guards, archive freeze matrix, and active-term jobs.
- [ ] `web/tests_term_lifecycle.py` — IFO authority, create/preflight/action confirmations, warnings, live scope, and archived POST refusal.
- [ ] `web/tests_term_reporting.py` — selector, range, link, pagination, CSV/PDF, and stored-report term contracts for IFO, Dean, and HR.
- [ ] Extend `ops/tests_reports.py` — term identity, generation, paths, notifications, latest/list, and legacy backfill behavior.
- [ ] Extend affected cases in `scheduling/tests.py`, `verification/tests.py`, `web/tests_hr.py`, `web/tests_dean_reporting.py`, `web/tests_ifo_utilization.py`, and import tests when signatures change.
- [ ] Add a source/coupling guard that inventories direct active-term lookups and known session-write entry points so future archive-guard bypasses fail tests.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SQL Server filtered uniqueness and lifecycle check constraints apply to representative legacy rows | A4 / D-01, D-06 | Requires the configured MSSQL instance and production-shaped legacy data | Run migration rehearsal on a restored/sanitized database, inspect mapped states, execute `sqlmigrate`, attempt a second ACTIVE insert and invalid date range, and confirm both fail without data loss. |
| Destructive legacy term reset is absent from the rollover UI and documented as break-glass only | A4 / D-04 | Operator-facing workflow and operational documentation need a human safety review | Walk the IFO term-management UI and runbook; confirm close/create/activate never calls `reset_term` and the command requires an explicit target plus archived-term refusal. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verification or Wave 0 dependencies.
- [ ] Sampling continuity: no three consecutive tasks without automated verification.
- [ ] Wave 0 covers all missing references.
- [ ] No watch-mode flags.
- [ ] Task-level feedback latency is measured and acceptable.
- [ ] `nyquist_compliant: true` is set in frontmatter.

**Approval:** pending

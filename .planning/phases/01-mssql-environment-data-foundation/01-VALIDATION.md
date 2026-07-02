---
phase: 1
slug: mssql-environment-data-foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-02
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (`manage.py test`), `unittest`-style — matches existing `scheduling/tests.py` |
| **Config file** | none — Django default discovery (`<app>/tests.py`); test DB `test_fluxtrack` on SQL Server |
| **Quick run command** | `py -3.12 manage.py test <module>.<Class> -v 2` |
| **Full suite command** | `py -3.12 manage.py test` |
| **Estimated runtime** | ~30–90 seconds (DB-backed tests build `test_fluxtrack` on SQL Server) |
| **Precondition** | dev login has `CREATE DATABASE` (server role `dbcreator`); SQL Server instance default collation is `_CI_` |

---

## Sampling Rate

- **After every task commit:** Run the specific new test class touched (`py -3.12 manage.py test <module>.<Class>`)
- **After every plan wave:** Run `py -3.12 manage.py test` (full suite on the SQL Server test DB)
- **Before `/gsd:verify-work`:** Full suite green on MSSQL + a manual `migrate` + `seed_demo` + R3 import cold run on a fresh `fluxtrack` DB
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-xx | 01 | 1 | ENV-01 | integration (smoke) | `py -3.12 manage.py migrate` then `py -3.12 manage.py test` | ❌ W0 | ⬜ pending |
| 1-01-xx | 01 | 1 | ENV-01 | integration | `py -3.12 manage.py test scheduling.tests.DatetimeRoundTripTests` | ❌ W0 | ⬜ pending |
| 1-01-xx | 01 | 1 | ENV-01 | integration | `py -3.12 manage.py test campus.tests.CollationRoundTripTests` | ❌ W0 | ⬜ pending |
| 1-01-xx | 01 | 1 | ENV-02 | integration (parity) | `py -3.12 manage.py test scheduling.tests.R3ParityTests` | ❌ W0 | ⬜ pending |
| 1-01-xx | 01 | 1 | ENV-01 | unit (no DB, regression) | `py -3.12 manage.py test scheduling.tests.FacultyResolverTests` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs finalized by the planner; each success criterion maps to at least one automated test class above.*

---

## Wave 0 Requirements

- [ ] `scheduling/tests.py` (or `scheduling/tests/`) — add `DatetimeRoundTripTests` (`TestCase`) and `R3ParityTests` (`TransactionTestCase`, skip-if-CSV-missing) covering ENV-01 datetime round-trip + ENV-02 parity
- [ ] `campus/tests.py` — add `CollationRoundTripTests` (`TestCase`) covering tokens (CS) + emails (CI). No `campus/tests.py` exists today.
- [ ] Shared minimal fixtures — small factory helpers to build a Room/Floor/Term/Schedule/faculty without the full seed; consider a committed synthetic R3 fixture CSV for CI
- [ ] Framework install: none needed — Django test runner present. New requirement is the **SQL Server test DB grant** (`CREATE DATABASE`) + a `_CI_` instance default collation.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| App boots and serves every existing surface on `DB_ENGINE=mssql` | ENV-01 | Full-surface smoke needs a running server + browser; not unit-testable | Cold `migrate` + `seed_demo` on fresh `fluxtrack` DB, `runserver`, hit dev-login + each role landing surface |
| R3 parity on the **real** registrar CSV | ENV-02 | Real numbers (17/10/15/18/18) come from gitignored PII CSV under `/data/raw/`; automated test skips if absent | Run `import_offerings --building R --floor 3` + `materialize_sessions --days 7` against real CSV locally, confirm 17/10/15/18/18 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`campus/tests.py`, new test classes)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

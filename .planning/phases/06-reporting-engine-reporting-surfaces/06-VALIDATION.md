---
phase: 06
slug: reporting-engine-reporting-surfaces
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-15
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (unittest-based) — NOT pytest |
| **Config file** | none — Django discovers `<app>/tests*.py` |
| **Quick run command** | `py -3.12 manage.py test <app> -v1` (use the full `C:/Users/joshu_mnu8z3u/AppData/Local/Programs/Python/Python312/python.exe manage.py test ...` if bare `py` lacks Django) |
| **Full suite command** | `py -3.12 manage.py test -v1` |
| **Estimated runtime** | ~30–90 seconds (creates a test DB on MSSQL LocalDB) |

---

## Sampling Rate

- **After every task commit:** Run `py -3.12 manage.py test scheduling -v1` (or the app touched by the task)
- **After every plan wave:** Run the full suite `py -3.12 manage.py test -v1`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

> The planner fills one row per task. The pure aggregate layer (RESEARCH: `scheduling/reporting.py`)
> is the highest-value unit-test target — every aggregate must have a direct unit test with fixed
> Session fixtures, independent of any view. RPT-05 per-card isolation needs a test that injects a
> failing aggregate and asserts the other cards still render.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | RPT-01 | — | Pure aggregate returns correct scheduled/held/absent/verified counts from fixed Session fixtures | unit | `py -3.12 manage.py test scheduling.tests_reporting -v1` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scheduling/tests_reporting.py` — unit-test stubs for the pure aggregate layer (RPT-01/04/05)
- [ ] Shared Session/Department fixtures for a known term window (reuse the JOB-02 held/absent truth, incl. a MERGED sibling and a verified-by-checker case)

*Framework is already installed (Django runner); no new test framework needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Printable PDF renders correctly (layout/tables) | RPT-03 | ReportLab byte output is not visually asserted in a unit test | Generate a weekly report PDF, open it, confirm faculty rows + itemized absences render legibly |
| Auto-weekly JOB-03 fires on schedule | RPT-02 | Depends on the live BlockingScheduler wall-clock (Mon 06:00) | Run `manage.py runscheduler`, confirm the weekly_report job produces a stored WeeklyReport + notifies IFO/Dean |

*Automated tests cover aggregate correctness, CSV output, graceful degradation, and department-scoping/authorization.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

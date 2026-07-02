---
phase: 3
slug: duty-assignments-checker-verification
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `03-RESEARCH.md` § Validation Architecture. Task IDs are assigned by
> the planner; the requirement→test map below is the contract each task must satisfy.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (`unittest`), Django 6.0.6 — `SimpleTestCase` (pure gating cores), `TestCase`/`TransactionTestCase` (DB-backed on MSSQL) |
| **Config file** | none — settings-driven; test DB `test_fluxtrack` (SQL Server 2025 LocalDB, Windows auth) |
| **Quick run command** | `py -3.12 manage.py test verification` |
| **Full suite command** | `py -3.12 manage.py test` |
| **Estimated runtime** | Quick ~1–2s (pure cores); full suite ~30–60s (MSSQL DB setup dominates) |

---

## Sampling Rate

- **After every task commit:** the touched app's tests — `py -3.12 manage.py test verification` (pure `CheckerResolverTests`/`DistributeTests` run sub-second) plus the specific DB class for the task.
- **After every plan wave:** `py -3.12 manage.py test verification scheduling web`.
- **Before `/gsd:verify-work`:** full suite green — `py -3.12 manage.py test`. MUST keep the Phase-1/2 suites green (note: two `scheduling.tests.SweepTests` cases are **rewritten** this phase, not regressions — see Wave 0).
- **Max feedback latency:** ~60 seconds.

---

## Per-Requirement Verification Map

Task IDs (`03-NN-MM`) are filled in by the planner; every task implementing a
requirement below MUST wire to the matching test class.

| Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| CHK-01 | Off-duty scan refused | unit (pure) | `verification.tests.CheckerResolverTests.test_off_duty_refused` | ❌ W0 | ⬜ pending |
| CHK-01 | Wrong-floor scan refused with a clear reason | unit (pure) | `verification.tests.CheckerResolverTests.test_wrong_floor_refused` | ❌ W0 | ⬜ pending |
| CHK-01 / IFO-06 | Active FLOOR assignment grants scan powers on that floor | integration | `verification.tests.CheckerScanDBTests.test_active_assignment_grants_scan` | ❌ W0 | ⬜ pending |
| CHK-02 | On-duty scan returns session state + faculty profile photo | integration | `verification.tests.CheckerScanDBTests.test_scan_returns_session_and_photo` | ❌ W0 | ⬜ pending |
| CHK-02 | Online session routes to `teams_link` (no room state) | integration | `verification.tests.CheckerScanDBTests.test_online_scan_redirects_to_teams` | ❌ W0 | ⬜ pending |
| CHK-03 / CHK-04 | Verify records a validation; `verified_by_checker` becomes true | integration | `verification.tests.CheckerScanDBTests.test_verify_marks_verified` | ❌ W0 | ⬜ pending |
| CHK-03 / #6 | Online Verify sets status ACTIVE + `checkin_method=online_manual` + actual_start | integration | `verification.tests.CheckerScanDBTests.test_online_verify_activates_session` | ❌ W0 | ⬜ pending |
| CHK-03 | Flag requires a note (empty note rejected) | integration | `verification.tests.CheckerScanDBTests.test_flag_requires_note` | ❌ W0 | ⬜ pending |
| CHK-05 | Flag fires `notify()` to IFO **and** HR | integration | `verification.tests.CheckerScanDBTests.test_flag_notifies_ifo_and_hr` | ❌ W0 | ⬜ pending |
| CHK-03 | `CONFIRMED_ABSENT` retired; not in choices, no emitter | unit + migration | `verification.tests.CheckerScanDBTests.test_confirmed_absent_not_in_choices` | ❌ W0 | ⬜ pending |
| CHK-07 | Coverage % = verified/total active, Absent excluded | integration | `verification.tests.FloorBoardTests.test_coverage_excludes_absent` | ❌ W0 | ⬜ pending |
| CHK-07 | Priority queue ordered oldest-active-first | integration | `verification.tests.FloorBoardTests.test_priority_queue_oldest_first` | ❌ W0 | ⬜ pending |
| CHK-08 | Valid queued scan applies on replay (preserves original `scanned_at`) | integration | `verification.tests.ReplayTests.test_valid_replay_applies` | ❌ W0 | ⬜ pending |
| CHK-08 | Stale queued scan not applied → IFO flag via `notify()` | integration | `verification.tests.ReplayTests.test_stale_replay_flags_ifo` | ❌ W0 | ⬜ pending |
| CHK-08 | Replay idempotent (same client uuid twice → one apply) | integration | `verification.tests.ReplayTests.test_replay_idempotent` | ❌ W0 | ⬜ pending |
| IFO-06 | Round-robin distributes online sessions deterministically | unit (pure) | `verification.tests.DistributeTests.test_round_robin_even_split` | ❌ W0 | ⬜ pending |
| IFO-06 | No online-duty Checker → sessions left unassigned + IFO flag | integration | `verification.tests.DistributeTests.test_no_checker_leaves_unassigned` | ❌ W0 | ⬜ pending |
| ROADMAP #6 | Un-verified online no-show → ABSENT (sweep exclusion removed) | integration | `scheduling.tests.SweepTests` (**REWRITE** existing online-exclusion cases) | ⚠️ exists, must change | ⬜ pending |
| ROADMAP #6 | Verified online (ACTIVE) skipped by the sweep | integration | `scheduling.tests.SweepTests.test_verified_online_not_marked_absent` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `verification/tests.py` — add `CheckerResolverTests` (SimpleTestCase, pure gating core) + `DistributeTests` (round-robin pure core).
- [ ] `verification/tests.py` — add `CheckerScanDBTests`, `FloorBoardTests`, `ReplayTests` (DB-backed); reuse the unique-key fixture helper pattern from `scheduling/tests.py:~292` (`_JobFixtureMixin`).
- [ ] `scheduling/tests.py` — **REWRITE** `test_online_no_show_stays_scheduled_declared` and `test_online_no_show_stays_scheduled_via_schedule` to assert the new inclusion semantics; add `test_verified_online_not_marked_absent`. (These are intentional behavior changes, not regressions — the sweep's online exclusion is removed this phase.)
- [ ] Shared fixture: a Checker + `Assignment` (active floor / active online-duty) + IFO + HR users.
- [ ] Framework install: **none** — Django test runner + MSSQL `test_fluxtrack` already in place.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live offline → reconnect replay in a real browser | CHK-08 | Service Worker + IndexedDB timing across a real network transition can't be unit-tested | Go offline, record 2–3 scans, reconnect; confirm valid ones apply and a stale one raises an IFO flag |
| Camera QR capture on a phone | CHK-02 | Hardware camera + permission | Scan a room QR on a mobile device; confirm the room resolves |
| Visual floor board (card colors, coverage bar, mobile layout) | CHK-07 | Visual/responsive judgment | Load the floor view on a phone; confirm colors match state and layout is usable one-handed |
| Opening the public MS Teams link + human identity match | CHK-02 / #6 | Human-in-the-loop judgment | Open an online session's Teams link; confirm the faculty photo matches the person on screen |

*All non-visual, non-hardware behaviors have automated verification above.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (incl. the two rewritten sweep tests)
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

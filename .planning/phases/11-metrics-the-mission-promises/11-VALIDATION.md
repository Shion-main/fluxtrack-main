---
phase: 11
slug: metrics-the-mission-promises
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-20
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Ground-truth edges are defined in `11-RESEARCH.md` § Validation Architecture —
> the planner lifts them into per-task `must_haves` and the map below.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (`django.test.runner.DiscoverRunner`) — unittest-style, NOT pytest |
| **Config file** | none — `manage.py test`; test DB is `test_fluxtrack` (separate from dev `fluxtrack`) |
| **Quick run command** | `C:\Users\joshu_mnu8z3u\AppData\Local\Programs\Python\Python312\python.exe manage.py test scheduling.tests.<Class>` |
| **Full suite command** | `C:\Users\joshu_mnu8z3u\AppData\Local\Programs\Python\Python312\python.exe manage.py test` |
| **Estimated runtime** | quick ~10–30s per class · full suite several minutes (~965+ tests) |

> Interpreter note: bare `python` lacks Django on this machine — always use the full
> Python312 path. See memory `django-test-interpreter`. After any migration-adding
> task, `migrate` the dev DB too (memory `dev-db-migration-drift`).

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched module's test class
- **After every plan wave:** Run the full suite
- **Before `/gsd-verify-work`:** Full suite must be green (baseline: 3 long-standing
  dev-login/home-redirect failures are the ONLY accepted reds — see STATE.md)
- **Max feedback latency:** ~30 seconds (quick), full suite pre-wave

---

## Per-Task Verification Map

> Filled by the planner from RESEARCH.md § Validation Architecture. Each new metric
> maps to a mutation-resistant assertion, not just "aggregate > 0".

| Task ID | Plan | Wave | Requirement | Threat Ref | Observable Ground Truth | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-------------------------|-----------|-------------------|-------------|--------|
| 11-XX-XX | XX | X | A3 / A6 / A8 | — | {lift from RESEARCH § Validation Architecture} | unit | `manage.py test …` | ⬜ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Mutation-resistant edges that MUST have a dedicated test (from RESEARCH)

- **Within-grace-but-late** session counts toward minutes-late and chronic-late
  (lateness is grace-independent, D-01) — the binding guard against a
  grace-gated mutation.
- **ABSENT** session contributes **zero** to lateness and zero to the coverage
  numerator (no `actual_start`; not held-verified).
- **In-flight ACTIVE** session (only `actual_start`, no `actual_end`) DOES
  contribute to lateness even though it is excluded from utilization — the two
  contracts differ on purpose.
- **Zero-coverage floor** with held-but-unverified sessions must APPEAR in the
  coverage list (not silently absent) — assert the floor row exists with 0%.
- **Ghost-room** predicate keys on `used_seconds == 0`, NOT rounded `used_hours ==
  0.0` — a room with ~40s of real use must NOT be flagged (rounding trap).
- **Chronic-late floor**: a faculty with < 5 held sessions in range is never
  flagged chronic even at 100% late frequency (D-02 minimum-sessions guard).

---

## Wave 0 Requirements

- Existing infrastructure covers all phase requirements (Django test runner in
  place; no new framework). New test modules are added alongside the code they
  cover (e.g. `scheduling/tests/…`), not as a Wave 0 install.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CSV opens cleanly in a spreadsheet + coverage/ghost-room render legibly on the IFO dashboard | A6/A8 | Visual/format check no unit test makes | Load `/ifo/…`, download CSV, open in Excel; confirm columns + zero-coverage floors visible |

---

## Validation Sign-Off

- [ ] All tasks have automated verify or are listed Manual-Only
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Every mutation-resistant edge above has a dedicated named test
- [ ] No watch-mode flags
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

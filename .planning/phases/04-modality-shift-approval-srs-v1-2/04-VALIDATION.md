---
phase: 4
slug: modality-shift-approval-srs-v1-2
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 4 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Seeded from `04-RESEARCH.md` § Validation Architecture. Per-task IDs bind at planning/execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Django test runner (`unittest` / `TestCase`, `SimpleTestCase`) |
| **Config file** | none — Django default; `config/settings.py` |
| **Quick run command** | `py -3.12 manage.py test scheduling.tests.ModalityShift ops.tests.RoomAvailabilityTests -v2` |
| **Full suite command** | `py -3.12 manage.py test` |
| **Estimated runtime** | targeted subset seconds; full suite ~1–3 min (estimate — measure at Wave 0) |

Existing suites to extend: `scheduling/tests.py` (541 lines), `verification/tests.py` (868), `ops/tests.py` (298), `web/tests.py` (167).

---

## Sampling Rate

- **After every task commit:** `py -3.12 manage.py test scheduling.tests.ModalityShift ops.tests.RoomAvailabilityTests -v2`
- **After every plan wave:** `py -3.12 manage.py test scheduling ops web`
- **Before `/gsd-verify-work`:** `py -3.12 manage.py test` must be fully green
- **Max feedback latency:** targeted subset should stay under ~15 s

---

## Per-Requirement Verification Map

Requirement → behavior → test binding (from RESEARCH.md § Phase Requirements → Test Map). Task IDs (`04-NN-MM`) and the Threat Ref column are bound when PLAN.md files exist; the Nyquist auditor finalizes this table post-planning.

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| MOD-01 | Lead-time gate refuses at/after Manila-midnight cutoff (boundary 23:59 vs 00:00) | unit (pure gate fn) | `manage.py test scheduling.tests.LeadTimeGateTests` | ❌ W0 |
| MOD-01 | Windowed request: cutoff checked against earliest affected session | unit | `manage.py test scheduling.tests.LeadTimeGateTests` | ❌ W0 |
| MOD-01 | Single + recurring scope resolves correct in-window set; out-of-window untouched | integration | `manage.py test scheduling.tests.ShiftScopeTests` | ❌ W0 |
| MOD-02 | Deterministic Dean routing; refuse-at-submit when no dept / vacant Dean | unit | `manage.py test scheduling.tests.DeanRoutingTests` | ❌ W0 |
| MOD-03 | →Online approval sets effective Online + `room_released_at` on each in-window session | integration | `manage.py test scheduling.tests.ApplyOnlineTests` | ❌ W0 |
| MOD-03 | Future in-window session materialized later is born released (JOB-01 hook) | integration | `manage.py test scheduling.tests.BornReleasedTests` | ❌ W0 |
| MOD-04 | →F2F approval assigns original-room-if-free else first-free-in-building | integration | `manage.py test scheduling.tests.ApplyF2FTests` | ❌ W0 |
| MOD-04 | No free room → approval blocked, request STAYS pending, session unchanged (no partial apply) | integration | `manage.py test scheduling.tests.ApplyF2FTests` | ❌ W0 |
| MOD-04 / D-08 | Availability query overlap semantics (half-open; released/absent/online excluded; Booking overlap) | unit (property-style) | `manage.py test ops.tests.RoomAvailabilityTests` | ❌ W0 |
| MOD-04 / D-06 | TOCTOU: picked room taken between select and approve → re-resolves to another free room | integration | `manage.py test scheduling.tests.ApproveRaceTests` | ❌ W0 |
| MOD-05 | IFO notified informationally on apply; decision notifies faculty; submit notifies Dean | integration | `manage.py test scheduling.tests.ShiftNotifyTests` | ❌ W0 |
| MOD-05 | Withdraw while pending (requester-only); non-pending / non-owner refused | unit/integration | `manage.py test scheduling.tests.WithdrawTests` | ❌ W0 |
| MOD-06 | Effective modality after shift is read by resolver/sweep (coupling test) | integration | `manage.py test scheduling.tests.EffectiveModalityCouplingTests` | ❌ W0 |
| MOD-02 / MOD-06 | IDOR: non-Dean approve, cross-department approve, foreign withdraw all refused | integration (view) | `manage.py test web.tests.ModalityShiftAuthzTests` | ❌ W0 |
| DOC-01 | `.md` has v1.2 markers (MOD area, DEAN-04, no CHK-06, policy row); `.docx` regenerates without error | smoke | script / `manage.py test` assertion | ❌ W0 |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · W0 = created in Wave 0*

---

## Wave 0 Requirements

- [ ] `scheduling/tests.py` — LeadTimeGate, ShiftScope, DeanRouting, ApplyOnline, BornReleased, ApplyF2F, ApproveRace, ShiftNotify, Withdraw, EffectiveModalityCoupling
- [ ] `ops/tests.py` — RoomAvailabilityTests (overlap predicate, building scope, Booking + released/online exclusion)
- [ ] `web/tests.py` — ModalityShiftAuthzTests (IDOR / role gates)
- [ ] Fixtures: a Dean + faculty in one Department, a Schedule with Sessions, an Online schedule with a room, a competing Booking/Session for conflict cases (extend `seed_demo` pattern)
- [ ] DOC-01 smoke assertion + `pypandoc_binary` install

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `FluxTrack_SRS.docx` renders correctly (tables/headings intact) after regeneration | DOC-01 | Visual fidelity of the generated `.docx` is not asserted by a smoke test | Open the regenerated `.docx`; confirm the new MOD area, DEAN-04, policy-register row, and removed CHK-06 render as expected |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < ~15s (targeted subset)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

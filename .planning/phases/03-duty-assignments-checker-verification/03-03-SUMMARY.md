---
phase: 03-duty-assignments-checker-verification
plan: 03
subsystem: verification
tags: [ifo, assignment, duty-roster, online, round-robin, apply-layer, notify, htmx, franken-ui, management-command]
requires:
  - verification.resolver.distribute_online_sessions (03-01, pure round-robin)
  - verification.models.Assignment / AssignmentScope / AssignmentType / DutyRole (03-01)
  - scheduling.Session.online_checker FK (03-01)
  - ops.notify.notify (Phase 2 single write path)
  - ops.policy.get_policy (materialization_horizon_days)
  - web/ifo.ifo_required + Franken UI page shell (ifo/live.html, ifo/rooms.html)
provides:
  - verification.services.assign_online_sessions (thin apply -> Session.online_checker)
  - scheduling assign_online management command (daily round-robin pass, ASCII)
  - web.ifo.assignments_list / assignment_create (+ /ifo/assignments* routes)
  - templates/ifo/assignments.html + _assignment_form.html (IFO-06 create UI)
  - IFO home "Assignments" surface card
affects:
  - 03-05 (online verification reads Session.online_checker owner set here)
  - Phase-4 modality-shift (a ->Online shift reuses assign_online_sessions)
  - Phase-5 (surfaces the online_assigned / online_unassigned Notification rows written here)
tech-stack:
  added: []
  patterns: [pure-core-decides-thin-apply-audits, materialize-before-write-HY010, notify-single-write-path, server-side-validated-build, htmx-partial-swap]
key-files:
  created:
    - verification/services.py
    - scheduling/management/commands/assign_online.py
    - templates/ifo/assignments.html
    - templates/ifo/_assignment_form.html
  modified:
    - verification/tests.py
    - web/ifo.py
    - web/urls.py
    - web/views.py
decisions:
  - assign_online_sessions returns {assigned, unassigned} counts; empty online roster leaves online_checker NULL and flags IFO once rather than guessing an owner (T-03-10)
  - ONLINE assignment create pre-assigns across today..+horizon for a standing posting (date NULL), or just the dated day — so a roster set after materialization still picks up its sessions (RESEARCH Pattern 3, "assign lazily when the roster is known")
  - The Assignment is built server-side from validated choice fields; FLOOR requires >=1 real floor pk, ONLINE ignores floors; invalid input renders a 400 error partial, never a 500 (T-03-08/09)
  - Each assigned Checker gets ONE summary online_assigned Notification per run (write-only CHK-02; read surface is Phase 5)
metrics:
  duration: ~14m
  completed: 2026-07-03
  tasks: 3
  files: 8
status: complete
---

# Phase 3 Plan 03: IFO Duty Assignments & Online Round-Robin Apply Summary

Delivered the IFO-facing side of IFO-06: a non-admin Franken UI where IFO posts Checkers/Guards to floors (shift or standing) or grants online duty (`scope=ONLINE`), plus the apply layer that pre-assigns each unowned online session to exactly one online-duty Checker via 03-01's pure `distribute_online_sessions` round-robin — writing `Session.online_checker` (audited), flagging IFO when no online-duty Checker exists, and notifying each assigned Checker at pre-assignment time. A standalone `assign_online` management command runs the same pass daily.

## What Was Built

### Task 1 — DistributeDBTests + AssignmentCreateTests (TDD RED)
`verification/tests.py` gained two DB-backed suites on the existing `_CheckerFixtureMixin`:
- `DistributeDBTests`: `test_no_checker_leaves_unassigned` (no online-duty Checker -> `online_checker` NULL + `notify(IFO, online_unassigned)`), and `test_round_robin_assigns_online_checker` (2 Checkers / 4 online sessions -> deterministic 2/2 split, every session owned, each Checker notified `online_assigned`).
- `AssignmentCreateTests`: `test_ifo_creates_floor_assignment`, `test_ifo_creates_online_duty_assignment` (no floor requirement), `test_non_ifo_forbidden` (Checker POST -> 403).

Confirmed RED before Tasks 2-3: the distribute tests raised `ImportError` on `verification.services`; the create tests hit `404` on the unwired `/ifo/assignments/create` (2 errors + 3 failures).

### Task 2 — verification/services.py + assign_online command (GREEN)
`verification/services.assign_online_sessions(target_date, now=None)`:
1. materializes the date's unowned online sessions with `list()` **before** any write (MSSQL HY010 guard, mirroring `scheduling/jobs.py`) — effective modality (`declared_modality` overrides `schedule.modality`) `== online`, `online_checker` NULL only (re-runs don't reshuffle owned sessions);
2. gathers distinct, ordered active online-duty Checker ids (`role=CHECKER, scope=ONLINE, status=active`, standing or date-matching);
3. delegates the split to the pure `R.distribute_online_sessions` (round-robin is **not** reimplemented);
4. empty roster + candidates -> leave NULL, `notify(role=IFO_ADMIN, type=online_unassigned)`, return `{assigned:0, unassigned:N}`;
5. otherwise writes `Session.online_checker` + one `AuditLog(session.online_checker_assigned)` per assignment, then fires ONE `notify(users=[checker], type=online_assigned, link=/checker/online)` per assigned Checker (batched summary, write-only CHK-02).

`scheduling/management/commands/assign_online.py` (`BaseCommand`) runs the service across `today..+materialization_horizon_days` (both flags overridable), printing ASCII-only summary lines (`->` arrows, `self.style.SUCCESS`).

### Task 3 — IFO assignment views + templates + roster-save trigger (GREEN)
`web/ifo.py` added `@ifo_required` `assignments_list` (GET: active roster grouped by role/scope + create form) and `assignment_create` (`@require_http_methods(["POST"])`): builds the Assignment server-side from validated fields, writes `AuditLog(assignment.created)`, and — when `scope=ONLINE` — calls `assign_online_sessions` across the affected date(s) so a newly-online-duty Checker immediately picks up unowned online sessions. Invalid input (no user / bad role/type/scope / FLOOR with no floor) renders a friendly `400` error partial, never a `500`.

`templates/ifo/assignments.html` (page shell, extends `base.html`) + `templates/ifo/_assignment_form.html` (htmx-swappable create form + active roster) conform to the approved 03-UI-SPEC Franken UI system (`uk-card`/`uk-select`/`uk-btn-primary`/`uk-label`, Lucide `uk-icon`, `h-11`/`h-12` touch targets, `{% comment %}` header). Routes wired in `web/urls.py`; an "Assignments" card added to `SURFACES[Role.IFO_ADMIN]` in `web/views.py`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `.iterator(` acceptance-grep collision with docstring token**
- **Found during:** Task 2
- **Issue:** The acceptance criterion greps for the literal substring `.iterator(` being absent from `verification/services.py`. The module docstring described the HY010 guard as "never `.iterator()`", so the grep matched its own explanatory comment even though no streaming cursor is used (same class of collision 03-01 hit with `timezone.now()`).
- **Fix:** Reworded the docstring to "never a streaming cursor" — semantically identical, no literal collision. The write loop genuinely runs over a materialized `list()`.
- **Files modified:** verification/services.py
- **Commit:** ddefaf1

## Verification Results

- `py -3.12 manage.py test verification.tests.DistributeDBTests verification.tests.AssignmentCreateTests` — 5 tests, OK (round-robin split, IFO flag, floor + online-duty create, non-IFO 403).
- `py -3.12 manage.py test verification scheduling web` — 64 tests, OK (no regression to 03-01/03-02 cores, Faculty scan, sweep, Checker scan).
- `py -3.12 manage.py assign_online --help` — exits 0 (command registered), ASCII-only output.
- Task-2 grep gates: `distribute_online_sessions` + `list(` present, `online_assigned` present (count 2), no `.iterator(` in services.py.
- Task-3 grep gates: `ifo_assignments` + `ifo_assignment_create` in urls.py, `assign_online_sessions` called in ifo.py, `/ifo/assignments` in views.py, 8× `@ifo_required` in ifo.py.

## Threat Mitigations Applied

- **T-03-08 (EoP, non-IFO creating duty grants):** both assignment views carry `@ifo_required`; `assignment_create` is `@require_http_methods(["POST"])` + CSRF (base.html `hx-headers`). Verified by `test_non_ifo_forbidden` (403, no row written).
- **T-03-09 (Tampering, forged scope/floor):** the Assignment is built server-side from validated choice fields (`scope` constrained to `AssignmentScope.values`, FLOOR floors filtered to real pks via `Floor.objects.filter(pk__in=...)`); every create writes an `AuditLog(assignment.created)` with the resolved floors.
- **T-03-10 (Repudiation, silent unassigned online sessions):** empty online roster leaves `online_checker` NULL and fires `notify(IFO, online_unassigned)` rather than guessing; each assignment is audited. Verified by `test_no_checker_leaves_unassigned`.
- **T-03-11 (DoS, HY010 on batch assignment):** candidate sessions materialized with `list()` before the write loop (no streaming cursor), mirroring `scheduling/jobs.py`.
- **T-03-SC (package installs):** no new packages this phase.

## Known Stubs

None that block the plan goal. The `online_assigned` / `online_unassigned` Notification rows are write-only here — their read surface is Phase 5 (NOTIF), and 03-05's "Online to verify" pull-list is the interim work queue (amended CHK-02, as designed). The IFO "Reports" home card stays `href="#"` (out of scope).

## Notes for Downstream Plans

- **03-05 (online verification):** read `Session.online_checker == request.user` for the Checker's "Online to verify" list; the owner link is written here. The `online_assigned` Notification (`link=/checker/online`) points at that surface.
- **Phase 4 (modality shift -> Online):** reuse `assign_online_sessions(target_date)` after approving a ->Online shift so the newly-online session gets an owner; it is idempotent (skips already-owned sessions).
- **Roster edits:** `assign_online_sessions` only fills NULL owners — reassigning an already-owned session (IFO override) is not built here; if Phase 5 adds reassign, it must clear `online_checker` first or the service will skip it.

## Self-Check: PASSED
- FOUND: verification/services.py
- FOUND: scheduling/management/commands/assign_online.py
- FOUND: templates/ifo/assignments.html
- FOUND: templates/ifo/_assignment_form.html
- FOUND commit: 5fd884f (test RED), ddefaf1 (feat services + command), 609bdd6 (feat views + templates)

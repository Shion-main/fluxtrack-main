---
phase: 03-duty-assignments-checker-verification
plan: 05
subsystem: verification
tags: [checker, online-verify, teams-link, sweep-inclusion, coupling, franken-ui, chk-02, chk-03, roadmap-6]
requires:
  - web.checker._apply_action (03-02 — the shared validation apply seam, extended here)
  - web.checker.checker_required (03-02 — Role.CHECKER guard)
  - web.checker.action re-gate pattern (03-02 — server-side ownership re-verify)
  - scheduling.models.Session.online_checker (03-03 — online ownership FK, round-robin assigned)
  - scheduling.models.Session.teams_link / CheckinMethod.ONLINE_MANUAL
  - scheduling.resolver.is_no_show_past_grace (Phase 2 — the shared no-show predicate)
  - ops.notify.notify (single notification write path)
provides:
  - web.checker.online_list (CHK-02 online-to-verify list view)
  - web.checker.online_open (CHK-02 Teams-link open + Verify/Flag controls, 404 for non-owner)
  - web.checker._online_action (online branch of /checker/action, server-side re-gated)
  - web.checker._is_online_on_duty / _online_session (online duty + ownership re-derivation)
  - templates/checker/online_list.html + _online_list.html + online_open.html (UI-SPEC-conformant)
  - /checker/online + /checker/online/<session_id> routes
  - sweep_no_shows now includes online (exclusion guard removed)
affects:
  - Phase 4 modality-shift (a shift-to-Online session gains an online_checker + this verify path)
  - HR/IFO attendance reporting (online sessions now reach ABSENT via the sweep)
tech-stack:
  added: []
  patterns: [server-side-re-gate, shared-apply-seam-extension, coupled-change-single-plan, single-notify-write-path]
key-files:
  created:
    - templates/checker/online_list.html
    - templates/checker/_online_list.html
    - templates/checker/online_open.html
  modified:
    - web/checker.py
    - web/urls.py
    - web/views.py
    - scheduling/jobs.py
decisions:
  - Online validations reuse session.room for the NOT-NULL CheckerValidation.room FK — online sessions still carry their scheduled room, so no schema change / migration was needed to record an online verify.
  - The online status semantics (Verify -> ACTIVE + actual_start + ONLINE_MANUAL; Flag-not-present -> ABSENT) live INSIDE the extended _apply_action behind an `online=True` flag, so the F2F/Blended path is untouched (record-only, no silent status override).
  - The online re-gate re-derives ownership (online_checker_id == user.pk), active online-duty (_is_online_on_duty), and actionability (not ABSENT/COMPLETED) server-side from the POST session_id — a foreign/stale/forged online action is refused and writes nothing, mirroring the 03-02 floor re-gate.
  - online_open renders a dedicated online_open.html (not in the plan's artifact list) because the open-to-verify screen needs the Teams link + Verify/Flag controls; the two listed templates (online_list, _online_list) are the list surface only.
  - The sweep exclusion removal and the online Verify-activates path ship in THIS single plan (Task 2 + Task 3) — decoupling would mark every online session Absent the moment grace passes.
metrics:
  duration: ~14m
  completed: 2026-07-03
  tasks: 3
  files: 7
status: complete
---

# Phase 3 Plan 05: Online Verification Path + Sweep Inclusion Summary

Shipped the milestone's highest-risk coupling (ROADMAP criterion #6) as one atomic change: an online-duty Checker now opens each assigned online session's public MS Teams link and records **Verify present** (which *activates* the session — the online analog of a faculty room check-in) or **Flag: not present** (which drives it Absent authoritatively). Only because a genuine online attendee is now made ACTIVE was it safe to remove the JOB-02 sweep's online-exclusion guard — so an un-verified online no-show past grace now falls to ABSENT under the SAME `is_no_show_past_grace` predicate as F2F, while a verified (ACTIVE) online session is skipped.

## What Was Built

### Task 1 — RED tests (pre-committed at `2af4803`, not re-done)
The prior executor committed the RED contract: two `SweepTests` online cases rewritten from exclusion (stays SCHEDULED) to inclusion (→ ABSENT), a new `test_verified_online_not_marked_absent` (ACTIVE online skipped), and three `CheckerScanDBTests` online cases (verify-activates, redirect-to-teams + foreign-404 + no-link-flags-IFO, flag-not-present-absent), plus the `_online_duty_assignment` / `_owned_online_session` fixtures. Confirmed RED at execution start: **5 failures** (2 sweep inclusion + 3 online) before any implementation.

### Task 2 — Online verify path (`818c992`)
`web/checker.py` gains, all `checker_required`:
- `online_list` — today's owned, still-SCHEDULED effective-online sessions (verified ones have become ACTIVE and drop off), rendered to `online_list.html` + `_online_list.html`.
- `online_open(session_id)` — resolves the owned online session (`_online_session`, 404 for a non-owner via `Http404`); a non-empty `teams_link` renders `online_open.html` (the Teams link + Verify/Flag controls, no room-state card); an empty `teams_link` renders the "No Teams link" state AND `notify(role=IFO_ADMIN, type="online_no_link", …)` so IFO can fix it rather than a dead redirect.
- `_online_action` — the online branch of `/checker/action`, dispatched when a POST carries a `session_id` and **no** `room_id`. It re-gates server-side (ownership + `_is_online_on_duty` + actionable) BEFORE any write, then calls the extended `_apply_action(…, online=True)`.

`_apply_action` was **extended, not forked**: behind an `online=True` flag it additionally sets `status=ACTIVE`, `actual_start`, `checkin_method=ONLINE_MANUAL` on a Verify, or `status=ABSENT` on a Flag-not-present — while the F2F/Blended path stays record-only (no status override). The flag notify(IFO+HR) path is reused unchanged. Routes `/checker/online` + `/checker/online/<int:session_id>` wired in `web/urls.py`; home `SURFACES[Role.CHECKER]` gains an "Online to verify" card.

### Task 3 — Sweep inclusion (`dd36ec8`)
`scheduling/jobs.py` `sweep_no_shows` loses its `effective_modality == Modality.ONLINE: continue` guard, so online SCHEDULED no-shows past grace fall to ABSENT under the shared predicate; the now-unused `Modality` import was dropped. The materialize-first HY010 guard, the shared-predicate re-affirm, the SCHEDULED→ABSENT idempotency, the per-absence AuditLog(by=sweep), and the never-stamp-`room_released_at` guarantee are all intact. The docstring now documents online inclusion + the coupling to the Verify path.

## Deviations from Plan

**1. [Rule 2 — Missing artifact] Added `templates/checker/online_open.html`**
- **Found during:** Task 2. The plan's artifact list names only `online_list.html` + `_online_list.html`, but `online_open` (the Teams-open + Verify/Flag screen the RED test drives via `GET /checker/online/{id}`) needs its own template.
- **Fix:** Created `online_open.html` conforming to 03-UI-SPEC §9 (Franken UI, `#outcome` htmx swap target, no room card). The two listed templates remain the list surface.
- **Commit:** `818c992`

Otherwise the plan executed as written; no Rule 1/3/4 deviations.

## Verification Results

- **RED confirmed before implementation:** `py -3.12 manage.py test scheduling.tests.SweepTests verification.tests.CheckerScanDBTests` → 5 failures (2 sweep inclusion + 3 online).
- **Task 2:** `py -3.12 manage.py test verification.tests.CheckerScanDBTests` → 10 tests OK (3 online + 7 F2F still green).
- **Task 3 grep gate:** `Modality.ONLINE` absent from `sweep_no_shows` body → prints `exclusion-removed`.
- **Coupled proof:** `py -3.12 manage.py test scheduling verification` → 70 tests OK (online Verify-activates + sweep-inclusion pass in one run).
- **Requested suite:** `py -3.12 manage.py test verification scheduling web` → 72 tests OK.
- **Full suite (phase gate):** `py -3.12 manage.py test` → 92 tests OK — the two rewritten sweep cases are intentional behavior changes, not regressions.

## Threat Mitigations Applied

- **T-03-15 (Tampering — premature Absent for genuine online attendees):** the Verify-activates path (status=ACTIVE) ships in the SAME plan as the exclusion removal; `test_verified_online_not_marked_absent` gates it (ACTIVE online is never swept).
- **T-03-16 (Spoofing — verifying a session not assigned to you):** `online_open` filters `online_checker == request.user` (404 otherwise) AND `_online_action` re-verifies ownership + active online-duty + actionability server-side from the POST `session_id` before `_apply_action` — a forged/stale/foreign online action is refused with an audited `checker.action_refused` and writes nothing.
- **T-03-17 (Repudiation — silent status override on F2F Flag):** online Flag-not-present sets ABSENT authoritatively; the F2F Flag path stays record-only (the `online=True` flag scopes the status writes), so F2F never silently overrides status.
- **T-03-18 (DoS — HY010 on wider sweep writes):** the materialize-first `list(...)` guard is retained; no `.iterator()` introduced.

## Known Stubs

None. Every surface renders live data. `online_open` links to the real `session.teams_link`; the empty-link path is a genuine IFO-flagging state, not a placeholder. The deferred manual check (opening a real public Teams link + human identity match against the faculty photo) is human-judgment verification, not missing functionality.

## Notes for Downstream Plans

- **Phase 4 modality-shift:** a session shifted to Online should set `online_checker` (round-robin, as 03-03 does) so it surfaces in `online_list` and can be verified/swept through this path.
- Reuse `_is_online_on_duty` for any other online-duty gate; it mirrors `_active_floor_ids` but is floor-agnostic.
- The online CheckerValidation carries `room=session.room` (the scheduled room) to satisfy the NOT-NULL FK — filter online validations by `session` + `action`, not by room semantics.

## Self-Check: PASSED
- FOUND: templates/checker/online_list.html
- FOUND: templates/checker/_online_list.html
- FOUND: templates/checker/online_open.html
- FOUND: web/checker.py (online_list, online_open, _online_action, _is_online_on_duty, _online_session)
- FOUND: web/urls.py (/checker/online + /checker/online/<session_id>)
- FOUND: web/views.py ("Online to verify" -> /checker/online)
- FOUND: scheduling/jobs.py (online exclusion removed)
- FOUND commit: 2af4803 (RED), 818c992 (feat online verify), dd36ec8 (feat sweep inclusion)

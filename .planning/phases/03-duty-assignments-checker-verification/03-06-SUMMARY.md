---
phase: 03-duty-assignments-checker-verification
plan: 06
subsystem: verification
tags: [checker, offline, indexeddb, replay, idempotency, notify, gating, pure-core]
requires:
  - verification.resolver.resolve_checker_scan (03-01)
  - web.checker._active_floor_ids / _room_session_state / _apply_action / _room_from_payload (03-02)
  - ops.notify.notify (Phase 2 single write path)
  - web/scan.py scan-idem cache idiom (idempotency pattern to mirror)
provides:
  - web.checker.replay (POST /checker/replay) — offline batch re-validation endpoint
  - web.checker._room_from_replay_token — QR-token/manual-code lookup for replay items
  - static/checker/offline_queue.js — IndexedDB queue + reconnect drain + banner (window.FluxTrackOfflineQueue)
  - templates/checker/scan.html offline-capture fallback UI
affects: []
tech-stack:
  added: []
  patterns: [pure-core-decides, thin-apply-audits, server-side-re-gate, notify-single-write-path, client-side-indexeddb-queue, cache-idempotency-by-client-uuid]
key-files:
  created:
    - static/checker/offline_queue.js
  modified:
    - web/checker.py
    - web/urls.py
    - templates/checker/scan.html
    - verification/tests.py
decisions:
  - "The replay endpoint re-runs resolve_checker_scan against CURRENT server-derived state per item (active floors + room session state), never the client's offline snapshot — a stale item is recorded (AuditLog checker.replay_conflict) and IFO-notified instead of applied."
  - "Idempotency is keyed on the client-supplied client_uuid via the Django cache with no expiry (timeout=None), mirroring web/scan.py's scan-idem idiom but permanent rather than per-minute since a uuid is unique forever."
  - "Flag items with an empty note are treated as a replay conflict (reason=note-required) rather than silently applied — reuses the Pitfall 4 rule from the live action endpoint."
  - "_room_from_replay_token supports both QR token and six-digit manual code (mirrors _room_from_payload's lookup style) without rate limiting, since replay is already checker_required + per-item idempotency-guarded."
  - "Offline capture on the client asks the Checker to pick Verify/Confirm-empty/Flag-not-present locally (no live session state available offline) — the server's re-validation on replay is what makes this safe; client-side choice is never trusted."
metrics:
  duration: ~5m
  completed: 2026-07-03
  tasks: 3
  files: 4
status: complete
---

# Phase 3 Plan 06: Offline Checker Scan Queue + Reconnect Replay Summary

Delivered CHK-08: a vanilla-JS IndexedDB queue on the Checker scan page captures scans made while offline, and a new `/checker/replay` endpoint re-validates every queued item against **current** server state through the exact same pure gating core (`resolve_checker_scan`) the live scan uses — applying it if still valid (preserving the original offline `scanned_at`) or recording it and flagging IFO via `notify()` if it no longer applies. Replay is idempotent per client-supplied `client_uuid` so a double-replay never double-applies.

## What Was Built

### Task 1 — ReplayTests (RED)
Added `ReplayTests(_CheckerFixtureMixin, TestCase)` to `verification/tests.py`: `test_valid_replay_applies` (a still-actionable queued scan applies with `offline_queued=True` and the original `scanned_at` preserved, not `now`), `test_stale_replay_flags_ifo` (a session that is currently ABSENT is not applied, writes `AuditLog(checker.replay_conflict)`, and notifies IFO), `test_replay_idempotent` (the same `client_uuid` posted twice applies at most once — second returns `status: duplicate`). Confirmed RED via 404 (route unwired) before Task 2.

### Task 2 — `web/checker.py` replay endpoint + route
`checker.replay` (`@checker_required @require_http_methods(["POST"])`) parses `{"items": [...]}`, materializes the list up front (MSSQL HY010 guard, no `.iterator()`), and per item:
1. Idempotency guard on `checker-replay:{client_uuid}` (Django cache, `timeout=None`) — a repeated uuid short-circuits to `duplicate`.
2. Resolves the room via `_room_from_replay_token` (new helper — QR token or six-digit manual code, mirroring `_room_from_payload`'s lookup style without rate limiting since replay is already authenticated + idempotency-guarded).
3. Re-derives the checker's **current** `_active_floor_ids` and the room's **current** `_room_session_state`, and re-runs `R.resolve_checker_scan` against that live state — never the offline snapshot.
4. If actionable AND the action is valid AND (not a flag OR the note is non-empty): calls `_apply_action(..., offline=True, scanned_at=<parsed original timestamp>)`, sets the idempotency cache key, and returns `status: applied`.
5. Otherwise (off-duty, wrong-floor, absent, already-verified, bad-room, bad-payload, or an empty-note flag): writes `AuditLog(checker.replay_conflict)` and `notify(role=Role.IFO_ADMIN, type="checker_replay_conflict")`, returning `status: flagged` with a `reason`.

Wired `path("checker/replay", checker.replay, name="checker_replay")` in `web/urls.py`, alongside the existing 03-02/03-04/03-05 `/checker/*` routes (none clobbered).

### Task 3 — IndexedDB queue + scan-page wiring
`static/checker/offline_queue.js` (vanilla JS, no wrapper library): opens an IndexedDB database (`fluxtrack_checker_offline`, store `queue`, keyed by `client_uuid`), exposing `window.FluxTrackOfflineQueue` with `enqueue()`, `drain()`, `count()`, `initBanner()`. `enqueue()` generates a `client_uuid` via `crypto.randomUUID()` (with a non-crypto fallback for older browsers) and extracts the room token client-side the same way the server parses it (QR deep-link `?t=` or six-digit manual code). `drain()` batch-POSTs the whole queue to `/checker/replay` with the CSRF token read from the `csrftoken` cookie; `applied`, `flagged`, and `duplicate` are all treated as terminal outcomes and removed locally, while a network failure mid-drain leaves the queue untouched for the next `online` event. The live "offline / N queued" banner (`#offline-banner`) updates on `online`/`offline` events and shows an applied-vs-flagged summary after a successful drain, matching the approved 03-UI-SPEC copy. `window.indexedDB` is feature-detected: when absent, `FluxTrackOfflineQueue.available` stays `false`, `enqueue()` rejects, and the banner/offline-capture UI show an "offline capture unavailable" message instead of crashing.

`templates/checker/scan.html` now loads the script, renders the banner, and — since a genuinely offline device also can't reach `/checker/resolve` to see live room state — falls back to a local offline-capture card (Verify present / Confirm empty / Flag not present, with an optional note required only for the flag) whenever a scan attempt fails offline (`!navigator.onLine`), throws a network error, or an htmx `sendError` fires on the manual-code form. The captured scan is enqueued client-side without ever being trusted; the server's replay re-validation is the actual gate.

## Deviations from Plan

None — plan executed exactly as written. `_room_from_replay_token` (manual-code fallback lookup) and the client-side offline-capture prompt UI are implementation details within the plan's stated scope (files_modified matched exactly: `web/checker.py`, `web/urls.py`, `static/checker/offline_queue.js`, `templates/checker/scan.html`, `verification/tests.py`).

## Verification Results

- `py -3.12 manage.py test verification.tests.ReplayTests` — 3 tests, OK.
- `py -3.12 manage.py test verification scheduling web` — 75 tests, OK (no regression to any 03-01..05 surface).
- `py -3.12 manage.py test` (full suite) — 95 tests, OK.
- Task-2 grep gates: `resolve_checker_scan` + `def replay` + `offline=True` present in `web/checker.py`; `checker-replay:` cache key present; no `.iterator(` in the replay path; `checker_replay` route present in `web/urls.py`.
- Task-3 grep gates: `indexedDB` + `/checker/replay` + `randomUUID` present in `offline_queue.js`; no `idb`/`localforage` reference; `window.indexedDB` feature-detect guard present; `offline_queue.js` loaded and an "offline"/"queued" banner rendered in `scan.html`.

## Threat Mitigations Applied

- **T-03-19 (Tampering, trusting a stale offline decision):** replay re-runs `resolve_checker_scan` against CURRENT state per item; non-actionable items are recorded + IFO-flagged, never applied. Verified by `test_stale_replay_flags_ifo`.
- **T-03-20 (Spoofing, forged replay batch):** `checker_required` + CSRF; re-validation re-derives `_active_floor_ids(request.user, now)` and the room's current session state server-side per item — an off-duty or stale replay item is flagged, identical to the live `action` re-gate.
- **T-03-21 (Tampering, duplicate/replayed uuid):** cache idempotency keyed on `client_uuid` (no expiry); a repeated uuid returns `duplicate`. Verified by `test_replay_idempotent`.
- **T-03-22 (Repudiation, backdated scanned_at abuse):** the original `scanned_at` is preserved for provenance, but the DECISION uses current state + `now`; every applied/flagged item writes an `AuditLog` row.
- **T-03-23 (DoS, HY010 on the per-item write loop):** items are iterated over a materialized `list(...)`, never `.iterator()` — grep-verified.
- **T-03-SC (package installs):** no new packages this phase; IndexedDB is browser-native.

## Known Stubs

None that block the plan goal. The offline-capture UI intentionally omits a "Flag: identity mismatch" option (no faculty photo is available offline for identity comparison) — only Verify / Confirm-empty / Flag-not-present are offered offline, which matches what a Checker can meaningfully judge without network access to the identity-match surface.

## Notes for Downstream Plans

- Manual/browser verification of the real offline → reconnect flow (Service Worker + IndexedDB timing across an actual network transition) is deferred per 03-VALIDATION.md — automated coverage here is the server-side re-validation contract (`ReplayTests`), which is what CHK-08 requires to be provably correct regardless of client timing.
- This is the final plan of Phase 3 (wave 6 of 6). All CHK-01..05/07/08, IFO-06 (incl. online-duty), and ROADMAP criterion #6 (online verification joining JOB-02) are now built and green across `verification`, `scheduling`, and `web`.

## Self-Check: PASSED
- FOUND: static/checker/offline_queue.js
- FOUND: web/checker.py
- FOUND: web/urls.py
- FOUND: templates/checker/scan.html
- FOUND: verification/tests.py (ReplayTests)
- FOUND commit: 4d80108 (test RED), a0b454c (feat replay endpoint), 153eef5 (feat offline queue + scan wiring)

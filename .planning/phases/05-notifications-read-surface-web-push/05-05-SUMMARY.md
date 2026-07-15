---
phase: 05-notifications-read-surface-web-push
plan: 05
subsystem: web
tags: [notifications, web-push, service-worker, vapid, soft-prompt, pwa, django]

requires:
  - phase: 05-notifications-read-surface-web-push
    provides: "VAPID_PUBLIC_KEY + push cadence (05-02); fault-isolated push_outbox sender (05-03); _bell.html partial + #push-controls placeholder + vapid_public_key context (05-04)"
provides:
  - "web/views.py: SW_JS push + notificationclick handlers, CACHE bumped v4 -> v5"
  - "web/push.py: subscribe / unsubscribe / vapid_public_key endpoints (validated, per-user, deduped on endpoint)"
  - "static/js/push.js: urlBase64ToUint8Array + currentState + enablePush + soft-prompt banner gating (D-07)"
  - "templates/base.html + faculty/home.html + faculty/schedule.html: bell mounted in BOTH shells + soft-prompt banner + push.js include"
  - "web/tests_push.py: subscribe persist/dedup/validate + login-required + bell-mount markup + SW handler assertions"
affects: []

tech-stack:
  added: []
  patterns:
    - "Soft pre-prompt gating: Notification.requestPermission() fires ONLY on the Enable click, so a stray Block never permanently kills the origin (D-07)"
    - "Every push calls showNotification inside waitUntil -- a silent push revokes the subscription on iOS (RESEARCH Pitfall 2)"
    - "PushSubscription dedup via update_or_create(endpoint=...) so a re-subscribe updates rather than duplicates (Pitfall 6)"
    - "Cross-shell widget mounted once per shell (Franken header + faculty ft-top), driven by the 05-04 context processor"

key-files:
  created:
    - "web/push.py"
    - "static/js/push.js"
    - "web/tests_push.py"
  modified:
    - "web/views.py"
    - "web/urls.py"
    - "templates/base.html"
    - "templates/faculty/home.html"
    - "templates/faculty/schedule.html"

key-decisions:
  - "subscribe validates endpoint is https + keys has p256dh/auth; rejects otherwise (400) before any write (T-05-14)"
  - "subscribe/unsubscribe are POST-only, @login_required, act only on request.user's rows (T-05-09/T-05-15); client sends X-CSRFToken explicitly (Pitfall 5)"
  - "soft banner shows only when currentState()==='default' and no localStorage not-now flag; denied hides banner + shows passive settings note (cannot re-prompt a denied origin)"
  - "CACHE bumped v4 -> v5 in the SAME change as the SW handlers so the new SW activates via the existing purge + skipWaiting + clients.claim"

patterns-established:
  - "Web-push front-end split: SW handlers in SW_JS, endpoints in web/push.py (one module per surface), client flow in static/js/push.js"
  - "Soft pre-prompt as a self-DoS mitigation for a stray permission Block (D-07)"

requirements-completed: [NOTIF-01, NOTIF-02]

metrics:
  duration: ~15min (Tasks 1-3) + human-verify UAT
  completed: 2026-07-15
  tasks: 4
  files: 8

status: complete
---

# Phase 5 Plan 05: Web Push Client + Bell Mount Summary

**The service worker gains push + notificationclick handlers (CACHE v5), subscribe/unsubscribe/key endpoints persist a per-user validated PushSubscription, and push.js drives the soft pre-prompt (Enable gates the real browser permission, D-07) before subscribing with the VAPID key -- while the 05-04 bell is mounted in BOTH the Franken header and the faculty ft-top, closing NOTIF-02 end-to-end and making NOTIF-01 visible.**

## Performance

- **Duration:** ~15 min (Tasks 1-3) + operator human-verify UAT
- **Completed:** 2026-07-15
- **Tasks:** 4 (3 auto + 1 blocking human-verify)
- **Files:** 8 (3 created, 5 modified)

## Accomplishments
- `web/views.py` `SW_JS`: appended a `push` listener that defensively parses `event.data.json()` (generic FluxTrack fallback on parse failure) and always calls `showNotification` inside `waitUntil` (silent push revokes the subscription on iOS), plus a `notificationclick` listener that focuses a matching client or `openWindow`s the deep-link (`data.link`, fallback `/notifications`). `CACHE` bumped `v4 -> v5` in the same change.
- `web/push.py`: `subscribe` (POST, `@login_required`, validates https endpoint + p256dh/auth keys, `update_or_create` dedup on endpoint scoped to `request.user`), `unsubscribe` (deletes only the user's own row for the posted endpoint), `vapid_public_key` (returns the base64url public key as JSON).
- `static/js/push.js`: `urlBase64ToUint8Array`, `currentState()`, `enablePush(vapidPublicKey, csrftoken)` calling `Notification.requestPermission()` only on invocation then subscribing and POSTing `sub.toJSON()` with `X-CSRFToken`; soft-banner gating on `default` + localStorage not-now flag; denied path shows the passive settings note; granted-without-sub silently re-subscribes.
- Bell mounted in BOTH shells (D-01): the Franken header `<nav>` in `templates/base.html` and the faculty navy `ft-top` in `templates/faculty/home.html` + `templates/faculty/schedule.html`; soft-prompt banner + `push.js` include wired globally with `vapid_public_key` + `csrf_token`.
- `web/tests_push.py`: 11 tests green -- subscribe persists exactly one row, re-subscribe dedups on endpoint, invalid payload (non-https / missing keys) returns 400 and writes nothing, endpoints require login, rendered authenticated page contains the bell mount markup, and `SW_JS` contains the push + notificationclick handlers and `v5`.

## Task Commits

1. **Task 1: SW push + notificationclick handlers; bump CACHE v5** - `86b3ca1` (feat)
2. **Task 2: subscribe/unsubscribe/key endpoints + client push.js** - `3078b3e` (feat)
3. **Task 3: mount bell in both shells + soft-prompt banner + push.js include** - `23f2fec` (feat)
4. **Task 4: blocking human-verify UAT** - operator-approved 2026-07-15 (no code)

## Decisions Made
- **CACHE bump lives with the handler change.** Bumping `v4 -> v5` in the same commit as the new SW handlers guarantees the updated worker activates (existing activate-purge + skipWaiting + clients.claim handle rollout); the push subscription lives on `pushManager` and survives the cache bump, so no re-subscribe is needed.
- **Soft pre-prompt is the self-DoS mitigation (D-07).** The real `Notification.requestPermission()` fires only from the Enable action; Not-now / ignore never triggers the browser prompt, keeping the origin re-askable from the settings page — a real capstone-demo hazard avoided.

## Deviations from Plan
**None.** All plan-declared files were created/modified exactly as specified; Tasks 1-3 committed as planned and Task 4's blocking human-verify gate was approved by the operator.

## Deliberate Non-Defects (do not "fix")
- **Push front-end delivery is not automatically testable.** The end-to-end push (real browser permission, VAPID subscribe, tab-closed notification, deep-link) is intentionally verified via the Task 4 human-verify gate — a headless test cannot exercise the browser permission prompt or the OS notification. The automated layer asserts persistence/validation/markup + the SW handler strings; the live round-trip is the operator UAT.

## Threat Model Coverage
- **T-05-14 (tampering, subscribe payload):** `subscribe` validates the endpoint is an https URL and keys carry both p256dh + auth, returning 400 otherwise before any write; stored only via `update_or_create` for `request.user`. Covered by the invalid-payload test.
- **T-05-15 (CSRF):** endpoints are POST-only (`require_http_methods`); the raw fetch sends `X-CSRFToken` explicitly (Pitfall 5).
- **T-05-09 (info disclosure):** `unsubscribe` deletes only `request.user`'s `PushSubscription` rows; no cross-user endpoint deletion.
- **T-05-16 (self-DoS via Block):** soft pre-prompt (D-07) fires the browser prompt only on Enable, so a stray Block cannot be reached from an ignored/Not-now banner — the origin stays re-askable.

## User Setup Required
- Web-push demo target: desktop Chrome/Edge is the reliable path. iOS web push works ONLY for a Home-Screen-installed PWA on 16.4+, not a Safari tab (RESEARCH Pitfall 2). The push_outbox sender (`manage.py runscheduler`) must be running for delivery.

## Human-Verify UAT Result
- **APPROVED** by operator (2026-07-15). Bell renders in both shells; soft pre-prompt gates the real permission (Not-now fires no prompt, Enable on settings does); a key-event push arrives with the tab closed and deep-links; mute suppresses both the list row and the push.

## Next Phase Readiness
- Phase 05 is COMPLETE (5/5 plans). All four success criteria are met: polled in-app list (NOTIF-01), VAPID push with tab closed (NOTIF-02), mute suppresses list + push (NOTIF-03), and failed push is fault-isolated from the triggering job (05-03).
- Next: **Phase 6 — Reporting Engine & Reporting Surfaces** (needs planning; `06-01: TBD`). Depends on Phase 2 (correct absent counts) and Phase 5 (push for report-ready), both now satisfied.

## Self-Check: PASSED

- FOUND: web/push.py, static/js/push.js, web/tests_push.py, web/views.py (SW_JS v5 + handlers), web/urls.py, templates/base.html, templates/faculty/home.html, templates/faculty/schedule.html
- FOUND commits: 86b3ca1, 3078b3e, 23f2fec
- Tests: web.tests_push 11/11 green
- Human-verify: operator-approved 2026-07-15

---
*Phase: 05-notifications-read-surface-web-push*
*Completed: 2026-07-15*

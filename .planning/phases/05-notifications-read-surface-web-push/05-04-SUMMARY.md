---
phase: 05-notifications-read-surface-web-push
plan: 04
subsystem: web
tags: [notifications, read-surface, context-processor, htmx, mute, django]

requires:
  - phase: 05-notifications-read-surface-web-push
    provides: "ops/notifications.py single map + visible_qs/unread_count/_mark_read (05-01); VAPID_PUBLIC_KEY + push cadence (05-02)"
provides:
  - "web/context.py: global notifications(request) context processor (poll_ms + unread + vapid_public_key), both shells"
  - "web/notifications.py: bell (read-only poll), dropdown/list (auto-read on open), settings_page, mute_toggle views"
  - "notifications/{_bell,_bell_inner,_rows,list,settings}.html templates"
  - "web/tests_notifications.py: 12 tests locking D-02/D-03/D-05 + audit-silence + per-user scoping"
affects: [05-05-render-push-client]

tech-stack:
  added: []
  patterns:
    - "Global context processor for a cross-shell widget (the bell) that cannot be supplied per-view (RESEARCH Pitfall 4)"
    - "Read-only poll vs mark-read-on-open split: badge clears only on OPEN (D-02/D-03), poll never writes"
    - "Presence-as-mute toggle via Post/Redirect/Get + htmx hx-select fragment swap"

key-files:
  created:
    - "web/context.py"
    - "web/notifications.py"
    - "web/tests_notifications.py"
    - "templates/notifications/_bell.html"
    - "templates/notifications/_bell_inner.html"
    - "templates/notifications/_rows.html"
    - "templates/notifications/list.html"
    - "templates/notifications/settings.html"
  modified:
    - "config/settings.py"
    - "web/urls.py"

key-decisions:
  - "poll_ms reuses get_policy('poll_interval_seconds')*1000 (policy-driven, never hardcoded, D-02/Convention #3)"
  - "unread guarded for AnonymousUser so the login page never hits the DB"
  - "Mark-read on open is audit-silent (no AuditLog) -- sanctioned exception mirroring notify()/_mark_read"
  - "dropdown/list mark read only the rows actually shown (filter by captured ids), computed before the mark-read update"
  - "mute_toggle uses Post/Redirect/Get (302 -> notif_settings); htmx re-selects #mute-controls via hx-select"

patterns-established:
  - "Cross-shell widget context via a template context processor (bell), consumed by both the standard header shell and the faculty app-shell"
  - "Read-surface endpoints strictly user-scoped through visible_qs(request.user), never PK-addressed (T-05-09)"

requirements-completed: [NOTIF-01, NOTIF-03]

metrics:
  duration: 7min
  completed: 2026-07-09
  tasks: 3
  files: 10

status: complete
---

# Phase 5 Plan 04: Notifications Read Surface Summary

**A global context processor (poll_ms + unread + VAPID key) plus a polled read-only bell, auto-read-on-open dropdown/full-page history, and presence-based mute settings -- all filtered through the single 05-01 map so mute suppresses the list exactly as it suppresses push, and all audit-silent by design.**

## Performance

- **Duration:** ~7 min
- **Completed:** 2026-07-09
- **Tasks:** 3
- **Files:** 10 (8 created, 2 modified)

## Accomplishments
- `web/context.py` `notifications(request)` context processor exposing `poll_ms` (policy-driven), `unread` (mute-filtered, AnonymousUser-guarded), and `vapid_public_key` (empty-safe) to every page across BOTH shells; registered in `TEMPLATES` after the social_django processors.
- `web/notifications.py` five views: `bell` (READ-ONLY poll -- never marks read, D-02), `dropdown` + `list_page` (render THEN mark the shown rows read, D-03, audit-silent), `settings_page` (three mute groups + current state), and `mute_toggle` (POST-only, category-validated, presence-as-mute create/delete, D-05).
- Routes wired in `web/urls.py` (notif_bell / notif_dropdown / notifications / notif_settings / notif_mute).
- Five templates reusing the shipped htmx poll idiom and Franken UI; notification title/body always auto-escaped, never `|safe` (T-05-10). `_bell.html` is authored for 05-05 to mount into the shells; `settings.html` carries the inert `#push-controls` placeholder for the 05-05 push client.
- `web/tests_notifications.py`: 12 tests, all green, covering badge count + mute exclusion, poll-never-marks-read, auto-read-on-open, zero-AuditLog on read, mute-suppresses-list-keeps-unmapped, POST-only + unknown-category-400, login-required, and cross-user isolation.

## Task Commits

1. **Task 1: global notifications context processor + registration** - `9c8a9a5` (feat)
2. **Task 2: notification views + routes + tests** - `a6e23de` (feat)
3. **Task 3: notification templates** - `8a2c6dd` (feat)

## Files Created/Modified
- `web/context.py` (created) - `notifications(request)` context processor.
- `config/settings.py` (modified) - appended `web.context.notifications` to `TEMPLATES` context_processors (VAPID block untouched).
- `web/notifications.py` (created) - bell / dropdown / list_page / settings_page / mute_toggle.
- `web/urls.py` (modified) - imported the module + 5 routes.
- `web/tests_notifications.py` (created) - 12 read-surface tests.
- `templates/notifications/_bell.html`, `_bell_inner.html`, `_rows.html`, `list.html`, `settings.html` (created).

## Decisions Made
- **Task 2 verified without full test render, tests made green in Task 3.** The plan's Task 2 verify command runs the test suite, but the tests require the Task 3 templates. Rather than commit a red suite, Task 2 was verified via `manage.py check` + URL reversibility (both clean), then Task 3's template commit turned the 12 tests green. This mirrors a RED-then-GREEN ordering across the two commits.
- **Shown-rows-only mark-read.** `dropdown`/`list_page` capture the rendered rows as a list, render, then `_mark_read` a queryset filtered by those exact ids -- so a poll or a partial view never marks rows the user did not actually see, and a sliced queryset is never passed to `.filter()`.
- **mute_toggle is Post/Redirect/Get.** Returns a 302 to `notif_settings`; htmx form posts use `hx-select="#mute-controls"` to extract just the toggles fragment from the redirected page, so no sixth partial template was needed.

## Deviations from Plan

**None behavioral.** The only sequencing nuance is the Task 2/Task 3 verify ordering described above (templates land in Task 3, which is where the plan places them). All plan-declared files were created exactly as specified; no extra runtime files were added (the `deferred-items.md` log is a planning artifact, not code).

## Deliberate Non-Defects (do not "fix")
- The mark-read and mute-toggle writes emit **NO AuditLog**. This is intentional per the plan's DELIBERATE EXCEPTION and mirrors `_mark_read`/`notify()`'s own no-audit discipline (a read receipt is not a domain state change). Test `ReadSurfaceIsAuditSilentTests.test_open_writes_no_auditlog` asserts the AuditLog count is unchanged across a dropdown + list open, locking this as intended behavior.

## Threat Model Coverage
- **T-05-09 (info disclosure):** every view `@login_required` and scoped through `visible_qs(request.user)`; no PK-addressed cross-user access. `AccessControlTests.test_never_returns_another_users_rows` proves a user never sees or marks-read another user's rows.
- **T-05-11 (tampering on mute):** `mute_toggle` is `@require_http_methods(["POST"])`, validates the posted category against `NotificationCategory.values` (400 on unknown), CSRF-protected, and acts only on `request.user`. Covered by the reject-unknown + require-POST tests.
- **T-05-10 (XSS at render):** notification title/body rendered with Django auto-escaping, never `|safe`, in the shared `_rows.html`.
- **T-05-12 (audit-silence):** accepted by design (see Deliberate Non-Defects).

## Issues Encountered
- Running `manage.py test web ops` surfaced 3 FAILURES in `web.tests` (DevLoginCoexistTests, DevLoginCuratedDemoTests, HomeSurfaceNavTests) around the DEBUG dev-login / faculty-home path. **Verified pre-existing** by running the same tests in a detached worktree at commit `e929af2` (before this plan) -- they fail identically there, so they are unrelated to the notification read surface. Logged to `deferred-items.md` and left for separate triage (SCOPE BOUNDARY: not caused by this plan's changes).

## User Setup Required
None - no external service configuration required. The VAPID public key is already present (05-02); the actual push subscribe flow is 05-05.

## Next Phase Readiness
- 05-05 can mount `_bell.html` into `base.html` (standard shell) and the faculty app-shell, and wire the push client into the `#push-controls` placeholder + the soft-prompt banner using `vapid_public_key` from the context processor.

## Self-Check: PASSED

- FOUND: web/context.py, web/notifications.py, web/tests_notifications.py, templates/notifications/{_bell,_bell_inner,_rows,list,settings}.html, config/settings.py, web/urls.py
- FOUND commits: 9c8a9a5, a6e23de, 8a2c6dd
- Tests: web.tests_notifications 12/12 green

---
*Phase: 05-notifications-read-surface-web-push*
*Completed: 2026-07-09*

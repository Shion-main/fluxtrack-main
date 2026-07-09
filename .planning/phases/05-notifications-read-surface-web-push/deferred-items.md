# Deferred Items - Phase 05

Out-of-scope discoveries logged during execution (not fixed here).

## Pre-existing web.tests failures (present at commit e929af2, before plan 05-04)

Verified via a detached worktree at e929af2: these three failures exist
independently of 05-04's changes (notification read surface). They involve the
DEBUG dev-login path and faculty home routing, unrelated to notifications.

- `web.tests.DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`
- `web.tests.DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`
- `web.tests.HomeSurfaceNavTests.test_faculty_home_links_modality_request`

Symptom: dev-login POST does not authenticate in the test DB, so faculty-home
GETs return 302 (login redirect) instead of 200. Likely tied to the in-progress
faculty navy redesign / DEMO_USERNAMES curation. Owner should triage separately.

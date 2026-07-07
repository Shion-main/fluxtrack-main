# Deferred Items — Phase 04.2

Out-of-scope discoveries logged during execution (not fixed; SCOPE BOUNDARY).

## 04.2-01

- **Pre-existing (NOT a regression): `web.tests.LogoutTests.test_logout_flushes_session_and_redirects`
  and `web.tests.MicrosoftButtonPostTests.test_login_page_posts_to_social_begin` error with
  `ValueError: Missing staticfiles manifest entry for 'brand/login-background.jpg'`.**
  - **Root cause:** `templates/web/login.html` references `{% static 'brand/login-background.jpg' %}`
    and `config/settings.py` uses `whitenoise.storage.CompressedManifestStaticFilesStorage`, which
    requires a `collectstatic`-built manifest. The test environment has no manifest, so rendering
    the login page raises during `staticfiles_storage.url()`.
  - **Origin:** commit `061bd4c feat(login): redesign sign-in as two-panel MMCM institutional screen`
    — the in-progress login redesign, entirely outside phase 04.2. Plan 01 changed only
    `scheduling/*` (models, migration, merge.py, test_support.py, tests_merge.py); none touch
    templates or static assets.
  - **Why deferred:** unrelated to the merge core; a test-harness/staticfiles-manifest concern for
    the login-redesign work. Fix belongs with that effort (run `collectstatic` in the test bootstrap,
    or switch tests to a non-manifest storage / add the asset to the manifest).
  - **Confirmation:** `python manage.py test scheduling verification --noinput` = 190 tests OK
    (skipped=2). The ONLY web failures are these 2 login-static errors.

# Codebase Concerns

**Analysis Date:** 2026-07-21

This audit describes current `HEAD` (`6cff9a7`, Phase 11 complete). Historical
findings are treated as evidence only after checking the current implementation.
The active milestone sequence is in `.planning/ROADMAP.md`; detailed provenance for
the remaining audit items is in `docs/AUDIT-2026-07-19.md` and
`docs/PLAN-2026-07-20-post-audit-milestone.md`.

## Tech Debt

**Large, mixed-responsibility modules:**
- Issue: several modules combine routing, authorization, parsing, orchestration,
  persistence, and presentation context. `web/ifo.py` is over 100 KB;
  `scheduling/reporting.py`, `scheduling/tests.py`, and `web/tests.py` are each over
  50 KB.
- Files: `web/ifo.py`, `scheduling/reporting.py`, `scheduling/tests.py`,
  `web/tests.py`, `web/faculty.py`, `web/checker.py`
- Impact: changes have a broad regression surface, ownership boundaries are hard to
  see, and targeted review becomes slower even though test coverage is substantial.
- Fix approach: preserve current service seams while splitting by feature family;
  move IFO term/building/room/booking/import/report handlers into focused modules,
  keep pure reporting reductions separate from ORM query builders, and continue the
  already-established `tests_<feature>.py` split instead of adding to monoliths.

**Cache is an implicit correctness dependency with development defaults:**
- Issue: no `CACHES` setting exists, so Django uses per-process local-memory cache.
  Attendance idempotency, manual-code throttling, Checker action dedupe, and offline
  replay dedupe all depend on that cache.
- Files: `config/settings.py`, `web/scan.py`, `web/checker.py`
- Impact: keys are not shared across Gunicorn workers and vanish on recycle. Effective
  rate limits multiply by worker count; duplicate requests can apply on different
  workers; replay UUIDs are not durable.
- Fix approach: configure Redis or Django database cache before multi-worker deploy.
  Persist offline `client_uuid` behind a database unique constraint because a cache
  alone is not an authoritative offline-attendance ledger.

**Dependency reproducibility is incomplete:**
- Issue: only a subset of dependencies is exactly pinned. Runtime packages such as
  DRF, WhiteNoise, Pillow, APScheduler, and pywebpush use broad ranges; there is no
  compiled lock file and no production WSGI server dependency.
- Files: `requirements.txt`
- Impact: clean installs can resolve different transitive versions, and the intended
  Gunicorn deployment is not reproducible from the repository alone.
- Fix approach: add the selected production server, produce a reviewed lock/constraints
  file, and separate document-generation tooling such as `pypandoc_binary` when it is
  not needed at runtime.

**MSSQL-only migrations constrain portability:**
- Issue: the database decision is SQL Server-only and migrations contain T-SQL rather
  than portable Django operations.
- Files: `config/settings.py`, `campus/migrations/0002_cs_collation_tokens.py`
- Impact: SQLite/PostgreSQL cannot be used as lightweight substitutes for tests or
  disaster recovery. Contributors need SQL Server plus ODBC Driver 18.
- Fix approach: treat MSSQL as an explicit platform requirement in all runbooks; do
  not imply multi-database support unless the migration strategy is redesigned.

**Stale root artifacts and generated files obscure repository state:**
- Issue: graphify scratch files, `scratch_planpost.json`, tool directories, and a stale
  local `db.sqlite3` appear in the working tree; several are not ignored.
- Files: `.graphify_ast.json`, `.graphify_changed.txt`, `.graphify_chunk_a.txt`,
  `.graphify_chunk_b.txt`, `.graphify_old.json`, `scratch_planpost.json`, `db.sqlite3`,
  `.gitignore`
- Impact: `git status` is noisy and accidental commits are easier. The SQLite file is
  misleading because application settings are MSSQL-only.
- Fix approach: classify each artifact as committed deliverable or transient output,
  ignore/remove transient files, and retain only `.planning/graphs/` deliverables.

## Known Bugs

**Confirmation tokens can replay stale attendance decisions:**
- Symptoms: `/scan/confirm` trusts the signed outcome for up to 180 seconds and calls
  the mutation layer without re-running the resolver, checking current session state,
  or atomically consuming a nonce.
- Files: `web/scan.py`
- Trigger: double-submit a confirmation, or submit it after another request/sweep has
  changed the session. A second force-handover, room change, or early-end write can be
  applied from stale state.
- Workaround: avoid repeat confirmation clicks; server-side protection is required.
- Fix approach: re-fetch and lock affected rows, re-resolve against current state, and
  make a nonce single-use with a durable or shared atomic store.

**Offline Checker replay can target the wrong class:**
- Symptoms: the IndexedDB record stores `{client_uuid, token, action, note,
  scanned_at}` but no `session_id`. Replay resolves the room's session at replay time.
- Files: `static/checker/offline_queue.js`, `web/checker.py`
- Trigger: capture a scan offline, allow the room's next class to begin, then reconnect.
  The queued action may apply to the later session the checker never observed.
- Workaround: reconnect and drain before the room changes classes; conflicts detected
  by other current-state gates are flagged, but session identity is not checked.
- Fix approach: queue the observed session ID, require a server-side match on replay,
  and emit `checker.replay_conflict` on mismatch. This is Phase 14 H3.

**Faculty resolver prefers chronological order over scanned-room match:**
- Symptoms: among overlapping/window-containing scheduled sessions, the first session
  wins even when a later candidate matches the scanned room.
- Files: `scheduling/resolver.py`, `web/scan.py`
- Trigger: back-to-back or overlapping sessions where an earlier unstarted session is
  assigned elsewhere. The scan can show Wrong Room for the earlier class and permit a
  room rewrite instead of checking into the matching class.
- Workaround: none reliable at the UI layer.
- Fix approach: prefer a window-containing candidate whose `room_id` equals the
  scanned room, then fall back deterministically. This is Phase 14 M5.

**Future bookings do not consult recurring schedules:**
- Symptoms: `room_is_free()` checks materialized `Session` rows, active `Booking` rows,
  and approved modality reservations, but not recurring `Schedule` occurrences.
- Files: `ops/availability.py`, `web/ifo.py`,
  `scheduling/management/commands/materialize_sessions.py`
- Trigger: create a booking beyond the session-materialization horizon for a room/time
  occupied by a weekly schedule. Later materialization can create the conflict.
- Workaround: manually inspect the timetable before creating long-range bookings.
- Fix approach: add a shared schedule-occurrence oracle to booking validation or make
  materialization refuse and notify on collision. This is Phase 14 M3.

**Modality decision transitions are vulnerable to last-writer-wins races:**
- Symptoms: withdraw, reject, and approval re-fetch PENDING requests inside
  transactions but do not use `select_for_update()`.
- Files: `scheduling/services.py`
- Trigger: two Dean/faculty requests commit competing transitions concurrently.
- Workaround: operationally serialize decisions; application enforcement is absent.
- Fix approach: lock the request row before re-gating and keep consequence writes in
  the same transaction. This is Phase 14 M6.

## Security Considerations

**Production settings fail open:**
- Risk: the fallback secret is known, `DEBUG` defaults true, and allowed hosts default
  to `*`. Secure cookie, HTTPS redirect, proxy SSL, trusted-origin, and HSTS settings
  are absent.
- Files: `config/settings.py`
- Current mitigation: environment variables can override core values, CSRF middleware
  is enabled, clickjacking/nosniff middleware controls exist, and production work is
  explicitly not complete.
- Recommendations: default `DEBUG` false; refuse production startup with the fallback
  secret or wildcard hosts; configure `CSRF_TRUSTED_ORIGINS`,
  `SECURE_PROXY_SSL_HEADER`, secure session/CSRF cookies, HTTPS redirect, and HSTS.

**Entra redirect is hardcoded to localhost:**
- Risk: production Entra authentication cannot complete and operators may be tempted
  to weaken redirect/proxy settings to compensate.
- Files: `config/settings.py`, `accounts/backends.py`, `accounts/pipeline.py`
- Current mitigation: Authorization Code + PKCE backend and pre-provision-only pipeline
  are implemented; credentials remain environment-driven.
- Recommendations: make the exact redirect URI environment-driven and register the
  HTTPS production URI in the institutional tenant before cutover.

**Public and private media share one storage root:**
- Risk: profile photos need public delivery, while staged registrar imports and weekly
  report files are intentionally served through authorization-checked views. Mapping
  all of `MEDIA_ROOT` through Nginx exposes private files; mapping none makes photos
  fail in production.
- Files: `config/settings.py`, `config/urls.py`, `accounts/models.py`,
  `ops/import_staging.py`, `ops/reports.py`, `web/ifo.py`, `web/dean.py`
- Current mitigation: Django serves media only in DEBUG; report/import download views
  enforce role/department checks.
- Recommendations: split public photo storage from private report/import storage and
  preserve authenticated streaming or protected internal redirects for private files.

**Known-password demo data can still be forced outside DEBUG:**
- Risk: `seed_demo --force` creates/updates a staff superuser named `admin`; newly
  created demo accounts use `devpass123`.
- Files: `accounts/management/commands/seed_demo.py`
- Current mitigation: the command now refuses when DEBUG is false unless the operator
  explicitly passes `--force` (the earlier unguarded finding is resolved).
- Recommendations: exclude this command from production runbooks and prefer generated,
  forced-change break-glass credentials if production bootstrap is needed.

**CDN scripts are part of the trusted execution boundary:**
- Risk: Franken UI, htmx, and html5-qrcode execute from jsDelivr without a repository
  build artifact; scanner availability and UI integrity depend on a third party.
- Files: `templates/base.html`, `templates/faculty/scan.html`,
  `templates/checker/scan.html`, `web/views.py`
- Current mitigation: versions are pinned in URLs and the service worker refuses to
  cache cross-origin responses.
- Recommendations: vendor reviewed assets under `static/`, include them in the
  WhiteNoise manifest, and test offline scanner fallback. Phase 15 owns this work.

## Performance Bottlenecks

**Append-only operational tables have no retention policy:**
- Problem: the 15-second push-outbox scheduler produces a `JobRun` for every pass;
  AuditLog, notifications, sessions, and Django sessions also accumulate.
- Files: `scheduling/management/commands/runscheduler.py`, `ops/jobrun.py`,
  `ops/models.py`, `scheduling/models.py`
- Cause: no pruning/archival job exists and `clearsessions` is not scheduled.
- Improvement path: set documented retention windows, archive required attendance/audit
  history, prune high-frequency JobRun rows, and schedule expired-session cleanup.

**In-process reporting and file generation can be expensive:**
- Problem: aggregate/report modules are large and weekly CSV/PDF generation runs in the
  single blocking scheduler process.
- Files: `scheduling/reporting.py`, `scheduling/report_render.py`, `ops/reports.py`,
  `scheduling/management/commands/runscheduler.py`
- Cause: broad term/week queries and synchronous rendering share a process with sweep,
  materialization, and push delivery.
- Improvement path: measure production-size queries, retain the existing aggregate
  seams, add indexes from query evidence, and move heavy generation to an isolated
  worker only if measured scheduler latency requires it.

**Large IFO request module increases import and maintenance cost:**
- Problem: every IFO request imports a module containing many unrelated feature paths.
- Files: `web/ifo.py`, `web/urls.py`
- Cause: feature growth accumulated into a single view module.
- Improvement path: split by domain while retaining stable URL names and decorators;
  benchmark only if startup/import time becomes material.

## Fragile Areas

**Attendance state transitions span multiple seams:**
- Files: `web/scan.py`, `web/checker.py`, `web/faculty.py`, `scheduling/jobs.py`,
  `scheduling/merge.py`, `scheduling/resolver.py`, `verification/resolver.py`
- Why fragile: Faculty scans, online starts, Checker actions, merge propagation, offline
  replay, and the sweep all mutate the same state machine. Small predicate drift can
  create false Absents or contradictory audit rows.
- Safe modification: reuse `is_no_show_past_grace`, effective-modality helpers, and
  merge helpers; preserve status-guarded writes and transaction boundaries; test every
  entry seam plus concurrent/stale-state behavior.
- Test coverage: broad regression coverage exists, but stale confirmation, replay
  retargeting, and true concurrent transition tests remain gaps.

**SQL Server cursor/transaction behavior:**
- Files: `scheduling/jobs.py`, `scheduling/merge.py`, `scheduling/services.py`,
  `scheduling/management/commands/materialize_sessions.py`
- Why fragile: mutating rows while iterating a live MSSQL cursor previously caused
  HY010 failures. Several modules deliberately materialize querysets before writes.
- Safe modification: keep list-before-mutate discipline, use status-guarded updates,
  and verify transaction/locking changes on actual SQL Server.
- Test coverage: the suite is MSSQL-backed, but environment-dependent live tests can
  skip and are not a substitute for deployment smoke tests.

**Static manifest behavior differs between development and tests/production:**
- Files: `config/settings.py`, `static/`, `templates/`
- Why fragile: DEBUG serves source static files, while DEBUG false uses compressed
  manifest storage. A newly referenced asset can work locally but fail tests or deploy
  until `collectstatic` regenerates the manifest.
- Safe modification: run `collectstatic` after adding assets and include a production-
  settings render smoke test in CI/deploy.
- Test coverage: the behavior is documented in settings, not enforced by a dedicated
  packaging pipeline.

**Term reset is destructive while lifecycle UI is absent:**
- Files: `scheduling/management/commands/reset_term.py`, `scheduling/models.py`,
  `.planning/ROADMAP.md`
- Why fragile: the existing command deletes session/schedule history in batches and
  defaults to a hardcoded term name. That history feeds attendance and HR reports.
- Safe modification: do not use `reset_term` as rollover. Implement archive/close,
  create-next, and active-term selection without deleting historical rows (Phase 12).
- Test coverage: command mechanics exist, but the intended non-destructive lifecycle is
  not implemented yet.

## Scaling Limits

**Single-host scheduler:**
- Current capacity: one `BlockingScheduler` process with exactly four jobs:
  materialize, sweep, weekly report, and push outbox.
- Limit: there is no distributed lock or persistent job store. Starting two scheduler
  services duplicates work; missing Monday 06:00 can lose the weekly run; a stale DB
  connection can impair all jobs.
- Scaling path: keep exactly one supervised scheduler for the initial deployment, add
  startup weekly-report backfill, close/reopen stale connections, expose staleness
  health, and use a distributed lock/job architecture before horizontal scheduling.
- Files: `scheduling/management/commands/runscheduler.py`, `ops/jobrun.py`

**Local filesystem storage:**
- Current capacity: profile photos, staged imports, and reports live below one local
  `MEDIA_ROOT`.
- Limit: files do not follow requests across multiple hosts and are outside database
  snapshots; EC2 disk loss loses them.
- Scaling path: separate public/private stores and move durable media to managed object
  storage or a backed-up shared volume.
- Files: `config/settings.py`, `accounts/models.py`, `ops/import_staging.py`,
  `ops/reports.py`

**Database growth:**
- Current capacity: deployment planning assumes SQL Server Express/RDS constraints.
- Limit: high-frequency JobRun rows alone can grow by roughly 2.1 million rows/year at
  a 15-second cadence, before audits, notifications, sessions, and report metadata.
- Scaling path: retention/archival plus growth monitoring before production cutover.
- Files: `ops/models.py`, `ops/jobrun.py`,
  `scheduling/management/commands/runscheduler.py`

## Dependencies at Risk

**html5-qrcode 2.3.8:**
- Risk: the core camera gesture is CDN-only and the upstream release is old; load
  failure currently degrades inconsistently between scanner pages.
- Impact: Faculty/Checker camera scanning can disappear, leaving only manual code.
- Migration plan: vendor the reviewed artifact, surface an explicit camera-load error,
  retain the six-digit fallback, and evaluate a maintained scanner behind the same UI.
- Files: `templates/faculty/scan.html`, `templates/checker/scan.html`

**APScheduler 3.x:**
- Risk: the project intentionally depends on the pre-4 API and an in-memory job store.
- Impact: an uncontrolled major upgrade breaks scheduler wiring; memory scheduling does
  not survive downtime.
- Migration plan: preserve `<4` until a deliberate scheduler redesign; add resilience
  around the current service before considering APScheduler 4.
- Files: `requirements.txt`, `scheduling/management/commands/runscheduler.py`

**CDN UI runtime:**
- Risk: Franken UI and htmx availability is outside deployment control, and the PWA
  service worker caches only same-origin assets.
- Impact: offline/login/scan experiences can be unstyled or non-functional.
- Migration plan: vendor exact versions and cover them with static-manifest/offline
  smoke tests.
- Files: `templates/base.html`, `web/views.py`

## Missing Critical Features

**Non-destructive term lifecycle (Phase 12):**
- Problem: IFO cannot close/archive the active term and activate the next while keeping
  history. The available reset command is destructive.
- Blocks: safe semester rollover and reliable longitudinal reports.
- Files: `scheduling/models.py`, `scheduling/management/commands/reset_term.py`,
  `.planning/ROADMAP.md`

**Production operational baseline (Phase 15):**
- Problem: no Gunicorn/systemd/Nginx deployment artifacts, shared cache, health
  endpoint, structured `LOGGING`, error tracking, backup/restore runbook, retention
  jobs, scheduler staleness alert, or media split are present.
- Blocks: safe AWS cutover and credible recovery/monitoring operations.
- Files: `requirements.txt`, `config/settings.py`, `config/urls.py`,
  `scheduling/management/commands/runscheduler.py`, `.planning/ROADMAP.md`

**UX finish and error recovery (Phase 13):**
- Problem: custom 403/404/500 templates and handlers are not detected; several shell,
  navigation, global htmx-error, and PWA-theme issues remain scheduled work.
- Blocks: production-quality failure states and consistent mobile navigation.
- Files: `config/urls.py`, `templates/base.html`, `web/views.py`,
  `.planning/ROADMAP.md`

**Documentation reconciliation (Phase 16):**
- Problem: formal and collaborator docs contradict current code: MySQL/JWT/S3 versus
  MSSQL/session auth/local storage; `.planning/PROJECT.md`, `docs/PROGRESS.md`, and
  `docs/USE_CASES.md` describe older phase positions; `docs/db_schema.sql` is not an
  authoritative migration snapshot.
- Blocks: reliable onboarding, capstone traceability, and operations using docs as
  source of truth.
- Files: `FluxTrack_SRS.md`, `FluxTrack_SRS.docx`, `.planning/PROJECT.md`,
  `docs/PROGRESS.md`, `docs/USE_CASES.md`, `docs/db_schema.sql`,
  `.planning/ROADMAP.md`

## Test Coverage Gaps

**True concurrency and stale-confirmation behavior:**
- What's not tested: cross-transaction races for modality decisions and single-use,
  re-gated Faculty confirmations.
- Files: `scheduling/services.py`, `web/scan.py`, `scheduling/tests.py`, `web/tests.py`
- Risk: last-writer-wins or repeat mutation can corrupt authoritative records while
  ordinary sequential tests remain green.
- Priority: High

**Offline replay session identity:**
- What's not tested: a queued action retaining the exact session observed across a room
  turnover, because the client payload currently lacks session identity.
- Files: `static/checker/offline_queue.js`, `web/checker.py`, `web/tests_replay.py`
- Risk: verification can attach to the wrong class.
- Priority: High

**Fresh-clone real import coverage:**
- What's not tested: some real-workbook tests use gitignored `data/raw/` inputs and
  skip when those local files are absent.
- Files: `scheduling/tests_import.py`, `scheduling/tests_import_hardening.py`,
  `data/fixtures/r3_synthetic.csv`
- Risk: CI can report green while production-shaped XLSX parsing is not exercised.
- Priority: Medium; commit sanitized representative fixtures and fail visibly when the
  expected fixture contract is unavailable.

**Production packaging and operational smoke tests:**
- What's not tested: HTTPS proxy headers/cookies, production SSO redirect, media access
  separation, static manifest completeness, scheduler restart/backfill, health checks,
  backup restore, and multi-worker cache behavior.
- Files: `config/settings.py`, `config/urls.py`, `templates/`,
  `scheduling/management/commands/runscheduler.py`
- Risk: a large unit/integration suite can pass while first deployment fails or exposes
  private media.
- Priority: High before Phase 15 completes.

## Resolved Historical Findings — Do Not Reopen

- Online Faculty self-start now calls `propagate_merged_present` inside its transaction
  in `web/faculty.py` (audit H1 resolved).
- `propagate_merged_absent` now uses the shared grace predicate before absenting siblings
  in `scheduling/merge.py` (audit H2 resolved).
- Faculty occupancy lookup now excludes released rooms in `web/scan.py` (audit M4
  resolved).
- Sweep writes are status-guarded rather than blindly saving stale instances in
  `scheduling/jobs.py` (audit M7 resolved).
- `seed_demo` now refuses outside DEBUG unless `--force` is explicit in
  `accounts/management/commands/seed_demo.py`.
- The formerly red home/dev-login tests and offline-queue initial drain were fixed in
  the post-audit quick-win batch recorded by `.planning/STATE.md`.
- Authentication is no longer merely an unbuilt stub: Entra PKCE backend, pipeline,
  and routes exist in `accounts/backends.py`, `accounts/pipeline.py`,
  `config/settings.py`, and `config/urls.py`. Production tenant/proxy configuration
  remains Phase 15 work.
- SQL Server support, notifications, scheduler, Checker assignments, reporting,
  operational role surfaces, suspension/correction flows, campus CRUD, and mission
  metrics are implemented; the 2026-07-02 concerns map predates these features.

---

*Concerns audit: 2026-07-21*

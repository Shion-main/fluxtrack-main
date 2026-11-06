# Audit Hardening Implementation Plan

> **For agentic workers:** Use subagent-driven-development or executing-plans to implement these tasks with independent specification and quality review.

**Goal:** Resolve the 18 findings in `docs/AUDIT-2026-09-30.md`, preserving established attendance/merge semantics and validating against SQL Server.

**Architecture:** Keep the existing Django monolith. Use explicit browser account isolation, typed input boundaries, transactional state transitions, and shared database serialization for allocation writers. Preserve legacy records while preventing new inconsistent state; use migrations only where durable delivery state needs storage.

**Tech stack:** Django 6, Microsoft SQL Server/mssql-django, vanilla JavaScript/IndexedDB/service workers, pywebpush, Nginx/Gunicorn/systemd.

Work in `codex/audit-hardening-20260930` in the current checkout. Preserve the existing untracked audit and August plan. Do not deploy, push, or change live attendance data. Baseline: 1,378 tests, OK with two expected live-data skips.

## Task 1 — browser isolation and bounded public resources (findings 1, 2, 4, 16)

Files: `web/views.py`, `static/checker/offline_queue.js`, `templates/checker/scan.html`, `templates/base.html`, `web/checker.py` replay owner boundary, new focused regression tests.

- [x] Add behavioral regressions for unsupported icon sizes, service-worker private-response exclusion, queue ownership/account switching, and resetting scan context.
- [x] Limit icons before any Pillow work: `if size not in {192, 512}: raise Http404(...)` (include other sizes only if existing consumers require them).
- [x] Replace broad worker caching with public `/static/` and explicit supported icon paths. Bump cache version and delete legacy FluxTrack caches; never cache private/no-store responses. Provide an offline capture shell containing no attendance/identity data instead of relying on a cached authenticated page.
- [x] Partition offline records by rendered authenticated account ID, transmit owner, reject mismatched owners before receipts/audits, and quarantine legacy unowned observations. Preserve pending items on transient failures and warn about records belonging to another account. Reset `pendingSessionId` whenever payload changes.
- [x] Run affected suites; independently review specification then quality before accepting the task.

## Task 2 — attendance state and transactional evidence (findings 3, 5, 11-confirmation, 13, 14)

Files: `web/scan.py`, `web/checker.py`, `scheduling/resolver.py`, `verification/resolver.py`, new `ops/locking.py`, attendance regression tests.

- [x] Add tests for future/cancelled online actions, repeated ACTIVE verification preserving actual_start, evidence rollback/retry, occupied room moves, closing a room between resolve/confirm, and guarded duplicate transitions.
- [x] Establish one database locking seam used by competing operational writers; acquire it before domain reads and inside `transaction.atomic()`. Use a coarse transaction-owned SQL Server application lock over inconsistent row locks across alternate paths. Lock/update session state in the same transaction and rederive eligibility after acquiring the lock.
- [x] Online Verify/Flag-not-present accepts only a SCHEDULED session on its date within its scheduled window, with current duty and ownership. Never reset actual_start on an ACTIVE session; refuse terminal/cancelled sessions.
- [x] Place CheckerValidation, audit, online transition, propagation, and consequential notification writes in one transaction. Clear unsuccessful cache claims; idempotency must not mask rollback.
- [x] Refuse an ACTIVE room move into another faculty's occupied room; preserve the established explicit handover flow for eligible starts. Recheck room service state in the locked apply path.
- [x] Replace non-atomic scan cache get/set gating; authoritative state guards, rather than the cache alone, prevent duplicate writes.
- [x] Run all scan, online, checker, merge, replay and lifecycle suites and independent reviews.

## Task 3 — allocation and schedule integrity (findings 6, 7, 8, 11-approval, 12, 17)

Files: `ops/availability.py`, new `ops/bookings.py`, `scheduling/schedule_ops.py`, `scheduling/services.py`, `web/ifo.py`, `campus/services.py` if needed, regressions.

- [x] Cover overlapping booking rejection/rollback, room/faculty recurring schedule conflicts, legitimate merged sections, closed rooms, schedule edits/cancellations protecting ACTIVE sessions, superseded reservation release, and bad weekday/enrollment form inputs.
- [x] Reuse Task 2 locking seam in booking creation, schedule create/edit/cancel, physical modality approval, and room service changes. Recheck availability and insert/audit under one transaction. Keep lock acquisition ordering consistent.
- [x] Introduce shared schedule creation/validation, checking all weekly occurrences through term end and all relevant faculty/room conflicts, including beyond materialization horizon. Allow only existing legitimate merge equivalence. Delegate the HTTP view to it.
- [x] Validate weekday in 0–6 and enrollment as bounded nonnegative integer before writes; preserve friendly field errors and existing form contracts.
- [x] Lock affected sessions and retain SCHEDULED predicates in propagation updates; audit only rows actually changed.
- [x] `room_is_free` rejects out-of-service rooms. Reservation lookup selects the latest applicable approved decision per schedule, ignores superseded/archived/cancelled/excused occupancy consistently, and matches materialization's effective shift rules.
- [x] Run booking, room service, schedule, modality, availability, import and term suites and independent reviews.

## Task 4 — push, import and deployment boundaries (findings 9, 10, 15, 18)

Files: new `ops/push_validation.py`, `web/push.py`, `ops/push.py`, `ops/models.py`/migration if retry fields needed, `scheduling/xlsx.py`, `deploy/deploy.sh`, `deploy/README.md`, focused tests.

- [x] Regression tests reject loopback/private/unrecognized provider push destinations, malformed keys/JSON, oversized archive expansion/coordinates, and prove transient push failure retries and a production deployment environment is required.
- [x] Permit exact known browser push-provider origins or tightly defined provider suffixes, HTTPS/443 only, no credentials/fragments or redirects to arbitrary hosts. Validate base64url public point/auth key lengths and cap subscriptions per account. Validate again at send time to protect existing rows.
- [x] Persist bounded retry/backoff state; transient errors remain pending, permanent failures become terminal, and rows outside the old 15-minute selection window remain eligible under an explicit expiry policy. Do not send network operations while holding the attendance allocation lock.
- [x] Before ZIP/XML/grid allocation impose total expanded-byte, member, row, column and cell-count limits. Raise a controlled ValueError consumed by the existing import view. Small sparse malformed fixtures must fail without significant allocation.
- [x] Deployment loads `/etc/fluxtrack/fluxtrack.env` (overridable path for verification), exports values safely, and refuses non-production mode before checks/migration/collectstatic. Document the environment-file contract and smoke host configuration.
- [x] Run push, import/parser and deployment suites and independent reviews.

## Final verification

- [x] Review the complete diff for requirement coverage, lock ordering, SQL Server semantics, accidental changes, migration compatibility, and browser privacy.
- [x] `py -3.12 manage.py check`, `py -3.12 -m pip check`, `py -3.12 manage.py makemigrations --check --dry-run`.
- [x] Use `$env:DB_TEST_NAME='test_fluxtrack_hardening_20260930'; py -3.12 manage.py test --noinput`. Require full suite success; explain expected skips. Restore only SRS binary changes caused by tests.
- [x] Update audit with resolution evidence and remaining external verification. Report exact test results, source/docs links and limitations. Leave the branch reviewable locally without publication.


## Completion evidence

Implemented in the local codex/audit-hardening-20260930 branch. Independent browser specification/quality review and server tasks 2–4 specification/quality review passed. Server review additionally fixed draft conflicts, merged move eligibility, UTF-16 declarations, importer lifecycle revalidation and Unicode weekday input.

Full SQL Server suite: 1,418 tests in 171.141 seconds, OK with two existing live-data skips. The late importer/weekday changes additionally passed 37 importer/allocation/schedule tests in 87.597 seconds, no skips. Three Node behavioral scripts passed. Django check, pip check, migration dry-run and diff whitespace checks passed. Test-generated SRS binary restored.

No live migration, deployment, commit or push was performed. Apply ops.0008_push_retry_state during release. The global operational application lock is SQL Server-specific and trades write throughput for consistent allocation; reads remain concurrent. Raw SQL/admin edits bypass service validation. Real browser/device offline UAT, provider delivery, Linux deployment and institutional load/restore verification remain external checks; see the audit follow-up and deploy README.
Final focused importer/allocation/push/deployment verification: 62 tests passed in 85.720 seconds, no skips.

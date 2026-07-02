# Project Research Summary

**Project:** FluxTrack
**Domain:** Faculty attendance + facility utilization PWA (Django 6 + htmx, brownfield -- subsequent milestone on an already-mapped codebase)
**Researched:** 2026-07-02
**Confidence:** HIGH (MEDIUM on the Tailwind v4 / Franken UI build path and on MSSQL runtime behavior -- version compatibility itself is resolved)

## Executive Summary

FluxTrack is a mostly-scaffolded Django 6 + htmx PWA (scan resolver, Faculty check-in, IFO read surface already built and tested) moving into its correctness-and-completeness milestone: MSSQL cutover, a real status-sweep job, Checker verification (online + offline), modality-shift approval, notifications, reporting, and the remaining role surfaces (Guard, Dean, HR), followed by Entra ID SSO and AWS deployment. Across all four research tracks, the codebase's own conventions -- pure decision function plus thin ORM applier, AuditLog on every write, get_policy() over hardcoding, per-view role decorators -- turn out to extend cleanly to every new component: JOB-02's sweep, the modality state machine, and report aggregates are all "one more resolver-shaped module," not a new architectural pattern.

The most consequential finding is that the previously-flagged #1 risk is cleared: mssql-django 1.7.3 (released 2026-06-19) officially supports Django 6.0, so Django==6.0.6 can be pinned with no downgrade to 5.2 needed (5.2 LTS remains a documented fallback only if the runtime spike surprises). What remains genuinely risky is runtime behavior, not version compatibility: SQL Server's case-insensitive default collation can silently merge or duplicate rows that were distinct on SQLite, and mssql-django/pyodbc have open issues around timezone-aware datetime2 round-tripping that can shift Asia/Manila attendance by a full 8 hours if UTC storage is not verified explicitly. Both must be proven with real round-trip tests during the MSSQL spike, before JOB-02 is built on top of them. The second concrete integration risk is the Tailwind v4 / Franken UI 2.1 build path: Franken UI's official install is npm-first and the Tailwind standalone CLI cannot resolve npm plugins, so a short spike (build-time npm on dev/CI, Node-free production) is needed before deploy, not a foregone conclusion.

The research also corrects the sequencing implied by PROJECT.md's flat build order in two ways that materially change phase design. First, the shared notify() write path (promoting web/scan.py:_notify_ifo to ops/notifications.py:notify()) is a hidden prerequisite for both JOB-02's conflict flags and modality's approval notices -- it should land early as a small foundation task, well before the "notifications" slice that only needs to add the read surface (NOTIF-01) and push (NOTIF-02/03). Second, the single highest-risk coupling in the whole milestone is that JOB-02's Absent rule and the existing scan resolver's Absent rule must share one predicate (now > scheduled_start + grace) -- implemented as one extracted function called by both -- or a scan and a sweep will contradict each other on the same session.

## Key Findings

### Recommended Stack

The five not-yet-integrated pieces (MSSQL, Entra SSO, scheduler, web push, Tailwind build) all have HIGH-confidence, version-verified recommendations, with one MEDIUM-confidence integration risk (Tailwind/Franken UI). No new architectural library (Celery, DRF token auth, WebSockets) is warranted -- every piece has a "smallest viable" answer that reuses what already exists in the codebase (e.g., the PushSubscription model already present, so pywebpush is called directly with no wrapper).

**Core technologies:**
- mssql-django 1.7.3 + pyodbc + ODBC Driver 18: Django DB backend for SQL Server -- Microsoft-maintained, certifies Django 6.0, clears the version-pin risk.
- Django 6.0.6 (pinned, tightened from Django>=5.0,<7.0): matches SRS target and sits inside the mssql-django 1.7 support matrix; Django 5.2 LTS is the fallback only if the runtime spike breaks.
- django-allauth 65.18.0 (OpenID Connect, Auth Code + PKCE): Entra ID SSO for a server-rendered app -- keep Django session auth end-to-end, do not introduce a backend-issued JWT layer.
- APScheduler 3.11.x (BlockingScheduler) in its own management command, run as a second, dedicated systemd service -- never started inside Gunicorn workers or AppConfig.ready().
- pywebpush 2.3+ with py-vapid: direct VAPID web push against the existing PushSubscription model; no wrapper library needed.
- Tailwind CSS v4 standalone CLI + Franken UI 2.1: Franken UI 2.1 is built on Tailwind v4 (not v3); resolve the npm-plugin-vs-standalone-binary tension with build-time-only npm, keeping the production runtime Node-free; vendor CDN assets into static/ served by WhiteNoise so the service worker can cache them same-origin.

### Expected Features

Six unbuilt feature areas, all table-stakes for their respective roles (not differentiators to be traded off) -- the domain actual differentiator is that presence is physically verified, not self-reported, and every feature below either protects or extends that property.

**Must have (table stakes):**
- Checker verification UX -- floor view, on-duty gated scan, Verify/Flag/Confirm-empty actions
- Offline scan queue (IndexedDB) with server-side re-validation on replay -- not blind-trust replay
- Modality shift approval (instructor to Dean to auto room-release/assign, lead-time gated)
- In-app notification list (NOTIF-01) plus web push (NOTIF-02) plus mute prefs (NOTIF-03)
- Weekly reporting plus faculty scorecards (pure aggregates, CSV and PDF, graceful degradation)
- Faculty locator (Guard) -- read-only, reuses existing room/schedule join

**Should have (differentiators, already implied by the above):**
- Server-side re-validation of offline scans (the correctness differentiator)
- Priority-queue floor view (oldest-unverified first)
- Auto room-release on modality approval (removes Checker from the release loop)
- Graceful-degradation reporting (one broken aggregate never blanks the page)

**Explicitly out of scope (anti-features, do not build):**
- Background Sync API for offline replay (not supported on iOS Safari/Firefox in 2026)
- WebSockets for live updates (SRS section 2.5 mandates polling only)
- Checker override of auto-Absent (removed with CHK-06; Absent is now final)
- Same-day/emergency modality declaration, email notifications, a general booking/conflict engine, payroll periods/locks

### Architecture Approach

The existing pure-resolver / side-effect-applier split (resolver.py decides, scan.py:_apply writes plus audits plus notifies) is replicated for every new decision surface: scheduling/sweep.py (JOB-02 planner) mirrors resolver.py; scheduling/modality.py mirrors it for the modality state machine; ops/reports.py generalizes the same "pure, independently testable, no ORM writes" contract to report aggregates. The one hard structural rule shaping everything: the scheduler is a separate OS process, so any logic a job needs must live in an importable module the web layer and the job layer both call -- never inside a view function or a management command handle().

**Major components:**
1. scheduling/sweep.py and scheduling/jobs.py -- pure JOB-02 planner plus thin applier (marks Absent, releases rooms, flags conflicts); reuses a shared Absent predicate extracted from resolver.py.
2. scheduling/occupancy.py -- the single writer for room_released_at (release_room()) and single reader for room-free checks (is_room_free()), consumed by JOB-02, force-handover, and modality approval alike.
3. scheduling/modality.py -- pure lead-time eligibility plus find_free_room() (narrow, not a general booking engine) plus approve_request() applier for ModalityShiftRequest.
4. ops/notifications.py -- the single notify() write path (bulk Notification rows plus best-effort VAPID push), replacing the private web/scan.py:_notify_ifo.
5. ops/reports.py -- scope-parameterized (department=None) pure aggregate functions shared by IFO-09, DEAN-04, RPT-04, and JOB-03.
6. config/scheduler.py -- the systemd-run APScheduler bootstrap (django.setup() plus cron triggers to imported job functions only).
7. web/dean.py, web/checker.py, web/guard.py, web/hr.py, web/notifications.py, web/reporting.py -- new thin role surfaces, all following the existing per-view role_required decorator convention.

New code locations recommended by the research (none require a folder restructure -- flat-app layout stays fixed): scheduling/sweep.py, scheduling/occupancy.py, scheduling/modality.py, scheduling/jobs.py, ops/notifications.py, ops/reports.py, ops/jobs.py, config/scheduler.py, web/dean.py.

### Critical Pitfalls

1. MSSQL is case-insensitive by default; SQLite hides duplicate/uniqueness bugs (opaque tokens, faculty email lookups) -- decide per-column collation, test case-variant duplicates on real SQL Server, not SQLite.
2. mssql-django/pyodbc can drop or garble timezone offsets on datetime2 -- an 8-hour Asia/Manila shift is possible; store UTC everywhere, do all grace/Absent math in UTC, write an explicit aware-datetime round-trip test before building JOB-02 on top of it.
3. JOB-02 must be idempotent and never clobber a real outcome -- only transition SCHEDULED sessions past grace to ABSENT; never touch active/completed/already-absent; release rooms off actual completion plus hold window, not raw scheduled_end.
4. Offline Checker queue must re-validate every replayed scan server-side against current state -- blind replay-and-apply (the standard PWA pattern) is explicitly wrong here; unappliable scans are flagged for IFO, not force-applied or dropped.
5. APScheduler started inside Gunicorn workers (or AppConfig.ready()) fires every job N times -- run it as one dedicated, separate systemd process that never gets imported by the web workers.

Two additional pitfalls carry disproportionate blast radius and should stay visible through planning: Entra cutover can lock out all production login if DEBUG=False is flipped before SSO is proven end-to-end (keep one break-glass superuser); and RDS SQL Server Express 10 GB cap, combined with per-write AuditLog rows, needs a retention/pruning job before real usage, not as an afterthought.

## Implications for Roadmap

Based on combined research, the PROJECT.md build order (env -> JOB-02 -> IFO-06 -> Checker -> modality -> notif -> reporting -> Guard/Dean/HR -> auth/deploy) is directionally correct and should be kept, with two refinements: (a) land the notify() write path as a small foundation task inside the "env" phase, not deferred to the "notif" phase, since JOB-02 and modality both need it; (b) treat the Tailwind/Franken UI build spike as part of the final deploy phase, not earlier, since production styling is not on the critical path for correctness work.

### Phase 1: Environment and Platform Foundations
**Rationale:** Clears the version-risk question (mssql-django 1.7.3 supports Django 6.0 -- no downgrade needed) and stands up the two pieces of infrastructure every later phase depends on: the dedicated scheduler process and the shared notification write path.
**Delivers:** Django==6.0.6 pinned, mssql DB_ENGINE branch, MSSQL runtime spike (case-sensitivity plus timezone round-trip tests against real SQL Server), config/scheduler.py scaffold as a second systemd service, ops/notifications.py:notify() write path (_notify_ifo refactor).
**Uses:** mssql-django 1.7.3, pyodbc, ODBC Driver 18, APScheduler 3.11.x (BlockingScheduler, dedicated process).
**Avoids:** Pitfall 1 (collation), Pitfall 2 (timezone/datetime2), Pitfall 6 (N times job execution).

### Phase 2: Correctness Foundations -- JOB-02 status sweep and IFO-06 floor assignments
**Rationale:** PROJECT.md explicit build-order item one; both are hard blockers -- IFO-06 gates Checker on-duty access, JOB-02 makes Absent trustworthy without relying on every session being scanned. Both the Checker floor view and weekly reporting silently mis-count without JOB-02.
**Delivers:** scheduling/sweep.py (pure plan_status_sweep, mirrors resolver.py), scheduling/jobs.py:run_status_sweep() applier, scheduling/occupancy.py:release_room()/is_room_free() as the single occupancy writer/reader, IFO-06 Assignment model plus UI.
**Implements:** Pattern 1 (pure planner plus thin applier), shared Absent predicate extracted from resolver.py and reused by the sweep.
**Avoids:** Pitfall 3 (sweep idempotency/clobbering), Pitfall 5 (multi-worker idempotency -- consider a DB unique constraint over locmem cache).

### Phase 3: Core Attendance Loop -- Checker (online and offline)
**Rationale:** The milestone center of gravity; requires IFO-06 (hard) and a trustworthy JOB-02 (correctness) to already exist.
**Delivers:** on-duty-gated floor view with priority queue (oldest-unverified first, excludes Absent), scan plus Verify/Flag/Confirm-empty actions, IndexedDB offline queue with server-side re-validation on replay and idempotency keys.
**Addresses:** Feature 1 (Checker verification UX), Feature 2 (offline scan queue).
**Avoids:** Pitfall 4 (stale/blind replay), Pitfall 5 (client-timestamp trust, clock skew).

### Phase 4: Modality Shift Approval
**Rationale:** Self-contained and design-complete (modality-shift-approval-design.md); depends on occupancy.release_room() (Phase 2) and notify_ifo (Phase 1), which is why those two are pulled earlier than the flat PROJECT.md order implies.
**Delivers:** ModalityShiftRequest model, scheduling/modality.py (lead-time eligibility plus narrow find_free_room() conflict check plus approve_request() applier), Dean approval view, JOB-01 patch to stamp room_released_at at creation for already-Online recurring sessions.
**Implements:** Pattern 5 (modality state machine reusing room_released_at plus occupancy helper).
**Avoids:** silent partial-apply on Online-to-F2F with no free room (approval fails outright, no invented fallback).

### Phase 5: Notifications -- read surface and push
**Rationale:** NOTIF-01 (in-app list) is a low-risk read surface over rows the write path (Phase 1) is already producing, and should ship early to make Phase 3/4 events (wrong-room, modality approvals) actually visible -- today they are written but invisible. NOTIF-02 (push) is higher-risk platform work and hard-blocks Guard alerts, so it is sequenced deliberately, not bundled with NOTIF-01.
**Delivers:** web/notifications.py in-app polled list, push subscription endpoint plus service-worker push handler (VAPID), per-user mute prefs (NOTIF-03).
**Uses:** pywebpush plus py-vapid direct against the existing PushSubscription model.
**Avoids:** iOS push platform gotchas (user-gesture-triggered permission prompt, Home-Screen-install gating); regressions to service-worker navigation caching (Pitfall 7) when the push handler is added.

### Phase 6: Reporting Engine
**Rationale:** The widest dependency hub -- IFO-09, DEAN-04, HR, and the faculty scorecard all consume the same aggregates -- so build it once. Depends on JOB-02 (Phase 2) for correct absent counts and notify_deans (Phase 1/5) for RPT-02.
**Delivers:** ops/reports.py pure, scope-parameterized aggregate functions; ops/jobs.py:generate_weekly_reports() (JOB-03); CSV plus PDF export with graceful per-aggregate degradation.
**Implements:** Pattern 4 (isolated aggregates, try/except per card at the view boundary).
**Avoids:** week-boundary computed in UTC instead of Manila local; MSSQL-unsafe aggregate SQL (verify GROUP BY / date-truncation on real SQL Server).

### Phase 7: Remaining Role Surfaces -- Dean, Guard, HR
**Rationale:** Thin read-only reuse of Phase 6 aggregates and Phase 3 data; lowest risk and cost in the milestone.
**Delivers:** Dean dashboard (DEAN-04) plus department-scoped reporting, Guard floor monitor plus per-room schedule reuse plus faculty locator (GRD-01..05), HR verified-attendance list plus CSV export.
**Addresses:** Feature 6 (Faculty locator).
**Avoids:** over-exposing live faculty location outside the guard_required surface.

### Phase 8: Auth and Deployment -- Entra SSO, Tailwind build, AWS
**Rationale:** Cutover work belongs last: it must not gate correctness-phase development, and it carries the milestone two production-blast-radius pitfalls (total lockout, build-path risk) that need dedicated verification on staging before flipping DEBUG=False.
**Delivers:** django-allauth OIDC (Auth Code plus PKCE) with Django session auth end-to-end, break-glass superuser, unprovisioned-identity rejection (AUTH-03); Tailwind v4 standalone CLI plus vendored Franken UI assets (build-time npm, Node-free production) replacing the CDN; single EC2 (Gunicorn plus APScheduler as two systemd services) plus RDS SQL Server Express; AuditLog/Notification retention job ahead of the 10 GB Express cap.
**Uses:** django-allauth 65.18.0, Tailwind CSS v4 standalone CLI, Franken UI 2.1.x.
**Avoids:** Pitfall 7 (SW caching navigations/redirects), Pitfall 8 (Entra lockout), Pitfall 9 (implicit session-vs-JWT drift), Pitfall 10 (Express cap / single point of failure).

### Phase Ordering Rationale

- Dependency-driven, not just topical: IFO-06 hard-blocks Checker; JOB-02 occupancy.release_room() is introduced in Phase 2 but consumed by both modality (Phase 4) and force-handover -- building it once early prevents the exact "three writers drift apart" failure the modality design was written to eliminate.
- The notify() write path is pulled forward from its PROJECT.md "notifications" slot into Phase 1, because JOB-02 conflict flags (Phase 2) and modality approval notices (Phase 4) both need it; only the read surface and push (NOTIF-01/02/03) stay in Phase 5.
- Reporting is deliberately late (Phase 6) despite being high-value, because its absent counts are only correct once JOB-02 (Phase 2) has run, and it is most efficiently built once as a shared aggregate layer rather than piecemeal per consuming role.
- Auth/deploy is last (Phase 8) so that Entra ID all-or-nothing lockout risk and the Tailwind/Franken UI build spike are resolved against a feature-complete app on staging, not blocking correctness work earlier in the milestone.

### Research Flags

Needs deeper research during planning:
- **Phase 1 (MSSQL spike):** runtime behavior (collation, datetime2 timezone round-trip, select_for_update support) is unproven even though version compatibility is now resolved -- needs a dedicated spike task, not just a settings change.
- **Phase 8 (Tailwind v4 / Franken UI build):** the npm-plugin-vs-standalone-CLI tension is MEDIUM confidence; needs a short build-step spike before committing to Option A (build-time npm) vs Option B (pre-vendored CSS).
- **Phase 8 (Entra SSO):** must be verified end-to-end against the real project-owned tenant on a staging deploy with DEBUG=False before cutover -- the DEBUG-stub-only-door risk cannot be resolved on paper.

Phases with standard, well-documented patterns (research-phase can likely be skipped):
- **Phase 2 (JOB-02):** directly mirrors the already-built, already-tested resolver.py pattern.
- **Phase 3 (Checker):** offline-first queue pattern is standard PWA practice with one documented deviation (server-side re-validation) already specified in SRS CHK-08.
- **Phase 5 (Notifications):** notify() is a straightforward generalization of the existing _notify_ifo; pywebpush usage is a documented, standard integration.
- **Phase 6 (Reporting):** pure-aggregate-function pattern is the same shape as the resolver; only the MSSQL aggregate-SQL portability needs a quick check inside the Phase 1 spike.
- **Phase 7 (Guard/Dean/HR):** thin reuse of existing views/decorators and Phase 6 aggregates.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH (MEDIUM on Tailwind/Franken UI build path) | mssql-django, Django, allauth, APScheduler, pywebpush versions verified against PyPI/official sources; Franken-UI-on-Tailwind-v4 confirmed but exact build ergonomics need a spike. |
| Features | HIGH | Grounded in in-repo, current design specs (modality-shift-approval-design.md, dean-dashboard-design.md), docs/USE_CASES.md, and .planning/PROJECT.md -- exact contracts, not inference. |
| Architecture | HIGH | Grounded directly in the mapped codebase (.planning/codebase/ARCHITECTURE.md, CONVENTIONS.md) and the three approved design specs; every recommendation extends an existing precedent rather than introducing a novel pattern. |
| Pitfalls | HIGH | Library-specific claims verified against mssql-django/pyodbc/APScheduler docs and issue trackers; domain claims cross-checked against the codebase own CONCERNS.md and the resolver/scan code. |

**Overall confidence:** HIGH, with two explicitly flagged MEDIUM areas (Tailwind/Franken UI build ergonomics; MSSQL runtime behavior as distinct from version compatibility) that are already scheduled as spikes in Phase 1 and Phase 8 above.

### Gaps to Address

- **Franken UI 2.1 / Tailwind v4 build path:** genuine npm-vs-standalone-CLI tension not fully resolved by desk research -- resolve with a short build-step spike in Phase 8 before locking in Option A (build-time npm, Node-free production) vs Option B (pre-vendored CSS).
- **MSSQL runtime behavior:** version compatibility is resolved, but collation and timezone round-trip behavior on the exact mssql-django 1.7.3 version must be proven with real tests in Phase 1, not assumed from the general matrix.
- **SRS drift:** the SRS still references MySQL 8.0 in places while the deployment decision is SQL Server Express, and describes a backend-issued-JWT auth model that predates the Django-templates pivot -- both need reconciliation in the planned SRS v1.2 revision (documentation work, not code, but should not be left implicit through the milestone).
- **Session-vs-JWT decision:** research recommends Django session auth throughout (matches the real server-rendered architecture); this should be explicitly recorded as a decision in SRS v1.2 before Entra SSO code is written, so AUTH-05 (deactivation invalidates access) stays trivially satisfiable.

## Sources

### Primary (HIGH confidence)
- mssql-django 1.7: Django 6.0, SQL Server 2025 -- Microsoft Community Hub
- mssql-django v1.7.3 -- PyPI, Django 3.2-6.0
- Django 6.0 released -- djangoproject.com
- Django | endoflife.date -- 5.2 LTS to Apr 2028
- OpenID Connect / Microsoft -- django-allauth docs
- django-allauth v65.18.0 -- PyPI
- APScheduler FAQ -- readthedocs (no interprocess sync, duplicate-execution guidance)
- pywebpush -- PyPI
- mssql-django #371 -- USE_TZ plus non-UTC TIME_ZONE datetime conversion
- pyodbc #810 / #1141 -- timezone-aware datetime / DATETIMEOFFSET round-tripping
- Collations and case sensitivity -- Microsoft Learn
- .planning/codebase/ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, CONCERNS.md -- existing mapped architecture
- scheduling/resolver.py, web/scan.py, ops/models.py, ops/policy.py, verification/models.py -- read directly
- docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md, 2026-07-02-dean-dashboard-design.md, 2026-07-02-deployment-and-dev-practice-design.md -- approved design specs
- docs/USE_CASES.md, .planning/PROJECT.md

### Secondary (MEDIUM confidence)
- Franken UI 2.1 Installation / Theming docs -- built on Tailwind v4, partly gated content
- Standalone CLI: Tailwind without Node.js
- django-apscheduler -- GitHub, dedicated-process / duplicate-execution guidance
- Offline-first PWA sync/queue pattern sources (LogRocket 2025, MS Learn Background Syncs) -- Background-Sync-not-in-Safari confirmed across multiple sources
- Web push / VAPID plus iOS constraint sources (MagicBell, MDN) -- Home-Screen-install gating, user-gesture permission requirement

---
*Research completed: 2026-07-02*
*Ready for roadmap: yes*

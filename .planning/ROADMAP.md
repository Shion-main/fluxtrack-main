# Roadmap: FluxTrack

## Overview

FluxTrack is a mostly-scaffolded Django 6 + htmx attendance PWA (scan resolver,
Faculty check-in, and IFO read surface already shipped and tested) entering its
correctness-and-completeness milestone. The journey runs dependency-first: prove
the MSSQL runtime (no timezone drift, no case-folding surprises), then build the
correctness foundations every later feature trusts — a shared `notify()` write
path, a status sweep that makes "Absent" trustworthy without relying on scans,
and one dedicated scheduler process. On that base we build the Checker
verification loop (gated by floor assignments), the modality-shift approval
workflow (auto room-release/assign), the notification read/push surface, and a
single shared reporting-aggregate layer that powers every dashboard. The
remaining role surfaces (Guard, IFO ops, Faculty self-service, SysAdmin) come
next, and finally the production cutover — Entra ID SSO, a Node-free Tailwind
build, and AWS deploy — lands last so it never blocks feature work.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: MSSQL Environment & Data Foundation** - Prove SQL Server runtime (timezone + collation round-trips) and run existing import/materialize against it (completed 2026-07-03; 4/4 criteria verified, see 01-VERIFICATION.md)
- [x] **Phase 2: Correctness Foundations** - Shared notify() write path, JOB-02 status sweep + occupancy release, single scheduler process (completed 2026-07-02)
- [x] **Phase 3: Duty Assignments & Checker Verification** - Floor assignments gate an on-duty Checker's online + offline room verification (completed 2026-07-03)
- [x] **Phase 4: Modality Shift Approval & SRS v1.2** - Lead-time-gated faculty request, Dean approval, auto room-release/assign, SRS revision (completed 2026-07-03)
- [x] **Phase 04.1: Real-Data Integration — Full 2T SY2025-26 Term Load** (INSERTED) - Harden the importer to read the real .xlsx sources and load the whole term: 114-room master (names+capacities), online/blended/gym meetings, ~200 deduped instructors, ~2,021 schedules, materialized into a live checkable term (completed 2026-07-07)
- [x] **Phase 04.2: Co-Scheduled Session Attendance** (INSERTED) - Attendance handling for one instructor teaching 2+ sections at the same time in different rooms (129 slots, 54/200 profs): a single scan/verification must cover the co-scheduled sibling sessions so the sweep never falsely marks them Absent (completed 2026-07-07; verification passed after same-day gap closure — criterion #3 online coverage now 152/152 via D-01 refinement #2, online merge key = faculty + exact start; see 04.2-VERIFICATION.md)
- [x] **Phase 5: Notifications — Read Surface & Web Push** - In-app polled list + VAPID web push + per-user mute preferences (completed 2026-07-15)
- [x] **Phase 6: Reporting Engine & Reporting Surfaces** - One shared aggregate layer powering weekly report, scorecards, IFO/Dean/HR dashboards (completed 2026-07-15)
- [x] **Phase 06.1: Room Utilization & IFO-09 Closure** (INSERTED) - The facility-utilization half of the product: room-hours booked vs used, wasted room-hours, and a day x block heat grid. Closes the IFO-09 room-occupancy card that shipped as a second attendance metric. (completed 2026-07-19; CSV export deferred)
  **Goal:** IFO can read how much physical room capacity the campus actually used versus booked, see where and when it went unused, and act on the reclaimable hours — with the SRS's room-occupancy card restored to the dashboard.
  **Requirements:** IFO-09
  **Plans:** 7 plans across 6 waves
  Plans:

  - [x] 06.1-01-PLAN.md — Shared block ladder + the T1 room-hours aggregate (booked/used/available/wasted)
  - [x] 06.1-02-PLAN.md — Room-shaped test fixture + DB-backed aggregate tests + seed sanity recipe
  - [x] 06.1-03-PLAN.md — IFO-09 closure: five-card KPI row with Room Occupancy, plus the paginate isolation fix
  - [x] 06.1-04-PLAN.md — T2 heat grid + block saturation aggregates
  - [x] 06.1-05-PLAN.md — Per-room breakdown + building/floor rollup + least-used ranking
  - [x] 06.1-06-PLAN.md — The /ifo/utilization page: heat grid, tables, WCAG-AA heat scale
  - [ ] 06.1-07-PLAN.md — Per-room utilization CSV export — ◷ **DEFERRED** (droppable by design; nothing depends on it)
- [x] **Phase 7: Remaining Operational Surfaces** - Guard monitor/locator, IFO room & booking ops, Faculty self-service, job monitoring (completed 2026-07-19)

### Milestone v1.3 — "Operational Trust" (post-audit, added 2026-07-20)

From `docs/AUDIT-2026-07-19.md` (five-lens SRS audit + first-principles mission/UI
addendum). Sequenced mission-critical-first; deploy renumbered to run last. The old
standalone Phase 8 (deploy) becomes the **expanded Phase 15**.

- [x] **Phase 9: Attendance Trust Under Real Operations** (CRITICAL) - CANCELLED status, IFO class-suspension + holiday/break entry, sweep honors them, real Absent-correction path (A1/A2/A5) — completed 2026-07-20; 5/5 criteria, 30 new tests, suite 965 green
- [x] **Phase 10: Campus Structure Management** - Building/Floor CRUD, room out-of-service, single-schedule edit (A7/A9 + building gap) — completed 2026-07-20; 3/3 criteria, 29 tests, suite 994 green
- [x] **Phase 11: Metrics the Mission Promises** - Lateness, verification-coverage, utilization depth + deferred CSV export (A3/A6/A8) (completed 2026-07-20)
- [ ] **Phase 12: Term Lifecycle** - Close/archive a term + create/activate the next without destroying history (A4)
- [ ] **Phase 13: UX Finish** - Custom error pages, phone shell-jump fix, profile reachability, login navy, global htmx errors, PWA theme (B1-B6)
- [ ] **Phase 14: Correctness & Concurrency Hardening** - Booking/schedule oracle, room-preferring resolver, select_for_update, offline-replay retargeting (M3/M5/M6/H3)
- [ ] **Phase 15: Deploy Hardening & Cutover** (was Phase 8, expanded) - Entra SSO + EC2/RDS + Tailwind build, PLUS shared cache, HTTPS/proxy config, media split, CDN vendoring, scheduler resilience, logging, retention/backups
- [ ] **Phase 16: Documentation Pass** - SRS v1.3 (incl. shadcn-via-Franken), traceability restore, PROJECT.md refresh

## Phase Details

### Phase 1: MSSQL Environment & Data Foundation

**Goal**: FluxTrack runs correctly on SQL Server at the scale already validated on SQLite, with no timezone drift and no case-folding surprises — the proven base every later phase builds on.
**Depends on**: Nothing (first phase)
**Requirements**: ENV-01, ENV-02
**Success Criteria** (what must be TRUE):

  1. The app boots and serves every existing surface with `DB_ENGINE=mssql` against SQL Server Express, Django pinned to 6.0.6 (mssql-django 1.7.3, no downgrade).
  2. A timezone-aware attendance timestamp written then read back on SQL Server shows the same Asia/Manila instant — proven by an explicit aware-datetime round-trip test (no 8-hour drift).
  3. Case-variant values that were distinct on SQLite (opaque QR tokens, faculty emails) do not silently collide or duplicate on SQL Server — proven by a collation round-trip test.
  4. Registrar CSV import + session materialization produce the same sessions on MSSQL as on SQLite at the R3-slice scale.

**Plans**: 3 plans

Plans:

- [x] 01-01-PLAN.md — MSSQL settings branch, dependency pins & environment bring-up (migrate + seed on SQL Server) [Wave 1]
- [x] 01-02-PLAN.md — Datetime round-trip (no 8h drift) & R3 import/materialize parity tests [Wave 2]
- [x] 01-03-PLAN.md — Case-sensitive collation on qr_token/manual_code & collation round-trip tests [Wave 2]

### Phase 2: Correctness Foundations

**Goal**: "Absent" is trustworthy without relying on scans, contradictory room occupancy is flagged to IFO, every event flows through one notification write path, and all jobs run from one scheduler process. (Timer-based auto-release cut 2026-07-03; room release moves to the modality-approval flow in Phase 4.)
**Depends on**: Phase 1
**Requirements**: NOTIF-00, JOB-02a, JOB-02b, JOB-02c, ENV-04
**Success Criteria** (what must be TRUE):

  1. A session nobody scans into is marked Absent within one sweep interval, using the same grace predicate the live scanner uses — a scan and the sweep never disagree on the same session.
  2. Contradictory room occupancy raises a single (deduped) IFO room-conflict notification. The shared `release_room()` helper exists and is tested but is invoked only by the modality-approval flow (Phase 4), not on a timer — timer-based auto-release was cut 2026-07-03.
  3. Every notification in the system is created by one shared `notify()` write path — the ad-hoc `_notify_ifo` is gone and no other inline notifier remains.
  4. The materialize, sweep, and weekly-report jobs run automatically from one dedicated scheduler process, never duplicated across web workers, with last-run status recordable.
  5. Re-running the sweep never changes an already-decided session (idempotent — active, completed, and already-Absent sessions are untouched).

**Plans**: 5/5 plans complete

Plans:

- [x] 02-01-PLAN.md — Shared no-show grace predicate extraction (JOB-02a) [Wave 1]
- [x] 02-02-PLAN.md — Shared notify() write path + scan migration (NOTIF-00) [Wave 1]
- [x] 02-03-PLAN.md — Status sweep + deduped room-conflict flags (JOB-02b, JOB-02c) [Wave 2]
- [x] 02-04-PLAN.md — release_room() occupancy helper, built for MOD-03 (JOB-02c) [Wave 2]
- [x] 02-05-PLAN.md — Dedicated APScheduler process + JobRun observability (ENV-04) [Wave 3]

### Phase 3: Duty Assignments & Checker Verification

**Goal**: An on-duty Checker can verify physical presence room-by-room, online and offline, and only while actually assigned to that floor.
**Depends on**: Phase 2 (IFO-06 gates on-duty; trustworthy Absent from JOB-02; notify() for flags)
**Requirements**: IFO-06, CHK-01, CHK-02, CHK-03, CHK-04, CHK-05, CHK-07, CHK-08
**Success Criteria** (what must be TRUE):

  1. IFO can assign a Checker or Guard to a floor by shift or standing posting, and only that assignment grants on-duty powers.
  2. An off-duty or wrong-floor Checker scan is refused with a clear reason; an on-duty scan returns the room's current session state plus the scheduled faculty member's photo for identity matching.
  3. A Checker can Verify, Flag identity mismatch, Flag not present, or Confirm empty — a Verify marks the session checker-verified, and a flag is surfaced to IFO and HR (no dispute workflow).
  4. The floor view shows coverage progress and an oldest-unverified-first priority queue of active sessions, excluding Absent sessions.
  5. A scan made offline replays on reconnect and is re-validated server-side against current state before applying — never blindly trusted — or flagged for IFO if it no longer applies.
  6. For an online session, an on-duty Checker is notified and redirected to the class's public MS Teams link to verify the faculty is conducting the session; that Checker verification marks the online session present (the online analog of a room scan). This is what lets online sessions join the JOB-02 sweep (Phase 2 excludes online until this exists).

> **Captured 2026-07-03 (from user, during Phase 2 discussion):** online attendance is *Checker*-verified via the class's public MS Teams link, not faculty-self-declared. Amends **CHK-02** (for online, return/redirect to the Teams link instead of room state) and **CHK-03** (Checker verification actions apply to online sessions). Reconcile with **FAC-08** (Phase 7) which currently has the faculty self-start online. Online sessions get the same grace period as F2F; the Phase 2 sweep excludes them from Absent-marking until this Phase 3 verification path ships.

**Plans**: 6/6 plans complete

Plans:

- [x] 03-01-PLAN.md — Foundation: AssignmentScope + Session.online_checker + retire dead actions + pure decision cores (resolve_checker_scan, distribute_online_sessions) [Wave 1]
- [x] 03-02-PLAN.md — Checker room scan + F2F/Blended Verify / Verified-empty / note-required Flags → IFO+HR (CHK-01/02/03/04/05) [Wave 2]
- [x] 03-03-PLAN.md — IFO assignment UI (floor + online duty) + round-robin online-session pre-assignment (IFO-06) [Wave 3]
- [x] 03-04-PLAN.md — Checker floor board: color cards, coverage %, oldest-first priority queue, Absent excluded, htmx-polled (CHK-07) [Wave 4]
- [x] 03-05-PLAN.md — Online verification via Teams link (Verify activates session) + remove sweep online exclusion + rewrite sweep tests (CHK-02/03, ROADMAP #6) [Wave 5]
- [x] 03-06-PLAN.md — Offline IndexedDB queue + re-validated replay endpoint (apply-or-flag, idempotent) (CHK-08) [Wave 6]

### Phase 03.1: Authentication — Entra ID SSO (local-dev proof) (INSERTED)

**Goal:** Wire real Microsoft Entra ID sign-in (Authorization Code + PKCE) into the running Django app on localhost as the real auth path that replaces the DEBUG dev-login stub, proven end-to-end against the project-owned MMCM tenant: a bound faculty account signs in and lands on its role-home, an unprovisioned tenant account is refused, and the dev-login stub + superuser break-glass still work. Local-dev proof only — production https redirect, secret rotation, and staging cutover stay in the deploy phase.
**Requirements**: none mapped in ROADMAP; advances AUTH-01, AUTH-03, AUTH-05 locally (acceptance anchored on CONTEXT D-09). See 03.1-CONTEXT.md.
**Depends on:** Phase 3
**Plans:** 4/5 plans executed

Plans:
**Wave 1**

- [x] 03.1-01-PLAN.md — Install social-auth-app-django, add the PKCE mixin backend, wire the settings block + `auth/` URL include, migrate social_django (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03.1-02-PLAN.md — Custom pipeline (deny-unprovisioned + write azure_oid, with security audit) and the `link_entra` command (Wave 2)
- [x] 03.1-03-PLAN.md — Dev-login coexistence fix (name ModelBackend), always-visible Microsoft button, refreshed `.env.example` (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03.1-04-PLAN.md — Wave-0 automated tests: PKCE/wiring/deny/oid/link_entra + dev-login coexistence + logout (Wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [ ] 03.1-05-PLAN.md — Manual UAT gate: real Entra round-trip, live unprovisioned refusal, break-glass under DEBUG=False (D-09) (Wave 4) — ◷ **DEFERRED / to be continued** (begin-view 405 fixed in `c73a123`; live proof blocked on Entra redirect-URI registration for app `1610c487…`; see `03.1-UAT.md`)

### Phase 4: Modality Shift Approval & SRS v1.2

**Goal**: Faculty can request a lead-time-gated modality shift that a Dean approves, with rooms auto-released or auto-assigned, and the SRS brought back in sync with reality.
**Depends on**: Phase 2 (release_room, notify, JOB-01 extraction). Can run parallel to Phase 3.
**Requirements**: MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, DOC-01
**Success Criteria** (what must be TRUE):

  1. A faculty member can submit a modality-shift request (F2F/Blended ↔ Online) for a single or recurring session at least `modality_shift_lead_days` (default 2) ahead; a too-late request is refused.
  2. The request routes to the faculty member's department Dean, who can approve or reject with a reason; the faculty member can withdraw while still pending.
  3. Approving a →Online shift turns the affected session(s) Online and releases the room immediately (`room_released_at` stamped, not held on the timer); newly materialized Online sessions are born released.
  4. Approving a →F2F/Blended shift auto-assigns a free room in the same building, or fails outright with a clear reason if none is free (no silent partial apply); IFO is notified informationally.
  5. The SRS is revised to v1.2 — new MOD area, removed CHK-06, amended FAC-07/CHK-03, RPT-02-notifies-Deans, and `modality_shift_lead_days` in the policy register — in both `.md` and `.docx`.

**Plans**: 8/8 plans complete

Plans:

**Wave 1**

- [x] 04-01-PLAN.md — ModalityShiftRequest/Item models + status enum + modality_shift_lead_days policy default + shared test fixtures [Wave 1]
- [x] 04-02-PLAN.md — DOC-01: SRS v1.2 edit map + pypandoc_binary install (gated) + regenerate_srs_docx command [Wave 1]

**Wave 2** *(blocked on 04-01)*

- [x] 04-03-PLAN.md — ops/availability.py room-free query: half-open overlap, building-scoped, request-aware (D-18), faculty-conflict (D-17) [Wave 2]

**Wave 3** *(blocked on 04-01, 04-03)*

- [x] 04-04-PLAN.md — services: lead-time gate (D-02) + Dean routing (D-09) + in-window scope (D-01/D-19) + submit/withdraw/reject [Wave 3]

**Wave 4** *(blocked on 04-04)*

- [x] 04-05-PLAN.md — services: approval consequence — →Online release (MOD-03), →F2F assign/deny (MOD-04/D-07), time-move (D-16/D-17), reserve (D-18), notify (MOD-05) [Wave 4]

**Wave 5** *(blocked on 04-05)*

- [x] 04-06-PLAN.md — materialize_sessions born-released/born-assigned hook (D-04/D-18) [Wave 5]
- [x] 04-07-PLAN.md — Faculty availability-first submit picker + my-requests + withdraw + FAC-07 retirement (MOD-01/05/06) [Wave 5]

**Wave 6** *(blocked on 04-05, 04-07)*

- [x] 04-08-PLAN.md — Dean approval queue + approve/reject (dean_required, department-scoped) (MOD-02/04) [Wave 6]

### Phase 04.1: Real-Data Integration — Full 2T SY2025-26 Term Load (INSERTED)

**Goal**: FluxTrack's live term is the real 2nd Term SY 2025-2026 offering — the whole thing, not a slice. The hardened importer reads the registrar's real `.xlsx` exports directly, loads the full 114-room master (real names + capacities) plus every scheduled room, creates one deduped account per instructor (~200), and materializes ~2,021 real class schedules (F2F, blended, and online) into dated, checkable sessions — with a reconciliation report proving every one of the 1,211 offering rows is accounted for and nothing is silently dropped.
**Requirements**: none newly mapped; carries ENV-02 from R3-slice to full-term scale and unblocks the reporting phases (Phase 6) that need real data. See 04.1-CONTEXT.md for the 10 locked decisions.
**Depends on**: Phase 1 (MSSQL import/materialize base), Phase 4 (approved-shift materialize hook must survive the full load).
**Success Criteria** (what must be TRUE):

  1. The importer reads the real `.xlsx` sources directly (stdlib zip/XML, no new dependency) — no manual CSV re-export step.
  2. Online and blended and gym meetings are loaded, not skipped: ~1,100 sections / ~2,021 schedule rows / ~200 instructors / ~213 rooms, versus the 483/806 the old CSV-only importer produced.
  3. Rooms carry real names and capacities from the 114-room master; every room maps to the right building via the explicit R/A/GYM/V prefix table, with P/U/typo codes parked in a flagged "Unassigned" building — nothing silently dropped.
  4. Each meeting's modality is stamped by its room (physical → f2f/blended/scannable, virtual → online/checker-verified); a blended course yields both.
  5. Instructors are deduped (email, then normalized name) to one account each and are connected to every one of their materialized sessions; the ~10 email-less instructors are flagged as unable to authenticate until an email is supplied.
  6. A reconciliation report balances: 1,211 offering rows = schedules created + roomless-TBA-flagged + online-no-room + no-schedule-string; and an F2F, a blended, and an online class each appear on the correct instructor's faculty schedule and are checkable.

**Plans**: 4/4 plans complete

Plans:

- [x] 04.1-01-PLAN.md — Stdlib .xlsx reader + pure parse/classify/normalize/modality + reconcile() four-bucket partition (+ parser unit tests) [Wave 1]
- [x] 04.1-02-PLAN.md — load_room_master (114 named rooms + capacities via prefix map) + reversible reset_term guard [Wave 2]
- [x] 04.1-03-PLAN.md — Harden import_offerings: xlsx input, kept online/gym, per-meeting modality, instructor dedup, roomless-TBA, reconciliation report [Wave 2]
- [x] 04.1-04-PLAN.md — Run reset→room-master→import→materialize --days 14 on LocalDB; assert scale + F2F/blended/online spot check + human verify [Wave 3]

### Phase 04.2: Co-Scheduled Session Attendance (INSERTED)

**Goal**: One instructor who teaches two or more sections at the same time in different rooms can prove presence for all of them with a single check-in — the sweep never falsely marks a co-scheduled sibling session Absent.
**Depends on**: Phase 2 (JOB-02 sweep + grace predicate), Phase 3 (checker verification + online path), Phase 04.1 (the real term that exposed the pattern at scale).
**Discovered**: 2026-07-07, during Phase 04.1 live-load verification — logging in as the real professor GARAY surfaced that his sections MMA116-1-A301 (46 enrolled, A408-A) and A302 (24 enrolled, A408-B) meet at the same M/W 3:45 slot in the two halves of a divisible room. He can only scan one room, so the other session would be marked Absent by the sweep.
**Scale of the pattern**: 129 instructor+day+time slots hold 2+ concurrent sections, across 54 of 200 instructors (~27%) — physical (divisible-room halves like A408-A/B) and online (shared Teams link across sibling V-rooms).
**Not a data defect**: Phase 04.1 loaded the sections faithfully; merging them in-data would destroy their distinct rosters/section identity. The fix belongs in the attendance layer.
**Success Criteria** (what must be TRUE):

  1. A faculty scan/check-in that resolves one session also satisfies its co-scheduled sibling sessions (same faculty, same date, overlapping time) — all are marked present from the single event.
  2. The JOB-02 sweep never marks a session Absent when a co-scheduled sibling for the same faculty at that time is Present (or was checked in).
  3. The online analog holds: one Checker verification of a merged online class (shared Teams link) covers the co-scheduled online siblings.
  4. Non-co-scheduled sessions are unaffected — a genuinely missed class is still marked Absent as today.
  5. Reporting/rosters still see the sections as distinct (the fix is attendance-only; no data merge).

**Design options to weigh at plan time** (A recommended): (A) one scan marks the whole co-scheduled group present; (B) sweep exemption when a sibling is present; (C) manual checker/IFO correction only. — **Chosen: A** (propagate present; sweep unchanged by construction).

**Plans**: 4/4 plans complete
**Wave 1**

- [x] 04.2-01-PLAN.md — Merge core: pure D-01 detector + CheckinMethod.MERGED migration + GARAY fixture + atomic propagation helpers (present/absent) [Wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04.2-02-PLAN.md — Faculty scan seam: propagate present on CHECKED_IN + force-handover in one transaction [Wave 2]
- [x] 04.2-03-PLAN.md — Checker online seam: online Verify propagates present, online Flag-not-present propagates ABSENT; F2F record-only [Wave 2]
- [x] 04.2-04-PLAN.md — Sweep no-change confirmation (criteria #2/#4/D-08) + audit_merge_coverage command (empirical online #3) [Wave 2]

### Phase 5: Notifications — Read Surface & Web Push

**Goal**: The events already being written by `notify()` become visible to every role, in-app and via push, respecting mute preferences.
**Depends on**: Phase 2 (notify() write path emitting rows). Consumes events from Phases 3 and 4.
**Requirements**: NOTIF-01, NOTIF-02, NOTIF-03
**Success Criteria** (what must be TRUE):

  1. Every role sees a polled in-app notification list reading the `Notification` rows created by `notify()`.
  2. A subscribed client receives a web-push (VAPID) for key events (wrong-room, force handover, room conflict, weekly report ready) even with the tab closed.
  3. A user's mute preferences suppress muted notifications from both the in-app list and push.
  4. A failed push to a dead endpoint never breaks the scan, approval, or job that triggered it.

**Plans**: 5/5 plans executed — COMPLETE

Plans:

- [x] 05-01-PLAN.md — Notification foundation: mute model + pushed_at + single category->type map + helpers (D-04/D-05/D-06)
- [x] 05-02-PLAN.md — Web push dependency (pywebpush) + VAPID config/keypair + legitimacy gate (NOTIF-02)
- [x] 05-03-PLAN.md — Fault-isolated push delivery: scheduler push_outbox job + 410/404 pruning (NOTIF-02, criterion #4)
- [x] 05-04-PLAN.md — In-app read surface: context processor, polled bell + dropdown + full page, auto-read, mute UI (NOTIF-01/NOTIF-03)
- [x] 05-05-PLAN.md — Web push client: SW push handlers, subscribe flow + soft pre-prompt, bell mounted in both shells (NOTIF-01/NOTIF-02)

### Phase 6: Reporting Engine & Reporting Surfaces

**Goal**: One shared, independently tested aggregate layer powers the weekly report, faculty scorecards, and every dashboard (IFO, Dean, HR) — built once, consumed everywhere.
**Depends on**: Phase 2 (JOB-02 correct absent counts), Phase 5 (push for report-ready)
**Requirements**: RPT-01, RPT-02, RPT-03, RPT-04, RPT-05, IFO-09, DEAN-01, DEAN-02, DEAN-03, DEAN-04, HR-01, HR-02, HR-03
**Success Criteria** (what must be TRUE):

  1. A Weekly Consolidated Attendance Report generates per department — one row per faculty (scheduled, held, absent, attendance %, checker-verified) plus itemized absences — from pure, independently tested aggregates, exportable as CSV and printable PDF.
  2. The faculty scorecard, the IFO-09 dashboard, and the Dean dashboard (DEAN-04) all compute from the same shared aggregates over a selectable range, with faculty-scorecard drill-down.
  3. A Dean's access is read-only and scoped to their department(s); they can view and export their weekly report, which auto-generates weekly (JOB-03) and on demand, is stored, and notifies IFO and the relevant Dean(s).
  4. HR can view verified session-level attendance, filter/search by faculty, department, date range, and term, and export it as CSV for external payroll.
  5. A single failing aggregate shows an error in its own card while the rest of the page still renders.

**Plans**: 7/7 plans complete

Plans:

**Wave 1**

- [x] 06-01-PLAN.md — Pure aggregate layer (faculty_attendance/dept_summary/faculty_scorecard/safe_card) + reporting fixture + unit tests (RPT-01/04/05) [Wave 1]
- [x] 06-02-PLAN.md — ReportLab package-legitimacy gate + install (RPT-03 dependency) [Wave 1]

**Wave 2** *(blocked on Wave 1)*

- [x] 06-03-PLAN.md — CSV + PDF render layer (build_csv/build_pdf) + shared CSV-injection neutralizer (RPT-03) [Wave 2]
- [x] 06-04-PLAN.md — IFO-09 dashboard + faculty-scorecard drill-down + per-card isolation (IFO-09/RPT-04/05) [Wave 2]

**Wave 3** *(blocked on Wave 2)*

- [x] 06-05-PLAN.md — Weekly report generation + JOB-03 stub fill + notify IFO+Dean(s) + on-demand command (RPT-02) [Wave 3]
- [x] 06-06-PLAN.md — Dean dashboard + dept-scoped reporting/scorecard + CSV/PDF export (read-only, IDOR-safe) (DEAN-01/02/03/04) [Wave 3]

**Wave 4** *(blocked on Wave 3)*

- [x] 06-07-PLAN.md — HR session-level attendance list + faculty/dept/date/term filters + streaming payroll CSV export (HR-01/02/03) [Wave 4]

### Phase 7: Remaining Operational Surfaces

**Goal**: Complete the remaining role surfaces — Guard monitoring/locator, IFO room and booking operations, Faculty self-service, and scheduled-job monitoring.
**Depends on**: Phase 5 (push for Guard alerts), Phase 2 (occupancy for IFO manual release). Reuses Phase 6 views.
**Requirements**: GRD-01, GRD-02, GRD-03, GRD-04, GRD-05, IFO-01b, IFO-02, IFO-03b, IFO-05, IFO-08, FAC-08, FAC-11, FAC-12, SYS-04
**Success Criteria** (what must be TRUE):

  1. A Guard sees a live polled room-status monitor and per-room schedule for assigned floor(s), can locate a faculty member (current room/course/end time, or "Online — not on campus" / "Not in a class" + next class), receives debounced push alerts, and has no write access anywhere.
  2. IFO can create/edit/delete rooms from a dedicated non-admin UI, rotate a room's QR token + six-digit code (audit-logged, invalidating old posters), and import schedules by CSV upload with validation and conflict reporting.
  3. IFO can create/cancel conflict-checked ad-hoc bookings and manually release a held room, resolving room-conflict notifications.
  4. A faculty member can start an Online session via "Verify & Start" with a valid MS Teams link (no QR), view their own attendance history including Checker flags, and manage their profile photo and notification preferences.
  5. A System Admin can monitor scheduled-job status (last run, success/failure, rows affected).

**Already shipped out-of-band** (audited 2026-07-18, during UI-elevation work): SYS-04, GRD-01, GRD-03 (labelled GRD-02 in code — corrected by 07-01), and the notification-preferences half of FAC-12. The 12 plans below cover only the 11 remaining requirements.

**Out of scope, deferred to an inserted Phase 06.1 after Phase 07 ships**: room utilization / IFO-09 reporting aggregates (unfinished Phase 06 scope).

**Plans**: 12 plans across 10 waves

Plans:

**Wave 1**

- [x] 07-01-PLAN.md — Guard read-only enforcement (GRD-05), GRD-02/GRD-03 label correction, shared `web/room_state.py` extraction [Wave 1]
- [x] 07-02-PLAN.md — data foundations: `Booking.room` to PROTECT (D-19), four-relation room-delete probe (D-17/D-20), collision-safe `manual_code` minter (live intermittent defect), `ImportStaging` model + staging service (D-12) [Wave 1]

**Wave 2**

- [x] 07-03-PLAN.md — IFO room CRUD with named delete refusal (IFO-01b) [Wave 2]

**Wave 3**

- [x] 07-04-PLAN.md — QR token + six-digit code rotation, confirm then reprint (IFO-02) [Wave 3]

**Wave 4**

- [x] 07-05-PLAN.md — Manual room release + open-conflicts surface + `release_room` invariant update (IFO-08) [Wave 4]

**Wave 5**

- [x] 07-06-PLAN.md — Ad-hoc booking create/cancel, conflict-checked by `room_is_free` (IFO-05) [Wave 5]

**Wave 6**

- [x] 07-07-PLAN.md — Schedule import by upload, preview then commit; establishes the multipart house pattern (IFO-03b) [Wave 6]

**Wave 7**

- [x] 07-08-PLAN.md — Profile photo upload: validate, re-encode, EXIF-strip (FAC-12) [Wave 7]

**Wave 8**

- [x] 07-09-PLAN.md — Online Verify & Start with a pasted Teams link (FAC-08) [Wave 8]

**Wave 9**

- [x] 07-10-PLAN.md — Faculty attendance history, read-only, Checker flags visible (FAC-11) [Wave 9]

**Wave 10**

- [x] 07-11-PLAN.md — Guard per-room schedule, floor-authorized (GRD-02) [Wave 10]
- [x] 07-12-PLAN.md — Coalesced guard push fan-out from the sweep (GRD-04) [Wave 10]

### Phase 9: Attendance Trust Under Real Operations  *(CRITICAL)*

**Goal**: The attendance record survives real Philippine-campus operations — a class suspension (typhoon/LGU declaration) or a holiday never mass-marks the campus Absent, IFO can declare both without a superuser, and a wrongly-Absent record has a real audited correction path instead of a UI message that lies.
**Depends on**: Phase 2 (sweep + grace predicate). Nothing new.
**Requirements**: A1, A2, A5 (audit addendum); restores part of IFO-04.
**Success Criteria** (what must be TRUE):

  1. A terminal `CANCELLED` session status exists; a cancelled/suspended meeting is neither Absent nor held nor counted as booked in any report or utilization number.
  2. IFO can suspend classes for a date or date range (optionally building-scoped): affected already-materialized SCHEDULED sessions flip to CANCELLED (audit-logged), and future materialization skips those dates.
  3. `sweep_no_shows` honors `AcademicBreak` AND suspensions — no session on a covered date is ever marked Absent (closes the core typhoon-day defect).
  4. IFO can create/edit/delete academic breaks & holidays from the console (no Django admin); sweep + materialize both respect them.
  5. A checker or IFO admin can correct a wrongly-Absent session (reinstate), audit-logged; the faculty "a Checker can correct it" message becomes true or is rewritten to match reality.

**Plans**: TBD (to be created by /gsd-plan-phase)

### Phase 10: Campus Structure Management

**Goal**: IFO can manage the physical campus and the timetable end-to-end without a superuser — buildings, floors, rooms (done), out-of-service, and single-class corrections.
**Depends on**: Phase 9 (reuses CANCELLED for a cancelled schedule meeting).
**Requirements**: A7, A9 (audit addendum) + building/floor CRUD gap; restores IFO-03 CRUD half.
**Success Criteria**:

  1. IFO can create/edit/delete buildings and floors from the console with PROTECT-aware named delete (mirroring `room_delete`); the room-create floor picker shows new floors.
  2. A room can be taken out of service: scans refuse with a clear reason, it cannot be booked, and it drops from the utilization denominator.
  3. IFO can add/edit/cancel a single schedule meeting mid-term (not Django admin), and the safe mid-term re-import procedure is documented.

**Plans**: TBD

### Phase 11: Metrics the Mission Promises

**Goal**: The numbers the product exists to produce are visible — lateness, verification coverage, and utilization deep enough for facilities to act.
**Depends on**: Phase 9 (CANCELLED excluded from denominators). Reuses `scheduling/reporting.py`.
**Requirements**: A3, A6, A8 + IFO-09 06.1-07.
**Success Criteria**:

  1. Lateness (minutes late; chronic flag) is computed in the aggregate layer and shown on the scorecard, weekly report, and HR export.
  2. Verification coverage (verified/held by building & day, incl. zero-coverage floors) is on the IFO dashboard.
  3. Utilization gains a booked-but-never-used ghost-room list and per-room CSV export (finishing 06.1-07). Capacity-vs-enrollment "fit" is **deferred** (reopens the `reporting.py:947` T3 deferral once `enrolled_count` is validated on a real imported term); week-over-week trend is also out of scope. A8 is therefore partially addressed here.

**Plans**: 4/4 plans complete
**Wave 1**

- [x] 11-01-PLAN.md — Lateness in the aggregate layer: session_minutes_late + _lateness_map + FacultyRow/Scorecard fields (A3, D-01/D-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 11-02-PLAN.md — Lateness surfaces: weekly report render, HR CSV derived column, scorecard card (A3, D-03)
- [x] 11-03-PLAN.md — Verification coverage by building & weekday + zero-coverage floors on the IFO dashboard (A6, D-04)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 11-04-PLAN.md — Ghost-room list + per-room utilization CSV export, finishing 06.1-07 (A8 partial, IFO-09, D-05/D-06)

### Phase 12: Term Lifecycle

**Goal**: A term can be closed/archived read-only and the next created & activated, without deleting attendance history.
**Depends on**: Nothing — but must land before the current term ends.
**Requirements**: A4; restores part of IFO-04.
**Success Criteria**:

  1. A term-close flow marks a term inactive and preserves its rows read-only (no delete); `DEFAULT_TERM` is de-hardcoded.
  2. A next-term create/activate flow stands up a new active term without touching prior data; import/materialize target the active term.
  3. All reports/exports scope to a selectable term (HR already does — extend to Dean/IFO where missing).

**Plans**: 6/12 plans executed

- [x] 12-01-PLAN.md
- [x] 12-02-PLAN.md
- [x] 12-03-PLAN.md
- [x] 12-04-PLAN.md
- [x] 12-05-PLAN.md
- [ ] 12-06-PLAN.md
- [ ] 12-07-PLAN.md
- [x] 12-08-PLAN.md
- [ ] 12-09-PLAN.md
- [ ] 12-10-PLAN.md
- [ ] 12-11-PLAN.md
- [ ] 12-12-PLAN.md

### Phase 13: UX Finish

**Goal**: The app reads as finished — no bare error pages, no shell jumps, one brand.
**Depends on**: Nothing; can overlap Phases 10–12.
**Requirements**: B1–B6 (audit addendum).
**Success Criteria**:

  1. Branded 403/404/500 templates + wired handlers keep a user oriented with a route home.
  2. Floor roles never jump into a desktop-family page (navy notifications variant / correct routing).
  3. Profile reachable from every faculty screen; login uses the brand-navy token; a global htmx error listener shows failures on every surface; PWA theme_color matches the shell.

**Plans**: TBD

### Phase 14: Correctness & Concurrency Hardening

**Goal**: Close the last known ways the record can go wrong under real multi-user/offline load.
**Depends on**: Nothing; H3 has a client change, so before real offline checkers deploy.
**Requirements**: M3, M5, M6, H3 (main audit).
**Success Criteria**:

  1. A booking beyond the materialize horizon can no longer silently collide with a timetabled class (M3).
  2. The scan resolver prefers a window-containing candidate whose room matches the scanned room (M5).
  3. Modality withdraw/approve/reject use `select_for_update` (M6).
  4. Offline replay applies a queued verification to the session the checker actually saw, not whatever is in the room now (H3).

**Plans**: TBD

### Phase 15: Deploy Hardening & Cutover  *(was Phase 8, expanded)*

**Goal**: The feature-complete app deploys to AWS safely, over HTTPS, multi-worker-correct, with a real operational story.
**Depends on**: Phases 9–14 (deploy the finished system).
**Requirements**: AUTH-01, AUTH-03, AUTH-05, DEPLOY-01, DEPLOY-02 + the ops gaps from the main audit §3.
**Success Criteria** (what must be TRUE):

  1. Entra ID SSO (Auth Code + PKCE) replaces the dev-login stub with a break-glass superuser; an unprovisioned/deactivated identity is refused; single EC2 (Nginx + Gunicorn + scheduler unit) over HTTPS against RDS SQL Server Express; Node-free Tailwind build replaces the CDN.
  2. A shared cache backend (Redis or DB cache) backs every idempotency, rate-limit, and offline-replay-dedupe key — no per-worker LocMem; multi-worker is correct.
  3. HTTPS/proxy config complete: `CSRF_TRUSTED_ORIGINS`, `SECURE_PROXY_SSL_HEADER`, secure cookies + HSTS, fail-fast placeholder `SECRET_KEY`/`DEBUG`, env-driven SSO redirect URI, media public/private split.
  4. Operational baseline: htmx + Franken JS + html5-qrcode vendored (not just Tailwind); scheduler resilience (`close_old_connections`, staleness alert, weekly-report backfill); LOGGING + error reporting; retention jobs (JobRun/session) + a written backup story incl. media; gunicorn + lock file; health endpoint.

**Plans**: TBD. **Carried in:** the 03.1-05 live Entra UAT (blocked on redirect-URI registration + the sandbox-vs-MMCM-tenant question).

### Phase 16: Documentation Pass

**Goal**: The SRS and planning docs match the built system for the capstone defense.
**Depends on**: Features complete (documents the final state).
**Requirements**: DOC-01 follow-through.
**Success Criteria**:

  1. SRS v1.3 records every code-vs-spec divergence: MySQL→MSSQL, sessions-vs-JWT, S3→filesystem, JOB-02 room-release cut, CHK-02 online path, IFO-07 board, MOD-01 window, shadcn-via-Franken UI, plus the new suspension/holiday/campus/lifecycle features.
  2. IFO-04, SYS-01..03, and IFO-03's schedule-CRUD half are restored to traceability — built (Phases 9–12) or recorded out-of-scope with rationale.
  3. PROJECT.md Active/Key-Decisions refreshed; USE_CASES.md marked superseded.

**Plans**: TBD

## Progress

**Execution Order:**
Phases 1–7 complete (milestone ≤ v1.2). Milestone v1.3 executes:
9 → (10 ∥ 11 ∥ 13) → 12 → 14 → 15 → 16.
Phase 9 is CRITICAL and lands before any deploy. Deploy (15) is last so cutover
never blocks feature work; if the defense needs a live URL sooner, 15 may be
pulled forward but 9 still precedes any real use.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. MSSQL Environment & Data Foundation | 3/3 | Complete | 2026-07-03 |
| 2. Correctness Foundations | 5/5 | Complete | 2026-07-02 |
| 3. Duty Assignments & Checker Verification | 6/6 | Complete | 2026-07-03 |
| 03.1 Authentication — Entra ID SSO (INSERTED) | 4/5 | Live UAT deferred → folds into 15 | - |
| 4. Modality Shift Approval & SRS v1.2 | 8/8 | Complete | 2026-07-03 |
| 04.1 Real-Data Integration (INSERTED) | 4/4 | Complete | 2026-07-07 |
| 04.2 Co-Scheduled Session Attendance (INSERTED) | 4/4 | Complete | 2026-07-07 |
| 5. Notifications — Read Surface & Web Push | 5/5 | Complete | 2026-07-15 |
| 6. Reporting Engine & Reporting Surfaces | 7/7 | Complete | 2026-07-15 |
| 06.1 Room Utilization & IFO-09 Closure (INSERTED) | 6/7 | Complete (export deferred) | 2026-07-19 |
| 7. Remaining Operational Surfaces | 12/12 | Complete (verified + UAT) | 2026-07-19 |
| **— Milestone v1.3 "Operational Trust" —** | | | |
| 9. Attendance Trust Under Real Operations (CRITICAL) | Complete | 5/5 criteria, 30 tests | 2026-07-20 |
| 10. Campus Structure Management | Complete | 3/3 criteria, 29 tests | 2026-07-20 |
| 11. Metrics the Mission Promises | 4/4 | Complete    | 2026-07-20 |
| 12. Term Lifecycle | 6/12 | In Progress|  |
| 13. UX Finish | 0/TBD | Not started | - |
| 14. Correctness & Concurrency Hardening | 0/TBD | Not started | - |
| 15. Deploy Hardening & Cutover (was Phase 8, expanded) | 0/TBD | Not started | - |
| 16. Documentation Pass | 0/TBD | Not started | - |

**Totals (≤ v1.2):** 58/59 plans complete across 11 phases (06.1-07 CSV export is a
deliberate deferral, now folded into Phase 11).

**Milestone v1.3** adds 8 phases (9–16) from the 2026-07-20 audit. The quick-wins
batch (H1, H2, M4, M7, seed_demo guard, 3 red tests, dead utilities, offline drain)
already shipped ahead of the milestone.

---
*Roadmap created: 2026-07-02; milestone v1.3 added 2026-07-20.*
*Coverage: v1 requirement IDs mapped; v1.3 traces to docs/AUDIT-2026-07-19.md. Traceability reconciled in Phase 16.*

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

- [ ] **Phase 1: MSSQL Environment & Data Foundation** - Prove SQL Server runtime (timezone + collation round-trips) and run existing import/materialize against it
- [ ] **Phase 2: Correctness Foundations** - Shared notify() write path, JOB-02 status sweep + occupancy release, single scheduler process
- [ ] **Phase 3: Duty Assignments & Checker Verification** - Floor assignments gate an on-duty Checker's online + offline room verification
- [ ] **Phase 4: Modality Shift Approval & SRS v1.2** - Lead-time-gated faculty request, Dean approval, auto room-release/assign, SRS revision
- [ ] **Phase 5: Notifications — Read Surface & Web Push** - In-app polled list + VAPID web push + per-user mute preferences
- [ ] **Phase 6: Reporting Engine & Reporting Surfaces** - One shared aggregate layer powering weekly report, scorecards, IFO/Dean/HR dashboards
- [ ] **Phase 7: Remaining Operational Surfaces** - Guard monitor/locator, IFO room & booking ops, Faculty self-service, job monitoring
- [ ] **Phase 8: Auth Cutover & AWS Deployment** - Entra ID SSO, Node-free Tailwind build, single-EC2 + RDS deploy

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
- [ ] 01-01-PLAN.md — MSSQL settings branch, dependency pins & environment bring-up (migrate + seed on SQL Server) [Wave 1]
- [ ] 01-02-PLAN.md — Datetime round-trip (no 8h drift) & R3 import/materialize parity tests [Wave 2]
- [ ] 01-03-PLAN.md — Case-sensitive collation on qr_token/manual_code & collation round-trip tests [Wave 2]

### Phase 2: Correctness Foundations
**Goal**: "Absent" is trustworthy without relying on scans, rooms release on a timer, every event flows through one notification write path, and all jobs run from one scheduler process.
**Depends on**: Phase 1
**Requirements**: NOTIF-00, JOB-02a, JOB-02b, JOB-02c, ENV-04
**Success Criteria** (what must be TRUE):
  1. A session nobody scans into is marked Absent within one sweep interval, using the same grace predicate the live scanner uses — a scan and the sweep never disagree on the same session.
  2. Contradictory room occupancy raises a single (deduped) IFO room-conflict notification. The shared `release_room()` helper exists and is tested but is invoked only by the modality-approval flow (Phase 4), not on a timer — timer-based auto-release was cut 2026-07-03.
  3. Every notification in the system is created by one shared `notify()` write path — the ad-hoc `_notify_ifo` is gone and no other inline notifier remains.
  4. The materialize, sweep, and weekly-report jobs run automatically from one dedicated scheduler process, never duplicated across web workers, with last-run status recordable.
  5. Re-running the sweep never changes an already-decided session (idempotent — active, completed, and already-Absent sessions are untouched).
**Plans**: 5 plans

Plans:
- [ ] 02-01-PLAN.md — Shared no-show grace predicate extraction (JOB-02a) [Wave 1]
- [ ] 02-02-PLAN.md — Shared notify() write path + scan migration (NOTIF-00) [Wave 1]
- [ ] 02-03-PLAN.md — Status sweep + deduped room-conflict flags (JOB-02b, JOB-02c) [Wave 2]
- [ ] 02-04-PLAN.md — release_room() occupancy helper, built for MOD-03 (JOB-02c) [Wave 2]
- [ ] 02-05-PLAN.md — Dedicated APScheduler process + JobRun observability (ENV-04) [Wave 3]

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

**Plans**: TBD

Plans:
- [ ] 03-01: TBD

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
**Plans**: TBD

Plans:
- [ ] 04-01: TBD

### Phase 5: Notifications — Read Surface & Web Push
**Goal**: The events already being written by `notify()` become visible to every role, in-app and via push, respecting mute preferences.
**Depends on**: Phase 2 (notify() write path emitting rows). Consumes events from Phases 3 and 4.
**Requirements**: NOTIF-01, NOTIF-02, NOTIF-03
**Success Criteria** (what must be TRUE):
  1. Every role sees a polled in-app notification list reading the `Notification` rows created by `notify()`.
  2. A subscribed client receives a web-push (VAPID) for key events (wrong-room, force handover, room conflict, weekly report ready) even with the tab closed.
  3. A user's mute preferences suppress muted notifications from both the in-app list and push.
  4. A failed push to a dead endpoint never breaks the scan, approval, or job that triggered it.
**Plans**: TBD

Plans:
- [ ] 05-01: TBD

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
**Plans**: TBD

Plans:
- [ ] 06-01: TBD

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
**Plans**: TBD

Plans:
- [ ] 07-01: TBD

### Phase 8: Auth Cutover & AWS Deployment
**Goal**: Replace the dev-login stub with Entra ID SSO and deploy the feature-complete app to AWS with a Node-free production build — verified on staging before flipping DEBUG=False.
**Depends on**: Phase 7 (feature-complete app to cut over and deploy)
**Requirements**: AUTH-01, AUTH-03, AUTH-05, DEPLOY-01, DEPLOY-02
**Success Criteria** (what must be TRUE):
  1. Users authenticate via Microsoft Entra ID SSO (Authorization Code + PKCE) with Django sessions preserved; the dev-login stub is gone and a break-glass superuser remains.
  2. An authenticated Entra identity with no provisioned User is refused application access, and deactivating a user blocks further access.
  3. The app runs on a single AWS EC2 instance (Nginx + Gunicorn + a separate scheduler systemd unit) over HTTPS against RDS SQL Server Express.
  4. Franken UI styling is served from a Tailwind v4 standalone build step (production Node-free), replacing the CDN.
**Plans**: TBD

Plans:
- [ ] 08-01: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
(Phase 4 may run in parallel with Phase 3; both depend only on Phase 2.)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. MSSQL Environment & Data Foundation | 0/TBD | Not started | - |
| 2. Correctness Foundations | 0/5 | Not started | - |
| 3. Duty Assignments & Checker Verification | 0/TBD | Not started | - |
| 4. Modality Shift Approval & SRS v1.2 | 0/TBD | Not started | - |
| 5. Notifications — Read Surface & Web Push | 0/TBD | Not started | - |
| 6. Reporting Engine & Reporting Surfaces | 0/TBD | Not started | - |
| 7. Remaining Operational Surfaces | 0/TBD | Not started | - |
| 8. Auth Cutover & AWS Deployment | 0/TBD | Not started | - |

---
*Roadmap created: 2026-07-02*
*Coverage: 57/57 v1 requirement IDs mapped, 0 orphans. See REQUIREMENTS.md Traceability.*

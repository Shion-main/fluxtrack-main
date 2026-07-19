# Requirements: FluxTrack

**Defined:** 2026-07-02
**Core Value:** A faculty member checks in with one action, and the resulting attendance record is trustworthy — presence physically verified, lateness captured, ghost bookings detected.

Requirement IDs trace to `FluxTrack_SRS.md` §4 where they exist (AUTH/SCAN/FAC/
CHK/IFO/HR/GRD/DEAN/RPT/NOTIF/SYS/JOB). New areas introduced this cycle: `MOD`
(modality shift approval), plus infra prefixes `ENV`/`DEPLOY`/`DOC` for work the
SRS states as constraints rather than numbered functional requirements.

## Already Delivered (not phased — built + verified)

These are the PROJECT.md "Validated" set. Listed for traceability only; the
roadmap does NOT create phases for them.

- ✓ Django foundation + all domain models, env-driven settings, policy system
- ✓ Role-routed home + DEBUG dev-login stub (AUTH placeholder)
- ✓ Scan resolver pure core + Faculty check-in end-to-end (SCAN-01..07, FAC-01..06/09/10) — 16 tests
- ✓ IFO room + schedule surface, per-term view (IFO-11), live polling (IFO-07 partial)
- ✓ QR poster + code image (IFO-01 partial)
- ✓ CSV import + session materialization commands (IFO-03/JOB-01 logic, CLI-only)

## v1 Requirements (to build)

### Environment & Data (ENV)

- [x] **ENV-01**: Project runs on SQL Server via `mssql-django` in both local dev (SQL Server Express) and prod, with `DB_ENGINE=mssql`, Django pinned to 6.0.6, and a proven datetime2/timezone + collation round-trip (no Asia/Manila drift, no case-folding surprises)
- [x] **ENV-02**: Registrar CSV import + session materialization run correctly against MSSQL at the R3-slice scale already validated on SQLite

### Correctness Foundations (JOB / NOTIF-core)

- [x] **NOTIF-00**: A single shared `notify()` write-path service creates `Notification` rows for any role/event (replacing the ad-hoc `_notify_ifo` in `web/scan.py`), used by every downstream writer
- [x] **JOB-02a**: A pure decision function determines, for a given session and time, whether it is a no-show past grace — reusing the scan resolver's grace predicate so scan-time and sweep-time never disagree
- [x] **JOB-02b**: A status sweep marks no-show sessions Absent independent of any scan, so a session nobody scans into is still correctly Absent
- [x] **JOB-02c**: The sweep raises a room-conflict flag (via `notify()`, deduped until resolved) when occupancy is contradictory. A shared `release_room()` occupancy helper is built and tested in this phase but is invoked only by the modality-approval flow (MOD-03, Phase 4), NOT by the sweep on a timer — automatic timer-based room release was cut (2026-07-03) as unsafe when a class runs long; room lifecycle is driven by explicit approved events
- [x] **ENV-04**: All scheduled jobs (materialize/JOB-01, sweep/JOB-02, weekly report/JOB-03) run automatically via APScheduler in one dedicated scheduler process, never duplicated across web workers, with last-run status recordable

### Duty Assignments (IFO)

- [x] **IFO-06**: IFO can assign Checkers and Guards to floors by shift or standing posting, and those assignments are what grant on-duty powers

### Checker (CHK)

- [x] **CHK-01**: A Checker gains verification powers only while on duty (active assignment) on the scanned floor; off-duty/wrong-floor scans are refused with a clear reason
- [x] **CHK-02**: Scanning a room on the assigned floor returns the room's current session state plus the scheduled faculty member's profile photo for identity matching. For an **online** session, the Checker is instead notified (via `notify()`) and redirected to the class's **public MS Teams link** to verify the faculty is conducting the session (captured 2026-07-03; online is Checker-verified, not faculty-self-declared — reconcile with FAC-08)
- [x] **CHK-03**: A Checker can record one of: Verify, Flag identity mismatch, Flag not present, Confirm empty / Verified empty (no "Confirm absent" — Absent is final per the modality/sweep changes). These verification actions apply to **online** sessions too (verified via the MS Teams link per CHK-02), not only physical room scans (captured 2026-07-03)
- [x] **CHK-04**: A Verify finding marks the session checker-verified
- [x] **CHK-05**: A Flag identity mismatch is recorded and surfaced to IFO and HR, with no dispute workflow
- [x] **CHK-07**: A floor view shows coverage progress, a priority queue of oldest unverified active sessions, and color-coded room cards, excluding Absent sessions
- [x] **CHK-08**: Scans made offline queue locally and replay on reconnect, each re-validated server-side before applying (not blindly trusted) or flagged for IFO

### Modality Shift Approval (MOD — new)

- [x] **MOD-01**: A faculty member can submit a modality-shift request (F2F/Blended ↔ Online) for a single session or a recurring schedule, at least `modality_shift_lead_days` (default 2) before the affected date; too-late requests are refused
- [x] **MOD-02**: The request routes to the faculty member's department Dean, who can approve or reject with a reason (no dispute)
- [x] **MOD-03**: On approval of a →Online shift, the affected session(s) become Online and the room is released immediately (`room_released_at` stamped), not held on the timer; newly materialized Online sessions are born released
- [x] **MOD-04**: On approval of a →F2F/Blended shift, a free room in the same building is auto-assigned at approval time; if none is free, the approval fails with a clear reason (no silent partial-apply)
- [x] **MOD-05**: On approval, IFO is notified (informational, not a gate) via `notify()`; the faculty member may withdraw a request while still pending
- [x] **MOD-06**: This workflow replaces the FAC-07 self-declare; same-day changes have no formal path and fall back to existing scan-time behavior

### Notifications (NOTIF)

- [x] **NOTIF-01**: Every role sees an in-app notification list (polled) reading the `Notification` rows created by `notify()`
- [x] **NOTIF-02**: Subscribed clients receive web-push (VAPID) for floor activity and key events (wrong-room, force handover, room conflict, weekly report ready)
- [x] **NOTIF-03**: Per-user mute preferences suppress muted notifications

### Reporting (RPT)

- [x] **RPT-01**: A Weekly Consolidated Attendance Report generates per department — one row per faculty (scheduled, held, absent, attendance %, checker-verified count) plus itemized absences — from pure, independently tested aggregate functions
- [x] **RPT-04**: A faculty scorecard (scheduled vs held, attendance %, absences, early-ends, modality breakdown, selectable period) computes from the same shared aggregates
- [x] **RPT-03**: Reports export as both CSV and printable PDF, per department or all
- [x] **RPT-05**: A single failed aggregate degrades gracefully (its section shows an error, the page still renders)
- [x] **RPT-02**: The weekly report generates on demand and auto-weekly (JOB-03), stored, notifying IFO and the relevant Dean(s)

### Dean (DEAN)

- [x] **DEAN-01**: A Dean's access is read-only and scoped to their assigned department(s)
- [x] **DEAN-04**: A Dean dashboard shows department-scoped summary cards (Faculty, Sessions, Absences, Attendance %) plus a latest-weekly-report card, reusing the RPT aggregates
- [x] **DEAN-02**: A Dean can view department-scoped attendance reporting and per-faculty scorecards
- [x] **DEAN-03**: A Dean can view and export the weekly report for their department(s)

### Guard (GRD)

- [x] **GRD-01**: A Guard sees a live read-only room-status monitor for assigned floor(s), polled
- [x] **GRD-02**: A Guard can view each room's schedule (reusing the IFO-11 per-room view, guard-gated)
- [x] **GRD-03**: A Guard can locate a faculty member by name — current room/building/floor, course, end time, or "Online — not on campus" / "Not in a class" + next class
- [x] **GRD-04**: A Guard receives debounced web-push alerts for floor activity
- [x] **GRD-05**: A Guard has no write access anywhere

### HR (HR)

- [x] **HR-01**: HR can view verified attendance per faculty/session (present/absent, actual times, check-in method, checker-verification status)
- [x] **HR-02**: HR can filter/search by faculty, department, date range, and term
- [x] **HR-03**: HR can export session-level attendance as CSV for external payroll

### IFO — remaining (IFO)

- [x] **IFO-01b**: IFO can create/edit/delete rooms from a dedicated (non-admin) UI, with the existing poster/QR actions
- [x] **IFO-02**: IFO can rotate a room's QR token + six-digit code, audit-logged, invalidating old posters
- [x] **IFO-03b**: IFO can import schedules by CSV upload with validation and conflict reporting (surfacing the existing importer)
- [x] **IFO-05**: IFO can create/cancel ad-hoc room bookings, conflict-checked
- [x] **IFO-08**: IFO can manually release a held room and resolve room-conflict notifications
- [x] **IFO-09**: IFO sees a dashboard of summary cards over a selectable range with faculty-scorecard drill-down (shared RPT aggregates)

### Faculty — remaining (FAC)

- [x] **FAC-08**: A faculty member starts an Online session via "Verify & Start" with a valid MS Teams link (no QR); Blended still checks in by QR
- [x] **FAC-11**: A faculty member can view their own attendance history including Checker flags, read-only
- [x] **FAC-12**: A faculty member can manage their profile (photo used for Checker identity matching) and notification preferences

### System Admin (SYS)

- [x] **SYS-04**: A System Admin can monitor scheduled-job status (last run, success/failure, rows affected)

### Authentication (AUTH)

- [ ] **AUTH-01**: Users authenticate via Microsoft Entra ID SSO (Authorization Code + PKCE), replacing the dev-login stub, keeping Django sessions
- [ ] **AUTH-03**: An authenticated Entra identity with no provisioned User is refused application access
- [ ] **AUTH-05**: Deactivating a user blocks further access

### Deployment (DEPLOY)

- [ ] **DEPLOY-01**: The app is deployed to a single AWS EC2 instance (Nginx + Gunicorn + a separate scheduler systemd unit) over HTTPS, with MSSQL on AWS RDS SQL Server Express
- [ ] **DEPLOY-02**: Franken UI styling is served from a Tailwind v4 standalone build step (production Node-free), replacing the CDN

### Documentation (DOC)

- [x] **DOC-01**: The SRS is revised to v1.2 — new MOD area, DEAN-04, amended FAC-07/CHK-03, removed CHK-06, RPT-02 notifies Deans, `modality_shift_lead_days` in the policy register — in both `.md` and `.docx`

## Out of Scope

| Feature | Reason |
|---------|--------|
| Payroll lifecycle (periods/locks/finalize) | HR export only — explicit SRS boundary |
| Disputes/appeals workflow | SRS §7; records are read-only |
| Same-day/emergency modality declaration | Accepted gap; lead-time-gated approval only |
| Guard incident log, help requests, substitute flow | SRS §7 |
| Interactive booking calendar grid | SRS §7 (read-only per-room schedule is in scope) |
| Email notifications, dark-mode, coverage analytics | SRS §7 |
| React/Node frontend, two-server split, folder restructure | Ruled out — single Django app, solo dev |

## Traceability

Mapped to phases by the roadmapper. Every v1 requirement maps to exactly one
phase (see ROADMAP.md). Status values: Pending / In progress / Complete.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENV-01 | Phase 1 | Complete |
| ENV-02 | Phase 1 | Complete |
| NOTIF-00 | Phase 2 | Complete |
| JOB-02a | Phase 2 | Complete |
| JOB-02b | Phase 2 | Complete |
| JOB-02c | Phase 2 | Complete |
| ENV-04 | Phase 2 | Complete |
| IFO-06 | Phase 3 | Complete |
| CHK-01 | Phase 3 | Complete |
| CHK-02 | Phase 3 | Complete |
| CHK-03 | Phase 3 | Complete |
| CHK-04 | Phase 3 | Complete |
| CHK-05 | Phase 3 | Complete |
| CHK-07 | Phase 3 | Complete |
| CHK-08 | Phase 3 | Complete |
| MOD-01 | Phase 4 | Complete |
| MOD-02 | Phase 4 | Complete |
| MOD-03 | Phase 4 | Complete |
| MOD-04 | Phase 4 | Complete |
| MOD-05 | Phase 4 | Complete |
| MOD-06 | Phase 4 | Complete |
| DOC-01 | Phase 4 | Complete |
| NOTIF-01 | Phase 5 | Complete |
| NOTIF-02 | Phase 5 | Complete |
| NOTIF-03 | Phase 5 | Complete |
| RPT-01 | Phase 6 | Complete |
| RPT-02 | Phase 6 | Complete |
| RPT-03 | Phase 6 | Complete |
| RPT-04 | Phase 6 | Complete |
| RPT-05 | Phase 6 | Complete |
| IFO-09 | Phase 6 | Complete |
| DEAN-01 | Phase 6 | Complete |
| DEAN-02 | Phase 6 | Complete |
| DEAN-03 | Phase 6 | Complete |
| DEAN-04 | Phase 6 | Complete |
| HR-01 | Phase 6 | Complete |
| HR-02 | Phase 6 | Complete |
| HR-03 | Phase 6 | Complete |
| GRD-01 | Phase 7 | Done (shipped out-of-band 2026-07-18) |
| GRD-02 | Phase 7 | Done |
| GRD-03 | Phase 7 | Done (shipped out-of-band 2026-07-18) |
| GRD-04 | Phase 7 | Done |
| GRD-05 | Phase 7 | Done |
| IFO-01b | Phase 7 | Done |
| IFO-02 | Phase 7 | Done |
| IFO-03b | Phase 7 | Done |
| IFO-05 | Phase 7 | Done |
| IFO-08 | Phase 7 | Done |
| FAC-08 | Phase 7 | Done |
| FAC-11 | Phase 7 | Done |
| FAC-12 | Phase 7 | Done |
| SYS-04 | Phase 7 | Done (shipped out-of-band 2026-07-18) |
| AUTH-01 | Phase 8 | Pending |
| AUTH-03 | Phase 8 | Pending |
| AUTH-05 | Phase 8 | Pending |
| DEPLOY-01 | Phase 8 | Pending |
| DEPLOY-02 | Phase 8 | Pending |

**Coverage:**

- v1 requirements: 57 total distinct IDs (the earlier "48" figure predates the
  correctness-foundations split into NOTIF-00/JOB-02a/JOB-02b/JOB-02c/ENV-04 and
  the IFO-01b/IFO-03b variants; recounted here)

- Mapped to phases: 57 ✓
- Unmapped: 0 ✓
- Duplicates (in >1 phase): 0 ✓

---
*Requirements defined: 2026-07-02*
*Last updated: 2026-07-02 after roadmap creation (traceability populated, 57/57 mapped)*

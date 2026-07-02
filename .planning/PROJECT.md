# FluxTrack

## What This Is

FluxTrack is a Faculty Attendance and Facility Utilization Information
System for Mapúa Malayan Colleges Mindanao (MMCM) — a mobile-first PWA
backed by a Django service. It reduces a faculty member's class check-in to
a single action (scan a room QR or enter a six-digit code) and treats an
independent Checker's physical verification as the authoritative record of
presence, correlating scheduled room occupancy against actual detected
presence. It serves seven user roles (Faculty, Checker, IFO Admin, HR
Admin, Guard, Dean, System Admin) and is a capstone project.

## Core Value

A faculty member checks in with one action, and the resulting attendance
record is trustworthy — because presence is physically verified, lateness
is captured at the room level, and ghost bookings (rooms reserved but
unused) are detected automatically.

## Requirements

### Validated

<!-- Shipped and confirmed working in the codebase (verified in-browser / by tests). -->

- ✓ Django foundation: all domain models (accounts, campus, scheduling, verification, ops), env-driven settings, policy system — existing
- ✓ Role-routed home + DEBUG dev-login stub (stands in for Entra ID) — existing
- ✓ IFO room + schedule surface: rooms list, room detail, per-term schedule view (IFO-11), live "today" polling view (IFO-07 partial) — existing
- ✓ QR poster + code image generation with print-safe CSS (IFO-01 partial) — existing
- ✓ CSV schedule import + session materialization (management commands; IFO-03/JOB-01 logic, CLI-only) — existing
- ✓ Scan resolver: pure-function core with all Faculty outcomes, 16 passing tests (SCAN-01..07, FAC-02..06/09/10) — existing
- ✓ Faculty check-in surface: schedule view + scan page, end-to-end verified (FAC-01..06/09/10) — existing

### Active

<!-- Current scope. Building toward these. Grouped by the work still to do. -->

**Environment & platform**
- [ ] MSSQL migration (mssql-django + pyodbc; DB_ENGINE mssql branch) — spike Django 6.0.6 compat first
- [ ] Entra ID SSO replacing the dev-login stub (Auth Code + PKCE); resolve session-vs-JWT divergence
- [ ] AWS deployment: single EC2 (Nginx+Gunicorn+APScheduler) + RDS SQL Server Express
- [ ] Tailwind standalone-CLI build replacing the Franken UI CDN before deploy
- [ ] APScheduler as a dedicated scheduler process (JOB-01/02/03 wiring)

**Correctness foundations**
- [ ] JOB-02 status sweep: mark no-show sessions Absent independent of any scan; release rooms after hold; raise conflict flags
- [ ] IFO-06 Checker/Guard floor assignments (hard blocker for Checker)

**Core attendance loop**
- [ ] Checker surface (CHK-01..05/07/08): on-duty gating, room-state scan + photo, verify/flag actions, floor view, offline queue
- [ ] Modality shift approval workflow (new): ModalityShiftRequest, Dean approves, IFO notified, auto room-release; removes CHK-06, amends CHK-03/FAC-07
- [ ] Notifications: in-app list (NOTIF-01) + web push (NOTIF-02) + mute prefs (NOTIF-03)

**Reporting & remaining roles**
- [ ] Reporting engine (RPT-01..05): weekly consolidated report, faculty scorecard, pure aggregates
- [ ] Dean dashboard (new DEAN-04) + department-scoped reporting (DEAN-01..03); RPT-02 notifies Deans
- [ ] Guard surfaces (GRD-01..05): floor monitor, per-room schedule reuse, faculty locator
- [ ] HR surfaces (HR-01..03): verified attendance list, filter/search, CSV export
- [ ] IFO remaining: room CRUD UI, code rotation (IFO-02), bookings (IFO-05), manual release/conflict (IFO-08), dashboard (IFO-09), CSV-upload import UI
- [ ] Faculty remaining: modality control + Online Verify & Start (FAC-08), attendance history (FAC-11), profile + prefs (FAC-12)
- [ ] System Admin: job monitoring (SYS-04); user/settings/audit polish (SYS-01..03, admin-backed today)

**Documentation**
- [ ] SRS v1.2 revision (new MOD area, DEAN-04, amended FAC-07/CHK-03, removed CHK-06, RPT-02 notify Deans, modality_shift_lead_days policy)

### Out of Scope

<!-- From SRS §7 plus decisions made this session. -->

- Payroll lifecycle (periods, locks, finalization) — HR exports only; explicit boundary
- Disputes/appeals workflow — SRS §7; attendance records are read-only, no dispute
- Same-day/emergency modality declaration — accepted gap; lead-time-gated approval only
- Guard incident log, faculty help requests, substitute-teacher flow — SRS §7
- Interactive booking calendar grid — SRS §7 (read-only per-room schedule is in scope)
- Email notifications, dark-mode refinement, coverage analytics — SRS §7
- Separate React/Node frontend, two-server split — ruled out; single Django app
- Frontend/backend folder restructure — dropped (solo dev, cosmetic only)

## Context

- **Solo developer.** Earlier collaboration/folder-split plans dropped.
- **Rich prior documentation** drives this project: `FluxTrack_SRS.md`/`.docx`
  (IEEE 830 v1.1), `docs/USE_CASES.md` (per-requirement built/not status),
  `docs/SCENARIOS.md` (narrative per role), and 3 design specs under
  `docs/superpowers/specs/` (deployment-and-dev-practice, modality-shift-
  approval, dean-dashboard). `.planning/codebase/` holds the GSD map.
- **Stack** (SRS v1.1): Django 6 + DRF, server-rendered templates + htmx +
  Franken UI (CDN today), vanilla JS only for camera QR (html5-qrcode) and
  the Checker offline queue (IndexedDB), PWA. No React/Node runtime.
- **Established conventions** (see `.planning/codebase/CONVENTIONS.md`):
  resolver stays a pure function; every write action logs `AuditLog`;
  policy values via `get_policy()`/`SystemSetting`, never hardcoded;
  management commands print ASCII only (Windows cp1252); per-view role
  decorators; htmx partials named `_name.html`; signed tokens for two-step
  confirms.
- **Known concerns** (see `.planning/codebase/CONCERNS.md`): auth is a stub,
  MSSQL compat unproven, JOB-02 absent-detection missing, notifications have
  no read surface, only the resolver is tested, CDN-not-build-step, SRS
  drift vs. the 3 new specs.

## Constraints

- **Tech stack**: Django + htmx + Franken UI, no React/Node — fixed by SRS v1.1.
- **Database**: MSSQL in production (school/registrar IT requirement), local
  SQL Server Express dev; SQLite still works for quick local runs.
- **Deployment**: AWS single EC2 + RDS SQL Server Express, "simplest possible"
  for capstone scale (one campus, small user base).
- **Identity**: Microsoft Entra ID SSO (project-owned tenant) — dev-login stub
  until wired.
- **Platform**: mobile-first for Faculty/Checker, desktop-first responsive for
  admin roles; WCAG 2.1 AA; all role/data scoping enforced server-side.
- **Live data**: polling only, no WebSockets (SRS §2.5).
- **Environment**: Windows dev (`py -3.12`), Asia/Manila timezone.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Django templates + htmx + Franken UI over Next.js/React | Single-server deploy, no Node runtime, self-hydrating web components survive htmx swaps | ✓ Good (SRS v1.1, POC validated) |
| MSSQL via mssql-django | School/registrar IT requirement | — Pending (Django 6.0.6 compat unspiked) |
| Single EC2 + RDS SQL Server Express | Simplest AWS surface for capstone scale | — Pending |
| Solo dev; no folder split | Collaborator dropped; folder split was cosmetic only | ✓ Good |
| Modality shift approval (Dean→IFO, auto room-release) | Eliminates Checker room-release burden; rooms follow schedule | — Pending (design approved) |
| Remove CHK-06 (Absent override) | Absent becomes final; room releases on timer, no Checker action | — Pending (design approved) |
| Build order: env → JOB-02 → IFO-06 → Checker → modality → notif → reporting → Guard/Dean/HR → auth/deploy | Dependency-driven (Checker needs assignments + trustworthy Absent) | — Pending |

---
*Last updated: 2026-07-02 after initialization (brownfield, codebase mapped)*

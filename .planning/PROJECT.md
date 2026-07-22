# FluxTrack

## What This Is

FluxTrack is MMCM's Faculty Attendance and Facility Utilization Information
System. It is a mobile-first Progressive Web Application backed by one Django
service and Microsoft SQL Server. Faculty claim attendance with one room QR scan
or six-digit code; an independently assigned Checker provides the authoritative
verification. IFO, HR, Guards, Deans, and System Admins use the same system for
campus operations, reporting, oversight, and administration.

## Core Value

A faculty member checks in with one action and the resulting attendance record is
trustworthy: physical presence is independently verified, lateness is measured
from the room-level event, ghost bookings become visible, and holidays or class
suspensions never become false absences.

## Requirements

### Validated

- ✓ Microsoft SQL Server-only data layer, case-sensitive room credentials, and
  timezone-safe Asia/Manila behavior.
- ✓ Entra ID Authorization Code + PKCE integration with pre-provisioned accounts,
  Django sessions, role/data scope, deactivation refusal, and DEBUG-only dev login.
- ✓ Faculty day/week schedule, QR/manual check-in, Online self-start, checkout,
  attendance history, profile photo, and modality-shift requests.
- ✓ Checker floor/online duty, room and Online verification, coverage queue,
  identity/not-present flags, and durable offline replay.
- ✓ IFO schedule import and individual schedule operations; room, building, floor,
  code, booking, assignment, conflict, suspension, break, and term management.
- ✓ Dean modality decisions and department reporting; HR attendance/export; Guard
  monitor, room schedule, faculty locator, and debounced floor alerts.
- ✓ Weekly reports, scorecards, attendance/lateness/coverage/utilization metrics,
  guarded downloads, and production scheduler jobs.
- ✓ Operational trust: excused-day handling, reversible suspensions, corrections,
  room service state, Draft/Active/Archived term lifecycle, transaction/concurrency
  guards, shared database cache, and durable replay receipts.
- ✓ Node-free, same-origin frontend assets: Django templates, htmx, shadcn design
  language via Franken UI, html5-qrcode, PWA, and focused vanilla JavaScript.
- ✓ AWS deployment package: Nginx, Gunicorn, exactly one locked scheduler process,
  watchdog, HTTPS production checks, health probe, retention, backup, and rollback.

### Active

- [ ] Complete live Entra UAT with the institutional application registration and
  production redirect URI.
- [ ] Provision AWS EC2/RDS/network/DNS/TLS, restore rehearsal data, deploy the
  reviewed commit, and execute the production smoke checklist.
- [ ] Validate policy assumptions and report format against the official MMCM IRR
  before institutional production use.

### Out of Scope

- Payroll lifecycle, disputes/appeals, student grades or performance monitoring.
- Same-day emergency modality changes outside IFO's suspension/cancellation tools.
- Guard incident log, faculty help requests, substitutes, and email notifications.
- Interactive spatial floor-plan editor or calendar-first booking grid.
- A duplicate custom System Admin UI for user/settings/audit tasks already covered
  by guarded Django admin.
- React/Next.js, a separate Node frontend service, WebSockets, microservices,
  containers, Kubernetes, and multi-instance scaling for the capstone deployment.
- S3 as the current storage backend; media stays on persistent EBS-backed instance
  storage with a separate backup until scale or multi-instance hosting requires it.

## Context

- The repository is the implementation and planning source of truth. The formal
  specification is `FluxTrack_SRS.md` v1.3; `.docx` is generated from it.
- Django migrations are authoritative for schema. `docs/db_schema.sql` is a
  2026-07-07 snapshot and does not include later operational-trust migrations.
- The full SQL Server suite contains 1,259 tests, with two expected skips at the
  Phase 15 repository verification point.
- Feature work through Phase 14 and all five Phase 15 repository workstreams are
  complete. Phase 15 remains open only for credential-dependent external cutover.

## Constraints

- **Stack:** Python 3.12, Django 6, server-rendered templates, htmx, Franken UI,
  vanilla JavaScript, no Node runtime.
- **Database:** Microsoft SQL Server in development, test, and production through
  `mssql-django`, `pyodbc`, and ODBC Driver 18; no SQLite/MySQL fallback.
- **Deployment:** one Ubuntu EC2 instance plus private-subnet RDS SQL Server
  Express; Nginx → Gunicorn and one separate APScheduler systemd service.
- **Identity:** single-tenant Microsoft Entra ID; users are pre-provisioned and
  linked by institutional email/Entra object ID; no self-registration.
- **Storage:** static assets are manifested and served locally; private/generated
  media uses `FileSystemStorage` below a persistent, backed-up `MEDIA_ROOT`.
- **Security:** HTTPS in production, secure sessions and CSRF, server-side role and
  scope checks, resolver-only room credentials, and audit coupling for writes.
- **Operations:** Asia/Manila timezone, polling rather than WebSockets, exactly one
  scheduler, and shared state for multi-worker rate limiting/idempotency.

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Django templates + htmx; no SPA | One deployable service and server-authoritative authorization | Implemented |
| shadcn design language via Franken UI | Preserves shadcn tokens/components without React | Implemented; assets vendored |
| Microsoft SQL Server only | School/registrar IT requirement and one tested persistence contract | Implemented locally; RDS cutover pending |
| Django sessions, not an app-issued JWT | Server-rendered same-origin UI gains simpler revocation and CSRF protection | Implemented |
| Filesystem media, not S3 | Small single-instance scope; lower operational surface | Implemented with EBS backup requirement |
| No timer-based room release | Elapsed time does not prove physical vacancy | Implemented; MOD/IFO are the only release paths |
| Semantic room board, not a spatial map | No geometry data; sorted attention states scale to the full campus | Implemented |
| Single occurrence or next-N-week modality window | Matches recurring academic schedules and gives a bounded operator choice | Implemented |
| Django admin satisfies SYS-01..03 | Trusted technical operator tasks already have guarded, auditable CRUD/read surfaces | Implemented; duplicate UI out of scope |
| One EC2 + RDS; one scheduler process | Small capstone scale with a clear backup and failure model | Package complete; live cutover pending |

---
*Last updated: 2026-07-22 during Phase 16. Repository implementation is complete;
the remaining production gate requires institutional Entra and AWS access.*

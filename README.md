# FluxTrack

Faculty Attendance & Facility Utilization Information System for MMCM.
Django 6 + htmx + Franken UI (Tailwind), PWA, no React / no Node runtime,
SQL Server database. See `FluxTrack_SRS.md`.

> **Progress at a glance:** Phases 1–2 of 8 complete (SQL Server foundation +
> correctness foundations). For the full collaborator-facing status board — what's
> built, what's next, and how the phases map to requirements — see
> **[`docs/PROGRESS.md`](docs/PROGRESS.md)**.

## Requirements
- Python 3.12 (`py -3.12` launcher on Windows)
- **SQL Server** — local dev uses SQL Server 2025 **LocalDB** (Windows integrated
  auth) or SQL Server Express; prod uses AWS RDS SQL Server Express
- **ODBC Driver 18 for SQL Server** (system-wide; required by `mssql-django`/`pyodbc`)
- Dependencies: `py -3.12 -m pip install --user -r requirements.txt`
  (Django 6.0.6, mssql-django 1.7.3, APScheduler <4)

## Run the app
```
py -3.12 manage.py runserver 127.0.0.1:8020
```
Open http://127.0.0.1:8020 → dev-login (click any role).
Admin: http://127.0.0.1:8020/admin — sign in as `sysadmin` / `devpass123`.

Dev users (all password `devpass123`): `faculty` `checker` `ifo` `hr` `guard` `dean` `sysadmin`.

## First-time setup
Copy `.env.example` to `.env` and set the database vars. For local SQL Server
LocalDB with Windows auth:
```
DB_ENGINE=mssql
DB_NAME=fluxtrack
DB_HOST=(localdb)\MSSQLLocalDB
DB_TRUSTED_CONNECTION=yes        # Windows integrated auth (leave user/password empty)
```
Then:
```
py -3.12 manage.py migrate          # create the schema on SQL Server
py -3.12 manage.py seed_demo        # 7 dev-login users + a little demo data
```

## Background jobs (status sweep + scheduler)
The status sweep marks no-show sessions Absent independent of any scan, and flags
contradictory room occupancy to IFO. Run it once, or run the scheduler that fires
all jobs (materialize / sweep / weekly-report) automatically from **one dedicated
process** (never inside a web worker):
```
py -3.12 manage.py run_status_sweep   # one-shot: mark no-shows Absent + flag conflicts
py -3.12 manage.py runscheduler       # long-running: all jobs on their cadence (sweep every 5 min)
```
Run exactly one `runscheduler` process (a dedicated systemd unit in prod). Each
run records a `JobRun` row (last-run status for job monitoring); a failure
notifies System Admins.

## Tests
```
py -3.12 manage.py test              # full suite (builds an MSSQL test database)
py -3.12 manage.py test scheduling.tests.FacultyResolverTests   # fast pure-logic subset (no DB)
```

## Load real schedule data (IFO import)
Source files live in `data/raw/` (gitignored). The importer reads the Course
Offering CSV's `Schedule` column (day/time/room), skips virtual `V` rooms.

```
# preview a slice without writing
py -3.12 manage.py import_offerings --building R --floor 3 --dry-run

# import a slice
py -3.12 manage.py import_offerings --building R --floor 3

# create dated sessions for the next 7 days
py -3.12 manage.py materialize_sessions --days 7
```
Scale up by widening the filter: `--building R` (whole building) or no flags (whole campus).

## Reset the dev database
```
py -3.12 manage.py flush --no-input
py -3.12 manage.py seed_demo
```

## Project Structure
```
config/        settings (MSSQL-only DB branch), urls
accounts/      User (7 roles), Department
campus/        Building, Floor, Room (qr_token/manual_code case-sensitive collation)
scheduling/    AcademicTerm, Schedule, Session, resolver.py (scan outcome logic +
               shared is_no_show_past_grace predicate), jobs.py (status sweep +
               room-conflict detection), import/materialize/sweep/scheduler commands
verification/  Assignment, CheckerValidation
ops/           Booking, Notification, AuditLog, SystemSetting, WeeklyReport,
               RoomConflictFlag, JobRun; notify.py (single notification write path),
               occupancy.py (release_room helper), jobrun.py (run_job wrapper), policy.py
web/           frontend: dev-login, home, scan resolver views, Faculty + IFO surfaces, PWA shell
templates/     Django templates (Franken UI + htmx), no separate frontend build
data/          gitignored registrar source data (raw CSVs, PII)
docs/          PROGRESS.md (status board), use-cases/scenarios, design specs, session logs
.planning/     GSD roadmap, per-phase context/research/plans/verification (tracked)
poc/           throwaway proof-of-concept + screenshots
```
Any change that adds, removes, or renames a Django app or top-level
directory updates this section in the same session
(see `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`).

## Status
**Phases 1–2 of 8 complete** (both verified against real SQL Server):
- **Phase 1 — MSSQL Environment & Data Foundation:** runs on SQL Server via
  `mssql-django`; proven datetime2/timezone round-trip (no Asia/Manila drift) and
  case-sensitive collation on QR/manual-code tokens.
- **Phase 2 — Correctness Foundations:** shared `notify()` write path, JOB-02 status
  sweep (no-show → Absent independent of any scan, backfilling + idempotent),
  deduped room-conflict flags, and one dedicated APScheduler process with job
  last-run status.

Foundation, IFO room/schedule surface, scan resolver, and Faculty check-in were
built and verified end-to-end earlier. **Next up: Phase 3 — Duty Assignments &
Checker Verification.** See **[`docs/PROGRESS.md`](docs/PROGRESS.md)** for the full
phase-by-phase board and `docs/USE_CASES.md` for the per-role feature list.

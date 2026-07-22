# FluxTrack

Faculty Attendance & Facility Utilization Information System for MMCM. FluxTrack
uses Django 6, htmx, shadcn design language through Franken UI, a PWA shell, and
Microsoft SQL Server. It has no React application, Node runtime, or CDN dependency.

Repository implementation through Phase 16 is complete. The remaining production
gate is credential-dependent Entra UAT plus AWS/RDS/DNS/TLS provisioning and the
cutover smoke test. See [`docs/PROGRESS.md`](docs/PROGRESS.md) for the status board.

## Documentation

- [`FluxTrack_SRS.md`](FluxTrack_SRS.md) — normative SRS v1.3 and requirement traceability
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — software architecture and design rationale
- [`docs/IT_ARCHITECTURE.md`](docs/IT_ARCHITECTURE.md) — infrastructure and security boundaries
- [`deploy/README.md`](deploy/README.md) — production deployment, rollback, monitoring, and recovery
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — concise current implementation/cutover status
- [`docs/USE_CASES.md`](docs/USE_CASES.md) — superseded 2026-07-02 planning snapshot

## Requirements
- Python 3.12 (`py -3.12` launcher on Windows)
- **SQL Server** — local dev uses SQL Server 2025 **LocalDB** (Windows integrated
  auth) or SQL Server Express; prod uses AWS RDS SQL Server Express
- **ODBC Driver 18 for SQL Server** (system-wide; required by `mssql-django`/`pyodbc`)
- Dependencies: `py -3.12 -m pip install --user -r requirements.txt`
  (Django 6.0.6, mssql-django 1.7.3, APScheduler <4)

## Run the app
```
py -3.12 manage.py runserver 8000
```
Open http://localhost:8000 → dev-login (click any role).
Admin: http://localhost:8000/admin — sign in as `sysadmin` / `devpass123`.

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
static/vendor/ pinned same-origin htmx, Franken UI, and html5-qrcode runtime assets
deploy/        Nginx, Gunicorn, systemd units, deploy script, and AWS runbook
data/          gitignored registrar source data (raw CSVs, PII)
docs/          PROGRESS.md (status board), use-cases/scenarios, design specs, session logs
.planning/     GSD roadmap, per-phase context/research/plans/verification (tracked)
poc/           throwaway proof-of-concept + screenshots
```
Any change that adds, removes, or renames a Django app or top-level
directory updates this section in the same session
(see `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`).

## Status

- **Features:** all seven role surfaces, attendance/verification, import and
  schedule operations, campus/term/suspension management, notifications, reports,
  utilization/lateness/coverage metrics, and scheduler operations are built.
- **Production hardening:** shared SQL Server cache, durable offline replay dedupe,
  secure proxy/HTTPS settings, same-origin vendor assets, health/watchdog checks,
  retention, and the EC2/RDS deployment package are built.
- **Verification baseline:** the complete SQL Server suite passed 1,259 tests with
  two expected skips; production `check --deploy`, migrations, and `collectstatic`
  passed after Phase 15.
- **Open external gate:** institutional Entra callback/UAT and AWS production
  provisioning, restore rehearsal, DNS/TLS, and smoke testing require credentials
  not present in this repository.

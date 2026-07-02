# FluxTrack

Faculty Attendance & Facility Utilization Information System for MMCM.
Django + htmx + Franken UI (Tailwind), PWA, no React / no Node runtime. See `FluxTrack_SRS.md`.

## Requirements
- Python 3.12 (`py -3.12` launcher on Windows)
- Dependencies: `py -3.12 -m pip install --user -r requirements.txt`

## Run the app
```
py -3.12 manage.py runserver 127.0.0.1:8020
```
Open http://127.0.0.1:8020 → dev-login (click any role).
Admin: http://127.0.0.1:8020/admin — sign in as `sysadmin` / `devpass123`.

Dev users (all password `devpass123`): `faculty` `checker` `ifo` `hr` `guard` `dean` `sysadmin`.

## First-time setup
```
py -3.12 manage.py migrate          # create the database
py -3.12 manage.py seed_demo        # 7 dev-login users + a little demo data
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
config/        settings, urls
accounts/      User (7 roles), Department
campus/        Building, Floor, Room
scheduling/    AcademicTerm, Schedule, Session, resolver.py (scan outcome logic) + import/materialize commands
verification/  Assignment, CheckerValidation
ops/           Booking, Notification, AuditLog, SystemSetting, WeeklyReport, policy.py
web/           frontend: dev-login, home, scan resolver views, Faculty + IFO surfaces, PWA shell
templates/     Django templates (Franken UI + htmx), no separate frontend build
data/          gitignored registrar source data (raw CSVs, PII)
docs/          use-cases/build reference, design specs, session logs
poc/           throwaway proof-of-concept + screenshots
```
Any change that adds, removes, or renames a Django app or top-level
directory updates this section in the same session
(see `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`).

## Status
Foundation, IFO room/schedule surface, scan resolver, and Faculty check-in
are built and verified end-to-end. See `docs/USE_CASES.md` for the full
per-role feature list and what's built vs. not. Next up: Checker surface.

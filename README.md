# FluxTrack

FluxTrack is MMCM's Faculty Attendance and Facility Utilization Information
System. It is a server-rendered Django 6 application backed exclusively by
Microsoft SQL Server. The interface uses htmx and Franken UI, includes a PWA
shell, and requires no React application, Node.js runtime, frontend build, or
CDN connection.

Repository implementation through Phase 16 is complete. The remaining production
gate is credential-dependent Microsoft Entra UAT plus AWS/RDS/DNS/TLS
provisioning and the cutover smoke test. See
[`docs/PROGRESS.md`](docs/PROGRESS.md) for the current status.

## Documentation

- [`FluxTrack_SRS.md`](FluxTrack_SRS.md) — normative SRS v1.3 and requirement traceability
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — software architecture and design rationale
- [`docs/IT_ARCHITECTURE.md`](docs/IT_ARCHITECTURE.md) — infrastructure and security boundaries
- [`deploy/README.md`](deploy/README.md) — production deployment, rollback, monitoring, and recovery
- [`docs/PROGRESS.md`](docs/PROGRESS.md) — concise implementation and cutover status
- [`docs/db_schema.sql`](docs/db_schema.sql) — historical application-DDL reference; use Django migrations to build a current database
- [`docs/USE_CASES.md`](docs/USE_CASES.md) — superseded 2026-07-02 planning snapshot

## Prerequisites

- Git
- Python 3.12
- Microsoft SQL Server:
  - Windows development: SQL Server 2025 LocalDB, Express, or Developer Edition
  - Production: AWS RDS for SQL Server Express
- [Microsoft ODBC Driver 18 for SQL Server](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)
- Optional: SQL Server Management Studio (SSMS) or `sqlcmd` for running the
  database bootstrap SQL

The Python packages are pinned in [`requirements.txt`](requirements.txt),
including Django 6.0.6, `mssql-django` 1.7.3, and APScheduler 3.x.

## Quick start on Windows

Run these commands from the repository root in PowerShell.

### 1. Create a virtual environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, call `.\.venv\Scripts\python.exe` in place of
`python` in the remaining commands.

### 2. Create the environment file

```powershell
Copy-Item .env.example .env
```

The checked-in `.env.example` is safe to copy. The resulting `.env` is
gitignored and must not be committed. Choose one of the SQL Server connection
options below and update its `DB_*` values.

### 3. Create the Microsoft SQL Server database

Django creates and updates FluxTrack's tables, indexes, constraints, built-in
authentication tables, social-auth tables, and shared cache table. It does not
create the outer `fluxtrack` database or a SQL Server login. Create the empty
database first, then run Django migrations in step 4.

#### Option A: LocalDB with Windows authentication

Start the standard LocalDB instance:

```powershell
sqllocaldb start MSSQLLocalDB
```

Run this query in SSMS while connected to `(localdb)\MSSQLLocalDB`, or run it
with `sqlcmd`:

```powershell
sqlcmd -S "(localdb)\MSSQLLocalDB" -E -Q "IF DB_ID(N'fluxtrack') IS NULL CREATE DATABASE [fluxtrack];"
```

Set these values in `.env`:

```dotenv
DB_NAME=fluxtrack
DB_USER=
DB_PASSWORD=
DB_HOST=(localdb)\MSSQLLocalDB
DB_PORT=
DB_TRUSTED_CONNECTION=yes
DB_ODBC_EXTRA=Encrypt=yes;TrustServerCertificate=yes
```

`DB_PORT` must be empty for a LocalDB or named-instance connection.

#### Option B: SQL Server Express/Developer with SQL authentication

Run the following in SSMS or `sqlcmd` as a SQL Server administrator. Replace
the example password before executing it.

```sql
USE [master];
GO

IF DB_ID(N'fluxtrack') IS NULL
    CREATE DATABASE [fluxtrack];
GO

IF SUSER_ID(N'fluxtrack_app') IS NULL
    CREATE LOGIN [fluxtrack_app]
        WITH PASSWORD = N'Replace-With-A-Strong-Local-Password';
GO

USE [fluxtrack];
GO

IF DATABASE_PRINCIPAL_ID(N'fluxtrack_app') IS NULL
    CREATE USER [fluxtrack_app] FOR LOGIN [fluxtrack_app];
GO

-- Local development only: Django migrations need DDL permissions.
ALTER ROLE [db_owner] ADD MEMBER [fluxtrack_app];
GO
```

For a default TCP instance listening on port 1433, use:

```dotenv
DB_NAME=fluxtrack
DB_USER=fluxtrack_app
DB_PASSWORD=Replace-With-A-Strong-Local-Password
DB_HOST=127.0.0.1
DB_PORT=1433
DB_TRUSTED_CONNECTION=no
DB_ODBC_EXTRA=Encrypt=yes;TrustServerCertificate=yes
```

For a named Express instance, use `DB_HOST=localhost\SQLEXPRESS` and leave
`DB_PORT=` empty. Ensure TCP/IP is enabled if connecting over TCP.

The `db_owner` grant above is intentionally limited to a local development
database. Production should use a dedicated deployment identity for migrations
and a least-privileged application login; never connect FluxTrack as `sa`.

### 4. Build the current schema

The Django migrations in each app's `migrations/` directory are the schema
source of truth. They must be used instead of manually importing
`docs/db_schema.sql`, which is an older application-only DDL reference and does
not include Django's built-in or all current project migrations.

```powershell
python manage.py migrate --plan
python manage.py migrate
python manage.py showmigrations
```

The final command should show `[X]` beside every migration. Re-run
`python manage.py migrate` after pulling any code that adds migrations.

The migration set creates these main schema areas:

| Migration group | Main tables |
|---|---|
| Django and social auth | Migration history, permissions, groups, sessions, admin log, and Microsoft Entra association tables |
| `accounts` | `accounts_department`, `accounts_user`, and user permission joins |
| `campus` | `campus_building`, `campus_floor`, and `campus_room` |
| `scheduling` | Terms, breaks, suspensions, schedules, sessions, and modality-shift requests/items |
| `verification` | Checker assignments, validations, and offline replay receipts |
| `ops` | Bookings, import staging, notifications, push subscriptions, audit logs, reports, conflicts, job runs, settings, and `fluxtrack_cache` |

Do not create these tables by hand. Future migrations may alter their columns,
indexes, constraints, or data in a specific dependency order.

### 5. Load local demo data

```powershell
python manage.py seed_demo
```

This creates seven development accounts, campus records, a term, rooms, and a
sample session. All demo accounts use the password `devpass123`:

| Role | Username |
|---|---|
| Faculty | `faculty` |
| Checker | `checker` |
| IFO Admin | `ifo` |
| HR Admin | `hr` |
| Guard | `guard` |
| Dean | `dean` |
| System Admin | `sysadmin` |

`seed_demo` creates known-password accounts and must never be run against a
production database.

### 6. Validate and run

```powershell
python manage.py check
python manage.py runserver 8000
```

Open [http://localhost:8000](http://localhost:8000). With `DEBUG=True`, use
the development login and choose a role. Django Admin is available at
[http://localhost:8000/admin](http://localhost:8000/admin) with
`sysadmin` / `devpass123`.

## Environment configuration

The application loads `.env` from the repository root. The important settings
are:

| Variable | Development purpose |
|---|---|
| `FLUXTRACK_ENV` | Use `development` locally and `production` only behind the documented HTTPS proxy |
| `SECRET_KEY` | Replace with a strong secret in every non-disposable environment |
| `DEBUG` | Enables the local role picker when `True`; must be `False` in production |
| `ALLOWED_HOSTS` | Comma-separated hostnames; do not use `*` in production |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins required in production |
| `DB_NAME`, `DB_HOST`, `DB_PORT` | SQL Server database address |
| `DB_USER`, `DB_PASSWORD` | SQL authentication credentials; blank with Windows authentication |
| `DB_TRUSTED_CONNECTION` | Set `yes` for Windows authentication and `no` for SQL authentication |
| `DB_ODBC_EXTRA` | Trust a local self-signed certificate only in development |
| `DB_TEST_NAME` | Optional isolated test database name; defaults to `test_fluxtrack` |
| `MEDIA_ROOT` | Persistent storage for uploaded and generated private files |
| `VAPID_*` | Optional web-push configuration |
| `SOCIAL_AUTH_*` | Microsoft Entra application credentials and tenant configuration |

Production configuration is fail-fast: it requires explicit hosts, secure
database TLS, strong secrets, and the Entra settings. Follow
[`deploy/README.md`](deploy/README.md) rather than adapting the development
commands.

## Background jobs

Run the scheduler from one dedicated process, never inside a web worker:

```powershell
python manage.py runscheduler
```

It materializes sessions, runs the attendance status sweep, generates reports,
records each job in `JobRun`, and notifies System Admins about failures. Only one
`runscheduler` process may run for an environment.

Useful one-shot commands:

```powershell
python manage.py run_status_sweep
python manage.py materialize_sessions --days 7
python manage.py generate_weekly_report
```

Production runs the scheduler through the dedicated systemd unit documented in
the deployment runbook.

## Load real schedule data

Registrar source files belong in `data/raw/`, which is gitignored because the
files may contain personally identifiable information. The importer reads the
Course Offering CSV's `Schedule` column and skips virtual `V` rooms.

```powershell
# Preview a slice without writing.
python manage.py import_offerings --building R --floor 3 --dry-run

# Import the slice.
python manage.py import_offerings --building R --floor 3

# Create dated sessions for the next seven days.
python manage.py materialize_sessions --days 7
```

Widen the import by omitting `--floor`, or omit both filters to process the
whole campus. Always review a dry run before importing institutional data.

## Tests

```powershell
# Full suite; creates and removes the configured MSSQL test database.
python manage.py test

# Fast pure-logic subset.
python manage.py test scheduling.tests.FacultyResolverTests
```

The SQL Server login used by the full suite must be allowed to create and drop
`DB_TEST_NAME` (default `test_fluxtrack`). For a local SQL-auth development
login, an administrator can grant that server-level ability with:

```sql
ALTER SERVER ROLE [dbcreator] ADD MEMBER [fluxtrack_app];
```

Do not grant `dbcreator` to the production runtime login. Use a unique
`DB_TEST_NAME` for simultaneous test runs.

## Reset local data

To delete application data while retaining the schema:

```powershell
python manage.py flush --no-input
python manage.py seed_demo
```

To perform a completely clean schema rebuild, drop and recreate only the local
`fluxtrack` database, then run `migrate` and `seed_demo` again. Back up any data
you need before either reset.

## Troubleshooting SQL Server

- **ODBC driver not found:** install the x64 Microsoft ODBC Driver 18 and confirm
  that its exact name is `ODBC Driver 18 for SQL Server`.
- **Login timeout or server not found:** verify the instance name, start the SQL
  Server service/LocalDB instance, and enable TCP/IP for TCP connections.
- **Certificate-chain error locally:** keep
  `Encrypt=yes;TrustServerCertificate=yes` only for local SQL Server. Production
  must validate the real certificate chain.
- **Login failed for user:** make sure the login exists at server scope, the
  matching user exists inside `fluxtrack`, and `.env` matches the selected
  authentication mode.
- **Cannot open database:** create the outer `fluxtrack` database before running
  `migrate`; Django migrations create tables, not the database itself.
- **Migration permission denied:** the migration identity needs schema DDL
  permissions. The local setup grants `db_owner`; production uses the deployment
  procedure in `deploy/README.md`.

## Rooms and buildings workspace

`/ifo/rooms` opens the live operational board. Use **Directory** for the
searchable building → floor → room inventory; its filters are bookmarkable.
Academic, Admin, and Gym are physical campus buildings. Online and Unassigned
remain searchable system records, while IT labs are room types on Academic
Building Floor 3. The legacy `/ifo/buildings` list redirects to Directory;
building detail and mutation links continue to work for bookmarks and
integrations.

## Project structure

```text
config/        Environment-driven Django settings, URL and WSGI configuration
accounts/      Custom User, seven roles, departments, Entra provisioning
campus/        Buildings, floors, rooms, room types, QR/manual room codes
scheduling/    Terms, schedules, sessions, imports, jobs, and management commands
verification/  Checker assignments, validation, and offline replay receipts
ops/           Bookings, notifications, audit, reports, cache, and job monitoring
web/           Server-rendered role surfaces, resolver views, PWA and push endpoints
templates/     Django templates using Franken UI and htmx
static/        Source static assets and pinned same-origin browser dependencies
staticfiles/   Collected production static assets
deploy/        Nginx, Gunicorn, systemd units, deployment script, and AWS runbook
data/          Gitignored registrar source data
docs/          Architecture, status, schema reference, design and session records
.planning/     GSD roadmap, plans, research, verification, and project state
poc/           Throwaway proof-of-concept material and screenshots
```

Any change that adds, removes, or renames a Django app or top-level directory
must update this section in the same change.

## Current status

- **Features:** all seven role surfaces, attendance and verification, schedule
  import and operations, campus/term/suspension management, notifications,
  reports, utilization/lateness/coverage metrics, and scheduler operations are
  implemented.
- **Production hardening:** shared SQL Server cache, durable offline replay
  deduplication, secure proxy/HTTPS settings, same-origin vendor assets,
  health/watchdog checks, retention, and the EC2/RDS deployment package are
  implemented.
- **Verification baseline:** the complete SQL Server suite passed 1,259 tests
  with two expected skips; production deployment checks, migrations, and static
  collection passed at the documented baseline.
- **External production gate:** institutional Entra callback/UAT and AWS
  production provisioning, restore rehearsal, DNS/TLS, and smoke testing require
  credentials that are not stored in this repository.

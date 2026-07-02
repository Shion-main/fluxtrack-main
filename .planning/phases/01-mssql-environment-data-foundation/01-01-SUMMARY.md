---
phase: 01-mssql-environment-data-foundation
plan: 01
subsystem: database
tags: [mssql, mssql-django, pyodbc, django, sql-server, localdb, odbc-driver-18]

# Dependency graph
requires:
  - phase: 00-planning
    provides: locked MSSQL-only stack decision, R3 slice numbers, CONTEXT/RESEARCH
provides:
  - Single env-driven MSSQL DATABASES config (ENGINE "mssql", ODBC Driver 18)
  - Pinned Django 6.0.6 + mssql-django 1.7.3 (sqlite/mysql branches removed)
  - MSSQL .env template (DB_ODBC_EXTRA / DB_TEST_NAME / DB_TRUSTED_CONNECTION)
  - Proven fresh-migrated + seeded fluxtrack database on a real SQL Server instance
  - Env-driven Trusted_Connection support for local Windows-auth LocalDB
provides_summary: "Proven MSSQL runtime base every later phase and both Wave-2 validation plans build on."
affects: [01-02, 01-03, phase-2, phase-8]

# Tech tracking
tech-stack:
  added: [mssql-django==1.7.3, pyodbc==5.3.0, Microsoft ODBC Driver 18 for SQL Server]
  patterns:
    - "Single env-driven DATABASES block — dev vs prod differ only by .env (DB_ODBC_EXTRA, DB_TRUSTED_CONNECTION)"
    - "Nullable-unique azure_oid relies on mssql-django's filtered unique index (WHERE col IS NOT NULL) — no AlterField, clean rebuild only"

key-files:
  created:
    - .planning/phases/01-mssql-environment-data-foundation/01-01-SUMMARY.md
  modified:
    - config/settings.py
    - requirements.txt
    - .env.example

key-decisions:
  - "Local dev DB is SQL Server 2025 LocalDB + Windows auth (Trusted_Connection), not the planned Express + SQL login — added env-driven DB_TRUSTED_CONNECTION so prod SQL-auth is unchanged"
  - "No fix-forward migration needed: all five 0001_initial migrations applied cleanly on SQL Server (nullable-unique azure_oid created as a filtered unique index)"

patterns-established:
  - "Env-driven DB config: identical code across dev/test/prod, only .env changes (encryption + auth mode)"
  - "Trusted_Connection toggle added conditionally to OPTIONS via env_bool('DB_TRUSTED_CONNECTION')"

requirements-completed: [ENV-01]

# Metrics
duration: 20min
completed: 2026-07-03
---

# Phase 1 Plan 01: MSSQL Environment Cutover Summary

**FluxTrack cut over to SQL Server — Django 6.0.6 + mssql-django 1.7.3 pinned, a single env-driven `mssql` settings branch (sqlite/mysql gone), and the full existing schema migrated + seeded cleanly on a real SQL Server 2025 LocalDB instance.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-03
- **Tasks:** 3 (Task 2 human-action gate verified as already-provisioned)
- **Files modified:** 3 source (config/settings.py, requirements.txt, .env.example)

## Accomplishments
- Pinned `Django==6.0.6` + `mssql-django==1.7.3` (installed and imported; `pip show mssql-django` → `Version: 1.7.3`); dropped the `Django>=5.0,<7.0` pin and the MySQL/SQLite branches entirely.
- Replaced the two-arm `DB_ENGINE == mysql / else sqlite` switch in `config/settings.py` with one MSSQL `DATABASES` config: `ENGINE "mssql"`, ODBC Driver 18, env-driven `extra_params` (`DB_ODBC_EXTRA`), and `TEST.NAME` (`DB_TEST_NAME`) for Wave-2 test-DB isolation.
- Rewrote `.env.example` to the MSSQL template and updated the stale SQLite/MySQL docstring.
- Migrated the full existing schema (all five apps' `0001_initial`) on SQL Server with zero errors — live proof the nullable-unique `azure_oid` inserts cleanly as a filtered unique index and nothing in the schema is MSSQL-hostile.
- `seed_demo` created the 7 role users (all `azure_oid = NULL`) with no `IntegrityError`; dev-login route (`GET /login` → 200) and a role landing page (`GET /` after `force_login` → 200) both serve against the MSSQL DB (`SURFACE OK 200`).

## Final Settings Block

```python
# --- Database: SQL Server only (dev, test, prod) ---
DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": env("DB_NAME", "fluxtrack"),
        "USER": env("DB_USER", ""),          # dedicated login, NOT sa
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "1433"),
        "OPTIONS": {
            "driver": "ODBC Driver 18 for SQL Server",
            "extra_params": env("DB_ODBC_EXTRA", "Encrypt=yes;TrustServerCertificate=yes"),
        },
        "TEST": {"NAME": env("DB_TEST_NAME", "test_fluxtrack")},
    }
}
if env_bool("DB_TRUSTED_CONNECTION", False):
    DATABASES["default"]["OPTIONS"]["trusted_connection"] = "yes"
```

## SQL Server Instance / Login / Collation Used

- **Instance:** SQL Server 2025 **LocalDB** — `(localdb)\MSSQLLocalDB` (host from `.env`, "Verified working 2026-07-03").
- **Auth:** Windows integrated (Trusted_Connection), login `SHION\joshu_mnu8z3u` (LocalDB owner — effectively sysadmin, **not** `sa`). `DB_USER`/`DB_PASSWORD` empty; `DB_TRUSTED_CONNECTION=yes`.
- **Server collation:** `SQL_Latin1_General_CP1_CI_AS` (contains `_CI_` ✓).
- **`fluxtrack` DB collation:** `SQL_Latin1_General_CP1_CI_AS` (contains `_CI_` ✓ — email dedup safe, Pitfall 4).
- **Permissions:** `IS_SRVROLEMEMBER('dbcreator')` = 1 and `HAS_PERMS_BY_NAME(..., 'CREATE ANY DATABASE')` = 1 → Django test runner can build `test_fluxtrack`.
- **Driver:** `pyodbc.drivers()` includes `ODBC Driver 18 for SQL Server`.

## Deps Installed (re-confirmed)

- `Django==6.0.6`, `mssql-django==1.7.3` (`pip show mssql-django` → `Version: 1.7.3`), `pyodbc==5.3.0` (transitive).

## Fix-Forward Migrations Added

**None.** All `0001_initial` migrations applied cleanly on SQL Server; no corrective migration required. No `AlterField` on `azure_oid`, no squash (per LOCKED fix-forward/keep-history decision). The deliberate CS-collation migration for `qr_token`/`manual_code` (RESEARCH Pattern 2) is **not** part of this plan and remains for a later Wave-2 plan.

## Task Commits

1. **Task 1: Pin deps + MSSQL-only settings branch** — `2a99c61` (feat)
2. **Task 2: Provision SQL Server + login + DB (human-action gate)** — no commit (already-provisioned; verified against the live instance, no source change)
3. **Task 3: Migrate + seed bring-up smoke** — no commit (runtime verification; no new source files, no fix-forward migration needed)

**Plan metadata:** see final docs commit.

## Files Created/Modified
- `config/settings.py` — single env-driven MSSQL DATABASES block + Trusted_Connection toggle; docstring rewritten for SQL Server-only.
- `requirements.txt` — `Django==6.0.6`, `mssql-django==1.7.3`; MySQL/SQLite lines removed.
- `.env.example` — MSSQL env template (DB_NAME/USER/PASSWORD/HOST/PORT, DB_ODBC_EXTRA, DB_TEST_NAME, DB_TRUSTED_CONNECTION).

## Decisions Made
- **LocalDB + Windows auth instead of Express + SQL login.** The plan (Task 2) assumed native SQL Server Express 2022 + a dedicated `fluxtrack_app` SQL login. The environment was already provisioned as SQL Server 2025 LocalDB with Windows integrated auth (documented in `.env` and the "local SQL Server bring-up" commit). Rather than re-provision, I honored the existing working instance and made the settings env-driven for it.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added env-driven `DB_TRUSTED_CONNECTION` support to settings**
- **Found during:** Task 1 / Task 3 (connecting to the provisioned DB)
- **Issue:** The plan's exact `DATABASES` block uses `DB_USER`/`DB_PASSWORD` (SQL auth). The actually-provisioned instance is LocalDB using Windows integrated auth with empty user/password — the plan block cannot connect, which would block Task 3 (migrate/seed).
- **Fix:** Appended a conditional `if env_bool("DB_TRUSTED_CONNECTION", False): OPTIONS["trusted_connection"] = "yes"` after the DATABASES block, and documented `DB_TRUSTED_CONNECTION` in `.env.example`. Prod SQL-auth path is unchanged (toggle defaults off).
- **Files modified:** config/settings.py, .env.example
- **Verification:** Live connect succeeded (`CONNECT OK`, login `SHION\joshu_mnu8z3u`); `migrate`, `seed_demo`, and `SURFACE OK 200` all ran against the real MSSQL DB.
- **Committed in:** `2a99c61` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The deviation was necessary to connect to the already-provisioned environment. It strengthens the plan's own goal (fully env-driven config where dev/prod differ only by `.env`). No scope creep. The plan's per-column CS-collation migration and DB-backed parity/round-trip tests remain owned by later Wave-2 plans, as designed.

## Issues Encountered
None during planned work. Note: the Task 2 human-action gate was already satisfied before execution (instance up, `.env` populated, verified 2026-07-03) via LocalDB rather than Express — verified live rather than stopped.

## User Setup Required
Already satisfied. Local SQL Server 2025 LocalDB instance with a case-INsensitive `fluxtrack` database, `dbcreator`/`CREATE ANY DATABASE` rights, and ODBC Driver 18 are provisioned and verified. `.env` is populated (Windows auth). For a different machine/prod, copy `.env.example` and set `DB_*` (SQL auth) or `DB_TRUSTED_CONNECTION=yes` (Windows auth).

## Next Phase Readiness
- MSSQL runtime base is proven — Wave-2 validation plans (datetime2/UTC round-trip, CS/CI collation round-trip, R3 parity) can build directly on this migrated + seeded DB.
- The CS-collation migration for `qr_token`/`manual_code` (RESEARCH Pattern 2) is still pending and belongs to a later plan — not yet applied.
- Test-DB creation rights confirmed (`CREATE ANY DATABASE`), so the Django test runner can build `test_fluxtrack` for the Wave-2 DB-backed tests.

---
*Phase: 01-mssql-environment-data-foundation*
*Completed: 2026-07-03*

## Self-Check: PASSED

All claimed files exist (config/settings.py, requirements.txt, .env.example, 01-01-SUMMARY.md) and Task 1 commit 2a99c61 is present in git history.

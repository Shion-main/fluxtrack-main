---
created: 2026-07-03
phase_target: 1
source: environment bring-up (2026-07-03)
tags: [phase-1, mssql, localdb, env, executor-must-read]
---

# Phase 1 executor: local DB is SQL Server 2025 LocalDB (deviations from plan assumptions)

The Phase 1 human checkpoint (stand up SQL Server) is **DONE** — but the working
local engine differs from what plan 01-01 assumed. The executor building the
`config/settings.py` mssql branch MUST account for these.

## What's actually running (verified working 2026-07-03)
- **Engine:** SQL Server **2025 (v17.0.1000.7)** via **LocalDB** instance `MSSQLLocalDB`.
  (Native SQL Server 2022 Express would NOT run on this Win11 24H2 machine — RTM
  engine crash, `0xc06d007e` missing-DLL. LocalDB 2025 works.)
- **Database:** `fluxtrack` created, collation `SQL_Latin1_General_CP1_CI_AS` (CI ✓).
- **Auth:** Windows auth (Trusted_Connection). The Windows user is sysadmin, so the
  test runner's `CREATE DATABASE` (for `test_fluxtrack`) works with no extra grant.
- **Driver:** ODBC Driver 18, connection verified with
  `Encrypt=yes;TrustServerCertificate=yes` (matches the plan's local OPTIONS).
- **.env already set:** `DB_ENGINE=mssql`, `DB_NAME=fluxtrack`,
  `DB_HOST=(localdb)\MSSQLLocalDB`, `DB_PORT=` (empty), `DB_USER=`/`DB_PASSWORD=` empty,
  `DB_TRUSTED_CONNECTION=yes`, `DB_TEST_NAME=test_fluxtrack`.

## Deviation 1 — Windows auth locally, not SQL login
Plan 01-01 assumed host/port/user/password (SQL auth, mirroring RDS). LocalDB uses
Windows auth. The mssql `DATABASES` branch must build a **Trusted_Connection** ODBC
string when `DB_USER` is empty / `DB_TRUSTED_CONNECTION=yes`, and fall back to
`UID/PWD` SQL auth when `DB_USER` is set (prod/RDS). Keep it env-driven so prod is a
`.env` swap. HOST is a LocalDB pipe name `(localdb)\MSSQLLocalDB` with empty PORT —
the branch must not force `HOST,PORT` TCP syntax when PORT is empty.

## Deviation 2 — engine is 2025, prod target is 2022
`mssql-django` 1.7.3 is validated against SQL Server 2016–2022; 2025 is newer.
Behavior for Phase 1's tests (collation CS/CI, `datetime2` UTC round-trip) is identical
across versions, so this is fine for Phase 1. BUT: validate the full suite on a real
**SQL Server 2022** (RDS or Docker `mssql/server:2022`) before the Phase 8 deploy, in
case of a connector quirk. See also the ENV parity goal in 01-CONTEXT.md.

## Machine note (not code)
Native SQL Server on this laptop required a one-time fix: the Samsung boot SSD reported
16 KB physical sectors (SQL max 4 KB). Fixed via registry
`HKLM\SYSTEM\CurrentControlSet\Services\stornvme\Parameters\Device\ForcedPhysicalSectorSizeInBytes = "* 4095"`
+ reboot. Already applied. Relevant only if rebuilding the box or moving to another machine.

# Session — 2026-07-03: Phase 1 planned + local SQL Server brought up

## What was done

- **Phase 1 planned** (`/gsd:plan-phase 1`): research → 3 plans in 2 waves →
  Nyquist VALIDATION.md → plan-checker verified (PASSED on iteration 2 after one
  revision round). Plans:
  - 01-01 (wave 1): mssql settings branch, dep pins (Django 6.0.6 / mssql-django
    1.7.3 / pyodbc), DB bring-up checkpoint, `migrate` + `seed_demo` + test-client boot proof.
  - 01-02 (wave 2): datetime2 round-trip (no 8h Manila drift) + R3 parity 17/10/15/18/18.
  - 01-03 (wave 2): CS collation on `qr_token`/`manual_code` + collation round-trip.
  - Checker's iter-1 fixes: broken `migrate --check` gate, Wave-2 test-DB collision
    (isolated via `DB_TEST_NAME`), weak boot proof, collation index-survival check.
- **Entra ID verified + backend decided.** Ran a client-credentials token request
  against the tenant — client id / secret / tenant all valid and working. Registered
  redirect URI `…/auth/complete/azuread-tenant-oauth2/` is python-social-auth's
  `AzureADTenantOAuth2` convention → decided to adopt that backend (not custom MSAL)
  so the app conforms to the credentials. Creds in `.env` under both `ENTRA_*` and
  `SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_*`. Phase 8 work; todo captured.
- **Local SQL Server stood up** (the Phase 1 human checkpoint) — see the saga below.
  `fluxtrack` DB created on SQL Server 2025 LocalDB, `_CI_` collation, ODBC Driver 18
  verified. `.env` DB settings written.

## Key findings (the DB saga)

- **Root cause of repeated "install failed":** the Samsung boot SSD (C:) reports a
  **16 KB physical sector size**; SQL Server supports max 4 KB, so every engine
  crashed on startup ("misaligned log IOs → Fatal Error"). Not a version or hardware
  (Ryzen 5 5600H is fine) problem.
- **Fix:** registry `HKLM\SYSTEM\CurrentControlSet\Services\stornvme\Parameters\Device`
  → `ForcedPhysicalSectorSizeInBytes = "* 4095"` (REG_MULTI_SZ) + **reboot**. After
  this both NVMe drives report 4096 and the engine starts. (Reversible.)
- **Native SQL Server 2022 Express won't run on this box** even after the sector fix:
  2022 RTM (16.0.1000.6) crashes on Windows 11 24H2 with `0xc06d007e` (missing
  delay-loaded DLL). Unfixable without patched media. **SQL Server 2025 LocalDB runs
  fine**, so local dev uses that.
- **Verified working:** `(localdb)\MSSQLLocalDB`, DB `fluxtrack`, collation
  `SQL_Latin1_General_CP1_CI_AS`, ODBC Driver 18 with `Encrypt=yes;TrustServerCertificate=yes`,
  Windows auth (user is sysadmin → test-runner `CREATE DATABASE` works).

## What's left / next

- **`/gsd:execute-phase 1`** — plans are ready; DB checkpoint is done.
- **Executor must read** `.planning/todos/pending/phase1-localdb-env-deviations.md`:
  the settings mssql branch must build a **Trusted_Connection** string when `DB_USER`
  is empty (LocalDB/Windows auth), not force `HOST,PORT` TCP.
- **Parity caveat:** local engine is 2025 (v17); prod target is RDS 2022 (v16), and
  mssql-django 1.7.3 is validated to 2022. Phase 1 tests behave identically, but
  validate the suite on real 2022 (RDS or Docker `mssql/server:2022`) before Phase 8.
- **Optional cleanup:** 5 dead SQL instances from failed attempts (`SQLEXPRESS01/02/03`,
  `SQLEXPRESS04`, partial `FLUXTRACK`) can be removed (elevated).
- Entra: adopt `social-auth-app-django` `AzureADTenantOAuth2` in Phase 8; rotate the
  client secret before prod (it was shared in-session).

## Commits this session

`.planning/` Phase 1 artifacts (RESEARCH, VALIDATION, 3 PLANs, revision). Untracked:
`docs/sessions/2026-07-03-*.md` (this log), two `.planning/todos/pending/` notes.
`.env` is gitignored (DB + Entra creds live there, not committed).

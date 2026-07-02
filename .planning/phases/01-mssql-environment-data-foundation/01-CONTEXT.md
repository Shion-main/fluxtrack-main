# Phase 1: MSSQL Environment & Data Foundation - Context

**Gathered:** 2026-07-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Get FluxTrack running correctly on SQL Server — locally and in a way that
carries to the RDS prod target — at the R3-slice scale it already runs on
SQLite, with no timezone drift and no case-folding surprises. Covers ENV-01
and ENV-02. AWS RDS provisioning and actual deployment are NOT in this phase
(Phase 8) — but all DB config must be env-driven so prod is just a different
`.env`.

</domain>

<decisions>
## Implementation Decisions

### Local dev database
- **SQL Server Express 2022** installed natively on Windows (full parity
  with the RDS SQL Server Express prod target). Not Docker, not LocalDB/SQL
  Edge (those diverge on collation/features and undercut the parity goal).
- **Dedicated `fluxtrack` database + a dedicated SQL Server login** (NOT
  `sa`) for the app. Host/port/name/user/password live in `.env` (already
  gitignored), mirroring how RDS credentials will work in prod.
- **ODBC Driver 18 for SQL Server** with `Encrypt=yes;TrustServerCertificate=yes`
  in the LOCAL connection OPTIONS (local Express uses a self-signed cert).
  Prod (RDS) trusts a real cert chain — do NOT disable encryption; this must
  be env-driven so dev and prod differ safely.

### Cutover approach
- **Clean rebuild**, not data migration. Point `DB_ENGINE` at the fresh SQL
  Server DB, run `migrate` from scratch, re-run `seed_demo` (7 role users)
  and re-import the R3 slice. Current SQLite data is reproducible test data —
  rebuilding is simpler and re-exercises the import path on MSSQL (a success
  criterion anyway).
- **Automated parity test on the R3 slice**: import + materialize on MSSQL and
  assert the counts/values already validated on SQLite — 17 sections, 10
  rooms, 15 faculty, 18 schedules, 18 materialized sessions with correct
  times/faculty. Repeatable, catches silent datetime/collation regressions.
  (Satisfies success criterion 4.)
- **Fix-forward migrations, keep history.** If a migration operation fails on
  SQL Server, add a corrective migration or adjust the offending field —
  don't squash to a new baseline. Preserves the schema-evolution trail
  (matters for capstone defense).

### SQLite's fate
- **Remove the SQLite `DB_ENGINE` branch entirely — MSSQL only**, one
  database everywhere (dev, test, prod). Maximum parity, no engine-specific
  bug can hide. The existing `config/settings.py` DB switch currently has
  `mysql`/`sqlite` branches — replace with an `mssql` branch and drop
  `sqlite` (and `mysql`, now unused).
- **Tests target MSSQL** (no SQLite test path). Django's test runner creates
  a real SQL Server test database, so the dev login needs `CREATE DATABASE`
  permission. Note: the existing resolver tests are `SimpleTestCase` and
  touch no DB — they keep running without one and needn't be converted just
  to hit a DB (that gains nothing); the point is there is no SQLite fallback
  and any DB-backed test (the parity test, round-trips) runs on SQL Server.

### Collation & datetime correctness
- **Column-level case-sensitive collation** (e.g. `Latin1_General_100_CS_AS`)
  applied via migration to **`qr_token`** and **`manual_code`** only
  (opaque, case-distinct security tokens where a case-collision is a real
  bug). Rest of the DB stays at the normal (case-insensitive) collation —
  surgical, not database-wide.
- **Faculty email: case-INsensitive** (leave at default collation). This is
  MORE correct than SQLite was — the import matches a professor regardless of
  how the registrar cased their email, preventing duplicate faculty. Emails
  are case-insensitive by real-world convention.
- **Datetimes: `datetime2` storing UTC**, `USE_TZ=True`, convert to
  Asia/Manila only at display (templates). This is mssql-django's default
  DateTimeField mapping and avoids the `DATETIMEOFFSET`/pyodbc tz-loss
  round-trip quirk the pitfalls research flagged. An explicit aware-datetime
  round-trip test must prove a written timestamp reads back as the same
  Asia/Manila instant (no 8-hour drift). (Satisfies success criteria 2 & 3.)

### Claude's Discretion
- Exact test file organization (new `campus/tests.py` / `scheduling/tests.py`
  additions vs. a dedicated `tests/` — planner decides, consistent with the
  existing `scheduling/tests.py` SimpleTestCase style).
- Precise ODBC connection-string OPTIONS beyond the encryption settings above.
- How the collation override is expressed in migrations (raw SQL
  `RunSQL` vs. field `db_collation=` — mssql-django supports `db_collation`).

### Carried forward from research (LOCKED — not re-discussed)
- `mssql-django` **1.7.3**, pin **`Django==6.0.6`** — no downgrade (1.7.3
  officially supports Django 6.0). Django 5.2 LTS is the ONLY fallback, used
  only if the runtime spike surprises us.
- `pyodbc` + **Microsoft ODBC Driver 18 for SQL Server** as the driver stack.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### MSSQL migration — approach & risks
- `.planning/research/STACK.md` — mssql-django 1.7.3 / Django 6.0.6 support finding, connection config, driver stack
- `.planning/research/PITFALLS.md` — SQL Server case-insensitive collation, pyodbc DATETIMEOFFSET/datetime2 tz round-trip, top correctness risks with prevention steps
- `.planning/research/ARCHITECTURE.md` — where new code fits (though this phase is mostly config + tests)
- `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §1 — MSSQL decision, DB_ENGINE branch, requirements.txt additions (mssql-django, pyodbc)

### Existing codebase touchpoints
- `.planning/codebase/STACK.md`, `.planning/codebase/INTEGRATIONS.md`, `.planning/codebase/CONCERNS.md` — current DB config state and the mssql-migration concern
- `config/settings.py` — existing `DB_ENGINE` env switch (mysql/sqlite branches to replace with mssql-only), `USE_TZ`, `TIME_ZONE="Asia/Manila"`
- `requirements.txt` — Django pin to tighten to ==6.0.6; add mssql-django, pyodbc
- `campus/models.py` — `qr_token`, `manual_code` fields needing case-sensitive collation
- `accounts/models.py` — `User` email uniqueness (case-insensitive intent)
- `scheduling/models.py` — `Session` datetime fields (datetime2/UTC)
- `scheduling/management/commands/import_offerings.py`, `materialize_sessions.py` — the import/materialize path under the parity test
- `scheduling/tests.py` — existing SimpleTestCase + dataclass-fake pattern to mirror for new tests

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `config/settings.py` `DB_ENGINE` env switch: already the extension point —
  add an `mssql` branch, remove `sqlite`/`mysql`.
- `accounts/management/commands/seed_demo.py`: re-run after clean rebuild to
  recreate the 7 role users + policy SystemSettings.
- `import_offerings` / `materialize_sessions` commands: the exact subjects of
  the parity test; already validated on SQLite (known R3 numbers).
- `scheduling/tests.py`: SimpleTestCase + FakeSession/FakeSchedule dataclass
  style is the template for new tests (round-trip + parity).

### Established Patterns
- Env-driven settings via dotenv — dev/prod differ only by `.env`, so the
  encryption + credential differences (local self-signed vs RDS TLS) fit the
  existing pattern.
- Management-command output is ASCII-only (Windows cp1252) — any new command
  output must follow.

### Integration Points
- `config/settings.py` `DATABASES` — the one place the engine/driver/OPTIONS
  are configured.
- Migrations across `campus` (collation on qr_token/manual_code) and possibly
  others if any op is MSSQL-incompatible.

</code_context>

<specifics>
## Specific Ideas

- Parity is the whole point: the phase succeeds only when the R3 numbers
  (17/10/15/18/18) reproduce exactly on MSSQL and an aware timestamp
  round-trips to the same Asia/Manila instant.
- "More correct than SQLite" is acceptable and wanted for emails
  (case-insensitive), even though it's a behavior change — it prevents
  duplicate faculty.

</specifics>

<deferred>
## Deferred Ideas

- AWS RDS SQL Server Express provisioning + prod deployment — Phase 8.
  This phase only proves the runtime locally and keeps config env-driven so
  prod is a `.env` swap.
- Tailwind v4 / Franken UI standalone build (the other stack risk) — Phase 8.
- MySQL support — dropped entirely with SQLite (MSSQL-only decision).

</deferred>

---

*Phase: 01-mssql-environment-data-foundation*
*Context gathered: 2026-07-02*

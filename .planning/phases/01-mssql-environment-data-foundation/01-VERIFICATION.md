---
phase: 01-mssql-environment-data-foundation
verified: 2026-07-03T00:00:00Z
status: passed
score: 4/4 success criteria verified
---

# Phase 1: MSSQL Environment & Data Foundation Verification Report

**Phase Goal:** FluxTrack runs correctly on SQL Server at the scale already validated on SQLite, with no timezone drift and no case-folding surprises — the proven base every later phase builds on.
**Verified:** 2026-07-03
**Status:** passed
**Re-verification:** No — initial verification

## Environment Note

This machine runs SQL Server 2025 **LocalDB** with Windows integrated auth (`DB_TRUSTED_CONNECTION=yes` in `.env`), not the originally-planned SQL Server Express + SQL login. This is an approved deviation (documented in 01-01-SUMMARY.md and `.env`), and `config/settings.py` supports both auth modes env-driven (`DB_TRUSTED_CONNECTION` toggle, defaulting off so prod SQL-auth is unchanged). All live verification below was run against this real LocalDB instance — not mocked.

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | App boots and serves every existing surface with DB_ENGINE=mssql, Django 6.0.6 / mssql-django 1.7.3, no downgrade | VERIFIED | `py -3.12 -c "import django; print(django.get_version())"` → `6.0.6`; `pip show mssql-django` → `Version: 1.7.3`. `manage.py check` exits 0. Live test-client run: `GET /login` → 200, `force_login` + `GET /` (follow redirects) → 200, against the real MSSQL DB (re-ran independently, not just trusting SUMMARY). `requirements.txt` has no `mysqlclient`, no `Django>=5.0`; `config/settings.py` has zero occurrences of `django.db.backends` (sqlite/mysql branches fully removed). |
| 2 | Aware Asia/Manila attendance timestamp round-trips on SQL Server with no 8-hour drift | VERIFIED | `scheduling.tests.DatetimeRoundTripTests` (2 tests) re-run live against the real SQL Server test DB: both pass. `test_manila_midnight_instant_survives_roundtrip` asserts 00:30 PHT → 16:30 UTC same instant after `refresh_from_db()`; `test_manila_0800_reads_back_as_0000_utc` asserts 08:00 PHT → 00:00 UTC. No `DATETIMEOFFSET` usage; uses `datetime2`/aware-UTC storage per `USE_TZ=True`. |
| 3 | Case-variant opaque tokens (QR tokens) don't collide; case-variant faculty emails still dedupe | VERIFIED | `campus.tests.CollationRoundTripTests` (3 tests) re-run live: pass. Live `sys.columns` query confirms `qr_token`/`manual_code` on `campus_room` carry `Latin1_General_100_CS_AS` collation. Live `sys.indexes` query confirms both columns still have a unique index/constraint (`UQ_campus_room_qr_token`, `UQ_campus_room_manual_code`, `is_unique=True`) after the collation change — duplicate-token insert raises `IntegrityError` (proven by test). Case-variant email dedup test passes, confirming DB default collation is CI. |
| 4 | Registrar CSV import + session materialization produce the same sessions on MSSQL as SQLite at R3-slice scale | VERIFIED | Re-ran `scheduling.tests.R3ParityTests` and `ImportPathTests` live: both pass. `R3ParityTests` ran against the real registrar CSV (present on this machine, not skipped) and reproduced the exact validated counts: 17 sections / 10 rooms / 15 faculty / 18 schedules / 18 sessions. `ImportPathTests` against the committed CI-safe fixture (`data/fixtures/r3_synthetic.csv`, tracked in git, not under gitignored `/data/raw/`) reproduced 3/2/2/3 as specified. |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `config/settings.py` | Single env-driven MSSQL DATABASES config | VERIFIED | Contains `"ENGINE": "mssql"`, `extra_params`/`DB_ODBC_EXTRA`, `TEST.NAME`/`DB_TEST_NAME`, plus an approved `DB_TRUSTED_CONNECTION` addition for LocalDB. Zero `django.db.backends` references remain. `manage.py check` and `migrate --check` both exit 0. |
| `requirements.txt` | Pinned Django 6.0.6 + mssql-django 1.7.3 | VERIFIED | Exact pins present; `mysqlclient` and `Django>=5.0` removed; confirmed installed versions match exactly. |
| `.env.example` | MSSQL env template | VERIFIED | Contains `DB_ODBC_EXTRA`, `DB_TEST_NAME`, `DB_TRUSTED_CONNECTION`; no `DB_ENGINE=mysql`. |
| `scheduling/tests.py` | DatetimeRoundTripTests, R3ParityTests, ImportPathTests, make_session helper | VERIFIED | All classes present; all tests pass live against real SQL Server. `FacultyResolverTests` (pre-existing pure suite) still passes — 23 tests total in the module, all green. |
| `data/fixtures/r3_synthetic.csv` | Committed anonymized CSV | VERIFIED | Tracked in git, matches plan content exactly, drives `ImportPathTests` to the specified 3/2/2/3 counts. |
| `campus/migrations/0002_cs_collation_tokens.py` | CS collation migration with unique constraint reinstated | VERIFIED | Hand-written RunSQL migration (documented departure from a no-op `db_collation` AlterField); dynamically discovers and recreates the unique constraint. Live DB confirms both columns are CS-collated and still unique. |
| `campus/models.py` | `db_collation=` on qr_token/manual_code | VERIFIED | Present on both fields; `makemigrations --check --dry-run` reports "No changes detected" (model state matches DB). |
| `campus/tests.py` | CollationRoundTripTests | VERIFIED | 3 tests present and passing live: tokens-distinct, duplicate-raises-IntegrityError, emails-dedupe. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `config/settings.py DATABASES.default.OPTIONS.extra_params` | `env('DB_ODBC_EXTRA')` | env-driven ODBC string | WIRED | Confirmed by direct read of settings.py line 92-95. |
| `config/settings.py DATABASES.default.ENGINE` | mssql-django backend | `"ENGINE": "mssql"` | WIRED | Confirmed; live connection to real SQL Server succeeded for all test runs. |
| `scheduling/tests.py DatetimeRoundTripTests` | `Session.scheduled_start` on SQL Server `datetime2` | create → refresh_from_db → assertEqual | WIRED | Test re-executed live, passes against real DB (not mocked). |
| `scheduling/tests.py ImportPathTests` | `import_offerings` + `materialize_sessions` commands | `call_command` against fixture | WIRED | Test re-executed live; command output shows real import/materialize run (3 sections, 3 sessions). |
| `campus/migrations/0002 RunSQL` | `campus_room.qr_token`/`manual_code` columns | `ALTER COLUMN ... COLLATE` + constraint recreate | WIRED | Live `sys.columns`/`sys.indexes` query confirms collation and uniqueness on the real table. |
| `campus/tests.py CollationRoundTripTests` | collated columns + CI email default | `assertRaises(IntegrityError)` | WIRED | Test re-executed live, passes. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| ENV-01 | 01-01, 01-02, 01-03 | Project runs on SQL Server via mssql-django, DB_ENGINE=mssql, Django pinned 6.0.6, proven datetime2/timezone + collation round-trip | SATISFIED | Truths 1, 2, 3 above all directly verified live. |
| ENV-02 | 01-02 | Registrar CSV import + session materialization run correctly against MSSQL at R3-slice scale already validated on SQLite | SATISFIED | Truth 4 above, directly verified live (17/10/15/18/18 real-CSV run + 3/2/2/3 fixture run). |

No orphaned requirements: REQUIREMENTS.md traceability table maps only ENV-01 and ENV-02 to Phase 1, and both are declared across the three plans' frontmatter and satisfied.

### Anti-Patterns Found

None. Scanned `scheduling/tests.py` and `campus/tests.py` for TODO/FIXME/placeholder/stub markers — no matches. No empty handlers, no static-return stubs in the modified files. The one deliberate departure from the original plan template (RunSQL fallback instead of a no-op `db_collation` AlterField) is documented in 01-03-SUMMARY.md and independently confirmed to be necessary and correctly landed (verified live above) — not a shortcut.

### Human Verification Required

None. All four success criteria are provable by automated test/DB inspection and were independently re-executed against the live SQL Server instance during this verification (not just trusted from SUMMARY claims).

### Gaps Summary

No gaps. All must-haves from all three plans' frontmatter were independently re-verified against the actual codebase and a live SQL Server database:
- `manage.py check` and `migrate --check` both exit 0.
- Full re-run of `scheduling.tests` + `campus.tests` (23 tests) passes live, including the pre-existing `FacultyResolverTests` pure suite (regression-safe).
- `makemigrations --check --dry-run` reports no drift.
- Live `sys.columns`/`sys.indexes` queries against `campus_room` confirm CS collation + reinstated uniqueness.
- Live test-client check confirms `/login` and role-landing-page both serve 200 against MSSQL.
- Both requirement IDs (ENV-01, ENV-02) are satisfied with direct evidence.

The one approved environment deviation (LocalDB + Windows auth instead of Express + SQL login) is properly env-driven and does not compromise the phase goal — prod's SQL-auth path is unchanged and the `DB_TRUSTED_CONNECTION` toggle defaults off.

---

*Verified: 2026-07-03*
*Verifier: Claude (gsd-verifier)*

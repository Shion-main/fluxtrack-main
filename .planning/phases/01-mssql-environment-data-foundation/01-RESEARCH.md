# Phase 1: MSSQL Environment & Data Foundation - Research

**Researched:** 2026-07-02
**Domain:** Django 6.0 → SQL Server (mssql-django/pyodbc) cutover; timezone-correct storage; per-column collation; test-runner + parity tests
**Confidence:** HIGH (codebase read directly; stack/pitfalls cross-verified) / MEDIUM (collation-on-unique migration mechanics, test-DB collation control)

## Summary

Every strategic decision for this phase is already locked in CONTEXT.md; this research fills the **implementation gaps a planner needs** and de-risks the two known landmines (nullable-unique on `azure_oid`, collation-change on a unique column). The codebase is small and clean: five initial migrations, no `CheckConstraint`/conditional `UniqueConstraint`, no raw SQL, two JSONFields, and datetimes already stored via `USE_TZ=True` + `timezone.make_aware(...)`. Nothing in the schema is fundamentally MSSQL-hostile.

The single highest-value finding: **mssql-django already implements nullable-unique columns as filtered unique indexes (`WHERE col IS NOT NULL`), so the 7 seed users and 15 imported faculty that all carry `azure_oid = NULL` will `migrate`/insert cleanly** — the classic "SQL Server allows only one NULL in a UNIQUE constraint" trap is handled by the backend on a fresh CREATE. The documented mssql-django bugs in this area are all about *altering* a nullable-unique field, which this clean-rebuild phase never does.

The second finding shapes how collation is applied: changing a **unique** column's collation via a Django-generated `AlterField` is exactly the operation mssql-django has repeatedly mis-handled (unique index not reinstated). Because this is a clean rebuild, the reliable path is an **explicit `RunSQL` migration** (drop filtered unique index → `ALTER COLUMN ... COLLATE` → recreate index) wrapped with `state_operations` describing `db_collation`, rather than trusting the auto-generated `AlterField`.

**Primary recommendation:** Add an `mssql` branch to `DB_ENGINE` (drop `sqlite`/`mysql`), pin `Django==6.0.6` + `mssql-django==1.7.3`, apply CS collation to `qr_token`/`manual_code` via an explicit `RunSQL` migration, keep datetimes at `datetime2`/UTC (no `DATETIMEOFFSET`), and prove correctness with three DB-backed tests on the SQL Server test database: an aware-datetime round-trip, a collation round-trip (tokens stay distinct / emails dedupe), and an R3-slice import+materialize parity assertion (17/10/15/18/18).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ENV-01 | Project runs on SQL Server via mssql-django in dev + prod, `DB_ENGINE=mssql`, Django 6.0.6, proven datetime2/timezone + collation round-trip | Settings `mssql` branch (below), pinned versions verified, datetime2/UTC round-trip test design, per-column CS collation migration approach, nullable-unique filtered-index confirmation |
| ENV-02 | Registrar CSV import + session materialization run correctly on MSSQL at R3-slice scale | `import_offerings --building R --floor 3` + `materialize_sessions --days 7` produce 17/10/15/18/18; parity-test design; fixture-vs-real-file gap flagged |
</phase_requirements>

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Local dev DB:** SQL Server Express 2022 installed natively on Windows (NOT Docker, NOT LocalDB/SQL Edge). Dedicated `fluxtrack` database + a dedicated SQL Server login (NOT `sa`). Host/port/name/user/password in `.env` (gitignored).
- **Driver:** ODBC Driver 18 for SQL Server, with `Encrypt=yes;TrustServerCertificate=yes` in the LOCAL connection OPTIONS (local self-signed cert). Prod (RDS) trusts a real cert chain — do NOT disable encryption; encryption/trust must be env-driven so dev and prod differ safely.
- **Cutover:** Clean rebuild, not data migration. Point `DB_ENGINE` at the fresh SQL Server DB, `migrate` from scratch, re-run `seed_demo` (7 role users), re-import the R3 slice.
- **Parity test:** Automated test on the R3 slice — import + materialize on MSSQL, assert 17 sections, 10 rooms, 15 faculty, 18 schedules, 18 materialized sessions with correct times/faculty.
- **Migrations:** Fix-forward, keep history. If an op fails on SQL Server, add a corrective migration or adjust the field — do NOT squash to a new baseline.
- **SQLite's fate:** Remove the SQLite `DB_ENGINE` branch entirely — MSSQL only (dev, test, prod). Also drop the now-unused `mysql` branch. Tests target MSSQL; Django's test runner creates a real SQL Server test database, so the dev login needs `CREATE DATABASE` permission. Existing `SimpleTestCase` resolver tests touch no DB and keep running without one.
- **Collation:** Column-level case-sensitive collation (e.g. `Latin1_General_100_CS_AS`) applied via migration to `qr_token` and `manual_code` ONLY. Rest of DB stays case-insensitive.
- **Faculty email:** case-INsensitive (leave at default collation) — more correct than SQLite; the import matches a professor regardless of email casing, preventing duplicate faculty.
- **Datetimes:** `datetime2` storing UTC, `USE_TZ=True`, convert to Asia/Manila only at display. This is mssql-django's default DateTimeField mapping and avoids the `DATETIMEOFFSET`/pyodbc tz-loss round-trip. An explicit aware-datetime round-trip test must prove no 8-hour drift.
- **Versions (LOCKED, carried from research):** `mssql-django==1.7.3`, `Django==6.0.6` (no downgrade — 1.7.3 officially supports Django 6.0). Django 5.2 LTS is the ONLY fallback, used only if the runtime spike surprises us. `pyodbc` + Microsoft ODBC Driver 18.

### Claude's Discretion
- Exact test file organization (new `campus/tests.py` / `scheduling/tests.py` additions vs. a dedicated `tests/`), consistent with the existing `scheduling/tests.py` `SimpleTestCase` style.
- Precise ODBC connection-string OPTIONS beyond the encryption settings.
- How the collation override is expressed in migrations (raw SQL `RunSQL` vs. field `db_collation=`; mssql-django supports `db_collation`).

### Deferred Ideas (OUT OF SCOPE)
- AWS RDS SQL Server Express provisioning + prod deployment — Phase 8. This phase only proves the runtime locally and keeps config env-driven so prod is a `.env` swap.
- Tailwind v4 / Franken UI standalone build — Phase 8.
- MySQL support — dropped entirely with SQLite (MSSQL-only decision).
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mssql-django | 1.7.3 (2026-06-19) | Django DB backend `mssql` (`ENGINE: "mssql"`) | Microsoft-maintained, only actively-maintained MSSQL backend; certifies Django 6.0 |
| pyodbc | ≥5.2 (auto-pulled) | Python ↔ SQL Server over ODBC | Hard dependency of mssql-django; needs a system ODBC driver |
| Microsoft ODBC Driver 18 for SQL Server | 18.x (system MSI, not pip) | ODBC layer | Current TLS defaults; mssql-django supports 17 or 18 — use 18 |
| Django | 6.0.6 (pinned) | Framework | SRS target; inside mssql-django 1.7 support matrix |

### Supporting (already present, unchanged this phase)
| Library | Version | Purpose |
|---------|---------|---------|
| python-dotenv | ≥1.0 | `.env` loading (already wired in `config/settings.py`) |
| djangorestframework | ≥3.15 | Session-auth API (unaffected) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Django 6.0.6 | Django 5.2 LTS | Only if the spike hits a 6.0-specific runtime break (not expected). 5.2 is the guaranteed-safe floor. |
| mssql-django | django-mssql-backend / django-pyodbc-azure | Never — both abandoned; mssql-django is the official successor. |
| ODBC Driver 18 | ODBC Driver 17 | 17 works but 18 has current TLS/encrypt defaults; the LOCKED decision is 18. |

**requirements.txt changes:**
```diff
-Django>=5.0,<7.0
+Django==6.0.6
+mssql-django==1.7.3          # pulls pyodbc; needs ODBC Driver 18 installed system-wide
-# mysqlclient>=2.2          # uncomment for MySQL 8.0 on AWS RDS   ← delete (MySQL dropped)
```
`pyodbc` is pulled transitively; pinning `pyodbc>=5.2` explicitly is optional but harmless.

**Version verification:** `mssql-django==1.7.3` (2026-06-19) and `Django==6.0.6` were both verified against PyPI/official blog in `.planning/research/STACK.md` (HIGH). Re-confirm at install time with `py -3.12 -m pip index versions mssql-django` and `pip show mssql-django` after install.

## Architecture Patterns

This phase is **config + migration + tests only** — no new app, no new domain module. The flat app layout (`accounts/ campus/ scheduling/ verification/ ops/ web/`) is fixed.

### Pattern 1: The `mssql` settings branch (replaces sqlite/mysql)

Current `config/settings.py` (lines 77–96) has a two-arm `if DB_ENGINE == "mysql" / else sqlite`. Replace the whole block with a single MSSQL config. Keep everything env-driven so prod is a `.env` swap (encryption/trust differ safely between dev self-signed and RDS real cert).

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
            # env-driven encryption: local Express = self-signed (trust it);
            # RDS = real cert chain (Encrypt=yes, do NOT trust-blindly)
            "extra_params": env(
                "DB_ODBC_EXTRA",
                "Encrypt=yes;TrustServerCertificate=yes",
            ),
        },
    }
}
```
`.env.example` gains: `DB_ENGINE=mssql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT=1433`, `DB_ODBC_EXTRA`. Note the docstring at the top of `settings.py` (lines 1–5) still says "SQLite by default … MySQL" and must be updated. The `DB_ENGINE` variable name is kept only as documentation/guard; there is now only one branch (`mssql`), so the `env("DB_ENGINE")` switch can be removed entirely or reduced to an assertion.

- **Local:** `Encrypt=yes;TrustServerCertificate=yes` (Driver 18 defaults `Encrypt=yes`; local Express presents a self-signed cert, so trust it).
- **Prod (Phase 8):** `Encrypt=yes;TrustServerCertificate=no` + CA bundle — achieved purely by a different `DB_ODBC_EXTRA` in prod `.env`. No code change.

### Pattern 2: Per-column case-sensitive collation via explicit `RunSQL` (recommended over `db_collation` AlterField)

`campus.Room.qr_token` (`CharField(max_length=64, unique=True)`) and `manual_code` (`CharField(max_length=6, unique=True)`) need `Latin1_General_100_CS_AS`. **Both are `unique=True`, which mssql-django implements as a filtered unique index.** Altering the collation of a unique column is the exact operation mssql-django has repeatedly mishandled (issues #22, #45, #100, #286 — unique index not reinstated / `DROP CONSTRAINT` vs `DROP INDEX` mismatch after `AlterField`).

**Recommended:** an explicit `RunSQL` migration that owns the drop/alter/recreate, with `state_operations` so `makemigrations` doesn't re-detect drift:

```python
# campus/migrations/0002_cs_collation_tokens.py
from django.db import migrations, models

COLLATE = "Latin1_General_100_CS_AS"

def cs(table, col, length, unique_ix):
    return (
        f"DROP INDEX {unique_ix} ON {table}; "
        f"ALTER TABLE {table} ALTER COLUMN {col} nvarchar({length}) "
        f"COLLATE {COLLATE} NOT NULL; "
        f"CREATE UNIQUE INDEX {unique_ix} ON {table}({col}) WHERE {col} IS NOT NULL;"
    )

class Migration(migrations.Migration):
    dependencies = [("campus", "0001_initial")]
    operations = [
        migrations.RunSQL(
            sql=cs("campus_room", "qr_token", 64, "<qr_token_unique_index_name>"),
            reverse_sql="-- reverse: recreate without COLLATE",
            state_operations=[
                migrations.AlterField("room", "qr_token",
                    models.CharField(max_length=64, unique=True, db_collation=COLLATE)),
            ],
        ),
        # ...same for manual_code...
    ]
```
The exact auto-generated unique index name must be read from the DB after `migrate` (e.g. `sp_helpindex campus_room` or query `sys.indexes`) — mssql-django names filtered unique indexes non-obviously. Also add `db_collation="Latin1_General_100_CS_AS"` to the two model fields so state stays consistent and future `makemigrations` is a no-op.

**Fallback (Claude's discretion):** try the pure `db_collation=` field change first (generates an `AlterField`); if `migrate` succeeds and the unique index survives (verify with a duplicate-insert test), keep it — it's less code. Given the documented mssql-django AlterField-on-unique bugs, treat the `RunSQL` path as the safe default and the `db_collation` AlterField as the "try first, verify hard" option.

**Why not database-wide:** the rest of the DB (emails, codes, names) must stay case-insensitive; email dedup *depends* on the CI default. Collation is surgical, two columns only.

### Anti-Patterns to Avoid
- **Storing local time / using `DATETIMEOFFSET`:** re-introduces the pyodbc tz-loss round-trip (pitfalls #371/#810/#1141). Keep `datetime2` + UTC.
- **Squashing migrations to a new baseline:** violates the fix-forward/keep-history LOCKED decision.
- **A database-wide CS collation to "fix" tokens:** would silently make emails/usernames case-sensitive, re-breaking faculty dedup.
- **Converting the resolver `SimpleTestCase` suite to DB tests:** gains nothing; they are pure and must stay DB-free.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multiple-NULL unique on `azure_oid` | A custom partial-unique trigger or nullable-handling shim | mssql-django's built-in filtered unique index (automatic on CREATE) | Backend already emits `CREATE UNIQUE INDEX ... WHERE col IS NOT NULL`; 7 seed + 15 imported NULL rows insert fine |
| datetime2/UTC conversion | Manual UTC arithmetic at the ORM boundary | Django `USE_TZ=True` + `timezone.make_aware()` (already used in `materialize_sessions.py`) | Django always stores UTC when `USE_TZ=True` regardless of `TIME_ZONE`; convert only at display |
| Case-insensitive email match | A `.lower()`-normalized shadow column | SQL Server default CI collation + existing `get_or_create(email=...)` | The importer's dedup becomes CI automatically; no schema change |
| Creating the SQL Server test DB | A custom fixture DB bootstrap | Django test runner + `CREATE DATABASE` grant on the dev login | mssql-django creates/drops `test_<name>` and runs migrations automatically |

**Key insight:** almost every correctness property this phase needs is a *default behavior* of the locked stack (filtered index, UTC storage, CI collation). The work is (a) wiring the settings branch, (b) one surgical CS-collation migration, and (c) tests that *prove* the defaults hold — not building mechanisms.

## Common Pitfalls

### Pitfall 1: Nullable-unique `azure_oid` blocks migrate/seed on MSSQL
**What goes wrong:** `accounts.User.azure_oid = CharField(unique=True, null=True)`. All 7 `seed_demo` users and all 15 imported faculty have `azure_oid = NULL`. SQL Server's plain UNIQUE constraint permits only **one** NULL — naively this fails on the second NULL insert.
**Why it doesn't bite here:** mssql-django implements nullable-unique as a **filtered unique index** (`WHERE azure_oid IS NOT NULL`), so unlimited NULLs are allowed on a fresh CREATE. (Verified: mssql-django issues #45/#100/#22 confirm the filtered-index implementation; the bugs are only about *altering* such fields, which this phase never does.)
**How to avoid:** clean rebuild only (no AlterField on `azure_oid`). **Verify** with a test/manual check that `seed_demo` + R3 import both complete without `IntegrityError`.
**Warning signs:** `IntegrityError`/`UNIQUE KEY` violation on the second NULL-oid user insert → the filtered index was not created (would indicate a backend/version regression).

### Pitfall 2: 8-hour Asia/Manila drift if a naive datetime leaks in
**What goes wrong:** an aware `scheduled_start` written then read back shows a different instant (UTC+8 loss). Root cause is a naive datetime or a `DATETIMEOFFSET` column, not `datetime2`+UTC.
**Why it's already mostly avoided:** `USE_TZ=True` (settings line 111) + `materialize_sessions.py` uses `timezone.make_aware(datetime.combine(d, sch.start_time))`. Django stores UTC in `datetime2`. `seed_demo.py` also uses `make_aware`.
**How to avoid:** keep the DateTimeField→datetime2 default; never introduce `DATETIMEOFFSET`. Prove with the round-trip test (below). Do all grace/Absent math in UTC; convert to Manila only in templates (relevant Phase 2+).
**Warning signs:** a 08:00 Manila session reads back as 00:00 or 16:00; round-trip test off by exactly 8h.

### Pitfall 3: Collation-change AlterField silently drops the unique index
**What goes wrong:** using `db_collation=` on the two unique token columns generates an `AlterField` that mssql-django may execute without correctly reinstating the filtered unique index, leaving `qr_token`/`manual_code` non-unique on MSSQL.
**How to avoid:** prefer the explicit `RunSQL` (drop index → alter collation → recreate index). If using `db_collation` AlterField, **test that a duplicate token still raises `IntegrityError`** after migrate — don't assume.
**Warning signs:** two rooms with identical `manual_code` coexist; `makemigrations` keeps re-detecting the field.

### Pitfall 4: Test database default collation is case-sensitive
**What goes wrong:** the email-dedup ("more correct than SQLite") and the *rest* of the DB rely on the **database default** being case-INsensitive. If the SQL Server instance was installed with a `_CS_` server collation, the `fluxtrack` DB — and Django's auto-created `test_fluxtrack` — inherit CS, and faculty dedup silently breaks (case-variant emails become distinct faculty again).
**How to avoid:** confirm `SELECT SERVERPROPERTY('Collation')` returns a `_CI_` collation (SQL Server default is `SQL_Latin1_General_CP1_CI_AS`). Create the app DB explicitly CI: `CREATE DATABASE fluxtrack COLLATE SQL_Latin1_General_CP1_CI_AS;`. For the **test** DB, verify mssql-django creates it with the server default (CI); if the server is CS, set `DATABASES["default"]["TEST"] = {"COLLATION": "SQL_Latin1_General_CP1_CI_AS"}` (MEDIUM confidence — verify mssql-django honors `TEST["COLLATION"]`; otherwise ensure the server default is CI).
**Warning signs:** the collation round-trip test's email half fails (two faculty created for `Jdoe@` / `jdoe@`) even though the token half passes.

### Pitfall 5: Parity test needs the gitignored PII CSV
**What goes wrong:** the exact R3 numbers (17/10/15/18/18) derive from the real registrar file `data/raw/2T-25-26-Course Offerring(Sheet1).csv`, which is **gitignored** (`.gitignore` line 26 `/data/raw/`). A parity test that hard-codes those numbers only runs where the file exists (dev machine), not in a clean checkout/CI.
**How to avoid:** either (a) guard the test with `skipUnless(os.path.exists(DEFAULT_FILE))` and assert 17/10/15/18/18 on the dev machine, or (b) commit a small **synthetic/anonymized** R3-slice fixture CSV with its own known counts. Recommended: do both — the real-file test for true parity locally, a committed fixture so the import path is exercised anywhere. (Test organization is Claude's discretion.)
**Warning signs:** parity test errors with `FileNotFoundError` on a fresh clone.

## Code Examples

### Test 1: Aware-datetime round-trip (proves no 8h drift) — success criterion 2
```python
# scheduling/tests.py (new DB-backed class) — runs on the SQL Server test DB
from datetime import datetime
from zoneinfo import ZoneInfo
from django.test import TestCase
from django.utils import timezone
# ...create minimal Term/Schedule/Room/faculty or use a Session directly...

class DatetimeRoundTripTests(TestCase):
    def test_manila_instant_survives_roundtrip(self):
        manila = ZoneInfo("Asia/Manila")
        # a Manila local time straddling midnight (worst case for offset bugs)
        aware = datetime(2026, 7, 6, 0, 30, tzinfo=manila)   # 00:30 PHT = 16:30 UTC prev day
        s = Session.objects.create(..., scheduled_start=aware,
                                   scheduled_end=aware, ...)
        s.refresh_from_db()
        # equal to the second, same instant, regardless of tz representation
        self.assertEqual(s.scheduled_start, aware)
        self.assertEqual(s.scheduled_start.astimezone(ZoneInfo("UTC")).hour, 16)
```

### Test 2: Collation round-trip — success criterion 3
```python
class CollationRoundTripTests(TestCase):
    def test_qr_tokens_differing_only_in_case_stay_distinct(self):
        # CS collation on qr_token → these are two rooms, no collision
        Room.objects.create(code="R1", qr_token="AbC", manual_code="000001", floor=self.floor)
        Room.objects.create(code="R2", qr_token="abc", manual_code="000002", floor=self.floor)
        self.assertEqual(Room.objects.filter(qr_token__in=["AbC", "abc"]).count(), 2)
        # exact lookup is case-sensitive → resolves to exactly one room
        self.assertEqual(Room.objects.get(qr_token="AbC").code, "R1")

    def test_case_variant_emails_dedupe_to_one_faculty(self):
        # default CI collation → get_or_create matches regardless of case
        User.objects.create(username="a", email="Jdoe@mcm.edu.ph", role="faculty")
        u, created = User.objects.get_or_create(email="jdoe@mcm.edu.ph",
                                                defaults={"username": "b", "role": "faculty"})
        self.assertFalse(created)          # matched the existing row (no duplicate faculty)
        self.assertEqual(User.objects.filter(email__iexact="jdoe@mcm.edu.ph").count(), 1)
```

### Test 3: R3-slice import + materialize parity — success criterion 4 / ENV-02
```python
import os
from unittest import skipUnless
from django.core.management import call_command
from django.test import TransactionTestCase   # commands use transaction.atomic
from campus.models import Room
from accounts.models import Role, User
from scheduling.models import Schedule, Session

FILE = "data/raw/2T-25-26-Course Offerring(Sheet1).csv"

@skipUnless(os.path.exists(FILE), "registrar CSV not present (gitignored)")
class R3ParityTests(TransactionTestCase):
    def test_r3_slice_matches_sqlite_validated_numbers(self):
        call_command("import_offerings", building="R", floor=3)
        # pin the window so materialization is deterministic
        call_command("materialize_sessions", days=7)
        self.assertEqual(Schedule.objects.count(), 18)
        self.assertEqual(Room.objects.count(), 10)
        self.assertEqual(User.objects.filter(role=Role.FACULTY).count(), 15)
        self.assertEqual(Session.objects.count(), 18)
        # 17 "sections" = distinct (course_code, section) pairs before day-splitting
        self.assertEqual(
            Schedule.objects.values("course_code", "section").distinct().count(), 17)
```
Note: `materialize_sessions --days 7` yields 18 sessions because each of the 18 schedules' `day_of_week` occurs exactly once in any 7-day window, and the importer creates a term spanning the window with no breaks. The planner should pin `--from` to a fixed in-term date for run-to-run repeatability, or assert `>=`/exact against a controlled term.

### Commands that produce the R3 numbers (for the parity path)
```bash
py -3.12 manage.py migrate                       # fresh SQL Server schema
py -3.12 manage.py seed_demo                      # 7 role users + policy SystemSettings
py -3.12 manage.py import_offerings --building R --floor 3   # → 17 sections, 10 rooms, 15 faculty, 18 schedules
py -3.12 manage.py materialize_sessions --days 7  # → 18 sessions
```

## MSSQL-Compatibility Audit of Existing Schema

Read every migration (`accounts/campus/scheduling/verification/ops` `0001_initial`). Findings:

| Construct | Where | MSSQL status |
|-----------|-------|--------------|
| `azure_oid` nullable + unique | accounts.User | ✅ handled via filtered unique index (Pitfall 1) — the only real watch-item; clean rebuild is safe |
| `JSONField` | ops.AuditLog.payload, ops.PushSubscription.keys | ✅ maps to `nvarchar(max)`; no index/unique on them |
| `unique_together` w/ nullable col | ops.WeeklyReport (`week_start`,`department`) | ✅ filtered index; **not exercised in Phase 1** (no WeeklyReports created) |
| `PositiveIntegerField` | campus.Room.capacity, Schedule.enrolled_count | ✅ mssql-django adds a `>= 0` CHECK constraint |
| `TextField` / `URLField` / `ImageField` | several | ✅ `nvarchar(max)` / `nvarchar` |
| `GenericIPAddressField` | ops.AuditLog.ip_address | ✅ `nvarchar(39)` |
| `ManyToManyField` | verification.Assignment.floors, User.groups/permissions | ✅ standard through-tables |
| `Index` on Char/Date/FK | scheduling.Session, ops.AuditLog | ✅ all on indexable columns (none on `nvarchar(max)`) |
| `CheckConstraint` / conditional `UniqueConstraint` / `RunPython` schema ops | — | ✅ none present (nothing exotic to fail) |
| `auto_now_add` datetimes | several | ✅ `datetime2`, stored UTC |

**Conclusion:** `migrate` should apply cleanly on SQL Server on a fresh build. The only construct that historically breaks MSSQL (nullable-unique) is backend-handled for CREATE; Phase 1 does no `AlterField` that would trip the known mssql-django bugs — except the deliberate collation change, which is why the explicit-`RunSQL` approach is recommended.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `django-pyodbc-azure` / `django-mssql-backend` | `mssql-django` (`ENGINE: "mssql"`) | 2021+ (Microsoft took over) | Only maintained backend; Django 6.0 support in 1.7 |
| `sql_server.pyodbc` engine string | `"mssql"` short engine string | mssql-django | Use `"ENGINE": "mssql"` |
| SQLite/MySQL dev+prod split | MSSQL everywhere (this phase) | Now | Max parity; no engine-specific bug can hide |

**Deprecated/outdated in this repo:**
- `config/settings.py` docstring "SQLite by default … MySQL 8.0 on AWS RDS" — stale, must be rewritten for MSSQL-only.
- `requirements.txt` `# mysqlclient` comment and `Django>=5.0,<7.0` pin — remove/replace.
- SRS still references MySQL 8.0 in places (noted in PITFALLS.md P10) — SRS reconciliation is a DOC concern, not blocking Phase 1 code.

## Open Questions

1. **Does mssql-django honor `TEST["COLLATION"]` for the auto-created test DB?**
   - What we know: mssql-django creates `test_<name>` and runs migrations; column-level CS collation is applied by our migration regardless of DB default.
   - What's unclear: whether a CS *server* default can be overridden per-test-DB via `TEST["COLLATION"]`.
   - Recommendation: ensure the SQL Server instance default is CI (`SERVERPROPERTY('Collation')`); if it's CS, verify the `TEST["COLLATION"]` override or create the instance/DB CI. Confirm during the spike.

2. **Exact auto-generated unique-index names for `qr_token`/`manual_code`.**
   - What we know: mssql-django names filtered unique indexes non-obviously.
   - Recommendation: after first `migrate`, read the names from `sys.indexes`/`sp_helpindex campus_room` and use them literally in the `RunSQL` collation migration (or query them dynamically in the migration).

3. **`db_collation` AlterField vs `RunSQL` — which actually lands cleanly on 1.7.3?**
   - Recommendation: spike both on a throwaway DB; the phase's collation-round-trip test is the arbiter. Default to `RunSQL` given documented AlterField-on-unique bugs.

## Validation Architecture

*(nyquist_validation is enabled in config.json → section included.)*

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django test runner (`manage.py test`), `unittest`-style — matches existing `scheduling/tests.py` |
| Config file | none — Django default discovery (`<app>/tests.py`); test DB `test_fluxtrack` on SQL Server |
| Quick run command | `py -3.12 manage.py test scheduling.tests -v 2` (or the specific new test module) |
| Full suite command | `py -3.12 manage.py test` |
| Precondition | dev login has `CREATE DATABASE` (server role `dbcreator`) so the runner can build `test_fluxtrack`; SQL Server instance default collation is `_CI_` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| ENV-01 | `migrate` applies full schema on SQL Server (incl. nullable-unique `azure_oid`) | integration (smoke) | `py -3.12 manage.py migrate` then `py -3.12 manage.py test` (DB build proves it) | ❌ Wave 0 — no DB-backed test yet |
| ENV-01 | Aware Manila datetime round-trips with no 8h drift | integration | `py -3.12 manage.py test scheduling.tests.DatetimeRoundTripTests` | ❌ Wave 0 |
| ENV-01 | `qr_token` case-variants stay distinct (CS collation) | integration | `py -3.12 manage.py test campus.tests.CollationRoundTripTests` | ❌ Wave 0 |
| ENV-01 | Case-variant faculty emails dedupe to one user (CI default) | integration | `py -3.12 manage.py test campus.tests.CollationRoundTripTests` | ❌ Wave 0 |
| ENV-02 | R3 import + materialize = 17/10/15/18/18 on MSSQL | integration (parity) | `py -3.12 manage.py test scheduling.tests.R3ParityTests` | ❌ Wave 0 (needs real or fixture CSV) |
| ENV-01 | Existing pure resolver suite still green (no regression) | unit (no DB) | `py -3.12 manage.py test scheduling.tests.FacultyResolverTests` | ✅ exists (`SimpleTestCase`) |

### Sampling Rate
- **Per task commit:** the specific new test class touched (`... manage.py test <module>.<Class>`).
- **Per wave merge:** `py -3.12 manage.py test` (full suite on the SQL Server test DB).
- **Phase gate:** full suite green on MSSQL + a manual `migrate` + `seed_demo` + R3 import cold run on a fresh `fluxtrack` DB, before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `scheduling/tests.py` (or `scheduling/tests/`) — add `DatetimeRoundTripTests` (`TestCase`), `R3ParityTests` (`TransactionTestCase`, skip-if-CSV-missing) covering ENV-01/ENV-02.
- [ ] `campus/tests.py` — add `CollationRoundTripTests` (`TestCase`) covering tokens (CS) + emails (CI). (No `campus/tests.py` exists today.)
- [ ] Shared minimal fixtures — small factory helpers to build a Room/Floor/Term/Schedule/faculty without the full seed (keep DB tests fast); consider a committed synthetic R3 fixture CSV for CI.
- [ ] Framework install: none needed — Django test runner already present. New requirement is the **SQL Server test DB grant** (`CREATE DATABASE`) + a `_CI_` instance default collation.

## Sources

### Primary (HIGH confidence)
- Codebase read directly: `config/settings.py`, `requirements.txt`, `campus/models.py`, `accounts/models.py`, `scheduling/models.py`, `ops/models.py`, `verification/models.py`, all `*/migrations/0001_initial.py`, `scheduling/management/commands/import_offerings.py`, `materialize_sessions.py`, `accounts/management/commands/seed_demo.py`, `scheduling/tests.py`.
- `.planning/research/STACK.md` — mssql-django 1.7.3 / Django 6.0.6 support + versions verified against PyPI/Microsoft blog.
- `.planning/research/PITFALLS.md` — collation CI default, datetime2/pyodbc tz round-trip (mssql-django #371, pyodbc #810/#1141), CREATE DATABASE for test runner.
- `.planning/phases/01-.../01-CONTEXT.md` — locked decisions; R3 numbers.

### Secondary (MEDIUM confidence)
- mssql-django GitHub issues #22/#45/#100/#286 (WebSearch) — nullable-unique implemented as filtered unique index; AlterField-on-unique reinstatement bugs → informs the `RunSQL`-over-`AlterField` collation recommendation.
- SQL Server unique-index-on-nullable-column behavior (SQLAuthority / Simple Talk, WebSearch) — filtered index `WHERE col IS NOT NULL` allows multiple NULLs.
- Django #34219 (db_collation not preserved on alter) — reinforces caution on collation-change AlterField.

### Tertiary (LOW confidence — verify in spike)
- `TEST["COLLATION"]` honored by mssql-django for the auto-created test DB — unverified; mitigate by ensuring the instance default is CI.

## Metadata

**Confidence breakdown:**
- Standard stack / versions: HIGH — verified in STACK.md against PyPI + Microsoft blog; re-confirm at install.
- Settings branch + datetime2/UTC: HIGH — Django `USE_TZ` semantics + existing `make_aware` usage.
- Nullable-unique `azure_oid` on CREATE: HIGH — backend filtered-index behavior confirmed across multiple sources.
- Collation-on-unique migration mechanics: MEDIUM — documented mssql-django AlterField bugs; `RunSQL` recommended, spike-verify.
- Test-DB collation control: MEDIUM — depends on instance default; mitigation clear.
- Schema audit (no exotic ops): HIGH — read every migration.

**Research date:** 2026-07-02
**Valid until:** ~2026-08-01 (stable stack; re-verify mssql-django patch level if a >1.7.3 release appears)
</content>
</invoke>

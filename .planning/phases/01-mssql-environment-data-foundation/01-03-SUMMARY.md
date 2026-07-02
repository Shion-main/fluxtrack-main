---
phase: 01-mssql-environment-data-foundation
plan: 03
subsystem: database
tags: [mssql, mssql-django, collation, case-sensitive, migrations, django, campus]

# Dependency graph
requires:
  - phase: 01-mssql-environment-data-foundation (plan 01)
    provides: "MSSQL cutover — SQL Server 2025 LocalDB, mssql-django, TEST['NAME'] override, CI server default collation"
provides:
  - "Case-SENSITIVE collation (Latin1_General_100_CS_AS) on campus_room.qr_token + manual_code ONLY"
  - "Unique constraints on both token columns reinstated after the collation ALTER (uniqueness preserved)"
  - "CollationRoundTripTests proving CS tokens stay distinct/unique and CI faculty emails dedupe"
  - "Reusable pattern: recollate a unique column on mssql-django via RunSQL (DROP/ALTER/re-ADD constraint)"
affects: [scan-resolver, verification, checker, qr-token-security, faculty-import]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-column CS collation via hand-written RunSQL migration with state_operations (db_collation AlterField is a no-op on mssql-django 1.7.3)"
    - "Dynamic constraint-name discovery via sys.key_constraints (auto-names carry random hash suffixes)"

key-files:
  created:
    - campus/migrations/0002_cs_collation_tokens.py
    - campus/tests.py
  modified:
    - campus/models.py

key-decisions:
  - "Landed the RunSQL fallback (not the db_collation AlterField): sqlmigrate confirmed the AlterField emits '(no-op)' SQL, so it would leave the DB columns CI while model state falsely claimed CS."
  - "Used DROP/ADD CONSTRAINT (not DROP/CREATE INDEX): the NOT NULL token columns are backed by real UNIQUE CONSTRAINTS, not the filtered unique indexes the plan template assumed for nullable-unique columns."
  - "Recreated constraints under deterministic names (UQ_campus_room_qr_token/_manual_code) since the original mssql-django auto-names carry non-reproducible hash suffixes."

patterns-established:
  - "mssql-django collation-on-unique: discover constraint name from sys.key_constraints, DROP CONSTRAINT, ALTER COLUMN ... COLLATE, ADD CONSTRAINT ... UNIQUE, wrapped in RunSQL + state_operations."

requirements-completed: [ENV-01]

# Metrics
duration: 15min
completed: 2026-07-03
---

# Phase 1 Plan 3: Case-Sensitive Token Collation Summary

**Surgical `Latin1_General_100_CS_AS` collation on `campus_room.qr_token` + `manual_code` via a hand-written RunSQL migration (DROP/ALTER/re-ADD unique constraint), proven by a 3-test collation round-trip: CS tokens stay distinct AND unique, CI faculty emails still dedupe.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-03
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- Both opaque token columns now carry `Latin1_General_100_CS_AS` on SQL Server (verified via `sys.columns`), while the rest of the DB stays at the CI default `SQL_Latin1_General_CP1_CI_AS`.
- The unique enforcement on both columns survived the collation change — verified two ways: `sys.indexes` shows `is_unique = 1`, and a duplicate-token insert still raises `IntegrityError`.
- `makemigrations --check` reports no drift — model `db_collation` state matches the DB.
- `CollationRoundTripTests` (3 tests) pass on the isolated Wave-2 test DB `test_fluxtrack_campus`, proving both collation directions.

## Task Commits

1. **Task 1: Apply CS collation to qr_token + manual_code** - `9eda609` (feat)
2. **Task 2: CollationRoundTripTests (CS tokens, CI emails)** - `d5d29cf` (test)

## Files Created/Modified
- `campus/models.py` - Added `db_collation="Latin1_General_100_CS_AS"` to `Room.qr_token` and `Room.manual_code` so model state matches the DB.
- `campus/migrations/0002_cs_collation_tokens.py` - RunSQL migration: dynamically discover the unique constraint per column, DROP it, `ALTER COLUMN ... COLLATE Latin1_General_100_CS_AS NOT NULL`, re-ADD a unique constraint; `state_operations` describe the equivalent `db_collation` AlterField.
- `campus/tests.py` - Replaced placeholder with `CollationRoundTripTests`: tokens-distinct, duplicate-raises-IntegrityError, emails-dedupe.

## Which migration path landed

**RunSQL fallback (STEP C), not the `db_collation` AlterField (STEP B).** The TRY-FIRST `makemigrations campus` generated an `AlterField`-with-`db_collation` migration, but `sqlmigrate campus 0002` reported `(no-op)` for both fields — the documented mssql-django 1.7.3 footgun where a collation-only AlterField emits no DDL. That path would have left the columns CI while claiming CS in state, so it was deleted in favor of the explicit RunSQL migration.

## Actual constraint names on campus_room

- Before migration (mssql-django auto-generated UNIQUE CONSTRAINTS, `has_filter = 0` because the columns are NOT NULL):
  - `qr_token` → `UQ__campus_r__2254D5983F596FDA`
  - `manual_code` → `UQ__campus_r__6E108965BF9F8011`
- After migration (recreated under deterministic names):
  - `qr_token` → `UQ_campus_room_qr_token` (`is_unique = 1`)
  - `manual_code` → `UQ_campus_room_manual_code` (`is_unique = 1`)

## Email half confirmation

`test_case_variant_emails_dedupe_to_one_faculty` passed on `test_fluxtrack_campus`: a user created with `Jdoe@mcm.edu.ph` was matched (`created is False`) by `get_or_create(email="jdoe@mcm.edu.ph")`, and `email__iexact` counts a single user. This proves the instance/DB default collation is `_CI_` (the test DB inherited the server default `SQL_Latin1_General_CP1_CI_AS`) — faculty dedup is intact.

## Decisions Made
See `key-decisions` in frontmatter. In short: RunSQL over a no-op AlterField; DROP/ADD CONSTRAINT over DROP/CREATE INDEX; deterministic constraint names.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Plan template SQL targeted filtered indexes; real columns use unique CONSTRAINTS**
- **Found during:** Task 1 (apply CS collation)
- **Issue:** The plan's `<interfaces>` and fallback template treated `qr_token`/`manual_code` as filtered unique indexes (`DROP INDEX ... ; CREATE UNIQUE INDEX ... WHERE col IS NOT NULL`). Because both columns are NOT NULL, mssql-django actually backs them with real UNIQUE CONSTRAINTS (`sys.key_constraints`, `is_unique_constraint = 1`, `has_filter = 0`). `DROP INDEX` cannot drop a constraint-backed index, and a filtered `CREATE UNIQUE INDEX` would not match the original non-filtered semantics — the template SQL would have errored.
- **Fix:** Adapted the migration to discover the constraint name from `sys.key_constraints` (joined through `unique_index_id`), `ALTER TABLE ... DROP CONSTRAINT`, `ALTER COLUMN ... COLLATE`, then `ALTER TABLE ... ADD CONSTRAINT ... UNIQUE`.
- **Files modified:** campus/migrations/0002_cs_collation_tokens.py
- **Verification:** `sys.columns` shows CS collation; `sys.indexes` shows `is_unique = 1`; duplicate-insert raises `IntegrityError`; `makemigrations --check` clean.
- **Committed in:** `9eda609` (Task 1 commit)

**2. [Planned try-first/verify-hard] db_collation AlterField rejected as a no-op**
- **Found during:** Task 1 (STEP B)
- **Issue:** The auto-generated `AlterField(db_collation=...)` migration produced `(no-op)` SQL under `sqlmigrate` on mssql-django 1.7.3 — it would not actually recollate the columns.
- **Fix:** Deleted the generated `0002_alter_room_*` file and hand-wrote `0002_cs_collation_tokens.py` (STEP C fallback). This is the plan's documented fallback branch, not unplanned scope.
- **Committed in:** `9eda609` (Task 1 commit)

---

**Total deviations:** 1 blocking auto-fix (constraint vs. filtered index) + 1 planned fallback branch taken.
**Impact on plan:** No scope creep. Both were necessary for the collation to actually apply and for uniqueness to be reinstated. Only `campus_room` was touched — `accounts.User.email` collation is unchanged.

## Issues Encountered
- `sqlcmd` is not on PATH in this environment, so the plan's `sqlcmd` verification step could not be run directly. Substituted the identical `sys.indexes`/`sys.columns`/`sys.key_constraints` queries through Django's own DB connection (`manage.py shell`), which uses the exact same LocalDB connection settings — equivalent and arguably more reliable.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase success criterion 3 met: opaque tokens are CS + still unique on SQL Server; faculty emails remain CI and dedupe — proven by an automated round-trip test.
- Wave-2 test isolation worked (`DB_TEST_NAME=test_fluxtrack_campus`) with no collision against Plan 01-02's parallel run.
- No blockers introduced. The scan resolver (Phase 2+) can rely on case-sensitive token lookups.

---
*Phase: 01-mssql-environment-data-foundation*
*Completed: 2026-07-03*

## Self-Check: PASSED

- FOUND: campus/migrations/0002_cs_collation_tokens.py
- FOUND: campus/tests.py
- FOUND: .planning/phases/01-mssql-environment-data-foundation/01-03-SUMMARY.md
- FOUND commit: 9eda609 (Task 1 - feat)
- FOUND commit: d5d29cf (Task 2 - test)

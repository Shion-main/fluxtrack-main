---
phase: 07-remaining-operational-surfaces
plan: 02
subsystem: data-foundations
tags: [migration, referential-integrity, file-upload, staging, mssql]
requires: []
provides:
  - ops.models.ImportStaging
  - ops.import_staging (stage/resolve/consume/discard/staged_path/sweep)
  - campus.services.room_delete_blockers
  - Booking.room PROTECT (D-19)
affects:
  - 07-04 (IFO-02 rotation — consumes campus.codes.new_room_credentials)
  - 07-06 (owns the sweep_abandoned call site)
  - 07-07 (IFO-03b import commit — consumes the staging service)
  - IFO-01b room delete UI (consumes room_delete_blockers)
tech-stack:
  added: []
  patterns:
    - "reverse-accessor-only probes keep campus free of upward app imports"
    - "chunked copy at upload time, never temporary_file_path() across requests"
    - "DB_TEST_NAME isolates parallel plan test runs"
key-files:
  created:
    - campus/services.py
    - ops/import_staging.py
    - ops/tests_staging.py
    - ops/migrations/0005_booking_protect_import_staging.py
  modified:
    - ops/models.py
    - campus/tests.py
decisions:
  - "D-19's 'database-level guarantee' framing is not achievable via AlterField and never was — Django encodes on_delete in the Python Collector, never in DDL. The protection is real and verified, but it is ORM-level."
  - "room_delete_blockers counts FIVE relations; the fifth (SET_NULL assigned_room) is the only one no constraint can catch."
  - "STAGING_TTL_HOURS stays a module constant, not a FLUXTRACK_POLICY knob."
metrics:
  duration: ~50m
  tasks: 3
  tests-added: 21
  completed: 2026-07-19
status: complete
---

# Phase 07 Plan 02: Data Foundations Summary

Booking.room migrated to PROTECT, a five-relation room-delete probe that catches the
SET_NULL reservation no constraint can, and the disk-backed upload staging service
that holds an import file between preview and commit.

## Commits

| Task | Commit | Description |
|---|---|---|
| 1 | `857328a` | `Booking.room` CASCADE → PROTECT + `ImportStaging` model, one migration |
| 2 | `677997a` | `campus.services.room_delete_blockers` — five-relation probe |
| 3 | `c175400` | `ops.import_staging` — stage/resolve/consume/discard/sweep |

## The migration: what actually happened

`sqlmigrate ops 0005` emitted, for the `Booking.room` AlterField:

```
--
-- Alter field room on booking
--
-- (no-op)
```

The plan anticipated this as the mssql-django `AlterField` defect from Phase 01.
**It is not that defect.** Introspecting the live constraints proves why:

```
ops_booking                    -> campus_room  ON DELETE: NO_ACTION
ops_roomconflictflag           -> campus_room  ON DELETE: NO_ACTION
scheduling_modalityshiftitem   -> campus_room  ON DELETE: NO_ACTION
scheduling_schedule            -> campus_room  ON DELETE: NO_ACTION
scheduling_session             -> campus_room  ON DELETE: NO_ACTION
verification_checkervalidation -> campus_room  ON DELETE: NO_ACTION
```

Every FK to `campus_room` is `NO_ACTION` — including `scheduling_schedule` and
`scheduling_session`, which have **always** been `on_delete=PROTECT`, and
`ops_roomconflictflag`, which is CASCADE. Django never encodes `on_delete` in the
DDL on any backend; it is implemented entirely in the Python `Collector` so that
signals fire. There was no `ON DELETE CASCADE` clause to remove, so a no-op is the
correct and expected output here.

**Honest consequence for D-19.** Its stated goal — "the refusal is a database
guarantee, not a view-level courtesy" — is not what was achieved, and is not
achievable through `AlterField`. What was achieved, verified empirically:

| Path | Before | After |
|---|---|---|
| `room.delete()` (ORM, admin, shell) | Collector CASCADE — **bookings destroyed**, delete succeeds | `ProtectedError` — nothing deleted |
| Raw `DELETE FROM campus_room` | refused by `NO_ACTION` FK | refused by `NO_ACTION` FK (unchanged) |

So the database was already refusing raw deletes the whole time; the actual hole was
the ORM path, and that is the hole this migration closes. The net protective effect
D-19 wanted is in place — via a different mechanism than D-19 assumed.

Proof against the real DB (created and rolled back):

```
blockers          : {'bookings': 1}
DELETE RESULT     : ProtectedError raised — refused
bookings survive  : 1
```

Note that booking had `status="cancelled"` — confirming all bookings block, not just
active ones (D-19).

## The fifth blocker is not defensive thoroughness — it is load-bearing

The plan-checker's find is validated empirically. A room referenced *only* by a
Dean-approved `ModalityShiftItem.assigned_room`:

```
probe says        : {'reservations': 1}
delete SUCCEEDED  : PROTECT did not fire (assigned_room is SET_NULL)
assigned_room now : None
```

The delete succeeds and silently nulls a live approved reservation. The first four
relations are PROTECT, so for those the probe only upgrades a `ProtectedError` 500
into a named refusal. For the fifth, **the probe is the only control that exists.**
Its test asserts on the `reservations` key specifically, because a truthiness
assertion would pass against a four-relation implementation.

Excluded with reasoning recorded in the docstring: `modality_preferred_items`
(a preference is not a reservation; D-18 re-resolves at approval) and `conflict_flags`
(CASCADE, derived state, regenerated by the next sweep).

## Deviations from Plan

**1. [Rule 1 — Bug in a test's premise] Hostile-filename test proved Django's control, not ours**

- **Found during:** Task 3
- **Issue:** The plan specified that a hostile `original_name` is "preserved verbatim."
  It is not — Django's `UploadedFile.name` setter already reduces
  `../../../../etc/passwd/evil.csv` to `evil.csv` before the service sees it. The
  original test asserted verbatim preservation and failed. More importantly, as
  written it would have been **proving Django's sanitization rather than our path
  construction** — it would still pass if our code naively joined the client name.
- **Fix:** Split into two tests. One records Django's real basenaming behavior
  (defense in depth). A second drives a raw, unsanitized name straight into
  `stage_upload` via a minimal upload stand-in and asserts
  `stored_path == imports/staging/<token>.csv` — proving T-07-04 holds independently
  of any upstream sanitization, which is what a future custom upload handler or
  direct service call would depend on.
- **Files:** `ops/tests_staging.py`
- **Commit:** `c175400`

**2. [Rule 3 — Blocking issue] Test-database contention with the parallel plan 07-01**

- **Found during:** Task 2 verification
- **Issue:** Test runs failed with `Database 'test_fluxtrack' already exists` /
  `Cannot drop database ... currently in use`. Polling `sys.dm_exec_sessions` showed
  an actively cycling Python session holding it — plan 07-01 running its own suite
  against the same shared test database.
- **Fix:** Used the `DB_TEST_NAME` env var that `config/settings.py:TEST` already
  exposes for exactly this ("isolate parallel Wave-2 test runs"), pointing this
  plan's runs at `test_fluxtrack_0702`. **No processes were killed and no database
  was dropped** — killing the holder would have destroyed the parallel agent's run.
- **Files:** none (invocation-level only)
- **Note for the orchestrator:** any wave running plans in parallel should set
  `DB_TEST_NAME` per plan. Full-suite counts also drift between plans on a shared
  branch — see below.

**3. [Observation, no action] Plan 07-01 commits to the same branch**

Commits `6e863b0`, `6dceafd`, `ce0b32b` (07-01) are interleaved with this plan's on
`phase-07-operational-surfaces`. This fully accounts for the suite count:
515 baseline + 21 (this plan) + 3 (07-01 `GuardReadOnlyTests`) = **539**. No files
outside this plan's `files_modified` were touched by this agent.

## Test Results

Full suite run twice on the isolated database, identical both times:

```
Ran 539 tests in 112.924s   FAILED (failures=3, skipped=2)   [run 1]
Ran 539 tests in 113.880s   FAILED (failures=3, skipped=2)   [run 2]
```

**0 errors.** The 3 failures are exactly the known pre-existing set, untouched:
`DevLoginCoexistTests`, `DevLoginCuratedDemoTests`,
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

`UQ_campus_room_manual_code` collision count across both runs: **0**.
`scheduling.tests_room_master` is stably green — the intermittent defect
`campus/codes.py` was landed to fix does not reappear.

Other gates:
- `makemigrations --check --dry-run` → `No changes detected`
- `migrate` → `Applying ops.0005_booking_protect_import_staging... OK`
- Grep guard: no bare `randbelow` mint survives outside `campus/codes.py` (the two
  remaining hits are comments referencing it).
- No test wrote into the repo's `media/` — `media/` contains only `reports/`.

## Known Stubs

None. All three artifacts are complete services with no placeholder returns.
`sweep_abandoned` is deliberately **not** wired to the scheduler — plan 07-06 owns
that call site and the `NoImplicitSchedulerTests` 4-job invariant is untouched.

## Threat Flags

None beyond the plan's register. T-07-04, T-07-05, T-07-06, T-07-07 and T-07-09b are
covered by tests. **T-07-09 resolved differently than predicted** — the `AlterField`
no-op is correct Django behavior rather than an mssql-django defect, and
`room_delete_blockers` is the operative control for the SET_NULL relation regardless
(see above).

## Self-Check: PASSED

Files verified present: `campus/services.py`, `ops/import_staging.py`,
`ops/tests_staging.py`, `ops/migrations/0005_booking_protect_import_staging.py`.
Commits verified in `git log`: `857328a`, `677997a`, `c175400`.

---
phase: 03-duty-assignments-checker-verification
plan: 01
subsystem: verification
tags: [checker, resolver, pure-core, migration, model-extension, round-robin]
requires:
  - scheduling.Session (existing)
  - verification.Assignment / CheckerValidation (existing)
provides:
  - verification.resolver.resolve_checker_scan (pure gating core, CHK-01)
  - verification.resolver.distribute_online_sessions (pure round-robin, IFO-06)
  - verification.models.AssignmentScope (FLOOR/ONLINE)
  - Assignment.scope field (default FLOOR)
  - scheduling.Session.online_checker FK (nullable owner link)
  - ValidationAction retirement (confirmed_absent / confirmed_empty removed)
affects:
  - 03-02 (checker scan apply layer consumes resolve_checker_scan)
  - 03-03 (round-robin apply writes Session.online_checker)
  - 03-05 (online Flag-not-present branch)
  - Phase-4 modality-shift (sets Session.online_checker)
tech-stack:
  added: []
  patterns: [pure-decision-core, state-only-alterfield, defensive-runpython-assert]
key-files:
  created:
    - verification/resolver.py
    - verification/migrations/0002_assignment_scope.py
    - verification/migrations/0003_retire_dead_validation_actions.py
    - scheduling/migrations/0002_session_online_checker.py
  modified:
    - verification/models.py
    - scheduling/models.py
    - verification/tests.py
decisions:
  - VERIFIED_EMPTY is the single canonical empty action; confirmed_absent and confirmed_empty retired (research Open Q1)
  - AssignmentScope is an orthogonal field, not an overloaded AssignmentType member
  - Session.online_checker is a nullable FK (one owner, no history table) — AuditLog carries provenance
metrics:
  duration: ~25m
  completed: 2026-07-03
  tasks: 2
  files: 7
status: complete
---

# Phase 3 Plan 01: Checker Verification Foundation Summary

Built the ORM-free decision foundation for the entire Checker verification surface — a pure `resolve_checker_scan` gating core plus a deterministic `distribute_online_sessions` round-robin — and the minimal additive model surface (`Assignment.scope`, `Session.online_checker`) while retiring the two dead `ValidationAction` members, all migrating cleanly on SQL Server.

## What Was Built

### Task 1 — Pure checker decision cores (TDD)
`verification/resolver.py` mirrors `scheduling/resolver.py` exactly: UPPER_SNAKE outcome constants, an `ACTIONABLE` set, and a `CheckerResolution` dataclass whose `actionable` flag is computed in `__post_init__`.

- `resolve_checker_scan(active_floor_ids, scanned_floor_id, session_state, now)` — refuses off-duty (`OFF_DUTY`) and wrong-floor (`WRONG_FLOOR`) scans as distinct non-actionable outcomes, treats a missing/scheduled session as an actionable empty room (`NO_SESSION`), excludes `absent` sessions, short-circuits `already-verified`, and returns `ACTIVE_UNVERIFIED` (carrying `session_id`) for the live case. `now` is accepted for parity with the faculty resolver and reserved for future grace use — it is not read, keeping the core pure.
- `distribute_online_sessions(session_ids, checker_ids)` — deterministic round-robin by input order; returns `{}` on an empty checker roster so the caller can flag unassigned sessions to IFO.

Verified by `CheckerResolverTests` + `DistributeTests` (`SimpleTestCase`, no DB — any accidental ORM/clock read would error). The purity grep in the acceptance criteria (`'timezone.now()' not in src and 'objects.' not in src`) passes.

### Task 2 — Model extension + additive/state-only migrations
- `verification/models.py`: added `AssignmentScope(TextChoices)` (FLOOR/ONLINE) and `Assignment.scope` (default FLOOR); trimmed `ValidationAction` to exactly `{verified, flag_identity_mismatch, flag_not_present, verified_empty}`.
- `scheduling/models.py`: added `Session.online_checker` (nullable `SET_NULL` FK, `related_name="online_verifications"`).
- Three migrations, split to match the plan's file contract: `verification/0002_assignment_scope` (AddField), `verification/0003_retire_dead_validation_actions` (state-only AlterField + a forward `RunPython` asserting zero rows use the retired values, no-op reverse), and `scheduling/0002_session_online_checker` (AddField FK). Django initially merged the two verification ops into one file; it was split by hand and the combined file removed.
- `ModelExtensionTests` asserts the retirement and the FLOOR default.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Purity-grep collision with docstring token**
- **Found during:** Task 1
- **Issue:** The acceptance-criteria purity grep matches the literal substring `timezone.now()`. The resolver's own docstring/comments used that exact token to say "no `timezone.now()`", so the check failed even though the core is pure.
- **Fix:** Reworded the comments to "no wall-clock read" — semantically identical, no literal collision.
- **Files modified:** verification/resolver.py
- **Commit:** d5cc971

**2. [Rule 3 - Blocking] Django-generated combined migration split**
- **Found during:** Task 2
- **Issue:** `makemigrations` emitted a single `0002_assignment_scope_alter_checkervalidation_action.py` combining the AddField and the AlterField, but the plan's `<files>` contract requires `0002_assignment_scope.py` and a separate `0003_retire_dead_validation_actions.py` depending on 0002.
- **Fix:** Hand-authored 0002 (AddField only) and 0003 (AlterField + defensive RunPython), deleted the combined file; `makemigrations --check --dry-run` reports no changes.
- **Files modified:** verification/migrations/*
- **Commit:** e7bad01

## Verification Results

- `py -3.12 manage.py test verification` — 10 tests, OK (pure cores + model tests).
- `py -3.12 manage.py migrate` — scheduling 0002 + verification 0002/0003 applied clean on MSSQL.
- `py -3.12 manage.py makemigrations --check --dry-run` — no changes detected (models and migrations in sync).
- `py -3.12 manage.py test scheduling` — 40 tests, OK (no regression from the additive Session FK).

## Threat Mitigations Applied

- **T-03-01 (Tampering, retirement migration):** state-only AlterField + forward RunPython asserting zero `confirmed_absent`/`confirmed_empty` rows before removing the choices; no-op reverse. Applied clean (no stray rows exist).
- **T-03-02 (DoS, additive columns):** both new columns are nullable/defaulted; `migrate` verified against the dev MSSQL DB.

## Known Stubs

None — this plan is foundation-only (pure cores + model/migration surface). The apply layer, views, and templates that consume this seam are built in plans 02-06.

## Notes for Downstream Plans

- `resolve_checker_scan` intentionally does not carry `session_id` on `OFF_DUTY`/`WRONG_FLOOR`/`NO_SESSION`; the apply layer (03-02) supplies room/session context for the empty-room Verified-empty write.
- The `now` argument is a deliberate reserved seam — if online grace logic later needs it, the signature is already in place and both call sites (scan + replay) pass it.

## Self-Check: PASSED
- FOUND: verification/resolver.py
- FOUND: verification/migrations/0002_assignment_scope.py
- FOUND: verification/migrations/0003_retire_dead_validation_actions.py
- FOUND: scheduling/migrations/0002_session_online_checker.py
- FOUND commit: 80c695c (test), d5cc971 (feat resolver), e7bad01 (feat models)

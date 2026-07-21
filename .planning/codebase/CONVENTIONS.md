# Coding Conventions

**Analysis Date:** 2026-07-21

## Naming Patterns

**Files:**
- Use lowercase `snake_case.py` for implementation modules: `scheduling/report_render.py`, `ops/import_staging.py`, `web/reporting_common.py`.
- Keep Django framework files at their conventional names: `models.py`, `views.py`, `apps.py`, `admin.py`, `urls.py`, and `migrations/` in each app.
- Split a broad concern into a sibling module rather than extending an already-large generic file. Examples are `web/tests_ifo_utilization.py`, `scheduling/tests_reporting_lateness.py`, and `ops/tests_notifications.py` beside the older `tests.py` modules.
- Name management commands with verbs in `app/management/commands/`, such as `scheduling/management/commands/materialize_sessions.py` and `accounts/management/commands/link_entra.py`.
- Number migrations with Django's four-digit prefix and a descriptive suffix, for example `scheduling/migrations/0007_class_suspension_and_cancelled_reason.py`.

**Functions:**
- Use `snake_case` for functions and methods: `resolve_faculty_scan`, `reporting_range`, `send_push_outbox`.
- Prefix module-private helpers with `_`: `_aware`, `_exclude_virtual`, `_friendly_error`, `_active_term`.
- Name pure selectors/calculations for what they return (`session_minutes_late`, `ghost_rooms`) and state-changing services with imperative verbs (`suspend_classes`, `release_room`, `notify`).
- Name test methods `test_<behavior_or_rule>` and favor behavior language over implementation language, as in `test_within_grace_but_late_counts` in `scheduling/tests_reporting_lateness.py`.

**Variables:**
- Use `snake_case`; short domain-local names (`fx`, `resp`, `qs`, `sched`) are common inside tests and narrow functions.
- Use uppercase module constants for contracts, policy sets, and stable fixtures: `HELD_STATUSES`, `UTILIZATION_CSV_HEADER`, `MANILA`, `TERM_BUILDINGS`.
- Use `_id` suffixes for raw foreign-key identifiers and Django's generated `<field>_id` attributes to avoid unnecessary object loads, as in `scanned_room_id` and `online_checker_id`.

**Types:**
- Use `PascalCase` for Django models, dataclasses, enums, exceptions, and test classes: `AcademicTerm`, `Resolution`, `SessionStatus`, `ModalityShiftError`, `LatenessAggregateTests`.
- Use Django `TextChoices`/model constant types rather than bare status strings when a type exists. `scheduling/tests_reporting_lateness.py` explicitly imports `SessionStatus`; new production and test code should do the same.
- Use dataclasses for immutable/read-model-style aggregate outputs and pure resolver results, as in `scheduling/resolver.py` and `scheduling/reporting.py`.

## Code Style

**Formatting:**
- No formatter configuration is committed: no `pyproject.toml`, Black, Ruff, Prettier, or EditorConfig file was detected. Preserve the surrounding file's PEP 8-like style manually.
- Use four-space indentation, double quotes for most strings, trailing commas in multi-line calls/collections, and parenthesized continuation. Existing code sometimes aligns continuations to the opening call; match the edited module.
- Keep lines readable by splitting long conditions and calls inside parentheses. Examples: `scheduling/resolver.py` and `web/reporting_common.py`.
- Several newer modules declare `ASCII-only by convention (Windows cp1252)` in their docstrings, including `scheduling/test_support.py`, `web/tests_ifo_utilization.py`, and `web/reporting_common.py`. In those files, keep source text and comments ASCII-only. Do not propagate mojibake already visible in older files.

**Linting:**
- No project-wide linter command or configuration is committed.
- Existing targeted suppressions use inline `# noqa` with a rule when useful: `# noqa: E402` for deliberately late imports in `scheduling/tests.py`, and `# noqa: N802` for unittest hook names in `ops/tests_reports.py`.
- Do not add broad file-level suppressions. If an import must be late for test grouping or dependency isolation, document why beside the targeted suppression.

## Import Organization

**Order:**
1. Standard library imports (`datetime`, `decimal`, `unittest.mock`, `zoneinfo`).
2. Blank line.
3. Django and installed-package imports (`django.test`, `django.urls`, `pywebpush`).
4. Blank line.
5. Local app imports (`accounts.models`, `scheduling.reporting`, `web.ifo`).

Within a group, use one import per module or parenthesized multi-name imports. Representative files: `scheduling/tests_reporting_lateness.py`, `web/tests_ifo_utilization.py`, `scheduling/test_support.py`.

**Path Aliases:**
- Not applicable. Imports use absolute Django app paths such as `from scheduling.models import SessionStatus`; relative imports are not the project norm.
- For the configured user model, use `django.contrib.auth.get_user_model()` in runtime/test code. Direct app imports are reserved for other domain models.
- Use local imports inside helpers only when they intentionally delay model loading or isolate optional/live-data paths, as in `scheduling/tests_e2e.py`.

## Error Handling

**Patterns:**
- Domain/service layers raise named domain exceptions with stable machine-oriented messages, for example `ModalityShiftError` in `scheduling/services.py` and `PhotoError` in `accounts/photos.py`.
- Presentation code translates known domain messages into human copy at the edge and passes unknown messages through, demonstrated by `_friendly_error` and its tests in `web/tests_modality_form.py`.
- Validate request format in views, return a friendly `400` for correctable input, and keep business decisions in services/resolvers. The separation is documented and exercised across `web/faculty.py`, `scheduling/services.py`, and `scheduling/resolver.py`.
- Use narrow exception handlers around optional dashboard/report cards so one aggregate failure degrades that section instead of returning HTTP 500. Tests patch individual aggregate calls to raise in `web/tests_ifo_utilization.py` and `web/tests_reporting.py`.
- Background-job boundaries record failure and continue rather than killing the scheduler. Follow `ops/jobrun.py` for scheduled work; do not silently swallow errors in ordinary request/service code.
- Wrap multi-row state transitions in `transaction.atomic()` and use nested savepoints where a terminal denial must commit while partial application rolls back, following `scheduling/services.py`.

## Logging

**Framework:** Python `logging` plus persisted operational records.

**Patterns:**
- Use `logging.getLogger(__name__)` in infrastructure modules that need process diagnostics, such as push delivery and job execution.
- Domain mutations are primarily observable through `ops.models.AuditLog`, notifications through the single `ops.notifications.notify()` write path, and scheduled executions through `ops.models.JobRun`/`ops/jobrun.py`.
- Do not create an `AuditLog` merely for a notification; the triggering domain action owns the audit event. Preserve this separation when adding writers.
- Avoid `print()` in application code. Management commands should report user-facing progress through `self.stdout`/`self.stderr`.

## Comments

**When to Comment:**
- Explain business invariants, boundary semantics, and non-obvious backend constraints: strict `>` grace behavior in `scheduling/resolver.py`, MSSQL transaction choices, effective modality, merged-session propagation, and CSV-injection defenses.
- Include requirement/decision identifiers when they materially explain a rule (`D-01`, `IFO-09`, `JOB-02a`), as practiced throughout `scheduling/reporting.py` and focused tests.
- Avoid comments that merely restate a line. Prefer comments that say why a tempting alternative is wrong or what regression an assertion prevents.

**JSDoc/TSDoc:**
- Not applicable to the Python backend. JavaScript is small progressive-enhancement code under `static/` and does not use a generated documentation system.
- Python modules and public domain functions commonly use docstrings. Use a module docstring to define ownership/boundaries and function/class docstrings for contracts with non-obvious rules, as in `scheduling/resolver.py`, `scheduling/reporting.py`, and `scheduling/test_support.py`.

## Function Design

**Size:**
- Prefer small pure functions for decisions and calculations. Inject `now`, policy values, and pre-fetched data rather than querying the ORM or reading the wall clock inside a resolver; `resolve_faculty_scan()` and `is_no_show_past_grace()` in `scheduling/resolver.py` are canonical.
- Keep HTTP views thin: authorize, parse/validate format, fetch scoped context, call a service/aggregate, and render/redirect. When a role module grows, extract shared pure helpers (`web/reporting_common.py`) or a domain module instead of adding more duplication.
- Large orchestration modules currently exist (`web/ifo.py`, `scheduling/reporting.py`). New work should add a focused sibling when it represents a distinct concern and avoid new unrelated responsibilities in those files.

**Parameters:**
- Use keyword-only parameters for policy/configuration values and aggregates with many same-typed arguments, for example `resolve_faculty_scan(..., *, grace_min, early_end_min, open_min=15)`.
- Pass `now`/date ranges explicitly for deterministic domain logic. Obtain `timezone.now()`/`timezone.localdate()` at the outer seam.
- Accept model instances for coordinated service operations and IDs for pure comparison/resolver boundaries when object loading is unnecessary.

**Return Values:**
- Return typed result objects/dataclasses for multi-field calculations (`Resolution`, `FacultyRow`, `Scorecard`, `RoomUtilization`).
- Return booleans/counts for predicates and idempotent jobs; do not use exception flow for an expected yes/no result.
- Return a `SimpleNamespace` only for test fixture object graphs, as in `scheduling/test_support.py`; production APIs should use named domain types.

## Module Design

**Exports:**
- Use explicit module-level functions/classes/constants; wildcard imports are not used.
- Keep pure decision modules free of ORM and wall-clock dependencies. `scheduling/resolver.py`, `verification/resolver.py`, and pure helpers in `scheduling/reporting.py` establish this constraint.
- Put state mutation and audit/notification coordination in service modules (`scheduling/services.py`, `campus/services.py`, `ops/occupancy.py`), not templates or resolver cores.
- Put role-specific HTTP surfaces in the corresponding `web/*.py` module and route them through `web/urls.py`.

**Barrel Files:**
- Not used. App `__init__.py` files are empty/lightweight; import from the owning module directly.
- Do not add re-export barrels. They obscure Django app ownership and make circular imports more likely.

---

*Convention analysis: 2026-07-21*

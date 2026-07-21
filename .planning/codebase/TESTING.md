# Testing Patterns

**Analysis Date:** 2026-07-21

## Test Framework

**Runner:**
- Django 6.0.6 test runner, built on Python `unittest`.
- Config: `config/settings.py` via `DJANGO_SETTINGS_MODULE=config.settings` in `manage.py`; no separate test settings module is committed.
- Database-backed tests use the configured `mssql` backend and Django-created SQL Server test database. `README.md` states that the full suite builds an MSSQL test database.
- Repository inventory: 48 `tests*.py` modules, 1,053 `test_*` methods, and 232 conventionally named test classes under `accounts/`, `campus/`, `ops/`, `scheduling/`, `verification/`, and `web/`.

**Assertion Library:**
- `unittest` assertions provided by Django test cases: `assertEqual`, `assertTrue`, `assertRaises`, `assertContains`, `assertRedirects`, `assertNumQueries`, and mock call assertions.
- `unittest.mock`/`patch` for collaborators and failure injection.

**Run Commands:**
```powershell
py -3.12 manage.py test
py -3.12 manage.py test scheduling.tests.FacultyResolverTests
py -3.12 manage.py test web.tests_ifo_utilization
py -3.12 manage.py test --exclude-tag=e2e
```

The first two commands are documented in `README.md`. `scheduling/tests_e2e.py` uses Django's `@tag("e2e")`; exclude that tag for an ordinary empty-test-database run when explicitly selecting broad modules. On 2026-07-21 the shell exposed no installed `py -3.12`, so runtime execution could not be independently repeated during this map refresh.

## Test File Organization

**Location:**
- Tests are co-located with each Django app, not in a root `tests/` package.
- Small/legacy suites use `<app>/tests.py`, for example `accounts/tests.py` and `campus/tests.py`.
- Growing domains split by concern as `<app>/tests_<concern>.py`: `scheduling/tests_reporting_rooms.py`, `web/tests_ifo_coverage.py`, `ops/tests_push.py`.
- Shared fixture factories live in `scheduling/test_support.py`. It is deliberately named so Django does not discover it as a test module.

**Naming:**
- Files: `tests.py` or `tests_<concern>.py`.
- Classes: `<Behavior>Tests` or a reusable `<Concern>TestCase` base, e.g. `SessionMinutesLateFormulaTests` and `IfoDashboardTestCase`.
- Methods: `test_<rule_or_user_visible_behavior>`.
- Private fixture helpers: `_seed_late`, `_get`, `_schedule`; shared factories: `make_reporting_fixture`, `make_shift_fixture`.

**Structure:**
```text
accounts/
├── tests.py
└── tests_photos.py
scheduling/
├── tests.py
├── tests_<domain>.py
└── test_support.py
web/
├── tests.py
└── tests_<surface>.py
```

## Test Structure

**Suite Organization:**
```python
from django.test import SimpleTestCase, TestCase

from scheduling.models import SessionStatus
from scheduling.reporting import session_minutes_late
from scheduling.test_support import make_reporting_fixture


class SessionMinutesLateFormulaTests(SimpleTestCase):
    def test_early_arrival_not_negative(self):
        self.assertEqual(session_minutes_late(self.sched, earlier), 0)


class LatenessAggregateTests(TestCase):
    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_absent_zero_lateness(self):
        # seed one rule-specific condition
        row = self._row(self.fx.faculty_b)
        self.assertEqual(row.minutes_late_avg, Decimal("0.0"))
```

This pattern comes from `scheduling/tests_reporting_lateness.py`: keep pure formula tests DB-free, put DB-backed aggregate behavior in a sibling class, and make each test pin one named rule.

**Patterns:**
- Use `SimpleTestCase` for pure functions and parsers that must never query the database (`scheduling/tests.py`, `scheduling/tests_report_render.py`, `verification/tests.py`). An accidental ORM query then fails immediately.
- Use `TestCase` for ORM, client/view, template, auth, audit, and integration behavior. Its transaction wrapping is the default across `web/tests_*.py` and `ops/tests_*.py`.
- Use `TransactionTestCase` when the code under test owns `transaction.atomic()` boundaries or command-level transaction behavior, as in `scheduling/tests.py` and `scheduling/tests_room_master.py`.
- Use `setUp()` or a shared fixture factory for each test's independent object graph. Prefix unique fields when a test can create multiple graphs; `scheduling/test_support.py` documents and implements this convention.
- Assert both positive behavior and negative scope: correct role succeeds, unauthorized role redirects/403s, other department/term data is absent, and unrelated siblings remain unchanged.
- For user-facing views, assert status plus durable content/markup contracts with `assertContains` or decoded-body markers. Avoid brittle whitespace/class-order assertions unless document order is itself the requirement.
- Use `assertNumQueries` only for a deliberate query-budget contract, as in `web/tests_modality_form.py`.

## Mocking

**Framework:** `unittest.mock` (`mock.patch`, `patch`, `patch.object`).

**Patterns:**
```python
from unittest.mock import patch

with patch("web.ifo.room_utilization", side_effect=RuntimeError("boom")):
    response = self.client.get(self.url)
    self.assertEqual(response.status_code, 200)

with mock.patch("ops.push.webpush") as webpush:
    sent = send_push_outbox()
    webpush.assert_called_once()
```

Representative files are `web/tests_ifo_utilization.py` and `ops/tests_push.py`.

**What to Mock:**
- External delivery/network boundaries (`ops.push.webpush`).
- Randomness, file/image parser failure seams, and configured size limits (`campus/tests.py`, `accounts/tests_photos.py`).
- A sibling aggregate/service when testing section-level degradation or call wiring, patching where the collaborator is looked up (`web.ifo.*`, not its definition module).
- Wall-clock/settings only at the outer seam, using Django `override_settings` or targeted patches.

**What NOT to Mock:**
- Django ORM behavior, database constraints, transactions, audit rows, and notification rows when those are the behavior under test.
- Pure resolvers/calculations; call them directly with explicit inputs.
- The service layer in an end-to-end view mutation test when the purpose is to verify the full request-to-persistence flow.
- Model enums/constants. Import `SessionStatus`, `Role`, `Modality`, and related types instead of stubbing strings.

## Fixtures and Factories

**Test Data:**
```python
def make_shift_fixture(prefix="msf"):
    dept = Department.objects.create(
        name=f"{prefix} Department", code=f"{prefix}-DEP")
    faculty = User.objects.create(
        username=f"{prefix}_fac", role=Role.FACULTY, department=dept)
    # create the minimal connected room/term/schedule/session graph
    return SimpleNamespace(dept=dept, faculty=faculty, session=session)
```

This is the established shape in `scheduling/test_support.py`.

**Location:**
- Reusable cross-module factories: `scheduling/test_support.py` (`make_shift_fixture`, `make_merge_fixture`, `make_reporting_fixture`, `make_room_utilization_fixture`).
- Concern-local setup: the test module's `setUp()` and private helper methods.
- Committed anonymized import input: `data/fixtures/r3_synthetic.csv`.
- Real registrar inputs under gitignored `data/raw/` are optional local fixtures. Tests guard them with `unittest.skipUnless(os.path.exists(...))` in `scheduling/tests_import.py`, `scheduling/tests_import_hardening.py`, and `scheduling/tests_room_master.py`.
- Temporary media tests use `tempfile` directories plus `override_settings(MEDIA_ROOT=...)`, with cleanup in class/module teardown (`web/tests_faculty_profile.py`, `ops/tests_reports.py`, `ops/tests_staging.py`). Never write test uploads into the repository's real `media/` directory.

## Coverage

**Requirements:** None enforced. No coverage dependency, configuration, threshold, or CI workflow was detected.

**View Coverage:**
```powershell
# Not configured in this repository.
# If coverage.py is adopted, add it explicitly and document the command/threshold.
```

Treat current test counts as inventory, not a coverage percentage. `.planning/STATE.md` contains historical suite totals, but the executable source inventory (1,053 test methods) is the current authoritative structural evidence.

## Test Types

**Unit Tests:**
- Pure resolver/predicate tests use `SimpleTestCase`: `scheduling/tests.py`, `verification/tests.py`.
- Parser and document rendering tests avoid the DB: `scheduling/tests_import.py`, `scheduling/tests_report_render.py`, `scheduling/tests_srs.py`.
- Pure aggregate/formula rules are separated from ORM aggregation tests in modules such as `scheduling/tests_reporting_lateness.py` and `scheduling/tests_reporting_rooms.py`.

**Integration Tests:**
- Django `TestCase` exercises models, services, transactions, auth decorators, test client requests, templates, audit logs, notifications, and reporting together.
- Management command/import tests use `call_command` and, where needed, `TransactionTestCase` in `scheduling/tests.py`, `scheduling/tests_room_master.py`, and `accounts/tests.py`.
- MSSQL-specific behavior (collation, uniqueness, aware datetime round trips) is tested against the configured database in `campus/tests.py` and `scheduling/tests.py`.

**E2E Tests:**
- No browser automation framework is used.
- `scheduling/tests_e2e.py` contains `@tag("e2e")` live-term scale and spot-check assertions. They are guarded by whether a >2,000-schedule real term is loaded; its module docstring documents the clean-load sequence and direct `manage.py shell` helpers.
- Server-rendered user flows are otherwise tested through Django's test client, not Selenium/Playwright.

## Common Patterns

**Async Testing:**
```python
# No async test cases are present. Background work is invoked synchronously:
result = run_status_sweep()
self.assertEqual(result["absent"], expected)
```

APScheduler wiring and job boundaries are tested synchronously in `scheduling/tests.py`; push delivery is similarly exercised through `send_push_outbox()` in `ops/tests_push.py`.

**Error Testing:**
```python
with self.assertRaises(ModalityShiftError):
    submit_shift(...)

with patch("web.ifo.coverage_by_building_day", side_effect=BOOM):
    response = self.client.get(self.url)
self.assertEqual(response.status_code, 200)
self.assertContains(response, "Couldn't load this section")
```

Use exceptions for rejected domain operations, and assert atomicity: no partial writes, terminal status/audit only where specified, and unrelated records unchanged. For presentation degradation, inject the failure at one card/section boundary and prove the rest of the page still renders.

**Authorization and Scoping:**
```python
self.client.force_login(self.ifo)
response = self.client.get(reverse("ifo_dashboard"))
self.assertEqual(response.status_code, 200)

self.client.force_login(other_role)
response = self.client.get(reverse("ifo_dashboard"))
self.assertNotEqual(response.status_code, 200)
```

Every new role surface should include allowed-role, anonymous, wrong-role, and cross-department/cross-owner cases. Examples: `web/tests_ifo_utilization.py`, `web/tests_faculty_history.py`, `web/tests_hr.py`.

**Idempotency and Retry:**
- Run a writer twice and assert the second call creates no duplicate rows or external sends. Examples: `ops/tests_push.py`, `web/tests_merge_scan.py`, `ops/tests_reports.py`.
- For replay/offline flows, assert duplicate client UUID behavior and current-state revalidation, not merely the happy first request (`verification/tests.py`, `web/tests_merge_checker.py`).

**CSV/Report Contracts:**
- Assert exact header constants, row ordering/scope, MIME/filename, and spreadsheet-injection escaping in `scheduling/tests_report_render.py`, `web/tests_hr.py`, and `web/tests_ifo_utilization.py`.
- Keep report builder tests DB-free where the input is already a dataclass row; keep query/aggregation tests DB-backed.

---

*Testing analysis: 2026-07-21*

# Testing Patterns

**Analysis Date:** 2026-07-02

**Bottom line:** Automated testing is deliberately narrow. Exactly one module is unit-tested —
the pure scan resolver (`scheduling/tests.py`, 16 tests, no database). Everything else (views,
endpoints, templates, management commands, models) has **no automated tests**; the five other
`tests.py` files are empty Django stubs. The actual verification method for view/UI work has been
manual in-browser checking via the gstack `/browse` skill. This document describes what exists,
the large gap to the SRS's intended bar, and the patterns to follow when writing new tests.

## Test Framework

**Runner:**
- Django's built-in test runner (`unittest`-based). No third-party runner.
- No `pytest.ini`, `setup.cfg`, `tox.ini`, `conftest.py`, `pyproject.toml`, or `.coveragerc`
  exists — no pytest, no coverage tool, no CI config.
- `requirements.txt` lists no test/QA dependency (no `pytest`, `factory_boy`, `coverage`,
  `playwright`, `selenium`).

**Base class:**
- `django.test.SimpleTestCase` — used precisely because the one tested module needs **no
  database**. `SimpleTestCase` forbids DB queries, which structurally enforces the resolver's
  purity (`scheduling/tests.py:5,42`).

**Assertion style:**
- `unittest` assertions (`self.assertEqual`, `self.assertTrue`, `self.assertFalse`).

**Run commands:**
```bash
py -3.12 manage.py test                 # run all tests (only scheduling has real ones)
py -3.12 manage.py test scheduling      # run the resolver suite
py -3.12 manage.py test scheduling.tests.FacultyResolverTests.test_checkin_at_start_is_present
```
(No watch mode, no coverage command — neither is configured.)

## Test File Organization

**Location:**
- Django default: one `tests.py` per app, at the app root. Not co-located with source modules,
  not a `tests/` package.

**Current inventory:**
- `scheduling/tests.py` — 117 lines, 16 real tests. The only substantive suite.
- `accounts/tests.py`, `campus/tests.py`, `ops/tests.py`, `verification/tests.py`,
  `web/tests.py` — 3-line stubs, each just `from django.test import TestCase` +
  `# Create your tests here.` No tests.

**Naming:**
- Test class: `<Subject>Tests` (`FacultyResolverTests`).
- Test method: `test_<behavior_in_plain_english>` — descriptive, one behavior each
  (`test_checkin_after_grace_is_absent`, `test_wrong_room_needs_confirm`,
  `test_online_session_rejects_qr`).

## What IS Tested

**`scheduling/resolver.py` — the faculty scan decision logic (SCAN-01/02, SRS §6.6).**
The suite exhaustively covers every outcome branch of `resolve_faculty_scan`, including the
timing edges that matter most:

- Check-in at start / within grace / after grace (present vs. absent boundary at `grace_min`).
- Slightly-early allowed vs. far-too-early (`too-early`) vs. no schedule in a different room.
- Wrong room and room-occupied both setting `needs_confirm=True`, with room-occupied carrying
  `prior_session_id` for force handover.
- Online sessions rejecting QR, and `declared_modality` overriding the schedule's modality.
- Re-scan of an active session: near-end -> checkout, too-early -> `early-end` (needs confirm),
  wrong room while active -> `wrong-room`.
- Completed/absent sessions yielding `no-schedule`; a second session later the same day resolving
  correctly (`session_id` selection).

## Test Structure

The suite uses lightweight `@dataclass` fakes instead of real Django model instances — this is
what keeps it DB-free and fast. Follow this pattern for any future pure-function tests.

**Fakes (stand in for ORM objects the resolver only reads attributes off):**
```python
@dataclass
class FakeSchedule:
    modality: str = "f2f"

@dataclass
class FakeSession:
    id: int
    room_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    status: str = "scheduled"
    declared_modality: str = ""
    schedule: FakeSchedule = field(default_factory=FakeSchedule)
```

**Factory + call helpers (collapse boilerplate, inject sensible policy defaults):**
```python
T0 = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)  # a fixed "scheduled start"

def sess(**kw):                      # build a FakeSession overriding only what a test cares about
    defaults = dict(id=1, room_id=10, scheduled_start=T0,
                    scheduled_end=T0 + timedelta(minutes=90))
    defaults.update(kw)
    return FakeSession(**defaults)

def resolve(sessions, room_id=10, occupying=None, now=T0, **kw):
    policy = dict(grace_min=15, early_end_min=15)   # policy passed as args, not read from DB
    policy.update(kw)
    return R.resolve_faculty_scan(sessions, room_id, occupying, now, **policy)
```

**A representative test — fixed clock, no DB, assert on the outcome constant:**
```python
def test_checkin_after_grace_is_absent(self):
    r = resolve([sess()], now=T0 + timedelta(minutes=16))
    self.assertEqual(r.outcome, R.ABSENT)
```

**Patterns to reuse:**
- Time is injected (`now=`), never read from `timezone.now()` — deterministic, no freezegun needed.
- Policy values are injected as keyword args, never fetched via `get_policy()` — the unit under
  test stays pure.
- Assert against the resolver's exported outcome constants (`R.CHECKED_IN`, `R.ABSENT`), not raw
  strings, so a rename can't silently pass.

## Mocking

- **None used.** No `unittest.mock`, no Django mocking. The design sidesteps mocking entirely by
  testing a pure function with plain dataclass fakes. There is nothing to patch because the
  function performs no I/O.
- Guidance for new tests: prefer the same approach — push I/O to the edges and unit-test the pure
  core with fakes. Reach for `mock` only when testing the impure web layer (e.g. patching
  `_notify_ifo` or `cache`), which currently has no tests.

## Fixtures and Factories

- No Django fixtures, no `factory_boy`, no `setUp`/`tearDown` in the current suite. The `sess()`
  function is the only "factory," and it builds in-memory dataclasses.
- Seed/demo data for **manual** verification (not tests) lives in
  `accounts/management/commands/seed_demo.py` (dev users, password `devpass123`) and
  `scheduling/management/commands/import_offerings.py` / `materialize_sessions.py`.

## Coverage

- **No coverage measurement configured** and **none enforced.** By inspection, coverage is
  effectively limited to `scheduling/resolver.py`. The entire `web/` layer (`scan.py`, `ifo.py`,
  `faculty.py`, `views.py`), all models, all serializers/DRF surface, and all management commands
  are uncovered by automated tests.

## Test Types

**Unit tests:**
- Present, for the pure resolver only (`scheduling/tests.py`). Fast, DB-free, deterministic.

**Integration / API / view tests:**
- **Not present.** No `Client()`/`RequestFactory` tests exercise `web/urls.py` endpoints
  (`/scan/resolve`, `/scan/confirm`, `/faculty/schedule`, `/ifo/live`, …). The two-step signed-
  token confirm flow, the rate-limit and idempotency cache logic, the `AuditLog` write-on-every-
  event rule, and the role decorators are all **verified only by hand**.

**E2E / browser tests:**
- No automated E2E harness (no Playwright/Selenium). The de-facto E2E method has been **manual
  in-browser verification driven through the gstack `/browse` skill** — the design's Definition
  of Done requires each slice be "verified end-to-end in-browser (not just unit tests)"
  (`docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §3, item 4).
  Evidence of this manual method: `poc/` holds screenshots of every faculty/IFO outcome surface
  (`fac-checkedin.png`, `fac-wrongroom.png`, `fac-earlyend.png`, `ifo-live.png`, …), and
  `.gstack/browse-audit.jsonl` (219 lines) logs the browser-driving session.

## The Intended Bar (SRS §6.6) vs. Current State

SRS §6.6 (`FluxTrack_SRS.md:442`) sets the maintainability/testing target:

> "…the scan resolver and reporting aggregates implemented as pure functions covered by unit
> tests, and with **API tests per endpoint**."

Plus RPT-05 (`FluxTrack_SRS.md:339`): report aggregates shall be "pure, independently tested
functions" that degrade gracefully.

Status against that bar:

| Intended (SRS §6.6 / RPT-05) | Current state |
|---|---|
| Scan resolver = pure, unit-tested | **Met.** `scheduling/resolver.py` + 16 tests in `scheduling/tests.py`. |
| Reporting aggregates = pure, independently tested | **Not built.** No reporting module and no tests exist yet (RPT-01/02/05 pending). |
| API tests per endpoint | **Not built.** Zero endpoint/view tests. The only endpoints that exist (`web/urls.py`) are untested; DRF API surface is not yet implemented. |
| Two isolated JS modules (QR scanner, offline queue) independently testable | **Not built / not tested.** |

The gap is intentional and known for a solo-dev, early-phase project: the highest-risk logic
(the timing/branching resolver) is locked down with fast unit tests, while everything I/O-heavy
is currently checked manually in the browser. The clear next step to move toward the SRS bar is
adding view/API tests (Django `Client` or DRF `APIClient`) for the scan flow — asserting outcomes,
the signed-confirm round trip, rate-limit/idempotency behavior, and that an `AuditLog` row is
written per event — and unit-testing reporting aggregates the same way the resolver is tested once
they exist.

## Common Patterns

**Async testing:**
- Not applicable. No async views/tests; live surfaces use htmx polling, not async.

**Error / edge testing (the current suite's real strength):**
```python
def test_room_occupied_needs_confirm_and_carries_prior(self):
    r = resolve([sess()], occupying=77)
    self.assertEqual(r.outcome, R.ROOM_OCCUPIED)
    self.assertTrue(r.needs_confirm)
    self.assertEqual(r.prior_session_id, 77)
```
Edge behavior is asserted directly on the returned value object — including the `needs_confirm`
computed flag and carried IDs — rather than via exceptions. New tests should assert the full
`Resolution` shape (outcome + `needs_confirm` + `session_id`/`prior_session_id`), not just the
outcome string.

---

*Testing analysis: 2026-07-02*

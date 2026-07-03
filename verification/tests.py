"""Unit tests for the pure Checker decision cores (CHK-01, IFO-06, SRS 6.6).

The gating core and the round-robin distributor are pure: no ORM, no
timezone.now(). Both suites are SimpleTestCase, so any accidental database
access or timezone.now() call inside the cores would error the test.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from verification import resolver as R


def state(id=1, status="active", verified=False):
    """A tiny session_state value double: .id / .status / .verified."""
    return SimpleNamespace(id=id, status=status, verified=verified)


class CheckerResolverTests(SimpleTestCase):
    def test_off_duty_refused(self):
        r = R.resolve_checker_scan([], scanned_floor_id=5, session_state=state(), now=None)
        self.assertEqual(r.outcome, R.OFF_DUTY)
        self.assertFalse(r.actionable)

    def test_wrong_floor_refused(self):
        r = R.resolve_checker_scan([1, 2], scanned_floor_id=5, session_state=state(), now=None)
        self.assertEqual(r.outcome, R.WRONG_FLOOR)
        self.assertFalse(r.actionable)

    def test_no_session_is_actionable_empty(self):
        # No session object at all -> room empty -> Verified empty is actionable.
        r = R.resolve_checker_scan([5], scanned_floor_id=5, session_state=None, now=None)
        self.assertEqual(r.outcome, R.NO_SESSION)
        self.assertTrue(r.actionable)
        # A scheduled (not yet started) session also reads as an empty room.
        r2 = R.resolve_checker_scan([5], scanned_floor_id=5,
                                    session_state=state(status="scheduled"), now=None)
        self.assertEqual(r2.outcome, R.NO_SESSION)
        self.assertTrue(r2.actionable)

    def test_absent_is_excluded(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=7, status="absent"), now=None)
        self.assertEqual(r.outcome, R.ABSENT_EXCLUDED)
        self.assertEqual(r.session_id, 7)
        self.assertFalse(r.actionable)

    def test_already_verified(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=9, status="active", verified=True),
                                   now=None)
        self.assertEqual(r.outcome, R.ALREADY_VERIFIED)
        self.assertEqual(r.session_id, 9)
        self.assertFalse(r.actionable)

    def test_active_unverified_is_actionable(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=11, status="active", verified=False),
                                   now=None)
        self.assertEqual(r.outcome, R.ACTIVE_UNVERIFIED)
        self.assertEqual(r.session_id, 11)
        self.assertTrue(r.actionable)


class DistributeTests(SimpleTestCase):
    def test_round_robin_even_split(self):
        # 4 sessions across 2 checkers -> deterministic alternation by input order.
        result = R.distribute_online_sessions([101, 102, 103, 104], [7, 8])
        self.assertEqual(result, {101: 7, 102: 8, 103: 7, 104: 8})

    def test_empty_checkers_returns_empty(self):
        self.assertEqual(R.distribute_online_sessions([101, 102], []), {})

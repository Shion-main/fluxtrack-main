"""Mutation-resistant tests for the lateness aggregates (A3 / D-01 / D-02).

A NEW sibling of tests_reporting.py / tests_reporting_rooms.py, matching this app's
split of reporting tests by concern. Lateness is a distinct aggregate family that
redeems the PROJECT.md core-value promise that lateness is "captured at the room
level."

DB-FREE (SimpleTestCase) pinning the pure formula:
  SessionMinutesLateFormulaTests -- max(0, actual-scheduled) seconds; None -> 0;
                                    early arrival -> 0 (never negative).

DB-BACKED (TestCase) over make_reporting_fixture + add_session, one assertion per
locked rule:
  LatenessAggregateTests -- within-grace-late counts; sub-minute never counts;
                            ABSENT/CANCELLED contribute nothing; in-flight ACTIVE
                            DOES contribute; chronic >=30% frequency with a >=5-held
                            floor; FacultyRow/Scorecard field parity.

Django test runner (not pytest); reference module constants (SessionStatus,
HELD_STATUSES), never a bare status string. ASCII-only.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from scheduling.models import SessionStatus
from scheduling.reporting import (
    FacultyRow,
    Scorecard,
    faculty_attendance,
    faculty_scorecard,
    session_minutes_late,
)
from scheduling.test_support import MANILA, _aware, make_reporting_fixture

# The schedule start make_reporting_fixture seeds every session at (08:00 local);
# actual_start deltas are measured against it.
TEACH_START = time(8, 0)
TEACH_END = time(9, 30)


class SessionMinutesLateFormulaTests(SimpleTestCase):
    """A3 / D-01: the pure, grace-independent max(0, actual-scheduled) seconds formula."""

    def setUp(self):
        self.sched = datetime(2026, 7, 6, 8, 0, tzinfo=MANILA)

    def test_formula_max_zero(self):
        # 7 minutes late -> 420 seconds (the caller renders minutes).
        self.assertEqual(
            session_minutes_late(self.sched, self.sched + timedelta(minutes=7)), 420)

    def test_none_start_zero(self):
        # A NULL actual_start (never held) is answered explicitly as 0.
        self.assertEqual(session_minutes_late(self.sched, None), 0)

    def test_early_arrival_not_negative(self):
        # An early arrival floors at 0, never a negative that would cancel a
        # genuinely-late sibling in the average.
        self.assertEqual(
            session_minutes_late(self.sched, self.sched - timedelta(minutes=5)), 0)


class LatenessAggregateTests(TestCase):
    """A3 / D-01 / D-02: _lateness_map -> FacultyRow / Scorecard lateness fields.

    The fixture's pre-existing faculty_a/faculty_b sessions carry no actual_start, so
    the fold's ``actual_start__isnull=False`` guard excludes them and each test's
    held-with-start population is exactly the sessions it seeds (deterministic).
    """

    def setUp(self):
        self.fx = make_reporting_fixture()

    # -- helpers -----------------------------------------------------------------

    def _sched(self, d):
        return _aware(d, TEACH_START)

    def _seed_late(self, faculty, *, seconds=0, status=SessionStatus.COMPLETED,
                   end=True, d=None):
        """Seed one held session on ``faculty`` late by ``seconds`` (actual_start stamped)."""
        d = d or self.fx.week_start
        start = self._sched(d) + timedelta(seconds=seconds)
        end_dt = _aware(d, TEACH_END) if end else None
        return self.fx.add_session(
            faculty, d, status, actual_start=start, actual_end=end_dt)

    def _row(self, faculty):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        match = [r for r in rows if r.faculty_id == faculty.id]
        self.assertEqual(len(match), 1, "exactly one row per faculty")
        return match[0]

    # -- rules -------------------------------------------------------------------

    def test_within_grace_but_late_counts(self):
        # 3 min late: inside any grace window (so never ABSENT), yet grace-independent
        # lateness registers -- the whole point of D-01.
        self._seed_late(self.fx.faculty_a, seconds=180)
        row = self._row(self.fx.faculty_a)
        self.assertGreater(row.minutes_late_avg, Decimal("0.0"))
        self.assertGreaterEqual(row.late_sessions, 1)

    def test_sub_minute_not_a_late_session(self):
        # 5 sessions each 40s late: below the >=1-whole-minute frequency floor, so
        # never counted late, yet the magnitude still shows in the average.
        for _ in range(5):
            self._seed_late(self.fx.faculty_a, seconds=40)
        row = self._row(self.fx.faculty_a)
        self.assertEqual(row.late_sessions, 0)
        self.assertFalse(row.chronic_late)
        self.assertGreater(row.minutes_late_avg, Decimal("0.0"))

    def test_absent_zero_lateness(self):
        # An ABSENT session -- even with a (bogus) late actual_start -- contributes
        # nothing: the fold filters HELD_STATUSES, so ABSENT can never leak in.
        self.fx.add_session(
            self.fx.faculty_b, self.fx.tue, SessionStatus.ABSENT,
            actual_start=self._sched(self.fx.tue) + timedelta(minutes=15))
        row = self._row(self.fx.faculty_b)
        self.assertEqual(row.minutes_late_avg, Decimal("0.0"))
        self.assertEqual(row.late_sessions, 0)

    def test_cancelled_excluded_from_lateness(self):
        # A CANCELLED (suspension/holiday) session never contributes to lateness
        # (Phase 9 A1: neither held nor absent nor booked).
        self.fx.add_session(
            self.fx.faculty_b, self.fx.week_start, SessionStatus.CANCELLED,
            actual_start=self._sched(self.fx.week_start) + timedelta(minutes=20))
        row = self._row(self.fx.faculty_b)
        self.assertEqual(row.minutes_late_avg, Decimal("0.0"))
        self.assertEqual(row.late_sessions, 0)

    def test_inflight_active_contributes_to_lateness(self):
        # ACTIVE with actual_start set but actual_end NULL (still running): lateness
        # needs only the START, unlike room_utilization which excludes in-flight.
        self._seed_late(
            self.fx.faculty_a, seconds=600, status=SessionStatus.ACTIVE, end=False)
        row = self._row(self.fx.faculty_a)
        self.assertGreaterEqual(row.late_sessions, 1)
        self.assertGreater(row.minutes_late_avg, Decimal("0.0"))

    def test_chronic_threshold_boundary(self):
        # faculty_a: 5 held-with-start, 2 late by >=1 min (40%) -> chronic True.
        self._seed_late(self.fx.faculty_a, seconds=300)
        self._seed_late(self.fx.faculty_a, seconds=300)
        for _ in range(3):
            self._seed_late(self.fx.faculty_a, seconds=0)   # on-time
        # faculty_b: 5 held-with-start, 1 late (20%) -> chronic False.
        self._seed_late(self.fx.faculty_b, seconds=300)
        for _ in range(4):
            self._seed_late(self.fx.faculty_b, seconds=0)
        row_a = self._row(self.fx.faculty_a)
        row_b = self._row(self.fx.faculty_b)
        self.assertTrue(row_a.chronic_late)
        self.assertEqual(row_a.late_sessions, 2)
        self.assertFalse(row_b.chronic_late)
        self.assertEqual(row_b.late_sessions, 1)

    def test_chronic_floor_below_five_never_flagged(self):
        # 4 held, ALL late: still below the >=5-held floor, so never flagged even at
        # 100% late frequency (D-02).
        for _ in range(4):
            self._seed_late(self.fx.faculty_a, seconds=600)
        row = self._row(self.fx.faculty_a)
        self.assertFalse(row.chronic_late)
        self.assertEqual(row.late_sessions, 4)

    def test_facultyrow_lateness_fields(self):
        # FacultyRow carries the three fields, populated (5-min-late -> avg 5.0).
        self._seed_late(self.fx.faculty_a, seconds=300)
        row = self._row(self.fx.faculty_a)
        self.assertIsInstance(row, FacultyRow)
        self.assertIsInstance(row.minutes_late_avg, Decimal)
        self.assertEqual(row.minutes_late_avg, Decimal("5.0"))
        self.assertEqual(row.late_sessions, 1)
        self.assertFalse(row.chronic_late)   # only 1 held-with-start

    def test_scorecard_lateness_fields(self):
        # Scorecard carries the same fields and agrees with FacultyRow over the same
        # faculty/range (the two builders cannot drift).
        self._seed_late(self.fx.faculty_a, seconds=300)
        self._seed_late(self.fx.faculty_a, seconds=0)
        row = self._row(self.fx.faculty_a)
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)
        self.assertIsInstance(card, Scorecard)
        self.assertEqual(card.minutes_late_avg, row.minutes_late_avg)
        self.assertEqual(card.late_sessions, row.late_sessions)
        self.assertEqual(card.chronic_late, row.chronic_late)
        # non-trivial: (300s + 0s) / 2 held / 60 == 2.5 min average.
        self.assertEqual(card.minutes_late_avg, Decimal("2.5"))
        self.assertEqual(card.late_sessions, 1)

"""Unit tests for the verification-coverage aggregates (A6 / D-04).

A NEW sibling of tests_reporting.py / tests_reporting_rooms.py, matching this app's
existing split of reporting tests by concern. Verification coverage (verified over
HELD, by building x weekday, plus the explicit zero-coverage-floor list) is a
distinct aggregate family with its own honesty rules.

Each DB-backed TestCase pins exactly one rule from the plan's must_haves.truths, so
a mutation that breaks one rule fails one named test:

  CoverageByBuildingDayTests
    test_coverage_pct_verified_over_held        -- pct == _pct(verified, held) (D-04)
    test_coverage_excludes_virtual_rooms        -- physical-only; V-room ignored
    test_merged_sibling_lowers_coverage         -- MERGED held-but-unverified lowers it
    test_absent_and_cancelled_excluded_from_coverage -- neither touches the rate
  ZeroCoverageFloorsTests
    test_zero_coverage_floor_listed             -- held>0 AND verified==0 is VISIBLE
    test_covered_floor_absent                   -- a covered floor never appears

Django test runner (not pytest); reference module constants (DayOfWeek), never a
bare weekday int literal where a name reads clearer. ASCII-only.
"""
from datetime import time

from django.test import TestCase

from scheduling.models import (
    AcademicTerm,
    DayOfWeek,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.reporting import (
    CoverageRow,
    ZeroCoverageFloor,
    _pct,
    coverage_by_building_day,
    zero_coverage_floors,
)
from scheduling.test_support import (
    _aware,
    COV_MON,
    COV_WEEK_END,
    COV_WEEK_START,
    make_coverage_fixture,
)


def _cell(rows, building_code, day):
    """The one CoverageRow for a (building_code, weekday) cell, or None."""
    for r in rows:
        if r.building_code == building_code and r.day == day:
            return r
    return None


class CoverageByBuildingDayTests(TestCase):
    """The verified/HELD rate, grouped by (building, weekday), physical-only."""

    def setUp(self):
        self.fx = make_coverage_fixture("covr")
        self.kw = dict(term=self.fx.term, start=COV_WEEK_START, end=COV_WEEK_END)

    def test_rows_are_coverage_rows_ordered_by_building_then_day(self):
        rows = coverage_by_building_day(**self.kw)
        self.assertTrue(all(isinstance(r, CoverageRow) for r in rows))
        keys = [(r.building_code, r.day) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_coverage_pct_verified_over_held(self):
        """D-04: pct is verified/HELD (never scheduled), via _pct."""
        rows = coverage_by_building_day(**self.kw)
        cell = _cell(rows, self.fx.b1.code, DayOfWeek.MON)
        self.assertIsNotNone(cell)
        self.assertEqual(cell.held, 2)
        self.assertEqual(cell.verified, 1)
        self.assertEqual(cell.pct, _pct(cell.verified, cell.held))
        self.assertEqual(cell.pct, 50)

    def test_coverage_excludes_virtual_rooms(self):
        """D-04: an online V-room session -- even one verified -- never counts."""
        rows = coverage_by_building_day(**self.kw)
        codes = {r.building_code for r in rows}
        self.assertNotIn(self.fx.online_building.code, codes)
        # The verified V-room session did not inflate any physical cell: total
        # verified across the physical cells is exactly 1 (partial) + 2 (full) +
        # 1 (merged floor) = 4, NOT 5.
        self.assertEqual(sum(r.verified for r in rows), 4)

    def test_merged_sibling_lowers_coverage(self):
        """A MERGED held session has no validation, so it lowers the rate."""
        rows = coverage_by_building_day(**self.kw)
        cell = _cell(rows, self.fx.b2.code, DayOfWeek.WED)
        self.assertIsNotNone(cell)
        # Two held sessions; one is the MERGED sibling with no CheckerValidation.
        self.assertEqual(cell.held, 2)
        self.assertEqual(cell.verified, 1)
        self.assertLess(cell.verified, cell.held)
        self.assertEqual(cell.pct, 50)

    def test_absent_and_cancelled_excluded_from_coverage(self):
        """ABSENT contributes zero to the numerator and is out of the HELD
        denominator; a CANCELLED session contributes nothing to either side."""
        rows = coverage_by_building_day(**self.kw)
        cell = _cell(rows, self.fx.b1.code, DayOfWeek.TUE)
        self.assertIsNotNone(cell)
        # Only the two held sessions count. The ABSENT (which carries a stray
        # verified validation) and the CANCELLED are both excluded, so held is 2
        # (not 4) and verified is 0 (the absent validation never counts).
        self.assertEqual(cell.held, 2)
        self.assertEqual(cell.verified, 0)
        self.assertEqual(cell.pct, 0)


class ZeroCoverageFloorsTests(TestCase):
    """The explicit list of floors with held sessions but no verification (D-04)."""

    def setUp(self):
        self.fx = make_coverage_fixture("covz")
        self.kw = dict(term=self.fx.term, start=COV_WEEK_START, end=COV_WEEK_END)

    def test_zero_coverage_floor_listed(self):
        """A floor with held > 0 AND verified == 0 must appear EXPLICITLY."""
        floors = zero_coverage_floors(**self.kw)
        self.assertTrue(all(isinstance(f, ZeroCoverageFloor) for f in floors))
        keys = {(f.building_code, f.floor_number) for f in floors}
        self.assertIn((self.fx.b1.code, self.fx.b1f2.number), keys)
        zf = next(
            f for f in floors
            if (f.building_code, f.floor_number)
            == (self.fx.b1.code, self.fx.b1f2.number)
        )
        # It carries its held count so the surface can name "2 held, 0 verified".
        self.assertEqual(zf.held, 2)

    def test_covered_floor_absent(self):
        """A fully- or partially-covered floor never appears; nor a V-floor."""
        floors = zero_coverage_floors(**self.kw)
        keys = {(f.building_code, f.floor_number) for f in floors}
        # b2 F1 is fully verified; b1 F1 is partial (1 verified); b2 F2 has 1
        # verified beside the merged sibling -- none is zero-coverage.
        self.assertNotIn((self.fx.b2.code, self.fx.b2f1.number), keys)
        self.assertNotIn((self.fx.b1.code, self.fx.b1f1.number), keys)
        self.assertNotIn((self.fx.b2.code, self.fx.b2f2.number), keys)
        # The virtual room's floor is physical-only-excluded, so never listed.
        self.assertNotIn((self.fx.online_building.code, 1), keys)
        # Exactly one zero-coverage floor in the whole fixture.
        self.assertEqual(len(floors), 1)


class CoverageTermScopeTests(TestCase):
    """D-12: coverage aggregates require and honor one selected term."""

    def setUp(self):
        self.fx = make_coverage_fixture("covterm")
        self.draft = AcademicTerm.objects.create(
            name="covterm Draft", start_date=COV_WEEK_START,
            end_date=COV_WEEK_END, status=AcademicTerm.Status.DRAFT)

    def test_coverage_aggregates_require_term_keyword(self):
        kwargs = {"start": COV_WEEK_START, "end": COV_WEEK_END}
        with self.assertRaises(TypeError):
            coverage_by_building_day(**kwargs)
        with self.assertRaises(TypeError):
            zero_coverage_floors(**kwargs)

    def test_same_date_other_term_coverage_does_not_leak(self):
        sched = Schedule.objects.create(
            term=self.draft, course_code="COVD101", section="A",
            faculty=self.fx.faculty, room=self.fx.rooms["b1f2"],
            day_of_week=COV_MON.weekday(), start_time=time(8, 0),
            end_time=time(9, 30),
        )
        Session.objects.create(
            schedule=sched, faculty=self.fx.faculty, room=self.fx.rooms["b1f2"],
            date=COV_MON, scheduled_start=_aware(COV_MON, time(8, 0)),
            scheduled_end=_aware(COV_MON, time(9, 30)),
            status=SessionStatus.ACTIVE,
        )

        rows = coverage_by_building_day(
            term=self.fx.term, start=COV_WEEK_START, end=COV_WEEK_END)
        cell = _cell(rows, self.fx.b1.code, DayOfWeek.MON)
        self.assertEqual(cell.held, 2)

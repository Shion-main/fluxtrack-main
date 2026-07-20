"""IFO-09 / A6 / D-04: verification-coverage sections on /ifo/dashboard.

Plan 11-03 adds a verified/HELD coverage rate (by building x weekday, physical
rooms only) and an explicit zero-coverage-floor list to the IFO dashboard, each in
its own safe_card owner. This module proves those sections reached the screen, that
a zero-coverage floor is NAMED (not merely a low percentage), that a raising
coverage aggregate degrades to an error card instead of 500ing the page, and that
@ifo_required still gates access.

Classes:
  CoverageSectionTests   -- the sections render; context carries (value, error) pairs.
  ZeroFloorSurfaceTests  -- a zero-coverage floor is listed explicitly by name.
  CoverageIsolationTests -- D-04/RPT-05: a raising coverage aggregate errors alone.
  CoverageAuthTests      -- the new sections did not widen access.

Django TestCase, never pytest. ASCII-only.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from scheduling.reporting import CoverageRow, ZeroCoverageFloor
from scheduling.test_support import (
    COV_WEEK_END,
    COV_WEEK_START,
    make_coverage_fixture,
)

ERROR_TEXT = "Couldn't load this section"
BOOM = RuntimeError("coverage aggregate exploded")


class IfoCoverageTestCase(TestCase):
    """Shared setup: an IFO admin, the coverage fixture, and the dashboard URL."""

    def setUp(self):
        self.fx = make_coverage_fixture("ifocov")
        self.ifo = get_user_model().objects.create(
            username="ifocov_admin", email="ifocov_admin@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)
        self.url = reverse("ifo_dashboard")

    def _get(self, **params):
        params.setdefault("from", COV_WEEK_START.isoformat())
        params.setdefault("to", COV_WEEK_END.isoformat())
        return self.client.get(self.url, params)


class CoverageSectionTests(IfoCoverageTestCase):
    """The coverage sections render and carry (value, error) pairs."""

    def test_dashboard_renders_for_an_ifo_user(self):
        self.assertEqual(self._get().status_code, 200)

    def test_context_carries_a_coverage_two_tuple(self):
        resp = self._get()
        coverage = resp.context["coverage"]
        self.assertEqual(len(coverage), 2)
        self.assertIsNone(coverage[1])
        self.assertTrue(all(isinstance(r, CoverageRow) for r in coverage[0]))

    def test_context_carries_a_zero_floors_two_tuple(self):
        resp = self._get()
        zero_floors = resp.context["zero_floors"]
        self.assertEqual(len(zero_floors), 2)
        self.assertIsNone(zero_floors[1])
        self.assertTrue(
            all(isinstance(f, ZeroCoverageFloor) for f in zero_floors[0]))

    def test_the_coverage_section_is_labelled_and_shows_a_weekday(self):
        body = self._get().content.decode()
        self.assertIn("Verification coverage", body)
        # The weekday int was resolved to a label in the view (Monday carries cells).
        self.assertIn("Monday", body)

    def test_the_coverage_rate_reaches_the_screen(self):
        """The partial (b1, Mon) cell renders 50% verified/held on the page."""
        resp = self._get()
        rows = resp.context["coverage"][0]
        b1_mon = next(
            r for r in rows
            if r.building_code == self.fx.b1.code and r.day == 0)
        self.assertEqual(b1_mon.pct, 50)
        self.assertIn("50%", resp.content.decode())


class ZeroFloorSurfaceTests(IfoCoverageTestCase):
    """A zero-coverage floor must be VISIBLE by name (D-04), not buried."""

    def test_the_zero_coverage_floor_is_listed_by_name(self):
        body = self._get().content.decode()
        self.assertIn("Zero-coverage floors", body)
        # b1 Floor 2 is the fixture's one zero-coverage floor.
        self.assertIn(self.fx.b1.name, body)
        self.assertIn(f"Floor {self.fx.b1f2.number}", body)

    def test_a_covered_floor_is_not_in_the_zero_list(self):
        """The fully-verified b2 F1 must never be named as zero-coverage."""
        zero_floors = self._get().context["zero_floors"][0]
        keys = {(f.building_code, f.floor_number) for f in zero_floors}
        self.assertNotIn((self.fx.b2.code, self.fx.b2f1.number), keys)


class CoverageIsolationTests(IfoCoverageTestCase):
    """RPT-05 / D-04: a raising coverage aggregate errors in its OWN section."""

    def test_a_raising_coverage_aggregate_does_not_500_the_dashboard(self):
        with patch("web.ifo.coverage_by_building_day", side_effect=BOOM):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(ERROR_TEXT, body)
        # The raw exception text never reaches the page (information disclosure).
        self.assertNotIn("coverage aggregate exploded", body)

    def test_a_coverage_failure_leaves_the_zero_floor_section_standing(self):
        """The two coverage sections are independent safe_card owners: a failing
        rate must not blank the zero-floor list, which is a separate query."""
        with patch("web.ifo.coverage_by_building_day", side_effect=BOOM):
            resp = self._get()
        body = resp.content.decode()
        self.assertIn("Zero-coverage floors", body)
        # The zero-floor list still rendered its one floor by name.
        self.assertIn(f"Floor {self.fx.b1f2.number}", body)

    def test_the_kpi_row_survives_a_coverage_failure(self):
        """A coverage failure must not touch the attendance KPI row above it."""
        with patch("web.ifo.coverage_by_building_day", side_effect=BOOM):
            resp = self._get()
        self.assertIn('data-kpi-card="faculty"', resp.content.decode())


class CoverageAuthTests(IfoCoverageTestCase):
    """The new sections did not widen access; @ifo_required still applies."""

    def test_a_faculty_user_cannot_reach_the_dashboard(self):
        self.client.force_login(self.fx.faculty)
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_an_anonymous_user_cannot_reach_the_dashboard(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

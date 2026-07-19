"""IFO-09 closure: the Room Occupancy card on /ifo/dashboard.

The SRS names Room Occupancy in SESSION-HOURS as a dashboard card. Phase 6 built
Attendance % into that slot instead and no room-aware aggregate existed at all.
Phase 06.1 plan 01 built the aggregate; this module holds the tests that prove it
reached the screen and that the row degrades instead of 500ing.

Classes:
  DashboardOccupancyCardTests  -- the closure: five cards, session-hours, context.
  DashboardCardIsolationTests  -- D-05: three INDEPENDENT error owners, one row.
  DashboardRangeTests          -- one window, shared by every card.
  DashboardAuthTests           -- the new card did not widen access.

Django TestCase, never pytest. ASCII-only.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from scheduling.reporting import RoomUtilization
from scheduling.test_support import (
    RUTIL_WEEK_END,
    RUTIL_WEEK_START,
    make_room_utilization_fixture,
)

# A stable marker every KPI cell carries, so the card count is asserted against
# markup that a whitespace or class-order change cannot break.
CARD_MARKER = 'data-kpi-card="'

# The occupancy card's unit caption. IFO-09 is not closed unless a stakeholder can
# read the unit off the screen, so the string is asserted, not the mere 200.
SESSION_HOURS_CAPTION = "session-hours used / booked"

BOOM = RuntimeError("aggregate exploded")


class IfoDashboardTestCase(TestCase):
    """Shared setup: an IFO admin, the room fixture, and the dashboard URL."""

    def setUp(self):
        self.fx = make_room_utilization_fixture("ifoutil")
        self.ifo = get_user_model().objects.create(
            username="ifoutil_admin", email="ifoutil_admin@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)
        self.url = reverse("ifo_dashboard")

    def _get(self, **params):
        params.setdefault("from", RUTIL_WEEK_START.isoformat())
        params.setdefault("to", RUTIL_WEEK_END.isoformat())
        return self.client.get(self.url, params)


class DashboardOccupancyCardTests(IfoDashboardTestCase):
    """IFO-09: the room-occupancy card exists and reads in session-hours."""

    def test_dashboard_renders_for_an_ifo_user(self):
        self.assertEqual(self._get().status_code, 200)

    def test_context_carries_an_occupancy_two_tuple(self):
        resp = self._get()
        occupancy = resp.context["occupancy"]
        self.assertEqual(len(occupancy), 2)
        self.assertIsInstance(occupancy[0], RoomUtilization)
        self.assertIsNone(occupancy[1])

    def test_the_row_carries_five_kpi_cards(self):
        body = self._get().content.decode()
        self.assertEqual(body.count(CARD_MARKER), 5)

    def test_the_five_cards_are_in_the_d07_order(self):
        body = self._get().content.decode()
        positions = [
            body.index('data-kpi-card="faculty"'),
            body.index('data-kpi-card="occupancy"'),
            body.index('data-kpi-card="sessions"'),
            body.index('data-kpi-card="absences"'),
            body.index('data-kpi-card="attendance"'),
        ]
        self.assertEqual(positions, sorted(positions))

    def test_the_occupancy_card_is_labelled_and_states_its_unit(self):
        body = self._get().content.decode()
        self.assertIn("Room Occupancy", body)
        self.assertIn(SESSION_HOURS_CAPTION, body)

    def test_the_occupancy_card_shows_used_over_booked_hours(self):
        resp = self._get()
        util = resp.context["occupancy"][0]
        body = resp.content.decode()
        self.assertIn(str(util.used_hours), body)
        self.assertIn(str(util.booked_hours), body)

    def test_the_occupancy_card_states_reclaimable_hours_as_a_sentence(self):
        """The owner's framing: reclaimable capacity, not a scolding statistic."""
        resp = self._get()
        util = resp.context["occupancy"][0]
        body = resp.content.decode()
        self.assertIn("reclaimable", body.lower())
        self.assertIn(str(util.wasted_hours), body)

    def test_attendance_pct_is_retained_alongside_it(self):
        """D-07: Room Occupancy is ADDED, Attendance % is not displaced."""
        body = self._get().content.decode()
        self.assertIn("Attendance %", body)

    def test_in_flight_sessions_are_named_not_silently_zeroed(self):
        """D-09: a NULL must never read as a silent zero to a user."""
        resp = self._get()
        self.assertEqual(resp.context["occupancy"][0].in_flight, 1)
        self.assertIn("still running", resp.content.decode())


class DashboardCardIsolationTests(IfoDashboardTestCase):
    """D-05: three independent error owners in one row; none can 500 the page."""

    def test_occupancy_failure_leaves_the_other_four_cards_rendered(self):
        with patch("web.ifo.room_utilization", side_effect=BOOM):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("Couldn't load this section", body)
        for card in ("faculty", "sessions", "absences", "attendance"):
            self.assertIn(f'data-kpi-card="{card}"', body)
        self.assertNotIn('data-kpi-card="occupancy"', body)
        # And the raw exception text never reaches the page.
        self.assertNotIn("aggregate exploded", body)

    def test_faculty_attendance_failure_does_not_500_via_paginate(self):
        """Regression: paginate(request, rows[0]) passed None to Paginator.

        safe_card returns (None, message) when faculty_attendance raises, so the
        old unguarded call reached Paginator(None, ...) and the page 500'd -- an
        aggregate failure defeating the very isolation safe_card exists to
        provide. Reverting the `or []` guard in web/ifo.py turns this red.
        """
        with patch("web.ifo.faculty_attendance", side_effect=BOOM):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Couldn't load this section", resp.content.decode())

    def test_dept_summary_failure_leaves_the_occupancy_card_standing(self):
        """The occupancy card must NOT be nested inside the summary guard.

        The easy wrong path is to drop the new card into the existing
        `{% else %}` branch, which is invisible on a healthy page but makes a
        dept_summary failure delete the occupancy card too. Asserting the unit
        caption STRING (not merely a 200) is what catches that.
        """
        with patch("web.ifo.dept_summary", side_effect=BOOM):
            resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(SESSION_HOURS_CAPTION, body)
        self.assertIn('data-kpi-card="occupancy"', body)
        # And the four summary cells really did degrade, so this cannot pass by
        # the summary guard having been dropped altogether.
        self.assertIn("Couldn't load this section", body)
        self.assertNotIn('data-kpi-card="faculty"', body)


class DashboardRangeTests(IfoDashboardTestCase):
    """One window, shared by every card, degrading rather than raising."""

    def test_an_unparseable_from_degrades_to_the_current_week_with_a_note(self):
        resp = self.client.get(self.url, {"from": "not-a-date"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["range_note"])

    def test_occupancy_is_computed_over_the_same_window_the_page_reports(self):
        with patch("web.ifo.room_utilization") as mock_util:
            mock_util.return_value = None
            resp = self._get()
        kwargs = mock_util.call_args.kwargs
        self.assertEqual(kwargs["start"], resp.context["date_from"])
        self.assertEqual(kwargs["end"], resp.context["date_to"])
        self.assertIn("as_of", kwargs)
        self.assertIn("term", kwargs)

    def test_a_narrower_range_yields_a_smaller_occupancy_figure(self):
        week = self._get().context["occupancy"][0]
        one_day = self._get(**{
            "from": self.fx.mon.isoformat(), "to": self.fx.mon.isoformat(),
        }).context["occupancy"][0]
        self.assertLess(one_day.booked_hours, week.booked_hours)
        self.assertLess(one_day.available_hours, week.available_hours)

    def test_the_active_term_reaches_the_aggregate_so_the_ladder_is_derived(self):
        util = self._get().context["occupancy"][0]
        self.assertEqual(util.blocks_per_day, len(self.fx.blocks))
        self.assertEqual(util.physical_rooms, len(self.fx.rooms))


class DashboardAuthTests(IfoDashboardTestCase):
    """The new card did not widen access; @ifo_required is still applied."""

    def test_a_faculty_user_cannot_reach_the_dashboard(self):
        self.client.force_login(self.fx.faculty)
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_an_anonymous_user_cannot_reach_the_dashboard(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

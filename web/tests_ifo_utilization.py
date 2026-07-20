"""IFO-09: the Room Occupancy card on /ifo/dashboard, and the T2 utilization page.

The SRS names Room Occupancy in SESSION-HOURS as a dashboard card. Phase 6 built
Attendance % into that slot instead and no room-aware aggregate existed at all.
Phase 06.1 plan 01 built the aggregate; this module holds the tests that prove it
reached the screen and that the row degrades instead of 500ing.

Classes:
  DashboardOccupancyCardTests  -- the closure: five cards, session-hours, context.
  DashboardCardIsolationTests  -- D-05: three INDEPENDENT error owners, one row.
  DashboardRangeTests          -- one window, shared by every card.
  DashboardAuthTests           -- the new card did not widen access.

  UtilizationPageTests         -- T2: four sections on /ifo/utilization.
  UtilizationIsolationTests    -- D-05: FOUR independent error owners, one page.
  UtilizationNavTests          -- reachable from the console nav and the card.
  UtilizationPagingTests       -- the room table pages and keeps the range.
  UtilizationAccessTests       -- the new route did not widen access.

Django TestCase, never pytest. ASCII-only.
"""
import csv
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from campus.models import Room
from scheduling.reporting import RoomUtilization
from scheduling.test_support import (
    RUTIL_WEEK_END,
    RUTIL_WEEK_START,
    make_room_utilization_fixture,
)
from web.ifo import UTILIZATION_CSV_HEADER

# A stable marker every KPI cell carries, so the card count is asserted against
# markup that a whitespace or class-order change cannot break.
CARD_MARKER = 'data-kpi-card="'

# The occupancy card's unit caption. IFO-09 is not closed unless a stakeholder can
# read the unit off the screen, so the string is asserted, not the mere 200.
SESSION_HOURS_CAPTION = "session-hours used of"

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


# ===========================================================================
# IFO-09 tier T2 -- /ifo/utilization
# ===========================================================================

# Stable per-section markers, the same idea as data-kpi-card: the section count
# and the isolation behaviour are asserted against markup that a whitespace or
# class-order change cannot break. Each marker sits on the card OUTSIDE that
# section's error guard, so a failing section still identifies itself.
SECTIONS = ("grid", "rollup", "rooms", "blocks")

ERROR_TEXT = "Couldn't load this section"


class UtilizationPageTestCase(TestCase):
    """Shared setup: an IFO admin, the room fixture, and the utilization URL."""

    def setUp(self):
        self.fx = make_room_utilization_fixture("ifoutz")
        self.ifo = get_user_model().objects.create(
            username="ifoutz_admin", email="ifoutz_admin@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)
        self.url = reverse("ifo_utilization")

    def _get(self, **params):
        params.setdefault("from", RUTIL_WEEK_START.isoformat())
        params.setdefault("to", RUTIL_WEEK_END.isoformat())
        return self.client.get(self.url, params)


class UtilizationPageTests(UtilizationPageTestCase):
    """T2 reached the screen: four sections, a real grid, real numbers."""

    def test_the_page_renders_for_an_ifo_user(self):
        self.assertEqual(self._get().status_code, 200)

    def test_the_context_carries_four_independent_two_tuples(self):
        ctx = self._get().context
        for key in ("grid", "rollup", "breakdown", "saturation"):
            self.assertEqual(len(ctx[key]), 2, key)
            self.assertIsNone(ctx[key][1], key)
            self.assertIsNotNone(ctx[key][0], key)

    def test_all_four_sections_are_present(self):
        body = self._get().content.decode()
        for section in SECTIONS:
            self.assertIn(f'data-util-section="{section}"', body)

    def test_the_grid_row_count_matches_the_derived_ladder(self):
        grid = self._get().context["grid"][0]
        self.assertEqual(len(grid), len(self.fx.blocks))

    def test_every_grid_cell_states_a_number_so_colour_is_never_alone(self):
        """The AA rule: a reader who cannot see the shades still gets the answer."""
        grid = self._get().context["grid"][0]
        body = self._get().content.decode()
        for row in grid:
            for cell in row.cells:
                if cell.timetabled:
                    self.assertIsNotNone(cell.step)
                else:
                    # No capacity is not 0% -- it renders as the free-cell idiom.
                    self.assertIsNone(cell.step)
        self.assertIn("not timetabled", body)
        self.assertIn("%</span>", body)

    def test_the_heat_step_is_relative_to_the_busiest_cell_in_the_range(self):
        """No absolute good/bad band: nothing in this phase sets a target."""
        grid = self._get().context["grid"][0]
        cells = [c for row in grid for c in row.cells if c.timetabled]
        used = [c for c in cells if c.utilization_pct]
        top = max(c.utilization_pct for c in used)
        self.assertEqual(
            max(c.step for c in used), 4,
            "the busiest cell must reach the top of the ramp whatever its rate")
        self.assertTrue(all(c.step >= 1 for c in used))
        self.assertTrue(
            all(c.step == 0 for c in cells if not c.utilization_pct))
        # And the top of the ramp really is the busiest cell, not a fixed 100%.
        self.assertLess(top, 100)

    def test_the_room_table_carries_every_physical_room_including_unused(self):
        rows = self._get().context["breakdown"][0]
        self.assertEqual(len(rows), len(self.fx.rooms))
        self.assertEqual(rows[0].utilization_pct, 0)

    def test_the_rollup_reads_as_buildings_with_their_floors(self):
        rows = self._get().context["rollup"][0]
        self.assertEqual(
            len([r for r in rows if r.level == "building"]),
            len(self.fx.buildings))
        self.assertTrue(any(r.level == "floor" for r in rows))

    def test_saturated_blocks_are_ranked_descending_with_a_named_peak_day(self):
        rows = self._get().context["saturation"][0]
        pcts = [b.utilization_pct for b in rows]
        self.assertEqual(pcts, sorted(pcts, reverse=True))
        self.assertTrue(any(b.peak_day_label for b in rows))

    def test_wasted_hours_read_as_reclaimable_capacity_not_as_a_scolding(self):
        body = self._get().content.decode()
        self.assertIn("reclaimable as bookable slots", body)
        self.assertIn("Reclaimable h", body)

    def test_the_navy_faculty_vocabulary_has_not_leaked_onto_an_ifo_surface(self):
        """.ft-* is Faculty and Guard only; this page is Franken uk-*."""
        body = self._get().content.decode()
        self.assertNotIn('class="ft-', body)
        self.assertNotIn(" ft-", body)


class UtilizationIsolationTests(UtilizationPageTestCase):
    """D-05: four INDEPENDENT failure domains; none can 500 or blank another."""

    def _assert_isolated(self, target, still_visible):
        # assertLogs both asserts safe_card really logged server-side AND keeps
        # the deliberate traceback out of the runner's output.
        with self.assertLogs("scheduling.reporting", level="ERROR"):
            with patch(f"web.ifo.{target}", side_effect=BOOM):
                resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(ERROR_TEXT, body)
        # The raw exception text never reaches the page (info disclosure).
        self.assertNotIn("aggregate exploded", body)
        for section in SECTIONS:
            self.assertIn(f'data-util-section="{section}"', body)
        for marker in still_visible:
            self.assertIn(marker, body)
        return body

    def test_a_grid_failure_leaves_the_three_tables_standing(self):
        self._assert_isolated(
            "room_heat_grid", ["Busiest day", "Reclaimable h", "Seats"])

    def test_a_rollup_failure_leaves_the_grid_standing(self):
        self._assert_isolated("building_floor_rollup", ["not timetabled", "Seats"])

    def test_a_breakdown_failure_does_not_500_via_paginate(self):
        """The plan-03 bug, on a new page: Paginator(None) dies on len().

        Removing the `or []` guard in web.ifo.utilization turns this red, which
        is the point -- an aggregate failure must never defeat safe_card.
        """
        self._assert_isolated("room_breakdown", ["not timetabled", "Busiest day"])

    def test_a_saturation_failure_leaves_the_grid_and_rooms_standing(self):
        self._assert_isolated("block_saturation", ["not timetabled", "Seats"])


class UtilizationNavTests(UtilizationPageTestCase):
    """Reachable two ways, and highlighted on exactly one page."""

    def test_the_console_nav_carries_a_utilization_link(self):
        self.assertIn('href="/ifo/utilization"', self._get().content.decode())

    def test_the_link_is_active_here_and_not_on_the_dashboard(self):
        here = self._get().content.decode()
        self.assertIn(
            '<a href="/ifo/utilization" class="cns__link is-active"', here)
        self.assertIn('aria-current="page"', here)
        dash = self.client.get(reverse("ifo_dashboard")).content.decode()
        self.assertIn('href="/ifo/utilization"', dash)
        self.assertNotIn(
            '<a href="/ifo/utilization" class="cns__link is-active"', dash)

    def test_the_dashboard_occupancy_card_links_here_with_the_range(self):
        dash = self.client.get(
            reverse("ifo_dashboard"),
            {"from": RUTIL_WEEK_START.isoformat(),
             "to": RUTIL_WEEK_END.isoformat()},
        ).content.decode()
        # A literal & in template text, matching the scorecard link two rows
        # below it -- the local convention, not an accident.
        self.assertIn(
            f"/ifo/utilization?from={RUTIL_WEEK_START.isoformat()}"
            f"&to={RUTIL_WEEK_END.isoformat()}", dash)

    def test_the_range_is_applied_to_every_section_not_only_the_first(self):
        resp = self._get(**{
            "from": self.fx.mon.isoformat(), "to": self.fx.mon.isoformat()})
        wide = self._get()
        self.assertLess(
            resp.context["breakdown"][0][0].available_hours,
            wide.context["breakdown"][0][0].available_hours)
        self.assertLess(
            sum(b.available_hours for b in resp.context["saturation"][0]),
            sum(b.available_hours for b in wide.context["saturation"][0]))


class UtilizationPagingTests(UtilizationPageTestCase):
    """The room table is the largest list on the page, so it is paged."""

    def test_a_page_beyond_the_end_clamps_rather_than_raising(self):
        resp = self._get(page=9999)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("page", resp.context)

    def test_a_page_link_preserves_the_active_range(self):
        resp = self._get(page=1)
        querystring = resp.context["querystring"]
        self.assertIn(f"from={RUTIL_WEEK_START.isoformat()}", querystring)
        self.assertIn(f"to={RUTIL_WEEK_END.isoformat()}", querystring)

    def test_an_unparseable_range_degrades_to_the_current_week_with_a_note(self):
        resp = self.client.get(self.url, {"from": "notadate"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["range_note"])


class UtilizationAccessTests(UtilizationPageTestCase):
    """T-06.1-13: the new route added no new auth path."""

    def test_a_faculty_user_cannot_reach_the_page(self):
        self.client.force_login(self.fx.faculty)
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

    def test_an_anonymous_user_cannot_reach_the_page(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url).status_code, 200)


# ===========================================================================
# IFO-09 / 06.1-07 (D-06) -- the ghost-room section on /ifo/utilization
# ===========================================================================


class GhostRoomSectionTests(UtilizationPageTestCase):
    """D-05: the booked-but-never-used section reaches the page, scoped and named."""

    def test_the_page_carries_a_ghost_room_section(self):
        body = self._get().content.decode()
        self.assertIn('data-util-section="ghosts"', body)
        self.assertIn("Booked but never used", body)

    def test_the_context_carries_a_ghosts_two_tuple(self):
        ghosts = self._get().context["ghosts"]
        self.assertEqual(len(ghosts), 2)
        self.assertIsNone(ghosts[1])
        self.assertIsNotNone(ghosts[0])

    def test_a_booked_never_used_room_is_flagged_and_a_used_room_is_not(self):
        ids = {r.room_id for r in self._get().context["ghosts"][0]}
        # s_absent booked its window and recorded zero occupancy: a ghost.
        self.assertIn(self.fx.s_absent.room_id, ids)
        # s_full recorded a full session: never a ghost.
        self.assertNotIn(self.fx.s_full.room_id, ids)

    def test_the_ghost_list_scopes_to_the_applied_range(self):
        with patch("web.ifo.ghost_rooms") as mock_ghosts:
            mock_ghosts.return_value = []
            resp = self._get()
        kwargs = mock_ghosts.call_args.kwargs
        self.assertEqual(kwargs["start"], resp.context["date_from"])
        self.assertEqual(kwargs["end"], resp.context["date_to"])
        self.assertIn("as_of", kwargs)
        self.assertIn("term", kwargs)


class GhostCardIsolationTests(UtilizationPageTestCase):
    """T-11-13 / D-05: a raising ghost aggregate errors in its OWN card only."""

    def test_ghost_card_isolation(self):
        with self.assertLogs("scheduling.reporting", level="ERROR"):
            with patch("web.ifo.ghost_rooms", side_effect=BOOM):
                resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The ghost card renders its error card ...
        self.assertIn('data-util-section="ghosts"', body)
        self.assertIn(ERROR_TEXT, body)
        # ... the raw exception text never reaches the page (info disclosure) ...
        self.assertNotIn("aggregate exploded", body)
        # ... and the four original sections still stand.
        self.assertIn("not timetabled", body)
        self.assertIn("Seats", body)
        self.assertIn("Busiest day", body)


# ===========================================================================
# IFO-09 / 06.1-07 (D-06) -- the per-room utilization CSV export
# ===========================================================================


class UtilizationCsvTestCase(TestCase):
    """Shared setup: an IFO admin, the room fixture, and the CSV export URL."""

    def setUp(self):
        self.fx = make_room_utilization_fixture("ifocsv")
        self.ifo = get_user_model().objects.create(
            username="ifocsv_admin", email="ifocsv_admin@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)
        self.url = reverse("ifo_utilization_csv")

    def _csv(self, **params):
        params.setdefault("from", RUTIL_WEEK_START.isoformat())
        params.setdefault("to", RUTIL_WEEK_END.isoformat())
        return self.client.get(self.url, params)

    def _rows(self, resp):
        return list(csv.reader(io.StringIO(resp.content.decode())))


class UtilizationCsvTests(UtilizationCsvTestCase):
    """D-06: one row per physical room, the on-screen columns, a bounded export."""

    def test_utilization_csv_row_per_physical_room(self):
        resp = self._csv()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        rows = self._rows(resp)
        header, data = rows[0], rows[1:]
        self.assertEqual(header, UTILIZATION_CSV_HEADER)
        # Exactly one data row per physical room -- the virtual room is excluded,
        # matching room_breakdown (the CSV cannot diverge from the on-page table).
        self.assertEqual(len(data), len(self.fx.rooms))
        codes = {row[0] for row in data}
        self.assertNotIn(self.fx.vroom.code, codes)

    def test_the_csv_header_is_a_distinct_third_contract(self):
        """Pitfall 5: not the weekly report's nor the HR payroll export's header."""
        from scheduling.report_render import HEADER as REPORT_HEADER
        from web.hr import CSV_HEADER as HR_HEADER
        self.assertNotEqual(UTILIZATION_CSV_HEADER, REPORT_HEADER)
        self.assertNotEqual(UTILIZATION_CSV_HEADER, HR_HEADER)

    def test_utilization_csv_formula_neutralized(self):
        """T-11-10: a formula-triggering room name cannot become a live formula."""
        Room.objects.create(
            floor=self.fx.floors[0], code="IFOCSV-INJ",
            name="=cmd|calc", capacity=10,
            qr_token="ifocsv-inj-qr", manual_code="INJ001")
        cells = [c for row in self._rows(self._csv()) for c in row]
        injected = next(c for c in cells if "cmd|calc" in c)
        # csv_safe prefixed a literal apostrophe, so the cell is inert text.
        self.assertTrue(injected.startswith("'="))

    def test_utilization_csv_scopes_to_the_applied_range(self):
        with patch("web.ifo.room_breakdown") as mock_bd:
            mock_bd.return_value = []
            self._csv()
        kwargs = mock_bd.call_args.kwargs
        self.assertEqual(kwargs["start"], RUTIL_WEEK_START)
        self.assertEqual(kwargs["end"], RUTIL_WEEK_END)
        self.assertIn("as_of", kwargs)
        self.assertIn("term", kwargs)

    def test_the_filename_is_server_built_not_request_derived(self):
        """T-11-11: no path/header injection -- the name is built from the range."""
        resp = self._csv()
        self.assertEqual(
            resp["Content-Disposition"],
            f'attachment; filename="utilization-{RUTIL_WEEK_START}.csv"')

    def test_a_narrower_range_is_honoured_by_the_export(self):
        wide = len(self._rows(self._csv())) - 1
        # A physical room count is range-independent, but every row is still
        # produced for the one-day window (the export never truncates rooms).
        narrow = self._csv(
            **{"from": self.fx.mon.isoformat(), "to": self.fx.mon.isoformat()})
        self.assertEqual(len(self._rows(narrow)) - 1, wide)


class UtilizationCsvAccessTests(UtilizationCsvTestCase):
    """T-11-12: the export is IFO-only and GET-only; no new auth path opened."""

    def test_utilization_csv_gate(self):
        """A non-IFO (faculty) user is refused with 403."""
        self.client.force_login(self.fx.faculty)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_utilization_csv_post_405(self):
        """A POST to the GET-only export is refused with 405."""
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 405)

    def test_an_anonymous_user_is_refused(self):
        self.client.logout()
        self.assertNotEqual(self.client.get(self.url).status_code, 200)

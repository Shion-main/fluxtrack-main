"""Unit tests for the room-utilization aggregates (IFO-09, tier T1).

A NEW sibling of tests_reporting.py, matching this app's existing split of
reporting tests by concern (tests_reporting.py, tests_report_render.py,
tests_room_master.py). Room utilization is a distinct aggregate family.

DB-FREE (SimpleTestCase) classes, pinning pure arithmetic:
  HoursPctRoundingTests   -- zero-denominator + ROUND_HALF_UP contract of the rate.
  WeekdayMappingTests     -- "DayOfWeek needs no translation table" (D-06/D-10).
  BlockDurationTests      -- the span rule the derived ladder is built from.
  SessionContributionTests-- THE definition of used-hours every plan consumes.
  RoomCardIsolationTests  -- safe_card degrades a raising card to a generic message.

DB-BACKED (TestCase) classes, over make_room_utilization_fixture:
  DenominatorTests        -- D-10 cell sum, recomputed independently (plan 01).
  LadderDerivationTests   -- the ladder and cell set come from DATA, not literals.
  UsedHoursPolicyTests    -- one test per row of the D-03/D-09 metric contract.
  VirtualRoomExclusionTests -- D-04/D-08: V-rooms are invisible to every aggregate.
  ScopeTests              -- ARCHIVED schedules and the as_of clamp.

Django test runner (not pytest); reference module constants (SessionStatus,
DayOfWeek, ScheduleStatus, HELD_STATUSES), never a bare status string. ASCII-only.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from campus.models import Building, Floor, Room
from accounts.models import Role
from scheduling.models import (
    AcademicTerm,
    DayOfWeek,
    Schedule,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from scheduling.reporting import (
    HELD_STATUSES,
    _block_duration_seconds,
    _hours,
    _hours_pct,
    _physical_rooms,
    _session_contribution,
    _span_seconds,
    campus_block_ladder,
    room_utilization,
    safe_card,
    timetabled_cells,
)
from scheduling.test_support import make_room_utilization_fixture

UTC = datetime.timezone.utc

# A known Monday, used to derive every weekday by offset rather than by writing
# seven hardcoded per-day date literals.
KNOWN_MONDAY = datetime.date(2026, 7, 6)


def _at(hour, minute=0, day=6):
    """An aware UTC instant on a fixed July 2026 day (pure arithmetic input)."""
    return datetime.datetime(2026, 7, day, hour, minute, tzinfo=UTC)


class HoursPctRoundingTests(SimpleTestCase):
    """_hours_pct mirrors _pct's contract: guarded denominator, ROUND_HALF_UP.

    LO-02 applies verbatim -- an exact .5 tie must round up the conventionally
    expected way, not to even, so a stakeholder recomputing the rate by hand never
    sees an off-by-one.
    """

    def test_zero_denominator_is_zero_not_raise(self):
        self.assertEqual(_hours_pct(0, 0), 0)
        self.assertEqual(_hours_pct(3600, 0), 0)

    def test_negative_denominator_is_zero(self):
        self.assertEqual(_hours_pct(3600, -3600), 0)

    def test_exact_half_rounds_up_not_to_even(self):
        # 100 * 1 / 8 = 12.5 -> conventional 13 (Python round(12.5) == 12).
        self.assertEqual(_hours_pct(1, 8), 13)

    def test_exact_ratio_is_exact_integer(self):
        self.assertEqual(_hours_pct(1, 2), 50)
        self.assertEqual(_hours_pct(3600, 3600), 100)
        self.assertEqual(_hours_pct(0, 3600), 0)

    def test_hours_conversion_quantizes_to_one_decimal(self):
        self.assertEqual(str(_hours(3600)), "1.0")
        self.assertEqual(str(_hours(5400)), "1.5")
        self.assertEqual(str(_hours(0)), "0.0")


class WeekdayMappingTests(SimpleTestCase):
    """D-06: DayOfWeek is MON=0..SUN=6, byte-identical to date.weekday().

    timetabled_cells carries raw day_of_week values in TimetabledCell.day and
    room_utilization compares them straight against date.weekday() with no mapping.
    That claim is enforced here rather than trusted to a comment: if DayOfWeek is
    ever reordered, the denominator would silently count the wrong cells and this
    test is what catches it.
    """

    def test_every_member_matches_python_weekday(self):
        for offset, member in enumerate(DayOfWeek):
            day = KNOWN_MONDAY + datetime.timedelta(days=offset)
            self.assertEqual(member.value, day.weekday(), msg=f"{member.name}")

    def test_saturday_and_sunday_are_five_and_six(self):
        self.assertEqual(DayOfWeek.SAT.value, (KNOWN_MONDAY + datetime.timedelta(days=5)).weekday())
        self.assertEqual(DayOfWeek.SUN.value, (KNOWN_MONDAY + datetime.timedelta(days=6)).weekday())


class BlockDurationTests(SimpleTestCase):
    """The span rule the derived ladder is built from.

    A block's duration is the MODAL span of the schedules starting at it, so one
    mis-imported outlier cannot stretch or shrink a rung; a frequency tie resolves
    to the LONGEST span, because an understated block understates available_hours
    and would silently INFLATE the utilization rate.
    """

    def test_span_seconds_is_plain_wall_clock_arithmetic(self):
        self.assertEqual(
            _span_seconds(datetime.time(7, 0), datetime.time(8, 15)), 75 * 60)

    def test_span_seconds_floors_a_backwards_span_at_zero(self):
        # A campus block never crosses midnight, so a backwards span is bad data
        # and must not SUBTRACT capacity from the denominator.
        self.assertEqual(
            _span_seconds(datetime.time(8, 15), datetime.time(7, 0)), 0)

    def test_single_schedule_block(self):
        spans = [(datetime.time(9, 30), datetime.time(10, 45))]
        self.assertEqual(_block_duration_seconds(spans), 75 * 60)

    def test_modal_span_wins_over_an_outlier(self):
        spans = [
            (datetime.time(7, 0), datetime.time(8, 15)),
            (datetime.time(7, 0), datetime.time(8, 15)),
            (datetime.time(7, 0), datetime.time(10, 0)),  # outlier
        ]
        self.assertEqual(_block_duration_seconds(spans), 75 * 60)

    def test_frequency_tie_resolves_to_the_longer_span(self):
        spans = [
            (datetime.time(7, 0), datetime.time(8, 15)),   # 75 min
            (datetime.time(7, 0), datetime.time(9, 30)),   # 150 min
        ]
        self.assertEqual(_block_duration_seconds(spans), 150 * 60)

    def test_no_spans_is_zero_not_raise(self):
        self.assertEqual(_block_duration_seconds([]), 0)


class SessionContributionTests(SimpleTestCase):
    """D-03/D-09: THE single definition of booked vs used, as pure arithmetic.

    Every downstream plan in this phase consumes _session_contribution rather than
    re-deriving these rules, so the rules are pinned here where no fixture, term or
    database can obscure them.
    """

    SCHED_START = _at(7, 0)
    SCHED_END = _at(8, 15)

    def _contrib(self, status, actual_start=None, actual_end=None):
        return _session_contribution(
            status, self.SCHED_START, self.SCHED_END, actual_start, actual_end)

    def test_absent_is_booked_with_zero_used(self):
        # This zero IS the waste signal (D-03) -- it must never become "booked".
        booked, used, running = self._contrib(SessionStatus.ABSENT)
        self.assertEqual(booked, 75 * 60)
        self.assertEqual(used, 0)
        self.assertFalse(running)

    def test_absent_with_stray_timestamps_still_contributes_zero_used(self):
        booked, used, _ = self._contrib(
            SessionStatus.ABSENT, _at(7, 0), _at(8, 15))
        self.assertEqual(booked, 75 * 60)
        self.assertEqual(used, 0)

    def test_full_held_session_uses_its_whole_window(self):
        booked, used, running = self._contrib(
            SessionStatus.COMPLETED, _at(7, 0), _at(8, 15))
        self.assertEqual((booked, used, running), (75 * 60, 75 * 60, False))

    def test_early_release_contributes_only_the_actual_span(self):
        # D-03's early-end case. Derived from the TIMESTAMPS, never from the
        # ended_early flag -- seed_term shaves minutes off actual_end without ever
        # setting that flag, so a flag-keyed metric reports zero reclaimable hours
        # against the only dataset the number can be checked against.
        booked, used, _ = self._contrib(
            SessionStatus.COMPLETED, _at(7, 0), _at(8, 3))
        self.assertEqual(booked, 75 * 60)
        self.assertEqual(used, 63 * 60)
        self.assertEqual(booked - used, 12 * 60)

    def test_late_start_is_reclaimable_time(self):
        booked, used, _ = self._contrib(
            SessionStatus.COMPLETED, _at(7, 10), _at(8, 15))
        self.assertEqual(used, 65 * 60)

    def test_early_arrival_is_clamped_to_the_scheduled_window(self):
        # seed_term stamps actual_start up to 4 minutes BEFORE scheduled_start.
        # Unclamped this would report more used hours than booked and push the
        # rate past 100%, which is meaningless for a capacity metric.
        booked, used, _ = self._contrib(
            SessionStatus.COMPLETED, _at(6, 56), _at(8, 15))
        self.assertEqual(used, booked)

    def test_overrun_is_clamped_to_the_scheduled_window(self):
        booked, used, _ = self._contrib(
            SessionStatus.COMPLETED, _at(7, 0), _at(8, 45))
        self.assertEqual(used, booked)

    def test_used_never_exceeds_booked(self):
        for a_start, a_end in [
            (_at(6, 0), _at(9, 0)), (_at(6, 56), _at(8, 45)),
            (_at(7, 0), _at(8, 15)), (_at(7, 30), _at(7, 45)),
        ]:
            booked, used, _ = self._contrib(SessionStatus.COMPLETED, a_start, a_end)
            self.assertLessEqual(used, booked)

    def test_in_flight_active_session_is_excluded_from_both_sides(self):
        # D-09: a running class has no final used-hours. Counting its booked hours
        # against an incomplete numerator would fabricate waste that has not
        # happened. It is reported, not silently zeroed.
        booked, used, running = self._contrib(SessionStatus.ACTIVE, _at(7, 0), None)
        self.assertEqual((booked, used), (0, 0))
        self.assertTrue(running)

    def test_finished_session_with_no_end_stamp_is_booked_with_zero_used(self):
        # Not in flight (not ACTIVE), and a missing end stamp is not evidence of
        # use -- but the booking still happened, so it stays in the denominator of
        # the booking rate.
        booked, used, running = self._contrib(
            SessionStatus.COMPLETED, _at(7, 0), None)
        self.assertEqual((booked, used, running), (75 * 60, 0, False))

    def test_never_checked_in_scheduled_session_contributes_zero_used(self):
        booked, used, running = self._contrib(SessionStatus.SCHEDULED)
        self.assertEqual((booked, used, running), (75 * 60, 0, False))

    def test_actual_window_entirely_outside_the_scheduled_window_is_zero(self):
        booked, used, _ = self._contrib(
            SessionStatus.COMPLETED, _at(9, 0), _at(10, 0))
        self.assertEqual(used, 0)
        self.assertEqual(booked, 75 * 60)


class DenominatorTests(TestCase):
    """D-10: available_hours is a SUM over timetabled (day, block) cells.

    The denominator is recomputed here INDEPENDENTLY of reporting.py -- straight
    from the seeded Schedule rows, in plain Python, without calling any helper the
    implementation uses to build it. That is the point of the class: if
    room_utilization ever silently drifts back toward a days x blocks
    cross-product, or picks up a threshold or a hardcoded day, the two computations
    diverge and this fails. Asserting against a figure produced by the same code
    path would prove only that the code equals itself.

    The fixture deliberately reproduces the shape that forced D-10: a dense week of
    full-ladder days plus ONE outlier day carrying a single class in a single block.
    Under the old cross-product that outlier bought a whole day of capacity across
    every rung; under the cell sum it buys exactly one cell.
    """

    # Three ladder rungs, 75 minutes each, tiling exactly (07:00 / 08:15 / 09:30).
    # Deliberately NOT the live term's eleven -- the count must never be assumed.
    RUNGS = [
        (datetime.time(7, 0), datetime.time(8, 15)),
        (datetime.time(8, 15), datetime.time(9, 30)),
        (datetime.time(9, 30), datetime.time(10, 45)),
    ]
    DENSE_DAYS = [DayOfWeek.MON, DayOfWeek.TUE]
    OUTLIER_DAY = DayOfWeek.SUN

    # A full Mon-Sun calendar week, derived by offset from the known Monday.
    WEEK_START = KNOWN_MONDAY
    WEEK_END = KNOWN_MONDAY + datetime.timedelta(days=6)

    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="cell Term", start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 12, 31), is_active=True,
        )
        building = Building.objects.create(name="Cell Hall", code="CELL-BLD")
        floor = Floor.objects.create(building=building, number=1)
        self.rooms = [
            Room.objects.create(
                floor=floor, code=f"CELL-R{n}", capacity=40,
                qr_token=f"cell-qr-{n}", manual_code=f"C{n:05d}"[:6],
            )
            for n in range(2)
        ]
        # A virtual room, to prove it stays out of the physical denominator (D-04).
        self.virtual_room = Room.objects.create(
            floor=floor, code="VCELL1", capacity=0,
            qr_token="cell-qr-v", manual_code="CV0001",
        )
        self.faculty = User.objects.create(
            username="cell_fa", email="cell_fa@mcm.edu.ph",
            first_name="Cara", last_name="Cruz",
            role=Role.FACULTY, is_active=True,
        )
        self._seed_schedules()

    def _schedule(self, day, start, end, room):
        return Schedule.objects.create(
            term=self.term, course_code=f"CELL{day}{start.hour}",
            section="A", faculty=self.faculty, room=room,
            day_of_week=day, start_time=start, end_time=end,
            status=ScheduleStatus.ACTIVE,
        )

    def _seed_schedules(self):
        """Dense days fill every rung; the outlier day fills exactly one."""
        for day in self.DENSE_DAYS:
            for start, end in self.RUNGS:
                self._schedule(day, start, end, self.rooms[0])
        outlier_start, outlier_end = self.RUNGS[0]
        self.outlier = self._schedule(
            self.OUTLIER_DAY, outlier_start, outlier_end, self.rooms[1])

    # --- the independent recomputation -------------------------------------

    def _expected_available_seconds(self, start, end, as_of=None):
        """Recompute the denominator from the Schedule rows, not from reporting.py.

        Deliberately naive and self-contained: read every ACTIVE (day, start, end)
        triple, fold it into a {day: {start: duration}} cell map keyed exactly the
        way D-10 defines a cell, then walk the calendar range multiplying each day's
        cell seconds by the physical room count.
        """
        cells = {}
        rows = Schedule.objects.filter(
            term=self.term, status=ScheduleStatus.ACTIVE,
        ).values_list("day_of_week", "start_time", "end_time")
        for day, start_time, end_time in rows:
            span = int((
                datetime.datetime.combine(datetime.date(2000, 1, 1), end_time)
                - datetime.datetime.combine(datetime.date(2000, 1, 1), start_time)
            ).total_seconds())
            # Modal-duration resolution is irrelevant here: this fixture gives every
            # rung one consistent span, so max() and the modal rule agree.
            per_day = cells.setdefault(day, {})
            per_day[start_time] = max(per_day.get(start_time, 0), span)

        rooms = Room.objects.exclude(code__startswith="V").count()
        last_day = min(end, as_of) if as_of is not None else end
        total = 0
        day = start
        while day <= last_day:
            total += sum(cells.get(day.weekday(), {}).values())
            day += datetime.timedelta(days=1)
        return rooms * total

    def _util(self, **kwargs):
        kwargs.setdefault("start", self.WEEK_START)
        kwargs.setdefault("end", self.WEEK_END)
        return room_utilization(term=self.term, **kwargs)

    def test_available_hours_matches_the_independent_cell_sum(self):
        expected = self._expected_available_seconds(self.WEEK_START, self.WEEK_END)
        self.assertEqual(self._util().available_hours, _hours(expected))

    def test_as_of_clamps_both_computations_identically(self):
        as_of = self.WEEK_START + datetime.timedelta(days=1)   # through Tuesday
        expected = self._expected_available_seconds(
            self.WEEK_START, self.WEEK_END, as_of=as_of)
        self.assertEqual(self._util(as_of=as_of).available_hours, _hours(expected))

    def test_outlier_day_contributes_exactly_one_cell_not_a_full_ladder(self):
        """The regression D-10 exists for, in miniature.

        One class on one day must buy ONE cell of capacity, not len(ladder) cells.
        """
        by_day = {}
        for cell in timetabled_cells(self.term):
            by_day.setdefault(cell.day, []).append(cell)
        self.assertEqual(len(by_day[self.OUTLIER_DAY]), 1)
        for day in self.DENSE_DAYS:
            self.assertEqual(len(by_day[day]), len(self.RUNGS))
        # And the ladder itself is still the full campus-wide height, so the
        # outlier day is thinner than the grid rather than thinner than the term.
        self.assertEqual(len(campus_block_ladder(self.term)), len(self.RUNGS))

    def test_cross_product_would_overstate_and_is_not_what_ships(self):
        """Pin the DIFFERENCE, so a silent revert to days x blocks cannot pass."""
        util = self._util()
        cross_product_cells = util.teaching_days * util.blocks_per_day
        self.assertLess(util.timetabled_cells, cross_product_cells)
        # The gap is precisely the outlier day's unscheduled rungs.
        self.assertEqual(
            cross_product_cells - util.timetabled_cells, len(self.RUNGS) - 1)

    def test_timetabled_cells_counts_calendar_occurrences_over_the_range(self):
        util = self._util()
        expected = len(self.DENSE_DAYS) * len(self.RUNGS) + 1
        self.assertEqual(util.timetabled_cells, expected)
        self.assertEqual(util.teaching_days, len(self.DENSE_DAYS) + 1)

    def test_a_two_week_range_doubles_the_cells_and_the_capacity(self):
        one = self._util()
        two = self._util(end=self.WEEK_END + datetime.timedelta(days=7))
        self.assertEqual(two.timetabled_cells, one.timetabled_cells * 2)
        self.assertEqual(two.available_hours, one.available_hours * 2)

    def test_virtual_rooms_stay_out_of_the_physical_denominator(self):
        util = self._util()
        self.assertEqual(util.physical_rooms, len(self.rooms))
        self.assertNotIn(self.virtual_room, list(_physical_rooms()))

    def test_a_term_with_no_active_schedules_is_a_zero_denominator_not_a_crash(self):
        Schedule.objects.filter(term=self.term).update(
            status=ScheduleStatus.ARCHIVED)
        util = self._util()
        self.assertEqual(util.timetabled_cells, 0)
        self.assertEqual(util.teaching_days, 0)
        self.assertEqual(util.available_hours, _hours(0))
        self.assertEqual(util.utilization_pct, 0)

    def test_none_term_yields_an_empty_cell_set(self):
        self.assertEqual(timetabled_cells(None), [])


class RoomFixtureTestCase(TestCase):
    """Shared base: one room-shaped fixture and its documented minute totals.

    The totals below are the fixture's OWN documented contract
    (``make_room_utilization_fixture``'s docstring), written in minutes so a
    reader can add them up by hand. They are asserted, never derived from the code
    under test -- a figure produced by the implementation would only prove the
    implementation equals itself.
    """

    # Per-session (booked, used) minutes, straight off the fixture docstring.
    ROWS = {
        "s_full": (75, 75),
        "s_absent": (75, 0),
        "s_early": (75, 45),
        "s_early_unflagged": (75, 63),
        "s_late": (90, 70),
        "s_overrun": (75, 75),
        "s_noshow_stamped": (90, 0),
        "s_sat": (75, 75),
    }
    BOOKED_M = 630
    USED_M = 403
    ABSENT_M = 75
    UNUSED_HELD_M = 152
    WASTED_M = 227

    PHYSICAL_ROOMS = 8
    LADDER_RUNGS = 3
    CELLS = 7
    TEACHING_DAYS = 3

    def setUp(self):
        self.f = make_room_utilization_fixture()

    def _util(self, **kwargs):
        kwargs.setdefault("start", self.f.week_start)
        kwargs.setdefault("end", self.f.week_end)
        return room_utilization(term=self.f.term, **kwargs)

    def _without(self, session):
        """Delete ONE session (its Schedule stays, so the denominator is fixed)."""
        Session.objects.filter(pk=session.pk).delete()
        return self._util()

    def _hours_m(self, minutes):
        return _hours(minutes * 60)


class LadderDerivationTests(RoomFixtureTestCase):
    """D-06/D-10: the ladder and the cell set are DATA, never literals.

    Every count here is recomputed from the fixture's own querysets. An assertion
    of "11 blocks" or "5 teaching days" would encode today's import and is exactly
    what D-06 forbids.
    """

    def test_ladder_length_equals_the_distinct_active_start_times(self):
        expected = Schedule.objects.filter(
            term=self.f.term, status=ScheduleStatus.ACTIVE,
        ).values_list("start_time", flat=True).distinct().count()
        self.assertEqual(len(campus_block_ladder(self.f.term)), expected)
        # And the fixture's own documented rung count, as a cross-check.
        self.assertEqual(expected, self.LADDER_RUNGS)

    def test_each_rung_carries_the_fixture_blocks_own_duration(self):
        expected = {
            start: _span_seconds(start, end) for start, end in self.f.blocks
        }
        actual = {
            b.start: b.duration_seconds for b in campus_block_ladder(self.f.term)
        }
        self.assertEqual(actual, expected)
        # Two distinct durations, so no single "block length" can be assumed.
        self.assertEqual(len(set(expected.values())), 2)

    def test_saturday_is_picked_up_and_sunday_is_absent_from_the_data(self):
        # teaching_weekdays was removed by D-10; the day set is recovered from the
        # cell set, which is now the unit of capacity.
        days = {c.day for c in timetabled_cells(self.f.term)}
        self.assertIn(DayOfWeek.SAT, days)
        self.assertNotIn(DayOfWeek.SUN, days)
        self.assertEqual(days, {DayOfWeek.MON, DayOfWeek.WED, DayOfWeek.SAT})

    def test_saturday_is_thinner_than_the_grid(self):
        """SAT carries one rung; MON and WED carry all of them (the D-10 shape)."""
        by_day = {}
        for cell in timetabled_cells(self.f.term):
            by_day.setdefault(cell.day, []).append(cell)
        self.assertEqual(len(by_day[DayOfWeek.SAT]), 1)
        self.assertEqual(len(by_day[DayOfWeek.MON]), self.LADDER_RUNGS)
        self.assertEqual(len(by_day[DayOfWeek.WED]), self.LADDER_RUNGS)

    def test_none_term_has_no_ladder(self):
        self.assertIsNone(campus_block_ladder(None))

    def test_a_term_of_only_archived_schedules_has_no_ladder(self):
        Schedule.objects.filter(term=self.f.term).update(
            status=ScheduleStatus.ARCHIVED)
        self.assertIsNone(campus_block_ladder(self.f.term))
        self.assertEqual(timetabled_cells(self.f.term), [])

    def test_the_derived_shape_matches_the_fixtures_documented_totals(self):
        util = self._util()
        self.assertEqual(util.physical_rooms, self.PHYSICAL_ROOMS)
        self.assertEqual(util.blocks_per_day, self.LADDER_RUNGS)
        self.assertEqual(util.timetabled_cells, self.CELLS)
        self.assertEqual(util.teaching_days, self.TEACHING_DAYS)


class UsedHoursPolicyTests(RoomFixtureTestCase):
    """D-03/D-09, one test per row of the metric contract, against real rows.

    Each claim is defended by removing exactly one session and asserting the
    totals move by exactly that row's documented contribution. The Schedule stays
    behind, so the denominator is held constant and only the numerator moves.
    """

    def test_the_fixtures_documented_totals_hold(self):
        util = self._util()
        self.assertEqual(util.booked_hours, self._hours_m(self.BOOKED_M))
        self.assertEqual(util.used_hours, self._hours_m(self.USED_M))
        self.assertEqual(util.absent_hours, self._hours_m(self.ABSENT_M))
        self.assertEqual(util.unused_held_hours, self._hours_m(self.UNUSED_HELD_M))
        self.assertEqual(util.wasted_hours, self._hours_m(self.WASTED_M))

    def test_absent_adds_booked_hours_and_zero_used_hours(self):
        booked_m, used_m = self.ROWS["s_absent"]
        self.assertEqual(used_m, 0)
        after = self._without(self.f.s_absent)
        self.assertEqual(after.booked_hours, self._hours_m(self.BOOKED_M - booked_m))
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M))
        self.assertEqual(after.absent_hours, self._hours_m(0))
        self.assertEqual(after.absent_sessions, 0)

    def test_early_end_contributes_its_actual_span_and_the_rest_is_wasted(self):
        booked_m, used_m = self.ROWS["s_early"]
        after = self._without(self.f.s_early)
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M - used_m))
        # The 30 minutes it held but did not use leave unused_held with it.
        self.assertEqual(
            after.unused_held_hours,
            self._hours_m(self.UNUSED_HELD_M - (booked_m - used_m)))

    def test_unflagged_early_end_still_counts_as_wasted(self):
        """The binding guard: waste is derived from TIMESTAMPS, not the flag.

        ``s_early_unflagged`` ends 12 minutes early with ``ended_early`` False and
        ``room_released_at`` NULL -- the shape ``seed_term`` really produces. It is
        the ONLY fixture row where the flag DISAGREES with the timestamps, so it is
        the only row that fails if the waste metric is keyed off the boolean; every
        other early-end row has the flag set to match and would pass either way.

        Wave 1 confirmed the same disagreement on live data: ``early_end_sessions``
        read 0 for the week while ``unused_held_hours`` read 195.9. Do not delete
        this test as redundant with the aggregate assertions below -- they stay
        non-zero on a flag-keyed implementation because of ``s_early`` and
        ``s_absent``, and only this row exposes it.
        """
        row = Session.objects.get(pk=self.f.s_early_unflagged.pk)
        self.assertFalse(row.ended_early)
        self.assertIsNone(row.room_released_at)
        self.assertEqual(
            (row.scheduled_end - row.actual_end), datetime.timedelta(minutes=12))

        booked_m, used_m = self.ROWS["s_early_unflagged"]
        after = self._without(self.f.s_early_unflagged)
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M - used_m))
        self.assertEqual(
            after.unused_held_hours, self._hours_m(self.UNUSED_HELD_M - 12))
        self.assertEqual(after.wasted_hours, self._hours_m(self.WASTED_M - 12))

    def test_only_one_session_carries_the_ended_early_flag(self):
        """Pins the disagreement itself, so the test above cannot be argued away."""
        util = self._util()
        self.assertEqual(util.early_end_sessions, 1)
        # Yet TWO sessions genuinely ended early, and both of their remainders are
        # in the waste figure. A flag-keyed metric would report half of it.
        self.assertGreaterEqual(util.unused_held_hours, self._hours_m(30 + 12))

    def test_late_start_produces_wasted_hours(self):
        booked_m, used_m = self.ROWS["s_late"]
        after = self._without(self.f.s_late)
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M - used_m))
        self.assertEqual(
            after.unused_held_hours,
            self._hours_m(self.UNUSED_HELD_M - (booked_m - used_m)))

    def test_overrun_used_equals_booked_and_never_more(self):
        booked_m, used_m = self.ROWS["s_overrun"]
        self.assertEqual(booked_m, used_m)
        util = self._util()
        self.assertEqual(util.overrun_sessions, 1)
        self.assertEqual(util.early_arrival_sessions, 1)
        self.assertLessEqual(util.used_hours, util.booked_hours)

    def test_in_flight_is_in_neither_booked_nor_used_and_is_reported(self):
        util = self._util()
        self.assertEqual(util.in_flight, 1)
        after = self._without(self.f.s_inflight)
        self.assertEqual(after.in_flight, 0)
        self.assertEqual(after.booked_hours, self._hours_m(self.BOOKED_M))
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M))

    def test_completed_with_null_end_is_booked_with_zero_used(self):
        booked_m, used_m = self.ROWS["s_noshow_stamped"]
        self.assertEqual(used_m, 0)
        row = Session.objects.get(pk=self.f.s_noshow_stamped.pk)
        self.assertIsNotNone(row.actual_start)
        self.assertIsNone(row.actual_end)
        self.assertIn(row.status, HELD_STATUSES)
        after = self._without(self.f.s_noshow_stamped)
        self.assertEqual(after.booked_hours, self._hours_m(self.BOOKED_M - booked_m))
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M))

    def test_full_session_used_equals_booked(self):
        booked_m, used_m = self.ROWS["s_full"]
        self.assertEqual(booked_m, used_m)
        after = self._without(self.f.s_full)
        self.assertEqual(after.used_hours, self._hours_m(self.USED_M - used_m))
        self.assertEqual(after.booked_hours, self._hours_m(self.BOOKED_M - booked_m))

    def test_wasted_is_absent_plus_unused_held_and_is_not_zero(self):
        util = self._util()
        self.assertEqual(
            util.wasted_hours, util.absent_hours + util.unused_held_hours)
        # A waste metric reading zero on a fixture holding an absence AND two early
        # releases is broken. NOTE: this assertion alone does NOT catch flag-keying
        # -- s_early and s_absent keep it non-zero either way. The binding guard is
        # test_unflagged_early_end_still_counts_as_wasted.
        self.assertGreater(util.wasted_hours, 0)

    def test_used_never_exceeds_booked_which_never_exceeds_available(self):
        util = self._util()
        self.assertLessEqual(util.used_hours, util.booked_hours)
        self.assertLessEqual(util.booked_hours, util.available_hours)


class VirtualRoomExclusionTests(RoomFixtureTestCase):
    """D-04/D-08: a V-prefixed room is invisible to every physical aggregate."""

    def test_the_virtual_session_changes_nothing(self):
        before = self._util()
        after = self._without(self.f.s_virtual)
        self.assertEqual(after.booked_hours, before.booked_hours)
        self.assertEqual(after.used_hours, before.used_hours)
        self.assertEqual(after.physical_rooms, before.physical_rooms)
        self.assertEqual(after.available_hours, before.available_hours)

    def test_physical_rooms_excludes_the_virtual_room(self):
        util = self._util()
        self.assertEqual(util.physical_rooms, len(self.f.rooms))
        self.assertEqual(util.physical_rooms, self.PHYSICAL_ROOMS)
        self.assertNotIn(self.f.vroom, list(_physical_rooms()))
        self.assertTrue(self.f.vroom.is_virtual)

    def test_a_lowercase_v_room_is_excluded_too(self):
        """Room.code carries the DB-wide CI collation, so "v" matches "V" (D-08).

        Pinned by a test rather than assumed: if that collation ever changes, a
        lowercase-v room would silently join the physical denominator and dilute
        the rate with a room that does not exist.
        """
        before = _physical_rooms().count()
        lower = Room.objects.create(
            floor=self.f.vroom.floor, code="vlowercase1", capacity=0,
            qr_token="rutil-qr-lower", manual_code="LOWER1",
        )
        self.assertTrue(lower.is_virtual)
        self.assertEqual(_physical_rooms().count(), before)
        self.assertEqual(self._util().physical_rooms, self.PHYSICAL_ROOMS)


class ScopeTests(RoomFixtureTestCase):
    """What the aggregate is allowed to see: ARCHIVED schedules and as_of."""

    def test_a_session_on_an_archived_schedule_is_invisible(self):
        before = self._util()
        after = self._without(self.f.s_archived)
        self.assertEqual(after.booked_hours, before.booked_hours)
        self.assertEqual(after.used_hours, before.used_hours)
        # It really is a full session that would have moved the totals if visible.
        self.assertEqual(
            self.f.s_archived.schedule.status, ScheduleStatus.ARCHIVED)
        self.assertIsNotNone(self.f.s_archived.actual_end)

    def test_as_of_clamps_a_future_booking_out_of_both_sides(self):
        """A not-yet-happened booking must never be reported as wasted capacity."""
        util = self._util(as_of=self.f.mon)
        # Monday only: s_full, s_absent, s_early, s_early_unflagged, s_late.
        monday_booked = 75 + 75 + 75 + 75 + 90
        monday_used = 75 + 0 + 45 + 63 + 70
        self.assertEqual(util.booked_hours, self._hours_m(monday_booked))
        self.assertEqual(util.used_hours, self._hours_m(monday_used))
        self.assertEqual(util.teaching_days, 1)
        self.assertEqual(util.timetabled_cells, self.LADDER_RUNGS)
        # The denominator is clamped with the numerator, so the rate stays honest.
        self.assertEqual(
            util.available_hours,
            self._hours_m(self.PHYSICAL_ROOMS * (75 + 75 + 90)))

    def test_a_range_carrying_no_timetabled_day_is_zero_not_a_crash(self):
        util = self._util(start=self.f.sun, end=self.f.sun)
        self.assertEqual(util.teaching_days, 0)
        self.assertEqual(util.available_hours, _hours(0))
        self.assertEqual(util.utilization_pct, 0)


class RoomCardIsolationTests(SimpleTestCase):
    """D-05: a raising room aggregate degrades to a message, never a 500.

    Mirrors the CardIsolationTests in tests_reporting.py. The raw exception text
    must never reach the template (information disclosure).
    """

    def test_a_raising_card_returns_none_and_a_generic_message(self):
        def boom():
            raise ValueError("connection string secret-token-abc")

        with self.assertLogs("scheduling.reporting", level="ERROR"):
            value, error = safe_card(boom)
        self.assertIsNone(value)
        self.assertEqual(error, "This section could not be loaded.")
        self.assertNotIn("secret-token-abc", error)
        self.assertNotIn("ValueError", error)

    def test_a_working_card_returns_its_value_and_no_error(self):
        value, error = safe_card(lambda a, b=0: a + b, 1, b=2)
        self.assertEqual(value, 3)
        self.assertIsNone(error)


# ===========================================================================
# SEED SANITY CHECK -- how a human decides the number is believable
# ===========================================================================
#
# NOT a test, and deliberately so. `seed_term` is randomized per run, so any
# assertion against a seeded figure is flaky by construction. What follows is a
# recipe plus the four checks that make its output FALSIFIABLE, which is the
# thing a fixture cannot give you: a utilization number nobody can check against
# a real dataset is worse than no number at all.
#
# Copy-pasteable (Django's runner, MSSQL LocalDB; use the full interpreter path):
#
#   manage.py shell -c "
#   import datetime
#   from scheduling.models import AcademicTerm
#   from scheduling.reporting import room_utilization
#   t = AcademicTerm.objects.filter(is_active=True).first()
#   today = datetime.date.today()
#   start = today - datetime.timedelta(days=today.weekday())
#   end = start + datetime.timedelta(days=6)
#   u = room_utilization(start=start, end=end, term=t, as_of=today)
#   print('term', t, '| week', start, '..', end, '| as_of', today)
#   print('physical_rooms', u.physical_rooms, '| blocks_per_day', u.blocks_per_day,
#         '| teaching_days', u.teaching_days, '| timetabled_cells', u.timetabled_cells)
#   print('available', u.available_hours, '| booked', u.booked_hours,
#         '| used', u.used_hours, '| wasted', u.wasted_hours)
#   print('absent', u.absent_hours, '| unused_held', u.unused_held_hours)
#   print('utilization_pct', u.utilization_pct, '| booking_pct', u.booking_pct,
#         '| in_flight', u.in_flight)
#   "
#
# The week is derived from `today` rather than hardcoded so the recipe keeps
# working; substitute an explicit Monday/Sunday pair to inspect a past week.
#
# --- The four checks -------------------------------------------------------
#
# 1. used_hours <= booked_hours <= available_hours.
#    A violation of the RIGHT-hand inequality means one of: double-booked rooms,
#    sessions sitting outside the derived ladder, or a denominator that lost its
#    room-count factor. A violation of the left-hand one means the clamp in
#    _session_contribution is not being applied.
#
# 2. utilization_pct should land WELL BELOW saturation. `seed_term` runs a
#    60/20/20 modality split and moves every online class into a virtual room, so
#    a large share of physical capacity is genuinely idle. A figure near 100%
#    means virtual rooms or virtual sessions have leaked into the calculation
#    (check `_physical_rooms` / `_exclude_virtual`, D-04/D-08).
#
# 3. wasted_hours must be clearly NON-ZERO. `seed_term` marks roughly 8% of past
#    sessions ABSENT (seed_term.py:358-360) and shaves 5 or 12 minutes off the end
#    of roughly 40% of held ones (seed_term.py:370-371). A zero here means the
#    waste metric is keyed off the `ended_early` flag, which that command NEVER
#    sets. This is the failure mode
#    test_unflagged_early_end_still_counts_as_wasted exists to catch before it
#    reaches the dashboard.
#
# 4. in_flight should be non-zero when `seed_term` was run RECENTLY, because it
#    deliberately leaves `actual_end` NULL on the sessions running at seed time
#    (seed_term.py:384-395). A zero at a time of day when classes are in session
#    means the D-09 branch is not being reached. A zero on a database seeded days
#    ago is expected and says nothing -- those sessions are outside the window.
#
# These are OBSERVATIONS to reason about, not assertions to encode. The dataset is
# regenerated with a different seed and any test pinning a specific seeded figure
# will be flaky.

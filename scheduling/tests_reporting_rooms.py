"""Unit tests for the room-utilization aggregates (IFO-09, tier T1).

A NEW sibling of tests_reporting.py, matching this app's existing split of
reporting tests by concern (tests_reporting.py, tests_report_render.py,
tests_room_master.py). Room utilization is a distinct aggregate family.

This pass is deliberately DB-FREE (SimpleTestCase): the zero-denominator and
ROUND_HALF_UP contract of the hours rate (HoursPctRoundingTests), the
"DayOfWeek needs no translation table" claim that teaching_weekdays rests on
(WeekdayMappingTests), the block-duration span rule the ladder is built from
(BlockDurationTests), and THE definition of used-hours every downstream plan
consumes (SessionContributionTests). Plan 02 extends this module with the
DB-backed fixture tests; keeping this pass free of database access keeps that
split legible.

Django test runner (not pytest); reference module constants (SessionStatus,
DayOfWeek), never a bare status string. ASCII-only.
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
    SessionStatus,
)
from scheduling.reporting import (
    _block_duration_seconds,
    _hours,
    _hours_pct,
    _physical_rooms,
    _session_contribution,
    _span_seconds,
    campus_block_ladder,
    room_utilization,
    timetabled_cells,
)

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

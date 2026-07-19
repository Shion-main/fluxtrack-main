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

from django.test import SimpleTestCase

from scheduling.models import DayOfWeek, SessionStatus
from scheduling.reporting import (
    _block_duration_seconds,
    _hours,
    _hours_pct,
    _session_contribution,
    _span_seconds,
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

    teaching_weekdays returns raw day_of_week values and room_utilization compares
    them straight against date.weekday() with no mapping. That claim is enforced
    here rather than trusted to a comment: if DayOfWeek is ever reordered, the
    denominator would silently count the wrong days and this test is what catches
    it.
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

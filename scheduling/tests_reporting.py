"""Unit tests for the pure reporting aggregate layer (RPT-01/04/05).

These exercise scheduling/reporting.py against make_reporting_fixture: the
per-faculty aggregates (AggregateTests), the "held/absent read from Session.status
truth, never re-derived" contract (TruthReuseTests), the merge-filled-sibling
honest-verified rule (MergedSiblingTests), the safe_card per-card isolation
wrapper (CardIsolationTests), the scorecard slice (ScorecardTests), and the
timezone-correct week boundary on the local Session.date DateField
(WeekBoundaryTests). Django TestCase (not pytest); reference module constants
(SessionStatus, HELD_STATUSES, Modality), never bare status strings.
"""
from datetime import time
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from scheduling.models import Modality, SessionStatus
from scheduling.reporting import (
    HELD_STATUSES,
    AbsenceItem,
    DeptSummary,
    FacultyRow,
    Scorecard,
    _pct,
    dept_summary,
    faculty_attendance,
    faculty_scorecard,
    safe_card,
)
from scheduling.test_support import _aware, make_reporting_fixture


class PctRoundingTests(SimpleTestCase):
    """LO-02: _pct uses ROUND_HALF_UP so a .5 tie rounds up predictably, not the
    built-in round-half-to-even (banker's rounding)."""

    def test_zero_denominator_is_zero(self):
        self.assertEqual(_pct(0, 0), 0)

    def test_exact_half_rounds_up_not_to_even(self):
        # 100 * 1 / 8 = 12.5 -> conventional 13 (Python round(12.5) == 12).
        self.assertEqual(_pct(1, 8), 13)
        # 100 * 3 / 8 = 37.5 -> 38 (round(37.5) == 38 already, still correct).
        self.assertEqual(_pct(3, 8), 38)

    def test_non_tie_values_unchanged(self):
        self.assertEqual(_pct(6, 8), 75)
        self.assertEqual(_pct(1, 2), 50)
        self.assertEqual(_pct(5, 6), 83)   # 83.33 -> 83


class AggregateTests(TestCase):
    """RPT-01: scheduled/held/absent/verified/attendance_pct per FacultyRow."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def _row(self, rows, faculty):
        match = [r for r in rows if r.faculty_id == faculty.id]
        self.assertEqual(len(match), 1, "exactly one row per faculty")
        return match[0]

    def test_unscoped_returns_one_row_per_faculty(self):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        self.assertEqual({r.faculty_id for r in rows},
                         {self.fx.faculty_a.id, self.fx.faculty_b.id})
        self.assertTrue(all(isinstance(r, FacultyRow) for r in rows))

    def test_faculty_a_counts_match_seeded_statuses(self):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        row = self._row(rows, self.fx.faculty_a)
        self.assertEqual(row.scheduled, 8)
        self.assertEqual(row.held, 6)
        self.assertEqual(row.absent, 1)
        self.assertEqual(row.verified, 1)
        self.assertEqual(row.early_ends, 1)
        self.assertEqual(row.attendance_pct, 75)

    def test_faculty_a_itemized_absences(self):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        row = self._row(rows, self.fx.faculty_a)
        self.assertEqual(len(row.absences), 1)
        item = row.absences[0]
        self.assertIsInstance(item, AbsenceItem)
        self.assertEqual(item.date, self.fx.tue)

    def test_department_scoping(self):
        rows_a = faculty_attendance(
            start=self.fx.week_start, end=self.fx.sun, department=self.fx.dept_a)
        self.assertEqual({r.faculty_id for r in rows_a}, {self.fx.faculty_a.id})
        rows_b = faculty_attendance(
            start=self.fx.week_start, end=self.fx.sun, department=self.fx.dept_b)
        self.assertEqual({r.faculty_id for r in rows_b}, {self.fx.faculty_b.id})
        row_b = rows_b[0]
        self.assertEqual(row_b.scheduled, 2)
        self.assertEqual(row_b.held, 1)
        self.assertEqual(row_b.absent, 1)
        self.assertEqual(row_b.attendance_pct, 50)

    def test_attendance_pct_zero_when_no_scheduled(self):
        # An as_of before the whole week yields zero sessions -> no rows, no crash.
        rows = faculty_attendance(
            start=self.fx.week_start, end=self.fx.sun,
            as_of=self.fx.week_start.replace(day=1))
        self.assertEqual(rows, [])

    def test_as_of_clamps_future_scheduled_session(self):
        # as_of = Tuesday keeps Mon+Tue sessions but excludes the future Wednesday
        # SCHEDULED session from the denominator (a not-yet-missed session must not
        # lower attendance %).
        rows = faculty_attendance(
            start=self.fx.week_start, end=self.fx.sun, as_of=self.fx.tue)
        row = self._row(rows, self.fx.faculty_a)
        self.assertEqual(row.scheduled, 7)  # 8 minus the future Wednesday SCHEDULED

    def test_dept_summary_totals(self):
        summary = dept_summary(
            start=self.fx.week_start, end=self.fx.sun, department=self.fx.dept_a)
        self.assertIsInstance(summary, DeptSummary)
        self.assertEqual(summary.faculty_count, 1)
        self.assertEqual(summary.scheduled, 8)
        self.assertEqual(summary.held, 6)
        self.assertEqual(summary.absent, 1)
        self.assertEqual(summary.attendance_pct, 75)


class TruthReuseTests(TestCase):
    """RPT-01: held/absent read from Session.status, never re-derived from times."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def _row_a(self):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        return [r for r in rows if r.faculty_id == self.fx.faculty_a.id][0]

    def test_absent_session_counts_absent_not_held(self):
        row = self._row_a()
        self.assertEqual(row.absent, 1)
        # The ABSENT session must not leak into held.
        self.assertNotIn(SessionStatus.ABSENT, HELD_STATUSES)

    def test_flipping_timestamps_does_not_change_counts(self):
        before = self._row_a()
        # Mutate timestamps on the ABSENT session as if it had "started" -- status
        # is untouched, so the aggregate must not change (no timestamp re-derivation).
        self.fx.s_absent.actual_start = self.fx.s_absent.scheduled_start
        self.fx.s_absent.actual_end = self.fx.s_absent.scheduled_end
        self.fx.s_absent.save(update_fields=["actual_start", "actual_end"])
        after = self._row_a()
        self.assertEqual((before.scheduled, before.held, before.absent),
                         (after.scheduled, after.held, after.absent))

    def test_only_status_change_moves_the_count(self):
        before = self._row_a()
        self.fx.s_absent.status = SessionStatus.COMPLETED
        self.fx.s_absent.save(update_fields=["status"])
        after = self._row_a()
        self.assertEqual(after.held, before.held + 1)
        self.assertEqual(after.absent, before.absent - 1)


class MergedSiblingTests(TestCase):
    """04.2 D-09: a MERGED sibling is held but NOT checker-verified."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_merged_sibling_held_but_not_verified(self):
        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        row = [r for r in rows if r.faculty_id == self.fx.faculty_a.id][0]
        # s_merged (ACTIVE, MERGED, no validation) is in held...
        self.assertEqual(row.held, 6)
        # ...but verified counts ONLY the session with a real CheckerValidation.
        self.assertEqual(row.verified, 1)
        self.assertLess(row.verified, row.held)


class CardIsolationTests(TestCase):
    """RPT-05 / T-06-04: safe_card returns tuples; failure leaks no exception text."""

    def test_success_returns_value_and_no_error(self):
        value, error = safe_card(lambda: 42)
        self.assertEqual(value, 42)
        self.assertIsNone(error)

    def test_failure_returns_none_and_generic_message(self):
        secret = "raw-internal-detail-should-not-leak"

        def boom():
            raise RuntimeError(secret)

        value, error = safe_card(boom)
        self.assertIsNone(value)
        self.assertIsNotNone(error)
        self.assertNotIn(secret, error)
        self.assertNotIn("RuntimeError", error)

    def test_passes_through_args(self):
        value, error = safe_card(lambda a, b: a + b, 2, b=3)
        self.assertEqual(value, 5)
        self.assertIsNone(error)


class ScorecardTests(TestCase):
    """RPT-04: early-ends + effective-modality breakdown honoring declared_modality."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_scorecard_slice_matches_faculty_attendance(self):
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)
        self.assertIsInstance(card, Scorecard)
        self.assertEqual(card.faculty_id, self.fx.faculty_a.id)
        self.assertEqual(card.scheduled, 8)
        self.assertEqual(card.held, 6)
        self.assertEqual(card.absent, 1)
        self.assertEqual(card.attendance_pct, 75)

    def test_early_ends_counted(self):
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)
        self.assertEqual(card.early_ends, 1)

    def test_effective_modality_breakdown_counts_declared_online(self):
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)
        # The declared-ONLINE-over-F2F session is counted ONLINE (effective wins).
        self.assertEqual(card.modality_breakdown.get(Modality.ONLINE), 1)
        # The remaining five held sessions are F2F.
        self.assertEqual(card.modality_breakdown.get(Modality.F2F), 5)
        # Breakdown counts held sessions only.
        self.assertEqual(sum(card.modality_breakdown.values()), card.held)

    def test_itemized_absences_present(self):
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)
        self.assertEqual(len(card.absences), 1)
        self.assertIsInstance(card.absences[0], AbsenceItem)
        self.assertEqual(card.absences[0].date, self.fx.tue)

    def test_empty_range_faculty_returns_zeroed_scorecard(self):
        # The checker has no sessions -> zeroed Scorecard, no crash.
        card = faculty_scorecard(
            faculty=self.fx.checker, start=self.fx.week_start, end=self.fx.sun)
        self.assertEqual(card.scheduled, 0)
        self.assertEqual(card.held, 0)
        self.assertEqual(card.absent, 0)
        self.assertEqual(card.early_ends, 0)
        self.assertEqual(card.attendance_pct, 0)
        self.assertEqual(card.modality_breakdown, {})
        self.assertEqual(card.absences, [])


class LatenessParityTests(TestCase):
    """A3 / D-01: faculty_attendance and faculty_scorecard expose the SAME lateness
    fields for one faculty over one range -- the two builders share _lateness_map and
    so cannot drift (T-11-01)."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_facultyrow_and_scorecard_lateness_agree(self):
        # Seed one 4-min-late held session so the parity is over non-trivial values.
        late = _aware(self.fx.week_start, time(8, 4))
        end = _aware(self.fx.week_start, time(9, 30))
        self.fx.add_session(
            self.fx.faculty_a, self.fx.week_start, SessionStatus.COMPLETED,
            actual_start=late, actual_end=end)

        rows = faculty_attendance(start=self.fx.week_start, end=self.fx.sun)
        row = [r for r in rows if r.faculty_id == self.fx.faculty_a.id][0]
        card = faculty_scorecard(
            faculty=self.fx.faculty_a, start=self.fx.week_start, end=self.fx.sun)

        self.assertEqual(card.minutes_late_avg, row.minutes_late_avg)
        self.assertEqual(card.late_sessions, row.late_sessions)
        self.assertEqual(card.chronic_late, row.chronic_late)
        # The seeded 4-min-late session actually registered on both surfaces.
        self.assertEqual(row.late_sessions, 1)
        self.assertEqual(row.minutes_late_avg, Decimal("4.0"))


class WeekBoundaryTests(TestCase):
    """RPT-02 / Pitfall 1: date__range on the local Session.date -- no UTC drift."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_sunday_included_next_monday_excluded(self):
        # A session on the Sunday of the target week is INCLUDED; one on the
        # following Monday is EXCLUDED, when filtering by date__range on the local
        # DateField (proving no UTC scheduled_start boundary drift).
        self.fx.add_session(self.fx.faculty_b, self.fx.sun, SessionStatus.ABSENT)
        self.fx.add_session(
            self.fx.faculty_b, self.fx.next_monday, SessionStatus.ABSENT)

        rows = faculty_attendance(
            start=self.fx.week_start, end=self.fx.sun, department=self.fx.dept_b)
        row = [r for r in rows if r.faculty_id == self.fx.faculty_b.id][0]
        # Original 2 (Mon ACTIVE + Tue ABSENT) + the Sunday ABSENT = 3; the
        # next-Monday session is out of range.
        self.assertEqual(row.scheduled, 3)
        self.assertEqual(row.absent, 2)
        absence_dates = {a.date for a in row.absences}
        self.assertIn(self.fx.sun, absence_dates)
        self.assertNotIn(self.fx.next_monday, absence_dates)

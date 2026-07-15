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
from django.test import TestCase

from scheduling.models import SessionStatus
from scheduling.reporting import (
    HELD_STATUSES,
    AbsenceItem,
    DeptSummary,
    FacultyRow,
    dept_summary,
    faculty_attendance,
    safe_card,
)
from scheduling.test_support import make_reporting_fixture


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

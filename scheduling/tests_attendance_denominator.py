"""Attendance percentages exclude classes that were cancelled (SRS IFO-12).

A cancelled class did not meet, so it is neither held nor missed. Counting it as
"scheduled" would lower a faculty member's percentage for a typhoon they did not
cause. These tests fail if any of the three attendance aggregates counts it.
"""
from datetime import time, timedelta

from django.test import TestCase

from scheduling.models import Schedule, Session, SessionStatus
from scheduling.reporting import dept_summary, faculty_attendance, faculty_scorecard
from scheduling.test_support import IN_WINDOW_DATE, _aware, make_shift_fixture

NEXT_DAY = IN_WINDOW_DATE + timedelta(days=1)


class CancelledSessionDenominatorTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("den")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.held = self.fx.session
        self.held.status = SessionStatus.COMPLETED
        self.held.actual_start = self.held.scheduled_start
        self.held.actual_end = self.held.scheduled_end
        self.held.save()
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code="DEN2", section="A",
            faculty=self.fx.faculty, room=self.fx.room_b,
            day_of_week=NEXT_DAY.weekday(),
            start_time=time(8, 0), end_time=time(9, 30))
        self.cancelled = Session.objects.create(
            schedule=schedule, faculty=self.fx.faculty, room=self.fx.room_b,
            date=NEXT_DAY, scheduled_start=_aware(NEXT_DAY, time(8, 0)),
            scheduled_end=_aware(NEXT_DAY, time(9, 30)),
            status=SessionStatus.CANCELLED, cancelled_reason="Typhoon")
        self.kw = dict(term=self.fx.term, start=IN_WINDOW_DATE, end=NEXT_DAY,
                       as_of=NEXT_DAY)

    def test_faculty_row_ignores_cancelled_session(self):
        (row,) = faculty_attendance(**self.kw)
        self.assertEqual((row.scheduled, row.held, row.attendance_pct), (1, 1, 100))

    def test_department_summary_ignores_cancelled_session(self):
        summary = dept_summary(department=self.fx.dept, **self.kw)
        self.assertEqual(
            (summary.scheduled, summary.held, summary.attendance_pct), (1, 1, 100))

    def test_scorecard_ignores_cancelled_session(self):
        card = faculty_scorecard(faculty=self.fx.faculty, **self.kw)
        self.assertEqual(
            (card.scheduled, card.held, card.attendance_pct), (1, 1, 100))

    def test_faculty_with_only_cancelled_sessions_reports_zero_scheduled(self):
        self.held.delete()
        (row,) = faculty_attendance(**self.kw)
        self.assertEqual((row.scheduled, row.held, row.attendance_pct), (0, 0, 0))

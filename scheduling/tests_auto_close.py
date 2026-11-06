"""Unfinished classes close themselves, and never cost the next class (H2/H3).

Agreed rule: a class nobody checked out of is closed automatically, its end is
recorded as the scheduled end, and IFO is told because that end is an estimate.
Faculty keep the grace period after the bell to check out normally.
"""
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase

from accounts.models import Role
from django.contrib.auth import get_user_model
from ops.models import AuditLog, Notification
from scheduling import resolver as R
from scheduling.jobs import close_unfinished_sessions, sweep_no_shows
from scheduling.models import Modality, Schedule, Session, SessionStatus
from scheduling.term_lifecycle import preflight_term_action
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture

MANILA = ZoneInfo("Asia/Manila")
NEXT_DAY = DAY + timedelta(days=1)


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MANILA)


def fake_session(pk, status, room_id, start, end):
    return SimpleNamespace(
        id=pk, status=status, room_id=room_id, scheduled_start=start,
        scheduled_end=end, declared_modality="",
        schedule=SimpleNamespace(modality=Modality.F2F))


class ResolverAfterTheBellTests(SimpleTestCase):
    """A class that has ended must not be mistaken for the current class."""

    def resolve(self, sessions, room_id, now):
        return R.resolve_faculty_scan(sessions, room_id, None, now,
                                      grace_min=15, early_end_min=10)

    def setUp(self):
        self.finished = fake_session(1, "active", 10, at(8), at(9, 30))
        self.next_class = fake_session(2, "scheduled", 20, at(9, 30), at(11))

    def test_scanning_the_next_room_checks_into_the_next_class(self):
        result = self.resolve([self.finished, self.next_class], 20, at(9, 35))
        self.assertEqual((result.outcome, result.session_id), (R.CHECKED_IN, 2))

    def test_scanning_the_shared_room_checks_into_the_next_class(self):
        self.next_class.room_id = 10
        result = self.resolve([self.finished, self.next_class], 10, at(9, 35))
        self.assertEqual((result.outcome, result.session_id), (R.CHECKED_IN, 2))

    def test_scanning_the_old_room_still_checks_out_of_the_finished_class(self):
        result = self.resolve([self.finished, self.next_class], 10, at(9, 35))
        self.assertEqual((result.outcome, result.session_id), (R.CHECKED_OUT, 1))

    def test_finished_class_with_nothing_next_is_not_offered_a_room_move(self):
        result = self.resolve([self.finished], 20, at(9, 35))
        self.assertEqual(result.outcome, R.NO_SCHEDULE)

    def test_class_still_running_keeps_the_room_move_confirmation(self):
        result = self.resolve([self.finished], 20, at(9, 0))
        self.assertEqual((result.outcome, result.session_id), (R.WRONG_ROOM, 1))


class CloseUnfinishedSessionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("acl")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.session = self.fx.session  # scheduled 08:00-09:30
        self.session.status = SessionStatus.ACTIVE
        self.session.actual_start = at(8, 2)
        self.session.save()
        self.ifo = get_user_model().objects.create(
            username="acl_ifo", email="acl_ifo@mcm.edu.ph", role=Role.IFO_ADMIN,
            is_active=True)

    def test_records_the_scheduled_end_as_the_finish(self):
        self.assertEqual(close_unfinished_sessions(now=at(10)), 1)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.COMPLETED)
        self.assertEqual(self.session.actual_end, at(9, 30))

    def test_leaves_the_grace_period_for_a_normal_checkout(self):
        self.assertEqual(close_unfinished_sessions(now=at(9, 45)), 0)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.ACTIVE)

    def test_audits_each_closure_as_an_estimate(self):
        close_unfinished_sessions(now=at(10))
        entry = AuditLog.objects.get(event_type="session.auto_closed")
        self.assertEqual(entry.target_id, str(self.session.pk))
        self.assertIsNone(entry.actor)
        self.assertTrue(entry.payload["estimated"])

    def test_tells_ifo_once_for_a_whole_run(self):
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code="ACL2", section="A",
            faculty=self.fx.faculty, room=self.fx.room_b, day_of_week=0,
            start_time=time(9, 30), end_time=time(9, 40))
        Session.objects.create(
            schedule=schedule, faculty=self.fx.faculty, room=self.fx.room_b,
            date=DAY, scheduled_start=at(9, 30), scheduled_end=at(9, 40),
            status=SessionStatus.ACTIVE, actual_start=at(9, 31))
        self.assertEqual(close_unfinished_sessions(now=at(10)), 2)
        notes = Notification.objects.filter(user=self.ifo, type="session_auto_closed")
        self.assertEqual(notes.count(), 1)
        self.assertIn("2", notes.get().title)

    def test_second_run_changes_nothing(self):
        close_unfinished_sessions(now=at(10))
        self.assertEqual(close_unfinished_sessions(now=at(11)), 0)
        self.assertEqual(Notification.objects.filter(
            type="session_auto_closed").count(), 1)

    def test_term_can_close_after_a_forgotten_checkout(self):
        close_unfinished_sessions(now=at(10, 0, NEXT_DAY))
        preflight = preflight_term_action(
            self.fx.term.pk, "close", self.ifo, today=self.fx.term.end_date)
        self.assertNotIn("active_sessions", preflight.blockers)


class NextClassSurvivesForgottenCheckoutTests(TestCase):
    """The whole journey from audit finding H3, through the real views."""

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("nxt")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        Session.objects.filter(pk=self.fx.session.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(8, 1))
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code="NXT2", section="A",
            faculty=self.fx.faculty, room=self.fx.room_b, day_of_week=0,
            start_time=time(9, 30), end_time=time(11, 0))
        self.next_class = Session.objects.create(
            schedule=schedule, faculty=self.fx.faculty, room=self.fx.room_b,
            date=DAY, scheduled_start=at(9, 30), scheduled_end=at(11))
        self.client = Client()
        self.client.force_login(self.fx.faculty)

    def test_next_class_starts_and_previous_class_closes_at_its_end(self):
        with patch("django.utils.timezone.now", return_value=at(9, 35)):
            self.client.post("/scan/resolve", {
                "payload": f"https://x/scan?t={self.fx.room_b.qr_token}"})
        self.next_class.refresh_from_db()
        self.fx.session.refresh_from_db()
        self.assertEqual(self.next_class.status, SessionStatus.ACTIVE)
        self.assertEqual(self.fx.session.status, SessionStatus.COMPLETED)
        self.assertEqual(self.fx.session.actual_end, at(9, 30))
        self.assertEqual(self.fx.session.room_id, self.fx.room_a.pk)

    def test_sweep_does_not_mark_the_next_class_absent(self):
        with patch("django.utils.timezone.now", return_value=at(9, 35)):
            self.client.post("/scan/resolve", {
                "payload": f"https://x/scan?t={self.fx.room_b.qr_token}"})
        sweep_no_shows(now=at(9, 50))
        self.next_class.refresh_from_db()
        self.assertEqual(self.next_class.status, SessionStatus.ACTIVE)


class SweepWiringTests(TestCase):
    """Both sweep entry points must run the close, or nothing ever closes."""

    def setUp(self):
        self.fx = make_shift_fixture("wir")
        Session.objects.filter(pk=self.fx.session.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(8, 1))

    def assert_closed(self):
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.status, SessionStatus.COMPLETED)

    def test_scheduled_sweep_job_closes_unfinished_sessions(self):
        from scheduling.management.commands.runscheduler import _job_sweep
        _job_sweep()
        self.assert_closed()

    def test_manual_sweep_command_closes_unfinished_sessions(self):
        from io import StringIO
        from django.core.management import call_command
        call_command("run_status_sweep", stdout=StringIO())
        self.assert_closed()

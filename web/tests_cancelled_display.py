"""A cancelled class reads as cancelled on every surface (audit M3).

On a suspended day nobody should see a class "starting", a room with "Nobody
checked in", a Start button, or a next class that is not happening.
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase

from accounts.models import Role
from scheduling.models import Schedule, Session, SessionStatus
from scheduling.suspensions import suspend_classes
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification.models import Assignment, AssignmentScope, AssignmentType, DutyRole
from web.reporting_common import status_label
from web.room_state import room_tile

MANILA = ZoneInfo("Asia/Manila")
GRACE = timedelta(minutes=15)
User = get_user_model()


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


class StatusLabelTests(SimpleTestCase):
    def test_labels(self):
        cases = [(SessionStatus.ACTIVE, "Present"), (SessionStatus.COMPLETED, "Present"),
                 (SessionStatus.ABSENT, "Absent"), (SessionStatus.SCHEDULED, "Scheduled"),
                 (SessionStatus.CANCELLED, "Cancelled")]
        for status, label in cases:
            with self.subTest(status=status):
                self.assertEqual(status_label(status), label)


class CancelledDisplayTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("cdl")
        self.floor = self.fx.room_a.floor
        self.guard = self.staff(Role.GUARD, "cdl_grd", DutyRole.GUARD)
        self.checker = self.staff(Role.CHECKER, "cdl_chk", DutyRole.CHECKER)
        self.hr = User.objects.create(
            username="cdl_hr", email="cdl_hr@mcm.edu.ph", role=Role.HR_ADMIN,
            is_active=True)
        with frozen(at(6)):
            suspend_classes(term=self.fx.term, start_date=DAY, end_date=DAY,
                            reason="Typhoon")

    def staff(self, role, name, duty):
        user = User.objects.create(username=name, email=f"{name}@mcm.edu.ph",
                                   role=role, is_active=True)
        posting = Assignment.objects.create(
            user=user, role=duty, type=AssignmentType.STANDING,
            scope=AssignmentScope.FLOOR, term=self.fx.term)
        posting.floors.set([self.floor])
        return user

    def browser(self, user):
        client = Client()
        client.force_login(user)
        return client

    def room_a_sessions(self):
        return list(Session.objects.filter(room=self.fx.room_a, date=DAY)
                    .select_related("schedule", "faculty")
                    .order_by("scheduled_start"))

    def test_room_is_not_shown_as_starting(self):
        tile = room_tile(self.fx.room_a, self.room_a_sessions(), at(8, 5), GRACE)
        self.assertEqual(tile["state"], "idle")

    def test_room_is_not_shown_as_a_no_show(self):
        tile = room_tile(self.fx.room_a, self.room_a_sessions(), at(8, 40), GRACE)
        self.assertEqual(tile["state"], "idle")

    def test_room_with_a_real_class_later_reads_free(self):
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code="CDL2", section="A",
            faculty=self.fx.faculty, room=self.fx.room_a, day_of_week=0,
            start_time=time(14), end_time=time(15))
        later = Session.objects.create(
            schedule=schedule, faculty=self.fx.faculty, room=self.fx.room_a,
            date=DAY, scheduled_start=at(14), scheduled_end=at(15))
        tile = room_tile(self.fx.room_a, self.room_a_sessions(), at(8, 40), GRACE)
        self.assertEqual((tile["state"], tile["next"]), ("free", later))

    def test_guard_locator_skips_a_cancelled_next_class(self):
        with frozen(at(7)):
            response = self.browser(self.guard).get(
                "/guard/locate", {"q": self.fx.faculty.username})
        self.assertIsNone(response.context["next"])

    def test_guard_monitor_labels_it_cancelled(self):
        with frozen(at(7)):
            response = self.browser(self.guard).get("/guard/monitor/rows")
        self.assertContains(response, "Cancelled")
        self.assertNotContains(response, ">Scheduled<")

    def test_floor_coverage_ignores_cancelled_classes(self):
        with frozen(at(7)):
            response = self.browser(self.checker).get("/checker/floor/rows")
        self.assertEqual(
            (response.context["total"], response.context["coverage"]), (0, 100))

    def test_online_card_offers_no_start(self):
        with frozen(at(10, 5)):
            response = self.browser(self.fx.faculty).get("/faculty/online")
        (row,) = response.context["rows"]
        self.assertEqual(row["state"], "cancelled")
        self.assertFalse(row["can_start"])
        self.assertContains(response, "Typhoon")
        self.assertNotContains(response, "This class is finished")

    def test_faculty_history_shows_cancelled(self):
        response = self.browser(self.fx.faculty).get("/faculty/history")
        self.assertContains(response, "Cancelled")

    def test_hr_export_says_cancelled(self):
        response = self.browser(self.hr).get("/hr/attendance.csv", {
            "term": self.fx.term.pk, "from": str(DAY), "to": str(DAY)})
        rows = b"".join(response.streaming_content).decode().strip().splitlines()[1:]
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertIn(",Cancelled,", row)

    def test_guard_room_timeline_agrees_with_its_tile(self):
        with frozen(at(7)):
            response = self.browser(self.guard).get(f"/guard/rooms/{self.fx.room_a.code}")
        self.assertEqual(response.context["today"], [])

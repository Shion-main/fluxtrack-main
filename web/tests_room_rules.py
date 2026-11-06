"""Who really holds a room when a class scans in or moves (audit M6, M7).

An online class filed under a physical room has nobody in it, so it must never
trigger a handover or hide a real class. A move must respect a booking or another
class in that room, because those are commitments to someone else.
"""
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from accounts.models import Role
from ops.models import Booking
from scheduling import resolver as R
from scheduling.models import (CheckinMethod, Modality, Schedule, Session,
                               SessionStatus)
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification import resolver as CR
from verification.models import Assignment, AssignmentScope, AssignmentType, DutyRole
from web.scan import _move_blocked

MANILA = ZoneInfo("Asia/Manila")
User = get_user_model()


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


class Base(TestCase):
    prefix = "rul"

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture(self.prefix)
        self.colleague = self.person(Role.FACULTY, "col", department=self.fx.dept)

    def person(self, role, name, **fields):
        name = f"{self.prefix}_{name}"
        return User.objects.create(username=name, email=f"{name}@mcm.edu.ph",
                                   role=role, is_active=True, **fields)

    def browser(self, user):
        client = Client()
        client.force_login(user)
        return client

    def add_class(self, code, room, start, end, *, faculty=None, **fields):
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code=code, section="B",
            faculty=faculty or self.colleague, room=room,
            day_of_week=DAY.weekday(), start_time=start, end_time=end)
        return Session.objects.create(
            schedule=schedule, faculty=schedule.faculty, room=room, date=DAY,
            scheduled_start=at(start.hour, start.minute),
            scheduled_end=at(end.hour, end.minute), **fields)

    def scan(self, client, room):
        return client.post("/scan/resolve", {
            "payload": f"https://x/scan?t={room.qr_token}"})


class OnlineClassInPhysicalRoomTests(Base):
    """The online class is 'in' room B on paper; nobody is physically there."""
    prefix = "onr"

    def setUp(self):
        super().setUp()
        self.online = self.fx.online_session  # 10:00-11:30 in room B
        Session.objects.filter(pk=self.online.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(10))
        self.mine = self.add_class("F2F", self.fx.room_b, time(10), time(11, 30))

    def test_face_to_face_class_checks_in_normally(self):
        with frozen(at(10, 5)):
            self.scan(self.browser(self.colleague), self.fx.room_b)
        self.mine.refresh_from_db()
        self.assertEqual(self.mine.status, SessionStatus.ACTIVE)
        self.assertEqual(self.mine.checkin_method, CheckinMethod.QR_SCAN)

    def test_online_class_keeps_running(self):
        with frozen(at(10, 5)):
            self.scan(self.browser(self.colleague), self.fx.room_b)
        self.online.refresh_from_db()
        self.assertEqual(self.online.status, SessionStatus.ACTIVE)
        self.assertIsNone(self.online.actual_end)

    def test_real_class_in_the_room_still_offers_a_handover(self):
        real = self.add_class("REAL", self.fx.room_b, time(9), time(10, 30),
                              faculty=self.fx.faculty,
                              status=SessionStatus.ACTIVE, actual_start=at(9))
        with frozen(at(10, 5)):
            response = self.scan(self.browser(self.colleague), self.fx.room_b)
        self.assertEqual(response.context["resolution"].outcome, R.ROOM_OCCUPIED)
        self.assertEqual(response.context["resolution"].prior_session_id, real.pk)

    def test_checker_scan_finds_the_real_class_behind_the_online_one(self):
        Session.objects.filter(pk=self.mine.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(10, 2))
        checker = self.person(Role.CHECKER, "chk")
        posting = Assignment.objects.create(
            user=checker, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
            scope=AssignmentScope.FLOOR, term=self.fx.term)
        posting.floors.set([self.fx.room_b.floor])
        with frozen(at(10, 15)):
            response = self.browser(checker).post("/checker/resolve", {
                "payload": f"https://x/scan?t={self.fx.room_b.qr_token}"})
        self.assertEqual(response.context["resolution"].outcome, CR.ACTIVE_UNVERIFIED)
        self.assertEqual(response.context["session"].pk, self.mine.pk)


class RoomMoveTests(Base):
    """Faculty teach 08:00-09:30 in room A and scan room B at 08:05."""
    prefix = "mov"

    def setUp(self):
        super().setUp()
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.session = self.fx.session
        self.client = self.browser(self.fx.faculty)

    def book(self, start, end):
        return Booking.objects.create(
            room=self.fx.room_b, occupant_name="Board", purpose="x",
            start_datetime=start, end_datetime=end, status="active")

    def attempt(self):
        with frozen(at(8, 5)):
            return self.scan(self.client, self.fx.room_b)

    def assert_refused(self, response):
        self.assertEqual(response.context["resolution"].outcome, R.MOVE_OCCUPIED)
        self.assertNotIn("confirm_token", response.context)
        self.session.refresh_from_db()
        self.assertEqual(self.session.room_id, self.fx.room_a.pk)

    def assert_offered(self, response):
        self.assertEqual(response.context["resolution"].outcome, R.WRONG_ROOM)
        self.assertIn("confirm_token", response.context)

    def test_booked_room_is_refused(self):
        self.book(at(7), at(12))
        self.assert_refused(self.attempt())

    def test_refusal_tells_them_to_contact_ifo(self):
        self.book(at(7), at(12))
        self.assertContains(self.attempt(), "IFO")

    def test_room_with_another_class_about_to_start_is_refused(self):
        self.add_class("SOON", self.fx.room_b, time(9), time(10))
        self.assert_refused(self.attempt())

    def test_running_class_cannot_move_into_a_booked_room(self):
        Session.objects.filter(pk=self.session.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(8))
        self.book(at(7), at(12))
        self.assert_refused(self.attempt())

    def test_booking_after_the_class_does_not_block(self):
        self.book(at(9, 30), at(12))
        self.assert_offered(self.attempt())

    def test_class_after_this_one_does_not_block(self):
        self.add_class("LATER", self.fx.room_b, time(9, 30), time(10))
        self.assert_offered(self.attempt())

    def test_cancelled_class_does_not_block(self):
        self.add_class("OFF", self.fx.room_b, time(9), time(10),
                       status=SessionStatus.CANCELLED)
        self.assert_offered(self.attempt())

    def test_cancelled_booking_does_not_block(self):
        booking = self.book(at(7), at(12))
        Booking.objects.filter(pk=booking.pk).update(status="cancelled")
        self.assert_offered(self.attempt())

    def test_booking_made_after_the_preview_stops_the_confirmation(self):
        response = self.attempt()
        self.book(at(7), at(12))
        with frozen(at(8, 6)):
            confirm = self.client.post("/scan/confirm", {
                "token": response.context["confirm_token"]})
        self.assertEqual(confirm.status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.room_id, self.fx.room_a.pk)

    def test_a_merged_sibling_in_the_room_does_not_block_its_own_group(self):
        self.add_class("SIB", self.fx.room_b, time(8), time(9, 30),
                       faculty=self.fx.faculty)
        Schedule.objects.filter(course_code="SIB").update(
            course_code=self.session.schedule.course_code)
        self.assertFalse(
            _move_blocked(self.session, self.fx.room_b, at(8, 5), self.fx.term))

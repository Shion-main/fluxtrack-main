"""A room conflict alert means two real classes want one room (audit M4).

Merged sections are one class, and an online class is not in a room, so neither
may raise an alert. A false alarm here trains IFO and guards to ignore real ones.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Role
from campus.models import Room
from ops.models import Notification, RoomConflictFlag
from scheduling.jobs import detect_room_conflicts
from scheduling.models import Modality, Schedule, Session, SessionStatus
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture

MANILA = ZoneInfo("Asia/Manila")
NOW = datetime(DAY.year, DAY.month, DAY.day, 8, 10, tzinfo=MANILA)
User = get_user_model()


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=MANILA)


class RoomConflictAlertTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("rca")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.ifo = User.objects.create(
            username="rca_ifo", email="rca_ifo@mcm.edu.ph", role=Role.IFO_ADMIN,
            is_active=True)
        self.colleague = User.objects.create(
            username="rca_col", email="rca_col@mcm.edu.ph", role=Role.FACULTY,
            department=self.fx.dept, is_active=True)
        self.anchor = self.fx.session  # 08:00 in room A
        Session.objects.filter(pk=self.anchor.pk).update(status=SessionStatus.ACTIVE)

    def active_class(self, code, *, room=None, faculty=None, start=time(8),
                     modality=Modality.F2F):
        schedule = Schedule.objects.create(
            term=self.fx.term, course_code=code, section="B",
            faculty=faculty or self.fx.faculty, room=room or self.fx.room_a,
            day_of_week=DAY.weekday(), start_time=start, end_time=time(9, 30),
            modality=modality)
        return Session.objects.create(
            schedule=schedule, faculty=schedule.faculty, room=schedule.room, date=DAY,
            scheduled_start=at(start.hour, start.minute), scheduled_end=at(9, 30),
            status=SessionStatus.ACTIVE)

    def test_merged_sections_sharing_a_room_raise_no_alert(self):
        self.active_class("SIB")
        self.assertEqual(detect_room_conflicts(now=NOW), 0)
        self.assertFalse(Notification.objects.filter(type="room_conflict").exists())

    def test_two_instructors_in_one_room_still_raise_an_alert(self):
        self.active_class("OTHER", faculty=self.colleague)
        self.assertEqual(detect_room_conflicts(now=NOW), 1)

    def test_merged_pair_plus_another_instructor_raises_one_alert(self):
        self.active_class("SIB")
        self.active_class("OTHER", faculty=self.colleague)
        self.assertEqual(detect_room_conflicts(now=NOW), 1)

    def test_one_instructor_with_two_different_start_times_raises_an_alert(self):
        self.active_class("LATER", start=time(8, 30))
        self.assertEqual(detect_room_conflicts(now=NOW), 1)

    def test_online_classes_sharing_a_virtual_room_raise_no_alert(self):
        virtual = Room.objects.create(
            floor=self.fx.room_a.floor, code="V-RCA", capacity=0,
            qr_token="rca-v", manual_code="rcaV01")
        self.active_class("ON1", room=virtual, modality=Modality.ONLINE)
        self.active_class("ON2", room=virtual, faculty=self.colleague,
                          modality=Modality.ONLINE)
        self.assertEqual(detect_room_conflicts(now=NOW), 0)

    def test_online_class_filed_under_a_physical_room_raises_no_alert(self):
        self.active_class("ON", faculty=self.colleague, modality=Modality.ONLINE)
        self.assertEqual(detect_room_conflicts(now=NOW), 0)

    def test_an_open_false_alarm_clears_itself(self):
        self.active_class("SIB")
        flag = RoomConflictFlag.objects.create(
            room=self.fx.room_a, conflict_key=f"room:{self.fx.room_a.pk}")
        detect_room_conflicts(now=NOW)
        flag.refresh_from_db()
        self.assertEqual(flag.resolved_at, NOW)

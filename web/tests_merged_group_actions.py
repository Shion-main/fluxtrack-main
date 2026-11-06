"""A merged group acts as one class when it moves or is flagged (H5, M9).

One instructor teaching two sections at the same instant is one presence event,
so one confirmed room move and one not-present flag must each cover the group.
"""
from datetime import datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog
from scheduling.jobs import sweep_no_shows
from scheduling.models import (CheckinMethod, Modality, Schedule, Session,
                               SessionStatus)
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 CheckerValidation, DutyRole, ValidationAction)

MANILA = ZoneInfo("Asia/Manila")
User = get_user_model()


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


def add_session(fx, code, room, start, end, *, faculty=None, modality=Modality.F2F):
    schedule = Schedule.objects.create(
        term=fx.term, course_code=code, section="B", faculty=faculty or fx.faculty,
        room=room, day_of_week=DAY.weekday(), start_time=start, end_time=end,
        modality=modality)
    return Session.objects.create(
        schedule=schedule, faculty=schedule.faculty, room=room, date=DAY,
        scheduled_start=at(start.hour, start.minute),
        scheduled_end=at(end.hour, end.minute))


class MergedRoomMoveTests(TestCase):
    """Anchor and sibling share room A at 08:00 under different course codes."""

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("mrm")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.anchor = self.fx.session
        self.sibling = add_session(self.fx, "SIB", self.fx.room_a, time(8), time(9, 30))
        self.client = Client()
        self.client.force_login(self.fx.faculty)

    def scan(self, room):
        return self.client.post("/scan/resolve", {
            "payload": f"https://x/scan?t={room.qr_token}"})

    def move_to(self, room):
        response = self.scan(room)
        return self.client.post("/scan/confirm", {
            "token": response.context["confirm_token"]})

    def room_of(self, session):
        session.refresh_from_db()
        return session.room_id

    def test_confirmed_move_takes_the_sibling_along(self):
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(self.sibling), self.fx.room_b.pk)

    def test_one_check_in_after_the_move_covers_the_group(self):
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
            self.scan(self.fx.room_b)
        self.sibling.refresh_from_db()
        self.assertEqual(self.sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(self.sibling.checkin_method, CheckinMethod.MERGED)

    def test_sweep_does_not_mark_a_moved_sibling_absent(self):
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
            self.scan(self.fx.room_b)
        sweep_no_shows(now=at(8, 20))
        self.sibling.refresh_from_db()
        self.assertEqual(self.sibling.status, SessionStatus.ACTIVE)

    def test_running_class_moves_as_a_group(self):
        Session.objects.filter(pk__in=[self.anchor.pk, self.sibling.pk]).update(
            status=SessionStatus.ACTIVE, actual_start=at(8, 1))
        with frozen(at(8, 30)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(self.anchor), self.fx.room_b.pk)
        self.assertEqual(self.room_of(self.sibling), self.fx.room_b.pk)

    def test_same_course_section_in_another_room_moves_too(self):
        room_c = Room.objects.create(
            floor=self.fx.room_a.floor, code="mrm-C", capacity=40,
            qr_token="mrm-qr-c", manual_code="mrC003")
        other = add_session(self.fx, self.anchor.schedule.course_code, room_c,
                            time(8), time(9, 30))
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(other), self.fx.room_b.pk)

    def test_finished_section_keeps_its_recorded_room(self):
        Session.objects.filter(pk=self.sibling.pk).update(status=SessionStatus.ABSENT)
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(self.sibling), self.fx.room_a.pk)

    def test_another_faculty_members_class_stays_put(self):
        colleague = User.objects.create(
            username="mrm_col", email="mrm_col@mcm.edu.ph", role=Role.FACULTY,
            department=self.fx.dept, is_active=True)
        theirs = add_session(self.fx, "COL", self.fx.room_a, time(8), time(9, 30),
                             faculty=colleague)
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(theirs), self.fx.room_a.pk)

    def test_same_faculty_class_at_another_time_stays_put(self):
        later = add_session(self.fx, "LATER", self.fx.room_a, time(13), time(14))
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        self.assertEqual(self.room_of(later), self.fx.room_a.pk)

    def test_refused_move_leaves_the_sibling_in_place(self):
        colleague = User.objects.create(
            username="mrm_occ", email="mrm_occ@mcm.edu.ph", role=Role.FACULTY,
            department=self.fx.dept, is_active=True)
        with frozen(at(8, 5)):
            token = self.scan(self.fx.room_b).context["confirm_token"]
            occupant = add_session(self.fx, "OCC", self.fx.room_b, time(8), time(9, 30),
                                   faculty=colleague)
            Session.objects.filter(pk=occupant.pk).update(status=SessionStatus.ACTIVE)
            self.client.post("/scan/confirm", {"token": token})
        self.assertEqual(self.room_of(self.sibling), self.fx.room_a.pk)

    def test_moved_sibling_is_audited(self):
        with frozen(at(8, 5)):
            self.move_to(self.fx.room_b)
        entry = AuditLog.objects.get(event_type="session.merged_room_changed")
        self.assertEqual(entry.target_id, str(self.sibling.pk))
        self.assertEqual(entry.payload["merged_from"], self.anchor.pk)


class MergedOnlineFlagTests(TestCase):
    """Two online sections share a 10:00 start; one self-start covers both."""

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("mof")
        self.origin = self.fx.online_session
        self.sibling = add_session(self.fx, "SIBO", self.fx.room_b, time(10),
                                   time(11, 30), modality=Modality.ONLINE)
        self.checker = User.objects.create(
            username="mof_chk", email="mof_chk@mcm.edu.ph", role=Role.CHECKER,
            is_active=True)
        Assignment.objects.create(
            user=self.checker, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
            scope=AssignmentScope.ONLINE, term=self.fx.term)
        Session.objects.filter(pk__in=[self.origin.pk, self.sibling.pk]).update(
            online_checker=self.checker)
        self.faculty_client = Client()
        self.faculty_client.force_login(self.fx.faculty)
        self.checker_client = Client()
        self.checker_client.force_login(self.checker)
        with frozen(at(10, 5)):
            self.faculty_client.post(f"/faculty/online/{self.origin.pk}/start", {
                "teams_link": "https://teams.microsoft.com/l/meetup-join/x"})

    def flag(self, session, when=None):
        with frozen(when or at(10, 30)):
            return self.checker_client.post("/checker/action", {
                "action": "flag_not_present", "session_id": session.pk,
                "note": "Nobody in the meeting"})

    def status(self, session):
        session.refresh_from_db()
        return session.status

    def test_flagging_the_started_section_absents_the_inherited_sibling(self):
        self.flag(self.origin)
        self.assertEqual(self.status(self.sibling), SessionStatus.ABSENT)

    def test_flagging_the_inherited_section_absents_the_started_one(self):
        self.flag(self.sibling)
        self.assertEqual(self.status(self.origin), SessionStatus.ABSENT)

    def test_flag_during_grace_still_covers_an_inherited_sibling(self):
        self.flag(self.origin, when=at(10, 8))
        self.assertEqual(self.status(self.sibling), SessionStatus.ABSENT)

    def test_checker_verified_sibling_keeps_its_presence(self):
        CheckerValidation.objects.create(
            session=self.sibling, room=self.sibling.room, checker=self.checker,
            action=ValidationAction.VERIFIED)
        self.flag(self.origin)
        self.assertEqual(self.status(self.sibling), SessionStatus.ACTIVE)

    def test_sibling_activated_by_a_checker_keeps_its_presence(self):
        Session.objects.filter(pk=self.sibling.pk).update(
            checkin_method=CheckinMethod.ONLINE_MANUAL)
        self.flag(self.origin)
        self.assertEqual(self.status(self.sibling), SessionStatus.ACTIVE)

    def test_absented_sibling_is_audited_to_the_flag(self):
        self.flag(self.origin)
        entry = AuditLog.objects.get(event_type="session.merged_absent",
                                     target_id=str(self.sibling.pk))
        self.assertEqual(entry.payload["merged_from"], self.origin.pk)

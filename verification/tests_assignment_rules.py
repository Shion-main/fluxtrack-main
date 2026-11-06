"""Duty postings mean what they say, and ending one takes effect at once (M5).

A posting decides who may verify attendance, so a malformed one quietly grants
duty it should not. Ending a posting must also release its online sessions, or
those classes would belong to someone who can no longer verify them.
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from accounts.models import Role
from ops.models import AuditLog, Notification
from scheduling.models import AcademicTerm, Session, SessionStatus
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 CheckerValidation, DutyRole)

MANILA = ZoneInfo("Asia/Manila")
User = get_user_model()


def at(hour, minute=0):
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


class Base(TestCase):
    prefix = "asg"

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture(self.prefix)
        self.floor = self.fx.room_a.floor
        self.ifo_user = self.person(Role.IFO_ADMIN, "ifo")
        self.checker = self.person(Role.CHECKER, "chk")
        self.guard = self.person(Role.GUARD, "grd")
        self.ifo = self.browser(self.ifo_user)

    def person(self, role, name):
        name = f"{self.prefix}_{name}"
        return User.objects.create(username=name, email=f"{name}@mcm.edu.ph",
                                   role=role, is_active=True)

    def browser(self, user):
        client = Client()
        client.force_login(user)
        return client

    def posting(self, user, *, duty=DutyRole.CHECKER, scope=AssignmentScope.FLOOR,
                type_=AssignmentType.STANDING, **fields):
        assignment = Assignment.objects.create(
            user=user, role=duty, type=type_, scope=scope, term=self.fx.term, **fields)
        if scope == AssignmentScope.FLOOR:
            assignment.floors.set([self.floor])
        return assignment

    def end(self, assignment, when=None):
        with frozen(when or at(9)):
            return self.ifo.post(f"/ifo/assignments/{assignment.pk}/end")


class CreateRulesTests(Base):
    def create(self, **fields):
        data = {"user": self.checker.pk, "role": "checker", "type": "shift",
                "scope": "floor", "floors": [self.floor.pk], **fields}
        return self.ifo.post("/ifo/assignments/create", data)

    def test_refused_postings(self):
        cases = {
            "shift with no date": {"date": ""},
            "shift with times but no date": {"start_time": "08:00", "end_time": "09:00"},
            "standing with a date": {"type": "standing", "date": str(DAY)},
            "standing with a time": {"type": "standing", "start_time": "08:00"},
            "end before start": {"date": str(DAY), "start_time": "17:00",
                                 "end_time": "08:00"},
            "end equals start": {"date": str(DAY), "start_time": "08:00",
                                 "end_time": "08:00"},
            "guard duty on a checker": {"role": "guard", "type": "standing"},
            "checker duty on a guard": {"user": self.guard.pk, "type": "standing"},
            "online duty on a guard": {"user": self.guard.pk, "role": "guard",
                                       "type": "standing", "scope": "online"},
        }
        for label, fields in cases.items():
            with self.subTest(label):
                self.assertEqual(self.create(**fields).status_code, 400)
                self.assertEqual(Assignment.objects.count(), 0)

    def test_accepted_postings(self):
        cases = {
            "dated shift with a window": {"date": str(DAY), "start_time": "08:00",
                                          "end_time": "12:00"},
            "dated shift with no times": {"date": str(DAY)},
            "standing floor posting": {"type": "standing"},
            "standing guard posting": {"user": self.guard.pk, "role": "guard",
                                       "type": "standing"},
        }
        for label, fields in cases.items():
            with self.subTest(label):
                before = Assignment.objects.count()
                self.assertEqual(self.create(**fields).status_code, 200)
                self.assertEqual(Assignment.objects.count(), before + 1)


class EndPostingTests(Base):
    def setUp(self):
        super().setUp()
        self.assignment = self.posting(self.checker)

    def test_checker_action_is_refused_right_after_the_posting_ends(self):
        checker = self.browser(self.checker)
        self.end(self.assignment)
        with frozen(at(9, 1)):
            checker.post("/checker/action", {"action": "verified_empty",
                                             "room_id": self.fx.room_a.pk})
        self.assertFalse(CheckerValidation.objects.exists())

    def test_guard_goes_off_duty_at_once(self):
        posting = self.posting(self.guard, duty=DutyRole.GUARD)
        guard = self.browser(self.guard)
        self.end(posting)
        with frozen(at(9, 1)):
            response = guard.get("/guard/monitor/rows")
        self.assertFalse(response.context["on_duty"])

    def test_record_is_kept_and_leaves_the_roster(self):
        response = self.end(self.assignment)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "ended")
        self.assertNotIn(self.assignment, list(response.context["assignments"]))

    def test_ending_is_audited_with_the_actor(self):
        self.end(self.assignment)
        entry = AuditLog.objects.get(event_type="assignment.ended")
        self.assertEqual(entry.actor, self.ifo_user)
        self.assertEqual(entry.target_id, str(self.assignment.pk))

    def test_ending_twice_is_refused_politely(self):
        self.end(self.assignment)
        self.assertEqual(self.end(self.assignment).status_code, 400)
        self.assertEqual(AuditLog.objects.filter(
            event_type="assignment.ended").count(), 1)

    def test_roster_offers_an_end_control(self):
        response = self.ifo.get("/ifo/assignments")
        self.assertContains(response, f"/ifo/assignments/{self.assignment.pk}/end")

    def test_only_ifo_can_end_a_posting(self):
        response = self.browser(self.checker).post(
            f"/ifo/assignments/{self.assignment.pk}/end")
        self.assertEqual(response.status_code, 403)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.status, "active")

    def test_a_link_cannot_end_a_posting(self):
        response = self.ifo.get(f"/ifo/assignments/{self.assignment.pk}/end")
        self.assertEqual(response.status_code, 405)

    def test_posting_from_another_term_is_not_found(self):
        old_term = AcademicTerm.objects.create(
            name="asg old", start_date=DAY - timedelta(days=400),
            end_date=DAY - timedelta(days=300), status=AcademicTerm.Status.ARCHIVED)
        Assignment.objects.filter(pk=self.assignment.pk).update(term=old_term)
        self.assertEqual(self.end(self.assignment).status_code, 404)


class OnlineHandOverTests(Base):
    prefix = "onh"

    def setUp(self):
        super().setUp()
        self.online = self.posting(self.checker, scope=AssignmentScope.ONLINE)
        self.session = self.fx.online_session  # 10:00-11:30
        Session.objects.filter(pk=self.session.pk).update(online_checker=self.checker)

    def owner(self):
        self.session.refresh_from_db()
        return self.session.online_checker_id

    def test_upcoming_session_passes_to_a_colleague_on_duty(self):
        colleague = self.person(Role.CHECKER, "col")
        self.posting(colleague, scope=AssignmentScope.ONLINE)
        self.end(self.online)
        self.assertEqual(self.owner(), colleague.pk)

    def test_with_nobody_on_duty_it_is_unowned_and_ifo_is_warned(self):
        self.end(self.online)
        self.assertIsNone(self.owner())
        self.assertTrue(Notification.objects.filter(
            user=self.ifo_user, type="online_unassigned").exists())

    def test_running_class_passes_on_so_it_can_still_be_verified(self):
        colleague = self.person(Role.CHECKER, "run")
        self.posting(colleague, scope=AssignmentScope.ONLINE)
        Session.objects.filter(pk=self.session.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(10, 1))
        self.end(self.online, at(10, 30))
        self.assertEqual(self.owner(), colleague.pk)

    def test_finished_class_keeps_its_owner_as_a_record(self):
        Session.objects.filter(pk=self.session.pk).update(
            status=SessionStatus.COMPLETED)
        self.end(self.online, at(12))
        self.assertEqual(self.owner(), self.checker.pk)

    def test_session_covered_by_their_other_posting_stays_theirs(self):
        self.posting(self.checker, scope=AssignmentScope.ONLINE,
                     type_=AssignmentType.SHIFT, date=DAY,
                     start_time=time(9), end_time=time(12))
        self.end(self.online)
        self.assertEqual(self.owner(), self.checker.pk)

    def test_session_outside_their_other_posting_is_released(self):
        self.posting(self.checker, scope=AssignmentScope.ONLINE,
                     type_=AssignmentType.SHIFT, date=DAY,
                     start_time=time(13), end_time=time(15))
        self.end(self.online)
        self.assertIsNone(self.owner())

    def test_ending_a_floor_posting_leaves_online_sessions_alone(self):
        floor_posting = self.posting(self.checker)
        self.end(floor_posting)
        self.assertEqual(self.owner(), self.checker.pk)

"""Calendar and schedule changes must not rewrite what actually happened.

Covers audit findings H4 (lifting a suspension), H6 (editing a class), H7 (online
checker assignment) and H8 (declaring a holiday after sessions already exist).
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from accounts.models import Role
from ops.models import Notification
from scheduling.jobs import sweep_no_shows
from scheduling.models import (AcademicBreak, Modality, Schedule, Session,
                               SessionStatus)
from scheduling.schedule_ops import update_schedule
from scheduling.services import apply_approval, submit_modality_shift
from scheduling.suspensions import lift_suspension, suspend_classes
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification.models import Assignment, AssignmentScope, AssignmentType, DutyRole

MANILA = ZoneInfo("Asia/Manila")
User = get_user_model()


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


def make_ifo(name):
    return User.objects.create(username=name, email=f"{name}@mcm.edu.ph",
                               role=Role.IFO_ADMIN, is_active=True)


def add_class(fx, code, start, end, day=DAY):
    schedule = Schedule.objects.create(
        term=fx.term, course_code=code, section="A", faculty=fx.faculty,
        room=fx.room_b, day_of_week=day.weekday(), start_time=start, end_time=end)
    return Session.objects.create(
        schedule=schedule, faculty=fx.faculty, room=fx.room_b, date=day,
        scheduled_start=at(start.hour, start.minute, day),
        scheduled_end=at(end.hour, end.minute, day))


class LiftSuspensionTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("lft")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.morning = self.fx.session  # 08:00
        self.afternoon = add_class(self.fx, "LFT2", time(14, 0), time(15, 0))
        with frozen(at(6)):
            self.suspension, _ = suspend_classes(
                term=self.fx.term, start_date=DAY, end_date=DAY, reason="Typhoon")

    def status(self, session):
        session.refresh_from_db()
        return session.status

    def test_class_whose_time_passed_stays_cancelled_after_the_sweep(self):
        with frozen(at(12)):
            lift_suspension(self.suspension)
            sweep_no_shows()
        self.assertEqual(self.status(self.morning), SessionStatus.CANCELLED)

    def test_class_still_ahead_is_reinstated(self):
        with frozen(at(12)):
            reinstated = lift_suspension(self.suspension)
        self.assertEqual(reinstated, 1)
        self.assertEqual(self.status(self.afternoon), SessionStatus.SCHEDULED)

    def test_class_inside_its_grace_period_is_reinstated(self):
        with frozen(at(8, 10)):
            lift_suspension(self.suspension)
        self.assertEqual(self.status(self.morning), SessionStatus.SCHEDULED)


class HolidayTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("hol")
        self.fx.online_session.delete()
        self.fx.competitor.delete()
        self.session = self.fx.session  # 08:00
        self.ifo = Client()
        self.ifo.force_login(make_ifo("hol_ifo"))

    def declare(self):
        with frozen(at(6)):
            return self.ifo.post("/ifo/breaks/create", {
                "start_date": str(DAY), "end_date": str(DAY), "reason": "Holiday"})

    def test_existing_session_is_cancelled(self):
        self.declare()
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.CANCELLED)
        self.assertEqual(self.session.cancelled_reason, "Holiday")

    def test_faculty_cannot_check_in_on_the_holiday(self):
        self.declare()
        faculty = Client()
        faculty.force_login(self.fx.faculty)
        with frozen(at(8, 5)):
            faculty.post("/scan/resolve", {
                "payload": f"https://x/scan?t={self.fx.room_a.qr_token}"})
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.CANCELLED)

    def test_faculty_is_told_once(self):
        add_class(self.fx, "HOL2", time(14, 0), time(15, 0))
        self.declare()
        self.assertEqual(Notification.objects.filter(
            user=self.fx.faculty, type="class_suspended").count(), 1)

    def test_removing_the_holiday_later_never_creates_an_absence(self):
        self.declare()
        holiday = AcademicBreak.objects.get(term=self.fx.term)
        with frozen(at(9, 0, DAY + timedelta(days=3))):
            self.ifo.post(f"/ifo/breaks/{holiday.pk}/delete")
            sweep_no_shows()
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.CANCELLED)

    def test_removing_the_holiday_beforehand_restores_the_class(self):
        self.declare()
        holiday = AcademicBreak.objects.get(term=self.fx.term)
        with frozen(at(7)):
            self.ifo.post(f"/ifo/breaks/{holiday.pk}/delete")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.SCHEDULED)
        self.assertEqual(self.session.cancelled_reason, "")


class ScheduleEditKeepsApprovedMovesTests(TestCase):
    """Dean approval moved the first session to room B because A was taken."""

    def setUp(self):
        self.fx = make_shift_fixture("edt")
        self.schedule = self.fx.f2f_schedule
        with frozen(at(9, 0, DAY - timedelta(days=7))):
            request = submit_modality_shift(
                self.fx.faculty, [self.schedule], Modality.BLENDED, DAY, DAY,
                request_reason="x")
            apply_approval(request, self.fx.dean)
        self.moved = self.fx.session
        self.moved.refresh_from_db()
        self.assertEqual(self.moved.room_id, self.fx.room_b.pk)
        later = DAY + timedelta(days=7)
        self.plain = Session.objects.create(
            schedule=self.schedule, faculty=self.fx.faculty, room=self.fx.room_a,
            date=later, scheduled_start=at(8, 0, later),
            scheduled_end=at(9, 30, later))
        self.today = DAY - timedelta(days=6)

    def test_enrolment_edit_touches_no_session(self):
        updated = update_schedule(self.schedule, enrolled_count=35, today=self.today)
        self.moved.refresh_from_db()
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.enrolled_count, 35)
        self.assertEqual(self.moved.room_id, self.fx.room_b.pk)
        self.assertEqual(updated, 0)

    def test_edit_form_resubmitting_same_values_keeps_the_move(self):
        update_schedule(self.schedule, faculty=self.fx.faculty, room=self.fx.room_a,
                        start_time=time(8, 0), end_time=time(9, 30),
                        enrolled_count=35, today=self.today)
        self.moved.refresh_from_db()
        self.assertEqual(self.moved.room_id, self.fx.room_b.pk)

    def test_time_change_moves_ordinary_sessions_only(self):
        self.fx.competitor.schedule.delete()
        update_schedule(self.schedule, start_time=time(13, 0), end_time=time(14, 30),
                        today=self.today)
        self.moved.refresh_from_db()
        self.plain.refresh_from_db()
        later = self.plain.date
        self.assertEqual(self.plain.scheduled_start, at(13, 0, later))
        self.assertEqual(self.moved.scheduled_start, at(8, 0))

    def test_new_instructor_takes_moved_sessions_too(self):
        self.fx.competitor.schedule.delete()
        new_faculty = User.objects.create(
            username="edt_new", email="edt_new@mcm.edu.ph", role=Role.FACULTY,
            department=self.fx.dept, is_active=True)
        update_schedule(self.schedule, faculty=new_faculty, today=self.today)
        self.moved.refresh_from_db()
        self.assertEqual(self.moved.faculty_id, new_faculty.pk)


class OnlineAssignmentJobTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("onl")
        self.schedule = self.fx.online_schedule
        self.schedule.day_of_week = (DAY + timedelta(days=1)).weekday()
        self.schedule.save()

    def run_job(self, when=None):
        from scheduling.management.commands.runscheduler import _job_materialize
        with frozen(when or at(9)):
            _job_materialize()

    def test_new_sessions_get_the_standing_online_checker(self):
        checker = User.objects.create(
            username="onl_chk", email="onl_chk@mcm.edu.ph", role=Role.CHECKER,
            is_active=True)
        Assignment.objects.create(
            user=checker, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
            scope=AssignmentScope.ONLINE, term=self.fx.term)
        self.run_job()
        created = Session.objects.get(schedule=self.schedule,
                                      date=DAY + timedelta(days=1))
        self.assertEqual(created.online_checker_id, checker.pk)

    def test_repeat_runs_warn_ifo_only_once_when_nobody_is_on_duty(self):
        ifo = make_ifo("onl_ifo")
        self.run_job()
        first = Notification.objects.filter(user=ifo, type="online_unassigned").count()
        self.run_job(at(15))
        self.assertGreater(first, 0)
        self.assertEqual(
            Notification.objects.filter(user=ifo, type="online_unassigned").count(),
            first)

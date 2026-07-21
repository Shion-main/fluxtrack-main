"""Phase 10 (A9) single-schedule ops: add / edit / cancel a class mid-term.

The service safety rule is the thing under test: an edit or cancel touches ONLY
future SCHEDULED sessions; a session that already happened (ACTIVE/COMPLETED/
ABSENT) is never rewritten. ASCII-only.
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog
from scheduling.models import (AcademicTerm, Schedule, ScheduleStatus, Session,
                               SessionStatus)
from scheduling.schedule_ops import cancel_schedule, update_schedule

User = get_user_model()


def _term():
    return AcademicTerm.objects.create(
        name="A9 Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)


class ScheduleFixture:
    def __init__(self, term):
        self.term = term
        b = Building.objects.create(name="Struct", code="STR")
        self.floor = Floor.objects.create(building=b, number=1)
        self.faculty = User.objects.create(username="a9_fac", role=Role.FACULTY)
        self.faculty2 = User.objects.create(username="a9_fac2", role=Role.FACULTY)
        self.room1 = self._room("A9R1")
        self.room2 = self._room("A9R2")
        self.today = timezone.localdate()
        self.schedule = Schedule.objects.create(
            term=term, course_code="CS9", section="A", faculty=self.faculty,
            room=self.room1, day_of_week=self.today.weekday(),
            start_time=time(8, 0), end_time=time(9, 30), enrolled_count=30)
        self._seq = 0

    def _room(self, code):
        return Room.objects.create(floor=self.floor, code=code,
                                   qr_token=f"q-{code}",
                                   manual_code=str(700000 + hash(code) % 90000))

    def session(self, day_offset, status=SessionStatus.SCHEDULED):
        d = self.today + timedelta(days=day_offset)
        start = timezone.make_aware(timezone.datetime.combine(d, time(8, 0)))
        return Session.objects.create(
            schedule=self.schedule, faculty=self.faculty, room=self.room1, date=d,
            scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
            status=status)


class UpdateScheduleTests(TestCase):
    def setUp(self):
        self.fx = ScheduleFixture(_term())

    def test_edit_propagates_to_future_scheduled_only(self):
        past = self.fx.session(-3, status=SessionStatus.COMPLETED)
        absent = self.fx.session(-1, status=SessionStatus.ABSENT)
        future = self.fx.session(3)
        n = update_schedule(self.fx.schedule, faculty=self.fx.faculty2,
                            room=self.fx.room2, start_time=time(10, 0),
                            end_time=time(11, 30), enrolled_count=25,
                            actor=None, today=self.fx.today)
        self.assertEqual(n, 1)
        future.refresh_from_db()
        self.assertEqual(future.faculty_id, self.fx.faculty2.id)
        self.assertEqual(future.room_id, self.fx.room2.id)
        self.assertEqual(future.scheduled_start.astimezone(
            timezone.get_current_timezone()).hour, 10)
        # History untouched.
        past.refresh_from_db()
        absent.refresh_from_db()
        self.assertEqual(past.faculty_id, self.fx.faculty.id)
        self.assertEqual(past.room_id, self.fx.room1.id)
        self.assertEqual(absent.status, SessionStatus.ABSENT)

    def test_edit_audits(self):
        update_schedule(self.fx.schedule, faculty=self.fx.faculty2,
                        room=self.fx.room1, start_time=time(8, 0),
                        end_time=time(9, 30), enrolled_count=30, actor=None,
                        today=self.fx.today)
        self.assertTrue(AuditLog.objects.filter(
            event_type="schedule.updated",
            target_id=str(self.fx.schedule.pk)).exists())


class CancelScheduleTests(TestCase):
    def setUp(self):
        self.fx = ScheduleFixture(_term())

    def test_cancel_archives_and_cancels_future_sessions(self):
        past = self.fx.session(-2, status=SessionStatus.COMPLETED)
        future = self.fx.session(4)
        n = cancel_schedule(self.fx.schedule, actor=None, reason="Dropped",
                            today=self.fx.today)
        self.assertEqual(n, 1)
        self.fx.schedule.refresh_from_db()
        self.assertEqual(self.fx.schedule.status, ScheduleStatus.ARCHIVED)
        future.refresh_from_db()
        self.assertEqual(future.status, SessionStatus.CANCELLED)
        self.assertEqual(future.cancelled_reason, "Dropped")
        # A completed session is history -- untouched.
        past.refresh_from_db()
        self.assertEqual(past.status, SessionStatus.COMPLETED)

    def test_cancelled_schedule_not_rematerialized(self):
        # ARCHIVED schedules are excluded from materialize (status=ACTIVE filter),
        # so a cancelled class never comes back on the next run.
        cancel_schedule(self.fx.schedule, actor=None, today=self.fx.today)
        self.assertEqual(
            Schedule.objects.filter(status=ScheduleStatus.ACTIVE,
                                    pk=self.fx.schedule.pk).count(), 0)


class ScheduleConsoleTests(TestCase):
    def setUp(self):
        self.fx = ScheduleFixture(_term())
        self.ifo = User.objects.create(username="a9_ifo", role=Role.IFO_ADMIN)

    def test_edit_requires_ifo(self):
        self.client.force_login(self.fx.faculty)
        self.assertEqual(
            self.client.get(f"/ifo/schedules/{self.fx.schedule.pk}/edit").status_code,
            403)

    def test_edit_view_updates(self):
        self.fx.session(3)
        self.client.force_login(self.ifo)
        resp = self.client.post(f"/ifo/schedules/{self.fx.schedule.pk}/edit", {
            "faculty": str(self.fx.faculty2.pk), "room": str(self.fx.room2.pk),
            "start_time": "10:00", "end_time": "11:30", "enrolled_count": "25"})
        self.assertEqual(resp.status_code, 302)
        self.fx.schedule.refresh_from_db()
        self.assertEqual(self.fx.schedule.faculty_id, self.fx.faculty2.id)

    def test_edit_bad_time_is_400(self):
        self.client.force_login(self.ifo)
        resp = self.client.post(f"/ifo/schedules/{self.fx.schedule.pk}/edit", {
            "faculty": str(self.fx.faculty.pk), "room": str(self.fx.room1.pk),
            "start_time": "11:00", "end_time": "10:00", "enrolled_count": "1"})
        self.assertEqual(resp.status_code, 400)

    def test_cancel_view(self):
        self.fx.session(2)
        self.client.force_login(self.ifo)
        resp = self.client.post(f"/ifo/schedules/{self.fx.schedule.pk}/cancel",
                                {"reason": "Section merged"})
        self.assertEqual(resp.status_code, 302)
        self.fx.schedule.refresh_from_db()
        self.assertEqual(self.fx.schedule.status, ScheduleStatus.ARCHIVED)

    def test_new_schedule_creates_and_materializes(self):
        self.client.force_login(self.ifo)
        before = Schedule.objects.count()
        resp = self.client.post("/ifo/schedules/new", {
            "course_code": "NEW9", "section": "Z", "faculty": str(self.fx.faculty.pk),
            "room": str(self.fx.room2.pk), "day_of_week": str(self.fx.today.weekday()),
            "start_time": "13:00", "end_time": "14:30", "enrolled_count": "20",
            "modality": "f2f"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Schedule.objects.count(), before + 1)
        sch = Schedule.objects.get(course_code="NEW9", section="Z")
        # Materialized immediately: at least one upcoming session exists.
        self.assertTrue(Session.objects.filter(schedule=sch).exists())

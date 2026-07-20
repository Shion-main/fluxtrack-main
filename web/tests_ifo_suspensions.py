"""Phase 9 IFO surfaces: class suspensions, holidays/breaks, Absent corrections.

Service-level flip/excusal is covered by scheduling.tests_suspensions; these tests
cover the console: auth gating, that the view delegates to the service and reports
the outcome, validation 400s, and the D3 IFO-only correction semantics.

ASCII-only by convention (Windows cp1252).
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog, Notification
from scheduling.models import (AcademicBreak, AcademicTerm, ClassSuspension,
                               Schedule, Session, SessionStatus)

User = get_user_model()


def _term():
    return AcademicTerm.objects.create(
        name="IFO9 Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), is_active=True)


def _session(term, faculty, on_date, *, status=SessionStatus.SCHEDULED, seq=1,
             minutes_before_now=90, building=None):
    bldg = building or Building.objects.create(name=f"B{seq}", code=f"B{seq}")
    floor = Floor.objects.create(building=bldg, number=1)
    room = Room.objects.create(floor=floor, code=f"RM{seq:03d}",
                               qr_token=f"q{seq}", manual_code=f"66{seq:04d}")
    start = timezone.now() - timedelta(minutes=minutes_before_now)
    sch = Schedule.objects.create(
        term=term, course_code=f"CC{seq}", section="A", faculty=faculty,
        room=room, day_of_week=on_date.weekday(), start_time=time(8, 0),
        end_time=time(9, 30), enrolled_count=20)
    return Session.objects.create(
        schedule=sch, faculty=faculty, room=room, date=on_date,
        scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
        status=status)


class SuspensionConsoleTests(TestCase):
    def setUp(self):
        self.term = _term()
        self.ifo = User.objects.create(username="ifo9", role=Role.IFO_ADMIN)
        self.fac = User.objects.create(username="fac9", role=Role.FACULTY)
        self.today = timezone.localdate()
        self.client.force_login(self.ifo)

    def test_list_requires_ifo(self):
        self.client.force_login(self.fac)
        self.assertEqual(self.client.get("/ifo/suspensions").status_code, 403)

    def test_list_renders(self):
        self.assertEqual(self.client.get("/ifo/suspensions").status_code, 200)

    def test_create_suspends_and_cancels_sessions(self):
        s = _session(self.term, self.fac, self.today)
        resp = self.client.post("/ifo/suspensions/create", {
            "start_date": self.today.isoformat(), "reason": "Typhoon Pepito"})
        self.assertRedirects(resp, "/ifo/suspensions")
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.CANCELLED)
        self.assertEqual(s.cancelled_reason, "Typhoon Pepito")
        self.assertTrue(Notification.objects.filter(
            user=self.fac, type="class_suspended").exists())
        self.assertTrue(ClassSuspension.objects.filter(term=self.term).exists())

    def test_create_bad_date_is_400_not_500(self):
        resp = self.client.post("/ifo/suspensions/create", {
            "start_date": "2026-13-45", "reason": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_create_requires_reason(self):
        resp = self.client.post("/ifo/suspensions/create", {
            "start_date": self.today.isoformat(), "reason": "  "})
        self.assertEqual(resp.status_code, 400)

    def test_lift_reinstates(self):
        s = _session(self.term, self.fac, self.today)
        self.client.post("/ifo/suspensions/create", {
            "start_date": self.today.isoformat(), "reason": "Storm"})
        susp = ClassSuspension.objects.get(term=self.term)
        resp = self.client.post(f"/ifo/suspensions/{susp.pk}/lift")
        self.assertRedirects(resp, "/ifo/suspensions")
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)


class BreakConsoleTests(TestCase):
    def setUp(self):
        self.term = _term()
        self.ifo = User.objects.create(username="ifo9b", role=Role.IFO_ADMIN)
        self.client.force_login(self.ifo)
        self.d = timezone.localdate()

    def test_requires_ifo(self):
        self.client.logout()
        guard = User.objects.create(username="g9", role=Role.GUARD)
        self.client.force_login(guard)
        self.assertEqual(self.client.get("/ifo/breaks").status_code, 403)

    def test_create_and_delete_break(self):
        resp = self.client.post("/ifo/breaks/create", {
            "start_date": self.d.isoformat(), "reason": "Founding Day"})
        self.assertRedirects(resp, "/ifo/breaks")
        brk = AcademicBreak.objects.get(term=self.term)
        self.assertEqual(brk.reason, "Founding Day")
        self.assertTrue(AuditLog.objects.filter(
            event_type="academicbreak.created").exists())
        resp = self.client.post(f"/ifo/breaks/{brk.pk}/delete")
        self.assertRedirects(resp, "/ifo/breaks")
        self.assertFalse(AcademicBreak.objects.filter(pk=brk.pk).exists())

    def test_create_requires_reason(self):
        resp = self.client.post("/ifo/breaks/create", {
            "start_date": self.d.isoformat(), "reason": ""})
        self.assertEqual(resp.status_code, 400)


class CorrectionConsoleTests(TestCase):
    def setUp(self):
        self.term = _term()
        self.ifo = User.objects.create(username="ifo9c", role=Role.IFO_ADMIN)
        self.fac = User.objects.create(username="fac9c", role=Role.FACULTY)
        self.today = timezone.localdate()
        self.client.force_login(self.ifo)

    def test_list_requires_ifo(self):
        self.client.force_login(self.fac)
        self.assertEqual(self.client.get("/ifo/corrections").status_code, 403)

    def test_reinstate_absent_session_as_held(self):
        s = _session(self.term, self.fac, self.today, status=SessionStatus.ABSENT)
        resp = self.client.post(f"/ifo/sessions/{s.pk}/reinstate",
                                {"reason": "Checker could not reach the room"})
        self.assertRedirects(resp, "/ifo/corrections")
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.COMPLETED)
        self.assertIsNotNone(s.actual_start)
        self.assertTrue(AuditLog.objects.filter(
            event_type="session.absent_corrected", target_id=str(s.pk)).exists())

    def test_reinstate_requires_reason(self):
        s = _session(self.term, self.fac, self.today, status=SessionStatus.ABSENT)
        self.client.post(f"/ifo/sessions/{s.pk}/reinstate", {"reason": " "})
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)  # unchanged

    def test_cannot_reinstate_a_non_absent_session(self):
        s = _session(self.term, self.fac, self.today, status=SessionStatus.ACTIVE)
        self.client.post(f"/ifo/sessions/{s.pk}/reinstate", {"reason": "x"})
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ACTIVE)  # untouched

    def test_reinstate_requires_ifo(self):
        s = _session(self.term, self.fac, self.today, status=SessionStatus.ABSENT)
        self.client.force_login(self.fac)
        resp = self.client.post(f"/ifo/sessions/{s.pk}/reinstate", {"reason": "x"})
        self.assertEqual(resp.status_code, 403)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

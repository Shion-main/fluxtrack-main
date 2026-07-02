"""Integration tests for the scan flow's IFO notifications after the NOTIF-00
migration (§6.6, FAC-09/10).

ScanNotifyTests drives the real two-step confirm endpoints and asserts the
migrated call sites still create type="room_event" Notification rows for active
IFO admins — guarding T-02-05 (a silent notification regression during migration).
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from ops.models import Notification
from scheduling.models import AcademicTerm, Schedule, Session, SessionStatus


class ScanNotifyTests(TestCase):
    """A confirmed room-change and a confirmed force-handover each notify the IFO
    admin via the shared notify() write path (NOTIF-00)."""

    def setUp(self):
        cache.clear()  # locmem cache is not rolled back between tests
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="T", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), is_active=True)
        self.bldg = Building.objects.create(name="R", code="R")
        self.floor = Floor.objects.create(building=self.bldg, number=3)
        self.faculty = User.objects.create(username="fac_scan", role=Role.FACULTY)
        self.ifo = User.objects.create(username="ifo_scan", role=Role.IFO_ADMIN)
        self.client.force_login(self.faculty)

    def _room(self, code, qr, manual):
        return Room.objects.create(floor=self.floor, code=code,
                                   qr_token=qr, manual_code=manual)

    def _session(self, room, faculty, status, start, end):
        sch = Schedule.objects.create(
            term=self.term, course_code="CS101", section="A",
            faculty=faculty, room=room, day_of_week=0,
            start_time=time(8, 0), end_time=time(9, 30))
        return Session.objects.create(
            schedule=sch, faculty=faculty, room=room, date=timezone.localdate(),
            scheduled_start=start, scheduled_end=end, status=status)

    def _confirm(self, payload):
        """Drive /scan/resolve for a needs-confirm outcome, then post the signed
        token to /scan/confirm (the two-step flow, SCAN-04)."""
        resp = self.client.post("/scan/resolve", {"payload": payload})
        token = resp.context["confirm_token"]
        return self.client.post("/scan/confirm", {"token": token})

    def test_confirmed_room_change_notifies_ifo(self):
        now = timezone.now()
        room_a = self._room("R301", "tok-a", "300301")
        self._room("R302", "tok-b", "300302")  # room B — where faculty actually scanned
        self._session(room_a, self.faculty, SessionStatus.SCHEDULED,
                      now, now + timedelta(minutes=90))

        self._confirm("300302")  # scan room B while scheduled in room A -> WRONG_ROOM

        n = Notification.objects.filter(user=self.ifo, type="room_event").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.title, "Room change")

    def test_confirmed_force_handover_notifies_ifo(self):
        now = timezone.now()
        room_a = self._room("R303", "tok-c", "300303")
        other = get_user_model().objects.create(username="fac_other", role=Role.FACULTY)
        # Another faculty's ACTIVE session occupies room A.
        self._session(room_a, other, SessionStatus.ACTIVE,
                      now, now + timedelta(minutes=90))
        # My scheduled session in the same room.
        self._session(room_a, self.faculty, SessionStatus.SCHEDULED,
                      now, now + timedelta(minutes=90))

        self._confirm("300303")  # scan the occupied room -> ROOM_OCCUPIED handover

        n = Notification.objects.filter(user=self.ifo, type="room_event").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.title, "Force handover")

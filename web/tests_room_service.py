"""Phase 10 (A7) room out-of-service: refuse scans + bookings, drop from
utilization, and the IFO toggle. ASCII-only."""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog
from scheduling.models import (AcademicTerm, Schedule, Session, SessionStatus)
from scheduling.reporting import _physical_rooms

User = get_user_model()


_counter = {"n": 100000}


def _room(code="R100", oos=False, reason=""):
    b = Building.objects.create(name="B", code=f"B{code}")
    f = Floor.objects.create(building=b, number=1)
    _counter["n"] += 1
    return Room.objects.create(floor=f, code=code, qr_token=f"q-{code}",
                               manual_code=str(_counter["n"]),  # 6 numeric digits
                               out_of_service=oos, out_of_service_reason=reason)


class ScanRefusalTests(TestCase):
    def setUp(self):
        self.fac = User.objects.create(username="oos_fac", role=Role.FACULTY)
        self.client.force_login(self.fac)

    def test_scan_of_out_of_service_room_is_refused_with_reason(self):
        room = _room(code="OOS111", oos=True, reason="Under renovation")
        resp = self.client.post("/scan/resolve", {"payload": room.manual_code})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("out of service", body.lower())
        self.assertIn("Under renovation", body)

    def test_scan_of_in_service_room_is_not_blocked_by_this_gate(self):
        # An in-service room with no session for this faculty resolves to the
        # normal "no class" outcome, not the out-of-service refusal.
        room = _room(code="OK222", oos=False)
        resp = self.client.post("/scan/resolve", {"payload": room.manual_code})
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("out of service", resp.content.decode().lower())


class BookingRefusalTests(TestCase):
    def setUp(self):
        self.ifo = User.objects.create(username="oos_ifo", role=Role.IFO_ADMIN)
        self.client.force_login(self.ifo)

    def test_cannot_book_an_out_of_service_room(self):
        room = _room(code="BK333", oos=True)
        day = (timezone.localdate() + timedelta(days=1)).isoformat()
        resp = self.client.post("/ifo/bookings/create", {
            "occupant_name": "Accreditation", "purpose": "Visit",
            "room": str(room.pk), "date": day,
            "start_time": "10:00", "end_time": "12:00"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("out of service", resp.content.decode().lower())


class UtilizationDenominatorTests(TestCase):
    def test_out_of_service_room_excluded_from_physical_rooms(self):
        live = _room(code="LIVE44", oos=False)
        closed = _room(code="SHUT55", oos=True)
        codes = set(_physical_rooms().values_list("code", flat=True))
        self.assertIn("LIVE44", codes)
        self.assertNotIn("SHUT55", codes)


class ToggleTests(TestCase):
    def setUp(self):
        self.ifo = User.objects.create(username="tog_ifo", role=Role.IFO_ADMIN)
        self.fac = User.objects.create(username="tog_fac", role=Role.FACULTY)

    def test_toggle_out_and_back_audits(self):
        room = _room(code="TG666")
        self.client.force_login(self.ifo)
        self.client.post(f"/ifo/rooms/{room.code}/service",
                         {"reason": "Aircon repair"})
        room.refresh_from_db()
        self.assertTrue(room.out_of_service)
        self.assertEqual(room.out_of_service_reason, "Aircon repair")
        self.assertTrue(AuditLog.objects.filter(
            event_type="room.out_of_service", target_id=str(room.pk)).exists())
        # Toggle back clears the reason.
        self.client.post(f"/ifo/rooms/{room.code}/service")
        room.refresh_from_db()
        self.assertFalse(room.out_of_service)
        self.assertEqual(room.out_of_service_reason, "")

    def test_toggle_requires_ifo(self):
        room = _room(code="TG777")
        self.client.force_login(self.fac)
        resp = self.client.post(f"/ifo/rooms/{room.code}/service")
        self.assertEqual(resp.status_code, 403)
        room.refresh_from_db()
        self.assertFalse(room.out_of_service)

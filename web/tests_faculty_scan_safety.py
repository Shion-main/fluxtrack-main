"""Regression tests for faculty scan authorization and confirmation safety."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from scheduling import resolver as R
from scheduling.models import (
    AcademicTerm,
    CheckinMethod,
    Schedule,
    Session,
    SessionStatus,
)
from web.scan import CONFIRM_SALT, _apply

User = get_user_model()


class FacultyScanSafetyTests(TestCase):
    def test_active_move_allows_same_faculty_merged_sibling_in_destination(self):
        self.session.status = SessionStatus.ACTIVE
        self.session.save(update_fields=["status"])
        sibling = Session.objects.create(
            schedule=self.session.schedule, faculty=self.faculty,
            room=self.room_b, date=self.session.date,
            scheduled_start=self.session.scheduled_start,
            scheduled_end=self.session.scheduled_end,
            status=SessionStatus.ACTIVE,
            checkin_method=CheckinMethod.MERGED,
        )
        request = RequestFactory().post("/scan/confirm")
        request.user = self.faculty
        context = _apply(request, R.Resolution(R.WRONG_ROOM, self.session.pk),
                         self.room_b, CheckinMethod.QR_SCAN)
        self.assertNotIn("error", context)
        self.assertEqual(context["resolution"].outcome, R.WRONG_ROOM)
        self.session.refresh_from_db()
        sibling.refresh_from_db()
        self.assertEqual(self.session.room_id, self.room_b.pk)
        self.assertEqual(sibling.status, SessionStatus.ACTIVE)

    def test_confirm_refuses_room_closed_after_preview(self):
        token = self._wrong_room_token()
        self.room_b.out_of_service = True
        self.room_b.save(update_fields=["out_of_service"])
        response = self.client.post("/scan/confirm", {"token": token})
        self.assertEqual(response.status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.room_id, self.room_a.pk)

    def test_active_wrong_room_refuses_occupied_destination(self):
        self.session.status = SessionStatus.ACTIVE
        self.session.save(update_fields=["status"])
        resolution = R.resolve_faculty_scan(
            [self.session], self.room_b.pk, 999, timezone.now(),
            grace_min=15, early_end_min=15)
        self.assertEqual(resolution.outcome, R.MOVE_OCCUPIED)
        self.assertFalse(resolution.needs_confirm)

    def test_failed_confirmation_releases_nonce_and_rolls_back_room(self):
        from unittest.mock import patch
        token = self._wrong_room_token()
        with patch("web.scan.notify", side_effect=RuntimeError("notify failed")):
            with self.assertRaises(RuntimeError):
                self.client.post("/scan/confirm", {"token": token})
        self.session.refresh_from_db()
        self.assertEqual(self.session.room_id, self.room_a.pk)
        response = self.client.post("/scan/confirm", {"token": token})
        self.assertEqual(response.status_code, 200)

    def setUp(self):
        cache.clear()
        self.department = Department.objects.create(name="Scan Safety", code="SCAN-SAFE")
        self.faculty = User.objects.create(
            username="scan_safe_faculty",
            role=Role.FACULTY,
            department=self.department,
        )
        self.other_faculty = User.objects.create(
            username="scan_safe_other",
            role=Role.FACULTY,
            department=self.department,
        )
        self.checker = User.objects.create(
            username="scan_safe_checker",
            role=Role.CHECKER,
            department=self.department,
        )
        self.term = AcademicTerm.objects.create(
            name="Scan Safety Term",
            start_date=timezone.localdate() - timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=30),
            status=AcademicTerm.Status.ACTIVE,
        )
        building = Building.objects.create(name="Scan Safety Hall", code="SSH")
        floor = Floor.objects.create(building=building, number=1)
        self.room_a = Room.objects.create(
            floor=floor,
            code="SSH-101",
            qr_token="scan-safe-a",
            manual_code="101101",
        )
        self.room_b = Room.objects.create(
            floor=floor,
            code="SSH-102",
            qr_token="scan-safe-b",
            manual_code="101102",
        )
        now = timezone.now()
        schedule = Schedule.objects.create(
            term=self.term,
            course_code="SAFE101",
            section="A",
            faculty=self.faculty,
            room=self.room_a,
            day_of_week=now.weekday(),
            start_time=(now - timedelta(minutes=5)).time(),
            end_time=(now + timedelta(minutes=60)).time(),
        )
        self.session = Session.objects.create(
            schedule=schedule,
            faculty=self.faculty,
            room=self.room_a,
            date=timezone.localdate(),
            scheduled_start=now - timedelta(minutes=5),
            scheduled_end=now + timedelta(minutes=60),
            status=SessionStatus.SCHEDULED,
        )

    def _wrong_room_token(self):
        self.client.force_login(self.faculty)
        response = self.client.post("/scan/resolve", {"payload": "101102"})
        self.assertEqual(response.status_code, 200)
        return response.context["confirm_token"]

    def test_non_faculty_cannot_use_shared_scan_endpoints(self):
        self.client.force_login(self.checker)

        resolve_response = self.client.post("/scan/resolve", {"payload": "101101"})
        deep_link_response = self.client.get("/scan?t=scan-safe-a")

        self.assertEqual(resolve_response.status_code, 403)
        self.assertEqual(deep_link_response.status_code, 403)

    def test_confirmation_is_rejected_when_session_state_changed(self):
        token = self._wrong_room_token()
        self.session.status = SessionStatus.CANCELLED
        self.session.save(update_fields=["status"])

        response = self.client.post("/scan/confirm", {"token": token})

        self.assertEqual(response.status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.room_id, self.room_a.pk)

    def test_confirmation_token_cannot_be_replayed(self):
        token = self._wrong_room_token()

        first = self.client.post("/scan/confirm", {"token": token})
        second = self.client.post("/scan/confirm", {"token": token})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 409)

    def test_early_end_confirmation_requires_non_blank_reason(self):
        self.session.status = SessionStatus.ACTIVE
        self.session.actual_start = timezone.now() - timedelta(minutes=10)
        self.session.save(update_fields=["status", "actual_start"])
        self.client.force_login(self.faculty)
        token = signing.dumps(
            {
                "outcome": R.EARLY_END,
                "session_id": self.session.pk,
                "prior_session_id": None,
                "room_id": self.room_a.pk,
                "method": CheckinMethod.QR_SCAN,
                "user_id": self.faculty.pk,
                "nonce": "blank-reason-regression",
            },
            salt=CONFIRM_SALT,
        )

        response = self.client.post(
            "/scan/confirm",
            {"token": token, "reason": "   "},
        )

        self.assertEqual(response.status_code, 400)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.ACTIVE)

    def test_apply_refuses_a_foreign_faculty_session(self):
        request = RequestFactory().post("/scan/resolve")
        request.user = self.other_faculty
        resolution = R.Resolution(R.CHECKED_IN, self.session.pk)

        result = _apply(request, resolution, self.room_a, CheckinMethod.QR_SCAN)

        self.session.refresh_from_db()
        self.assertEqual(result["error"], "stale-confirmation")
        self.assertEqual(self.session.status, SessionStatus.SCHEDULED)

    def test_force_handover_refuses_a_prior_session_that_is_no_longer_active(self):
        now = timezone.now()
        schedule = Schedule.objects.create(
            term=self.term,
            course_code="SAFE202",
            section="B",
            faculty=self.other_faculty,
            room=self.room_a,
            day_of_week=now.weekday(),
            start_time=(now - timedelta(minutes=10)).time(),
            end_time=(now + timedelta(minutes=50)).time(),
        )
        prior = Session.objects.create(
            schedule=schedule,
            faculty=self.other_faculty,
            room=self.room_a,
            date=timezone.localdate(),
            scheduled_start=now - timedelta(minutes=10),
            scheduled_end=now + timedelta(minutes=50),
            status=SessionStatus.COMPLETED,
            actual_start=now - timedelta(minutes=10),
            actual_end=now,
        )
        request = RequestFactory().post("/scan/confirm")
        request.user = self.faculty
        resolution = R.Resolution(
            R.ROOM_OCCUPIED,
            self.session.pk,
            prior_session_id=prior.pk,
        )

        result = _apply(
            request,
            resolution,
            self.room_a,
            CheckinMethod.QR_SCAN,
        )

        self.session.refresh_from_db()
        self.assertEqual(result["error"], "stale-confirmation")
        self.assertEqual(self.session.status, SessionStatus.SCHEDULED)

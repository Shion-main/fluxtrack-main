"""Regression tests for faculty journey continuity and cancelled sessions."""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from scheduling.models import (
    AcademicTerm,
    Modality,
    Schedule,
    Session,
    SessionStatus,
)

User = get_user_model()


class FacultyJourneyFixture(TestCase):
    def setUp(self):
        self.department = Department.objects.create(
            name="Journey Department",
            code="JOURNEY",
        )
        self.faculty = User.objects.create(
            username="journey_faculty",
            role=Role.FACULTY,
            department=self.department,
            is_active=True,
        )
        self.term = AcademicTerm.objects.create(
            name="Journey Term",
            start_date=timezone.localdate() - timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=30),
            status=AcademicTerm.Status.ACTIVE,
        )
        building = Building.objects.create(name="Journey Hall", code="JH")
        floor = Floor.objects.create(building=building, number=1)
        self.room = Room.objects.create(
            floor=floor,
            code="JH-101",
            qr_token="journey-room",
            manual_code="711101",
        )

    def make_session(self, *, day_offset, status, reason="", code="JRN101"):
        start = timezone.now() + timedelta(days=day_offset, minutes=30)
        schedule = Schedule.objects.create(
            term=self.term,
            course_code=code,
            section="A",
            faculty=self.faculty,
            room=self.room,
            day_of_week=timezone.localtime(start).weekday(),
            start_time=time(8, 0),
            end_time=time(9, 30),
            modality=Modality.F2F,
        )
        return Session.objects.create(
            schedule=schedule,
            faculty=self.faculty,
            room=self.room,
            date=timezone.localtime(start).date(),
            scheduled_start=start,
            scheduled_end=start + timedelta(minutes=90),
            status=status,
            cancelled_reason=reason,
        )


class CancelledFacultyScheduleTests(FacultyJourneyFixture):
    def test_cancelled_session_is_not_selected_as_home_hero(self):
        self.make_session(
            day_offset=1,
            status=SessionStatus.CANCELLED,
            reason="Campus closure",
            code="CAN101",
        )
        upcoming = self.make_session(
            day_offset=2,
            status=SessionStatus.SCHEDULED,
            code="LIVE101",
        )
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/home")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["hero"]["rep"].pk, upcoming.pk)

    def test_schedule_labels_cancelled_session_and_reason(self):
        self.make_session(
            day_offset=0,
            status=SessionStatus.CANCELLED,
            reason="Campus closure",
            code="CAN102",
        )
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/schedule")

        self.assertContains(response, "Cancelled")
        self.assertContains(response, "Campus closure")

    def test_schedule_describes_rolling_window_accurately(self):
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/schedule")

        self.assertContains(response, "Next 7 days")

    def test_schedule_uses_the_canonical_modality_badge(self):
        self.make_session(
            day_offset=1,
            status=SessionStatus.SCHEDULED,
            code="BADGE101",
        )
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/schedule")

        self.assertContains(response, "modality-badge--f2f")
        self.assertContains(response, ">Face-to-face<")

    def test_home_quick_shift_preserves_class_and_target(self):
        session = self.make_session(
            day_offset=0,
            status=SessionStatus.SCHEDULED,
            code="PREFILL101",
        )
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/home")

        self.assertContains(
            response,
            f"/faculty/modality/new?schedule={session.schedule_id}&amp;target=online",
        )

    def test_missing_active_term_is_not_described_as_a_free_week(self):
        self.term.status = AcademicTerm.Status.ARCHIVED
        self.term.save(update_fields=["status"])
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/home")

        self.assertContains(response, "No active academic term")
        self.assertNotContains(response, "nothing scheduled in the next 7 days")


class FacultyAccessibilityCopyTests(FacultyJourneyFixture):
    def test_scan_page_has_announced_code_outcome_and_persistent_error_regions(self):
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/scan?manual=1")

        self.assertContains(response, 'id="otp-value"')
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, "showResolveError")

    def test_absence_recovery_points_to_ifo_not_checker(self):
        self.client.force_login(self.faculty)
        session = self.make_session(
            day_offset=0,
            status=SessionStatus.ABSENT,
            code="ABS101",
        )

        response = self.client.get("/faculty/online")

        # The session is F2F and therefore absent from Online; exercise the
        # shared scan outcome template directly through its rendered source.
        from django.template.loader import render_to_string
        from scheduling import resolver as R
        html = render_to_string(
            "faculty/_outcome.html",
            {
                "resolution": R.Resolution(R.ABSENT, session.pk),
                "session": session,
                "room": self.room,
            },
            request=response.wsgi_request,
        )
        self.assertIn("IFO office", html)
        self.assertNotIn("Checker can correct", html)

    def test_photo_upload_status_is_announced(self):
        self.client.force_login(self.faculty)

        response = self.client.get("/faculty/profile")

        self.assertContains(
            response,
            'id="photo-status" role="status" aria-live="polite"',
        )


@override_settings(DEBUG=True)
class ScanLoginReturnPathTests(FacultyJourneyFixture):
    def test_dev_login_returns_faculty_to_scanned_qr(self):
        response = self.client.post(
            "/login",
            {
                "username": self.faculty.username,
                "next": "/scan?t=journey-room",
            },
        )

        self.assertRedirects(
            response,
            "/scan?t=journey-room",
            fetch_redirect_response=False,
        )

    def test_login_page_forwards_safe_next_to_microsoft_and_dev_forms(self):
        response = self.client.get("/login?next=/scan%3Ft%3Djourney-room")

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            'name="next" value="/scan?t=journey-room"',
        )

    def test_login_rejects_external_return_path(self):
        response = self.client.post(
            "/login",
            {
                "username": self.faculty.username,
                "next": "https://evil.example/steal",
            },
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)

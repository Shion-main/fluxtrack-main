"""Dean direct modality override: department scope, consequences, and UI."""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from ops.models import AuditLog, Notification
from scheduling import services
from scheduling.models import (
    Modality,
    ModalityShiftStatus,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.test_support import MANILA, make_shift_fixture


def _move_to_tomorrow(session):
    day = timezone.localdate() + timedelta(days=1)
    session.date = day
    session.scheduled_start = datetime.combine(day, time(8, 0), tzinfo=MANILA)
    session.scheduled_end = datetime.combine(day, time(9, 30), tzinfo=MANILA)
    session.status = SessionStatus.SCHEDULED
    session.save(update_fields=[
        "date", "scheduled_start", "scheduled_end", "status",
    ])
    return session


class DeanModalityOverrideServiceTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("dov")
        _move_to_tomorrow(self.fx.session)
        self.ifo = get_user_model().objects.create(
            username="dov_ifo", role=Role.IFO_ADMIN, is_active=True)

    def _override(self, **kwargs):
        service = getattr(services, "dean_override_modality", None)
        self.assertIsNotNone(
            service, "dean_override_modality service has not been implemented")
        values = {
            "session": self.fx.session,
            "dean": self.fx.dean,
            "target_modality": Modality.ONLINE,
            "reason": "Campus transport disruption.",
            "now": timezone.now(),
        }
        values.update(kwargs)
        return service(**values)

    def test_department_dean_override_applies_and_is_distinctly_audited(self):
        result = self._override()

        self.assertEqual(result.status, ModalityShiftStatus.APPROVED)
        self.assertTrue(result.is_dean_override)
        self.assertEqual(result.request_reason, "Campus transport disruption.")
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.ONLINE)
        self.assertIsNotNone(self.fx.session.room_released_at)
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.dean_override",
            target_id=str(result.pk),
        ).exists())
        self.assertTrue(Notification.objects.filter(
            user=self.fx.faculty, type="modality_overridden").exists())
        self.assertTrue(Notification.objects.filter(
            user=self.ifo, type="modality_shift_applied").exists())

    def test_other_department_dean_cannot_override(self):
        other = make_shift_fixture("exx")

        with self.assertRaises(services.ModalityShiftError):
            self._override(dean=other.dean)

        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, "")

    def test_override_requires_reason_and_a_real_change(self):
        with self.assertRaises(services.ModalityShiftError):
            self._override(reason="  ")
        with self.assertRaises(services.ModalityShiftError):
            self._override(target_modality=Modality.F2F)

    def test_override_rejects_reason_over_storage_limit(self):
        with self.assertRaises(services.ModalityShiftError):
            self._override(reason="x" * 501)

    def test_override_back_to_physical_restores_room_occupancy(self):
        self._override()

        self._override(
            target_modality=Modality.F2F,
            reason="Return to on-campus delivery.",
        )

        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.F2F)
        self.assertIsNone(self.fx.session.room_released_at)

    def test_bulk_override_applies_each_selected_session(self):
        second_date = timezone.localdate() + timedelta(days=2)
        second = Session.objects.create(
            schedule=self.fx.f2f_schedule,
            faculty=self.fx.faculty,
            room=self.fx.room_a,
            date=second_date,
            scheduled_start=datetime.combine(
                second_date, time(8, 0), tzinfo=MANILA),
            scheduled_end=datetime.combine(
                second_date, time(9, 30), tzinfo=MANILA),
            status=SessionStatus.SCHEDULED,
        )
        bulk_override = getattr(
            services, "dean_bulk_override_modality", None)
        self.assertIsNotNone(
            bulk_override,
            "dean_bulk_override_modality service has not been implemented")

        results = bulk_override(
            sessions=[self.fx.session, second],
            dean=self.fx.dean,
            target_modality=Modality.ONLINE,
            reason="Department-wide remote delivery day.",
            now=timezone.now(),
        )

        self.assertEqual(len(results), 2)
        self.fx.session.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.ONLINE)
        self.assertEqual(second.declared_modality, Modality.ONLINE)

    def test_bulk_override_rolls_back_every_session_when_one_is_invalid(self):
        with self.assertRaises(services.ModalityShiftError):
            services.dean_bulk_override_modality(
                sessions=[self.fx.session, self.fx.online_session],
                dean=self.fx.dean,
                target_modality=Modality.ONLINE,
                reason="Department-wide remote delivery day.",
                now=timezone.now(),
            )

        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, "")
        self.assertFalse(AuditLog.objects.filter(
            event_type="modality_shift.dean_override",
        ).exists())


class DeanModalityOverrideViewTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("dvw")
        _move_to_tomorrow(self.fx.session)

    def test_faculty_navigation_and_roster_replace_modality_destination(self):
        other = make_shift_fixture("qxx")
        self.client.force_login(self.fx.dean)

        navigation = self.client.get("/dean/dashboard")
        response = self.client.get("/dean/faculty")

        self.assertContains(navigation, 'href="/dean/faculty"')
        self.assertContains(navigation, "> Faculty</a>")
        self.assertNotContains(navigation, "> Modality override</a>")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.fx.faculty.username)
        self.assertContains(response, self.fx.competitor_faculty.username)
        self.assertNotContains(response, other.faculty.username)
        self.assertContains(
            response, f'/dean/faculty/{self.fx.faculty.pk}')

    def test_old_modality_url_redirects_into_faculty_workspace(self):
        self.client.force_login(self.fx.dean)

        roster = self.client.get("/dean/modality/override")
        detail = self.client.get(
            "/dean/modality/override",
            {"faculty": str(self.fx.faculty.pk)},
        )

        self.assertRedirects(
            roster, "/dean/faculty", fetch_redirect_response=False)
        self.assertRedirects(
            detail,
            f"/dean/faculty/{self.fx.faculty.pk}",
            fetch_redirect_response=False,
        )

    def test_faculty_roster_cards_show_identity_photo_and_name(self):
        self.fx.faculty.first_name = "Avery"
        self.fx.faculty.last_name = "Santos"
        self.fx.faculty.profile_photo.name = "profile_photos/avery.jpg"
        self.fx.faculty.save(update_fields=[
            "first_name", "last_name", "profile_photo",
        ])
        self.client.force_login(self.fx.dean)

        response = self.client.get("/dean/faculty")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Avery Santos")
        self.assertContains(
            response, f'/profile/photo/{self.fx.faculty.pk}')
        self.assertContains(response, 'class="dn-faculty-card')

    def test_faculty_detail_shows_profile_recurring_schedule_and_upcoming_session(self):
        _move_to_tomorrow(self.fx.competitor)
        self.fx.faculty.first_name = "Avery"
        self.fx.faculty.last_name = "Santos"
        self.fx.faculty.save(update_fields=["first_name", "last_name"])
        self.client.force_login(self.fx.dean)

        response = self.client.get(
            f"/dean/faculty/{self.fx.faculty.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Avery Santos")
        self.assertContains(response, self.fx.faculty.email)
        self.assertContains(response, "Recurring schedule")
        self.assertContains(response, "Upcoming sessions")
        self.assertContains(response, self.fx.f2f_schedule.course_code)
        self.assertNotContains(
            response, self.fx.competitor.schedule.course_code)

    def test_faculty_detail_uses_canonical_badges_for_every_modality(self):
        Schedule.objects.create(
            term=self.fx.term,
            course_code="BLEND101",
            section="A",
            faculty=self.fx.faculty,
            room=self.fx.room_b,
            day_of_week=1,
            start_time=time(13, 0),
            end_time=time(14, 30),
            modality=Modality.BLENDED,
        )
        _move_to_tomorrow(self.fx.online_session)
        self.client.force_login(self.fx.dean)

        response = self.client.get(
            f"/dean/faculty/{self.fx.faculty.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "modality-badge--f2f")
        self.assertContains(response, "modality-badge--blended")
        self.assertContains(response, "modality-badge--online")
        self.assertContains(response, ">Face-to-face<")
        self.assertContains(response, ">Blended<")
        self.assertContains(response, ">Online<")
        self.assertNotContains(response, "Unknown modality")
        self.assertContains(response, 'class="dn-session__controls"')

    def test_faculty_detail_uses_one_change_form_for_single_or_multiple_sessions(self):
        self.client.force_login(self.fx.dean)

        response = self.client.get(
            f"/dean/faculty/{self.fx.faculty.pk}")
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select one or more sessions")
        self.assertContains(response, "Choose the new modality")
        self.assertContains(response, 'class="dn-change-flow"')
        self.assertContains(response, 'type="radio"')
        self.assertEqual(body.count('name="target_modality"'), 3)
        self.assertNotContains(response, "Change this session's modality")
        self.assertNotContains(response, 'class="dn-override')

    def test_cross_department_faculty_selection_is_not_found(self):
        other = make_shift_fixture("qxy")
        self.client.force_login(self.fx.dean)

        response = self.client.get(
            f"/dean/faculty/{other.faculty.pk}")

        self.assertEqual(response.status_code, 404)

    def test_dean_can_submit_single_override_from_faculty_detail(self):
        self.client.force_login(self.fx.dean)

        response = self.client.post(
            f"/dean/faculty/{self.fx.faculty.pk}", {
            "session": str(self.fx.session.pk),
            "target_modality": Modality.ONLINE,
            "reason": "Dean-authorized emergency remote delivery.",
        })

        self.assertEqual(response.status_code, 200)
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.ONLINE)
        self.assertContains(response, "Modality changed successfully")

    def test_dean_can_bulk_override_selected_upcoming_sessions(self):
        second_date = timezone.localdate() + timedelta(days=2)
        second = Session.objects.create(
            schedule=self.fx.f2f_schedule,
            faculty=self.fx.faculty,
            room=self.fx.room_a,
            date=second_date,
            scheduled_start=datetime.combine(
                second_date, time(8, 0), tzinfo=MANILA),
            scheduled_end=datetime.combine(
                second_date, time(9, 30), tzinfo=MANILA),
            status=SessionStatus.SCHEDULED,
        )
        self.client.force_login(self.fx.dean)

        response = self.client.post(
            f"/dean/faculty/{self.fx.faculty.pk}", {
                "action": "bulk_override",
                "sessions": [
                    str(self.fx.session.pk),
                    str(second.pk),
                ],
                "target_modality": Modality.ONLINE,
                "reason": "Department-wide remote delivery day.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.fx.session.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.ONLINE)
        self.assertEqual(second.declared_modality, Modality.ONLINE)
        self.assertContains(response, "2 sessions changed successfully")

    def test_unified_form_uses_singular_confirmation_for_one_session(self):
        self.client.force_login(self.fx.dean)

        response = self.client.post(
            f"/dean/faculty/{self.fx.faculty.pk}", {
                "action": "bulk_override",
                "sessions": [str(self.fx.session.pk)],
                "target_modality": Modality.ONLINE,
                "reason": "One class needs remote delivery.",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 session changed successfully")
        self.assertNotContains(response, "1 sessions changed successfully")

    def test_non_dean_is_forbidden(self):
        self.client.force_login(self.fx.faculty)
        url = f"/dean/faculty/{self.fx.faculty.pk}"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_forged_cross_department_session_is_not_found(self):
        other = make_shift_fixture("ryy")
        _move_to_tomorrow(other.session)
        self.client.force_login(self.fx.dean)

        response = self.client.post(
            f"/dean/faculty/{self.fx.faculty.pk}", {
            "session": str(other.session.pk),
            "target_modality": Modality.ONLINE,
            "reason": "Forged cross-department attempt.",
        })

        self.assertEqual(response.status_code, 404)

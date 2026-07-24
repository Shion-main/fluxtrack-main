"""Request-content and presentation regressions from the modality-flow audit."""
from datetime import datetime, time, timedelta
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scheduling.models import (
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Session,
    SessionStatus,
)
from scheduling.test_support import make_shift_fixture


class ModalityRequestDetailsBase(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("mard")
        self.future_date = timezone.localdate() + timedelta(days=30)
        self.future_session = Session.objects.create(
            schedule=self.fx.f2f_schedule,
            faculty=self.fx.faculty,
            room=self.fx.room_a,
            date=self.future_date,
            scheduled_start=timezone.make_aware(
                datetime.combine(self.future_date, time(8, 0))
            ),
            scheduled_end=timezone.make_aware(
                datetime.combine(self.future_date, time(9, 30))
            ),
            status=SessionStatus.SCHEDULED,
        )
        self.client.force_login(self.fx.faculty)

    def _post(self, **overrides):
        data = {
            "target_modality": Modality.ONLINE,
            "window_mode": "single",
            "on_date": self.future_date.isoformat(),
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "request_reason": "Recovering from surgery; class will meet on Teams.",
        }
        data.update(overrides)
        return self.client.post(reverse("faculty_modality_new"), data)


class ModalityRationaleTests(ModalityRequestDetailsBase):
    def test_form_requires_faculty_reason(self):
        response = self.client.get(reverse("faculty_modality_new"))

        self.assertContains(response, 'name="request_reason"')
        self.assertContains(response, 'name="request_reason"', html=False)
        self.assertContains(response, "required")

    def test_blank_reason_is_refused(self):
        response = self._post(request_reason="   ")

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "Tell your Dean why this change is needed",
            status_code=400,
        )

    def test_reason_over_500_characters_is_refused_cleanly(self):
        self.client.raise_request_exception = False
        response = self._post(request_reason="x" * 501)

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "500 characters or fewer",
            status_code=400,
        )

    def test_reason_is_persisted_and_shown_to_dean(self):
        reason = "Recovering from surgery; class will meet on Teams."

        response = self._post(request_reason=reason)

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            "request_reason",
            [field.name for field in ModalityShiftRequest._meta.fields],
        )
        request = ModalityShiftRequest.objects.get(requester=self.fx.faculty)
        self.assertEqual(request.request_reason, reason)

        self.client.force_login(self.fx.dean)
        queue = self.client.get(reverse("dean_queue"))
        self.assertContains(queue, reason)


class ModalityFieldSemanticsTests(ModalityRequestDetailsBase):
    def test_online_submission_ignores_hidden_room_and_time_values(self):
        response = self._post(
            new_start_time="14:00",
            new_end_time="15:00",
            **{f"preferred_room_{self.fx.f2f_schedule.pk}": str(self.fx.room_b.pk)},
        )

        self.assertEqual(response.status_code, 302)
        item = ModalityShiftItem.objects.get(
            request__requester=self.fx.faculty
        )
        self.assertIsNone(item.preferred_room_id)
        self.assertIsNone(item.new_start_time)
        self.assertIsNone(item.new_end_time)

    def test_form_exposes_exact_occurrences_for_review(self):
        response = self.client.get(reverse("faculty_modality_new"))

        self.assertContains(
            response,
            f'data-occurrences="{self.future_date.isoformat()}"',
        )


class ModalityRequestHistoryTests(ModalityRequestDetailsBase):
    def test_my_requests_shows_rationale_requested_and_assigned_details(self):
        self.assertIn(
            "request_reason",
            [field.name for field in ModalityShiftRequest._meta.fields],
        )
        request = ModalityShiftRequest.objects.create(
            requester=self.fx.faculty,
            dean=self.fx.dean,
            department=self.fx.dept,
            target_modality=Modality.F2F,
            window_start=self.future_date,
            window_end=self.future_date,
            request_reason="Students need an in-person laboratory.",
            status=ModalityShiftStatus.APPROVED,
            decided_by=self.fx.dean,
            decided_at=timezone.now(),
        )
        ModalityShiftItem.objects.create(
            request=request,
            schedule=self.fx.f2f_schedule,
            preferred_room=self.fx.room_a,
            assigned_room=self.fx.room_b,
            new_start_time=time(14, 0),
            new_end_time=time(15, 0),
        )

        response = self.client.get(reverse("faculty_modality_mine"))

        self.assertContains(response, "Students need an in-person laboratory.")
        self.assertContains(response, "2:00 PM")
        self.assertContains(response, "modality-badge--f2f")
        self.assertContains(response, ">Face-to-face<")
        self.assertContains(response, f"Preferred: {self.fx.room_a.code}")
        self.assertContains(response, f"Assigned: {self.fx.room_b.code}")
        self.assertContains(response, self.fx.dean.get_full_name() or self.fx.dean.username)


class ModalitySafetyMarkupTests(TestCase):
    def test_review_summary_does_not_insert_class_label_as_html(self):
        source = Path("static/faculty/modality.js").read_text(encoding="utf-8")

        self.assertNotIn(
            '"<b>" + sel[0].dataset.label + "</b>"',
            source,
        )

    def test_approval_and_withdrawal_require_confirmation(self):
        dean = Path("templates/dean/_queue.html").read_text(encoding="utf-8")
        faculty = Path(
            "templates/faculty/modality_mine.html"
        ).read_text(encoding="utf-8")

        self.assertIn("confirm(", dean)
        self.assertIn("confirm(", faculty)

    def test_review_summary_includes_requested_time_and_room_preference(self):
        source = Path("static/faculty/modality.js").read_text(encoding="utf-8")

        self.assertIn("Requested time:", source)
        self.assertIn("Preferred room for ", source)

"""Regression tests for the modality-request workflow audit."""
import inspect
from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from ops.availability import free_rooms_in_building
from scheduling import services
from scheduling.models import (
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.test_support import IN_WINDOW_DATE, make_shift_fixture


class ModalityApprovalAuditTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("mafa")

    def _pending(self):
        request = ModalityShiftRequest.objects.create(
            requester=self.fx.faculty,
            dean=self.fx.dean,
            department=self.fx.dept,
            target_modality=Modality.ONLINE,
            window_start=IN_WINDOW_DATE,
            window_end=IN_WINDOW_DATE,
            status=ModalityShiftStatus.PENDING,
        )
        ModalityShiftItem.objects.create(
            request=request,
            schedule=self.fx.f2f_schedule,
        )
        return request

    def test_approval_denies_request_when_no_actionable_sessions_remain(self):
        request = self._pending()
        self.fx.session.status = SessionStatus.COMPLETED
        self.fx.session.save(update_fields=["status"])

        result = services.apply_approval(request, self.fx.dean)

        self.assertEqual(result.status, ModalityShiftStatus.DENIED)
        self.assertIn("no sessions", result.decision_reason.lower())

    def test_out_of_service_rooms_are_not_availability_candidates(self):
        self.fx.room_b.out_of_service = True
        self.fx.room_b.out_of_service_reason = "Aircon repair"
        self.fx.room_b.save(
            update_fields=["out_of_service", "out_of_service_reason"]
        )

        rooms = free_rooms_in_building(
            self.fx.building,
            self.fx.online_session.scheduled_start,
            self.fx.online_session.scheduled_end,
            exclude_session_id=self.fx.online_session.pk,
        )

        self.assertNotIn(self.fx.room_b.pk, [room.pk for room in rooms])

    def test_duplicate_guard_runs_after_the_term_lock(self):
        source = inspect.getsource(services.submit_modality_shift)

        self.assertIn("_has_recent_modality_request", source)
        self.assertLess(
            source.index("_lock_writable_term"),
            source.index("_has_recent_modality_request"),
        )


class ModalitySubmissionAuditTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("mafs")

    def test_one_time_move_cannot_apply_to_multiple_classes(self):
        second_start = time(12, 0)
        second_end = time(13, 0)
        second_schedule = Schedule.objects.create(
            term=self.fx.term,
            course_code="MAF202",
            section="B",
            faculty=self.fx.faculty,
            room=self.fx.room_b,
            day_of_week=IN_WINDOW_DATE.weekday(),
            start_time=second_start,
            end_time=second_end,
            modality=Modality.F2F,
        )
        Session.objects.create(
            schedule=second_schedule,
            faculty=self.fx.faculty,
            room=self.fx.room_b,
            date=IN_WINDOW_DATE,
            scheduled_start=timezone.make_aware(
                datetime.combine(IN_WINDOW_DATE, second_start)
            ),
            scheduled_end=timezone.make_aware(
                datetime.combine(IN_WINDOW_DATE, second_end)
            ),
            status=SessionStatus.SCHEDULED,
        )

        with self.assertRaisesMessage(
            services.ModalityShiftError,
            "one class",
        ):
            services.submit_modality_shift(
                self.fx.faculty,
                [self.fx.f2f_schedule, second_schedule],
                Modality.F2F,
                IN_WINDOW_DATE,
                IN_WINDOW_DATE,
                time_move=(time(14, 0), time(15, 0)),
                now=timezone.make_aware(
                    datetime.combine(
                        IN_WINDOW_DATE - timedelta(days=10),
                        time(8, 0),
                    )
                ),
            )

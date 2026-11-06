"""Operational allocation invariants against the real SQL Server backend."""
from datetime import time, timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.db import close_old_connections
from django.utils import timezone

from ops.availability import room_is_free
from ops.models import AuditLog, Booking
from scheduling.models import Modality, ModalityShiftItem, ModalityShiftRequest, ModalityShiftStatus
from scheduling.schedule_ops import update_schedule
from web.tests_schedule_ops import ScheduleFixture, _term


class AllocationHardeningTests(TestCase):
    def setUp(self):
        self.fx = ScheduleFixture(_term())
        self.start = timezone.make_aware(timezone.datetime.combine(self.fx.today, time(12)))
        self.end = self.start + timedelta(hours=1)

    def test_closed_room_is_never_available(self):
        self.fx.room2.out_of_service = True
        self.fx.room2.save()
        self.assertFalse(room_is_free(self.fx.room2, self.start, self.end))

    def test_booking_rejects_overlap_and_audit_rollback(self):
        from ops.bookings import create_booking
        kwargs = dict(room=self.fx.room2, actor=self.fx.faculty, occupant_name="Visitor",
                      purpose="Meeting", start=self.start, end=self.end)
        with patch("ops.bookings.AuditLog.objects.create", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                create_booking(**kwargs)
        self.assertFalse(Booking.objects.exists())
        create_booking(**kwargs)
        with self.assertRaises(ValueError):
            create_booking(**kwargs)
        self.assertEqual(Booking.objects.count(), 1)

    def test_new_schedule_cannot_double_book_room_or_faculty(self):
        from scheduling.schedule_ops import create_schedule
        base = dict(term=self.fx.term, course_code="OTHER", section="B",
                    day_of_week=self.fx.today.weekday(), start_time=time(8),
                    end_time=time(9), enrolled_count=10, modality=Modality.F2F)
        for faculty, room in ((self.fx.faculty2, self.fx.room1), (self.fx.faculty, self.fx.room2)):
            with self.assertRaises(ValueError):
                create_schedule(**base, faculty=faculty, room=room)

    def test_legitimate_merged_section_can_be_added(self):
        from scheduling.schedule_ops import create_schedule
        merged = create_schedule(term=self.fx.term, course_code=self.fx.schedule.course_code,
            section="B", faculty=self.fx.faculty, room=self.fx.room1,
            day_of_week=self.fx.today.weekday(), start_time=time(8), end_time=time(9,30),
            enrolled_count=20, modality=Modality.F2F)
        self.assertIsNotNone(merged.pk)

    def test_draft_schedule_create_and_edit_reject_room_overlap(self):
        from scheduling.models import AcademicTerm, Schedule
        from scheduling.schedule_ops import create_schedule
        self.fx.term.status = AcademicTerm.Status.DRAFT
        self.fx.term.save(update_fields=["status"])
        base = dict(term=self.fx.term, course_code="DRAFT", section="B",
            faculty=self.fx.faculty2, room=self.fx.room1,
            day_of_week=self.fx.today.weekday(), start_time=time(8,30),
            end_time=time(10), modality=Modality.F2F)
        with self.assertRaisesMessage(ValueError, "room is occupied"):
            create_schedule(**base)
        self.assertFalse(Schedule.objects.filter(course_code="DRAFT").exists())
        base.update(room=self.fx.room2)
        moving = create_schedule(**base)
        with self.assertRaisesMessage(ValueError, "room is occupied"):
            update_schedule(moving, room=self.fx.room1)
        moving.refresh_from_db()
        self.assertEqual(moving.room_id, self.fx.room2.pk)

    def test_draft_merged_sections_and_adjacent_slots_remain_valid(self):
        from scheduling.models import AcademicTerm
        from scheduling.schedule_ops import create_schedule
        self.fx.term.status = AcademicTerm.Status.DRAFT
        self.fx.term.save(update_fields=["status"])
        base = dict(term=self.fx.term, course_code=self.fx.schedule.course_code,
            section="B", faculty=self.fx.faculty, room=self.fx.room1,
            day_of_week=self.fx.today.weekday(), start_time=time(8),
            end_time=time(9,30), modality=Modality.F2F)
        self.assertIsNotNone(create_schedule(**base).pk)
        base.update(course_code="ADJACENT", section="C", faculty=self.fx.faculty2,
                    start_time=time(9,30), end_time=time(10))
        self.assertIsNotNone(create_schedule(**base).pk)

    def test_faculty_edit_cannot_conflict_beyond_materialization(self):
        from scheduling.models import Schedule
        Schedule.objects.create(term=self.fx.term, course_code="OTHER", section="A",
            faculty=self.fx.faculty2, room=self.fx.room2, day_of_week=self.fx.today.weekday(),
            start_time=time(8,30), end_time=time(10))
        with self.assertRaises(ValueError):
            update_schedule(self.fx.schedule, faculty=self.fx.faculty2)

    def test_superseded_physical_reservation_does_not_block_released_room(self):
        old = ModalityShiftRequest.objects.create(requester=self.fx.faculty,
            target_modality=Modality.F2F, window_start=self.fx.today, window_end=self.fx.today,
            status=ModalityShiftStatus.APPROVED, decided_at=timezone.now()-timedelta(hours=1))
        ModalityShiftItem.objects.create(request=old, schedule=self.fx.schedule, assigned_room=self.fx.room2)
        new = ModalityShiftRequest.objects.create(requester=self.fx.faculty,
            target_modality=Modality.ONLINE, window_start=self.fx.today, window_end=self.fx.today,
            status=ModalityShiftStatus.APPROVED, decided_at=timezone.now())
        ModalityShiftItem.objects.create(request=new, schedule=self.fx.schedule)
        start = timezone.make_aware(timezone.datetime.combine(self.fx.today, time(8)))
        self.assertTrue(room_is_free(self.fx.room2, start, start+timedelta(hours=1)))

    def test_malformed_schedule_form_fields_return_400(self):
        from django.contrib.auth import get_user_model
        from accounts.models import Role
        operator = get_user_model().objects.create(username="allocation-ifo", role=Role.IFO_ADMIN)
        self.client.force_login(operator)
        fields = dict(course_code="NEW", section="A", faculty=str(self.fx.faculty.pk),
            room=str(self.fx.room2.pk), day_of_week=str(self.fx.today.weekday()),
            start_time="12:00", end_time="13:00", enrolled_count="1", modality="f2f")
        for enrollment in ("abc", "-1", "999999999999999"):
            fields["enrolled_count"] = enrollment
            self.assertEqual(self.client.post("/ifo/schedules/new", fields).status_code, 400)
            self.assertEqual(self.client.post(f"/ifo/schedules/{self.fx.schedule.pk}/edit", fields).status_code, 400)
        fields.update(enrolled_count="1")
        for weekday in ("99", "\u00b2"):
            fields["day_of_week"] = weekday
            self.assertEqual(self.client.post("/ifo/schedules/new", fields).status_code, 400)


class ConcurrentBookingTests(TransactionTestCase):
    def test_simultaneous_room_claims_yield_one_booking(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from ops.bookings import create_booking
        from ops.locking import operational_write
        fx = ScheduleFixture(_term())
        start = timezone.make_aware(timezone.datetime.combine(fx.today, time(12)))
        entered, second_started, second_acquired, release = (Event() for _ in range(4))
        def reserve(first):
            close_old_connections()
            try:
                if not first:
                    second_started.set()
                with operational_write():
                    if first:
                        entered.set()
                        if not release.wait(5):
                            raise AssertionError("test lock release timed out")
                    else:
                        second_acquired.set()
                    try:
                        create_booking(room=fx.room2, actor=fx.faculty, occupant_name="Concurrent",
                            purpose="Test", start=start, end=start+timedelta(hours=1))
                        return "created"
                    except ValueError:
                        return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            winner = pool.submit(reserve, True)
            self.assertTrue(entered.wait(5))
            loser = pool.submit(reserve, False)
            try:
                self.assertTrue(second_started.wait(5))
                self.assertFalse(second_acquired.wait(0.25), "competing writer must wait for transaction")
            finally:
                release.set()
            self.assertEqual(winner.result(timeout=10), "created")
            self.assertEqual(loser.result(timeout=10), "conflict")
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(event_type="booking.created").count(), 1)

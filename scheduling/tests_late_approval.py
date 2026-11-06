"""A late Dean decision never changes a class already running (audit M8).

Requests wait in the Dean's queue, so one can be approved after its class has
begun. The decision applies to what has not started; a running class stays exactly
as it is, and a request with nothing left to change is denied with a clear reason.
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from ops.models import Notification
from scheduling.models import Modality, ModalityShiftStatus, Session, SessionStatus
from scheduling.services import apply_approval, submit_modality_shift
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture

MANILA = ZoneInfo("Asia/Manila")
NEXT_WEEK = DAY + timedelta(days=7)


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MANILA)


class LateApprovalTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("lap")
        self.fx.competitor.delete()
        self.running = self.fx.session  # 08:00-09:30 in room A

    def submit(self, target, end=DAY):
        with patch("django.utils.timezone.now", return_value=at(9, 0, DAY - timedelta(days=7))):
            return submit_modality_shift(self.fx.faculty, [self.fx.f2f_schedule],
                                         target, DAY, end, request_reason="x")

    def start_class(self):
        Session.objects.filter(pk=self.running.pk).update(
            status=SessionStatus.ACTIVE, actual_start=at(8, 1))

    def approve(self, request):
        return apply_approval(request, self.fx.dean, now=at(8, 30))

    def add_next_week(self):
        return Session.objects.create(
            schedule=self.fx.f2f_schedule, faculty=self.fx.faculty,
            room=self.fx.room_a, date=NEXT_WEEK, scheduled_start=at(8, 0, NEXT_WEEK),
            scheduled_end=at(9, 30, NEXT_WEEK))

    def test_running_class_stays_in_person_with_its_room(self):
        request = self.submit(Modality.ONLINE)
        self.start_class()
        self.approve(request)
        self.running.refresh_from_db()
        self.assertEqual(self.running.declared_modality, "")
        self.assertIsNone(self.running.room_released_at)

    def test_running_class_keeps_its_room_on_a_room_based_change(self):
        request = self.submit(Modality.BLENDED)
        Session.objects.create(  # room A is taken, so a move would pick room B
            schedule=self.fx.online_schedule, faculty=self.fx.faculty,
            room=self.fx.room_a, date=DAY, scheduled_start=at(8),
            scheduled_end=at(9, 30), declared_modality=Modality.F2F)
        self.start_class()
        self.approve(request)
        self.running.refresh_from_db()
        self.assertEqual(self.running.room_id, self.fx.room_a.pk)
        self.assertEqual(self.running.declared_modality, "")

    def test_nothing_left_to_change_is_denied_with_a_clear_reason(self):
        request = self.submit(Modality.ONLINE)
        self.start_class()
        result = self.approve(request)
        self.assertEqual(result.status, ModalityShiftStatus.DENIED)
        self.assertIn("already started", result.decision_reason)
        self.assertTrue(Notification.objects.filter(
            user=self.fx.faculty, type="modality_shift_denied").exists())

    def test_later_sessions_still_change(self):
        later = self.add_next_week()
        request = self.submit(Modality.ONLINE, end=NEXT_WEEK)
        self.start_class()
        result = self.approve(request)
        later.refresh_from_db()
        self.running.refresh_from_db()
        self.assertEqual(result.status, ModalityShiftStatus.APPROVED)
        self.assertEqual(later.declared_modality, Modality.ONLINE)
        self.assertEqual(self.running.declared_modality, "")

    def test_later_sessions_get_a_room_on_a_room_based_change(self):
        later = self.add_next_week()
        request = self.submit(Modality.BLENDED, end=NEXT_WEEK)
        self.start_class()
        self.approve(request)
        later.refresh_from_db()
        self.running.refresh_from_db()
        self.assertEqual(later.declared_modality, Modality.BLENDED)
        self.assertEqual(self.running.declared_modality, "")

    def test_on_time_approval_is_unchanged(self):
        request = self.submit(Modality.ONLINE)
        with patch("django.utils.timezone.now", return_value=at(7)):
            result = apply_approval(request, self.fx.dean)
        self.running.refresh_from_db()
        self.assertEqual(result.status, ModalityShiftStatus.APPROVED)
        self.assertEqual(self.running.declared_modality, Modality.ONLINE)

"""Checker undo (evaluation checklist 3.3, decided 2026-11-14).

A Checker who taps the wrong result can undo it for 5 minutes, from the result
screen. Rules the user chose:

  - only the same Checker, only within 5 minutes of the tap;
  - undo removes the check (the audit trail keeps both the tap and the undo);
  - an undone flag still reached IFO and HR, so they get a "Flag withdrawn"
    follow-up rather than having the original silently erased;
  - online actions change class status (Verify starts the class and its merged
    sections, a flag marks them Absent). Undo puts each changed class back
    exactly as it was, but refuses if anything has changed it since.

ASCII-only by convention (Windows cp1252).
"""
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from ops.models import AuditLog, Notification
from scheduling.models import Session, SessionStatus
from scheduling.test_support import make_merge_fixture
from verification.models import CheckerValidation
from verification.tests import _CheckerFixtureMixin
from web.tests_merge_checker import _make_online_checker


class _F2FUndoBase(_CheckerFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.checker = self._checker()
        self._active_floor_assignment(self.checker, self.floor)
        self.room = self._room()
        self.session = self._session(self.room)
        self.client.force_login(self.checker)

    def _act(self, action, note=""):
        return self.client.post("/checker/action", {
            "action": action, "room_id": self.room.id,
            "session_id": self.session.id, "note": note})

    def _cv(self, action="verified"):
        return CheckerValidation.objects.get(session=self.session, action=action)


class CheckerUndoRoomScanTests(_F2FUndoBase):

    def test_result_screen_offers_undo(self):
        r = self._act("verified")
        cv = self._cv()
        self.assertContains(r, f'hx-post="/checker/undo/{cv.pk}"')
        self.assertContains(r, "undo for 5 minutes")
        # A multi-line {# #} is not a Django comment; it would print on screen.
        self.assertNotContains(r, "{#")

    def test_already_verified_screen_offers_undo_without_template_text(self):
        self._act("verified")
        r = self.client.post("/checker/resolve", {"payload": self._qr(self.room)})
        self.assertContains(r, 'data-outcome="already-verified"')
        self.assertContains(r, f'hx-post="/checker/undo/{self._cv().pk}"')
        self.assertNotContains(r, "{#")

    def test_double_tap_response_still_offers_undo(self):
        # The second tap in the same minute writes nothing (idempotency), but
        # its response replaces the screen, so it must still carry the undo.
        self._act("verified")
        r = self._act("verified")
        cv = self._cv()
        self.assertContains(r, f'hx-post="/checker/undo/{cv.pk}"')

    def test_undo_removes_the_check_and_is_audited(self):
        self._act("verified")
        cv = self._cv()
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-outcome="undone"')
        self.assertFalse(CheckerValidation.objects.filter(pk=cv.pk).exists())
        self.assertFalse(Session.objects.get(pk=self.session.pk).verified_by_checker)
        log = AuditLog.objects.get(event_type="checker.undone")
        self.assertEqual(log.actor, self.checker)
        self.assertEqual(log.payload["action"], "verified")
        # The original tap stays on the record.
        self.assertTrue(AuditLog.objects.filter(event_type="checker.verified").exists())

    def test_checker_can_record_again_in_the_same_minute(self):
        # Undo must clear the per-minute double-tap guard, or the corrected tap
        # would show "applied" while writing nothing.
        self._act("verified")
        self.client.post(f"/checker/undo/{self._cv().pk}")
        self._act("verified")
        self.assertEqual(CheckerValidation.objects.filter(
            session=self.session, action="verified").count(), 1)

    def test_undo_refused_after_five_minutes(self):
        self._act("verified")
        cv = self._cv()
        later = cv.scanned_at + timedelta(minutes=5, seconds=1)
        with patch("web.checker.timezone.now", return_value=later):
            r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertContains(r, 'data-outcome="undo-refused"')
        self.assertContains(r, "Ask IFO")
        self.assertTrue(CheckerValidation.objects.filter(pk=cv.pk).exists())
        self.assertFalse(AuditLog.objects.filter(event_type="checker.undone").exists())

    def test_undo_allowed_at_four_minutes(self):
        self._act("verified")
        cv = self._cv()
        later = cv.scanned_at + timedelta(minutes=4, seconds=59)
        with patch("web.checker.timezone.now", return_value=later):
            self.client.post(f"/checker/undo/{cv.pk}")
        self.assertFalse(CheckerValidation.objects.filter(pk=cv.pk).exists())

    def test_another_checker_cannot_undo(self):
        self._act("verified")
        cv = self._cv()
        other = self._checker()
        self._active_floor_assignment(other, self.floor)
        self.client.force_login(other)
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(CheckerValidation.objects.filter(pk=cv.pk).exists())

    def test_undo_is_post_only(self):
        self._act("verified")
        r = self.client.get(f"/checker/undo/{self._cv().pk}")
        self.assertEqual(r.status_code, 405)

    def test_confirm_empty_can_be_undone(self):
        empty_room = self._room()
        self.client.post("/checker/action", {
            "action": "verified_empty", "room_id": empty_room.id})
        cv = CheckerValidation.objects.get(room=empty_room, action="verified_empty")
        self.client.post(f"/checker/undo/{cv.pk}")
        self.assertFalse(CheckerValidation.objects.filter(pk=cv.pk).exists())

    def test_offline_replayed_check_cannot_be_undone(self):
        self._act("verified")
        cv = self._cv()
        cv.offline_queued = True
        cv.save(update_fields=["offline_queued"])
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertContains(r, 'data-outcome="undo-refused"')
        self.assertTrue(CheckerValidation.objects.filter(pk=cv.pk).exists())


class CheckerUndoFlagTests(_F2FUndoBase):

    def test_undone_flag_tells_ifo_and_hr_it_was_withdrawn(self):
        ifo, hr = self._ifo_admin(), self._hr_admin()
        self._act("flag_not_present", note="Room empty at 10:40")
        cv = self._cv("flag_not_present")
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertContains(r, "Flag withdrawn")
        self.assertFalse(CheckerValidation.objects.filter(pk=cv.pk).exists())
        for user in (ifo, hr):
            self.assertTrue(Notification.objects.filter(
                user=user, type="checker_flag_withdrawn").exists(), user.role)
        # The original alert is kept: they may already have read it.
        self.assertEqual(Notification.objects.filter(type="checker_flag").count(), 2)

    def test_undone_verify_sends_no_notice(self):
        self._ifo_admin()
        self._act("verified")
        self.client.post(f"/checker/undo/{self._cv().pk}")
        self.assertFalse(Notification.objects.filter(
            type="checker_flag_withdrawn").exists())


class CheckerUndoOnlineTests(TestCase):
    """Online Verify / flag change class status; undo puts it back exactly."""

    def setUp(self):
        cache.clear()
        self.fx = make_merge_fixture()
        self.now = self.fx.online_anchor.scheduled_start + timedelta(minutes=20)
        clock = patch("web.checker.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.checker = _make_online_checker(self.fx)
        self.client.force_login(self.checker)
        self.anchor_pk = self.fx.online_anchor.pk
        self.sibling_pk = self.fx.online_sibling.pk

    def _state(self, pk):
        s = Session.objects.get(pk=pk)
        return (s.status, s.actual_start, s.checkin_method)

    def _act(self, action, note=""):
        return self.client.post("/checker/action", {
            "action": action, "session_id": self.anchor_pk, "note": note})

    def test_undo_verify_restores_the_class_and_its_merged_section(self):
        before = {pk: self._state(pk) for pk in (self.anchor_pk, self.sibling_pk)}
        self._act("verified")
        self.assertEqual(self._state(self.sibling_pk)[0], SessionStatus.ACTIVE)
        cv = CheckerValidation.objects.get(session_id=self.anchor_pk)
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertContains(r, 'data-outcome="undone"')
        after = {pk: self._state(pk) for pk in (self.anchor_pk, self.sibling_pk)}
        self.assertEqual(after, before)
        self.assertFalse(CheckerValidation.objects.filter(pk=cv.pk).exists())

    def test_undo_verify_keeps_a_faculty_start_that_came_first(self):
        # D16: faculty may start an online class before the Checker verifies.
        # Undoing the Verify must leave the faculty's own start in place.
        started = self.now - timedelta(minutes=5)
        Session.objects.filter(pk=self.anchor_pk).update(
            status=SessionStatus.ACTIVE, actual_start=started,
            checkin_method="online_self")
        before = self._state(self.anchor_pk)
        self._act("verified")
        cv = CheckerValidation.objects.get(session_id=self.anchor_pk)
        self.client.post(f"/checker/undo/{cv.pk}")
        self.assertEqual(self._state(self.anchor_pk), before)

    def test_undo_flag_lifts_absent_from_the_whole_group(self):
        before = {pk: self._state(pk) for pk in (self.anchor_pk, self.sibling_pk)}
        self._act("flag_not_present", note="No one in the meeting")
        self.assertEqual(self._state(self.anchor_pk)[0], SessionStatus.ABSENT)
        cv = CheckerValidation.objects.get(session_id=self.anchor_pk)
        self.client.post(f"/checker/undo/{cv.pk}")
        after = {pk: self._state(pk) for pk in (self.anchor_pk, self.sibling_pk)}
        self.assertEqual(after, before)

    def test_undo_refused_when_the_class_changed_since(self):
        self._act("verified")
        cv = CheckerValidation.objects.get(session_id=self.anchor_pk)
        # The faculty ends the class before the Checker taps Undo.
        Session.objects.filter(pk=self.anchor_pk).update(
            status=SessionStatus.COMPLETED, actual_end=self.now)
        r = self.client.post(f"/checker/undo/{cv.pk}")
        self.assertContains(r, 'data-outcome="undo-refused"')
        self.assertContains(r, "changed since")
        self.assertTrue(CheckerValidation.objects.filter(pk=cv.pk).exists())
        self.assertEqual(self._state(self.anchor_pk)[0], SessionStatus.COMPLETED)
        # Nothing half-restored: the sibling is still as the Verify left it.
        self.assertEqual(self._state(self.sibling_pk)[0], SessionStatus.ACTIVE)

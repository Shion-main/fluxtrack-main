"""End-to-end merge-propagation tests for the Checker online seam (Phase 04.2-03).

Drives ``web/checker.py:_apply_action`` through the real ``/checker/action``
endpoint (session_id, no room_id -> the online branch) for the two
status-propagating online actions:

  - an online **Verify** activates the anchor AND flips its online co-scheduled
    siblings present (ACTIVE + checkin_method=MERGED + shared actual_start + one
    ``session.merged_present`` AuditLog), in one transaction, WITHOUT consulting
    ``teams_link`` (Post-Research Clarification #1: the D-01 course_code / V-room
    key is the sole merge key); merge-filled siblings get NO CheckerValidation
    (D-09) so their ``verified_by_checker`` stays False;
  - an online **Flag-not-present** drives the whole online merged group ABSENT
    immediately (D-07 online), each sibling audited ``session.merged_absent``.

The **F2F** Checker flag path is proven RECORD-ONLY (unchanged): driving
``_apply_action`` on the F2F anchor with ``online=False`` writes the flag but does
NOT force the merged F2F group ABSENT (D-07 F2F -> the JOB-02 sweep handles it).

Imports ``make_merge_fixture`` from scheduling.test_support (the canonical GARAY
graph, Plan 01). ASCII-only by convention (Windows cp1252).
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.utils import timezone

from accounts.models import Role
from ops.models import AuditLog
from scheduling.merge import _materialize_candidates, merged_sibling_ids
from scheduling.models import CheckinMethod, Session, SessionStatus
from scheduling.test_support import make_merge_fixture
from verification.models import (Assignment, AssignmentScope, CheckerValidation,
                                 DutyRole, ValidationAction)
from web.checker import _apply_action

User = get_user_model()


def _make_online_checker(fx, username="mmf_checker"):
    """A CHECKER user on standing ONLINE duty who owns the fixture online anchor.

    Standing ONLINE posting (``date`` NULL) is always on duty, so the re-gate
    passes regardless of wall-clock (``assignment_covers_now``). ``teams_link`` is
    blanked on both online rows to prove the merge key never consults it.
    """
    checker = User.objects.create(
        username=username, email=f"{username}@mcm.edu.ph",
        role=Role.CHECKER, department=fx.dept, is_active=True)
    Assignment.objects.create(
        user=checker, role=DutyRole.CHECKER, type="standing",
        scope=AssignmentScope.ONLINE, term=fx.term, status="active")
    fx.online_anchor.online_checker = checker
    fx.online_anchor.teams_link = ""
    fx.online_anchor.save(update_fields=["online_checker", "teams_link"])
    fx.online_sibling.teams_link = ""
    fx.online_sibling.save(update_fields=["teams_link"])
    return checker


class MergeCheckerOnlineVerifyTests(TestCase):
    """Task 1: one online Verify covers the online merged siblings present."""

    def setUp(self):
        cache.clear()
        self.fx = make_merge_fixture()
        self.checker = _make_online_checker(self.fx)
        self.client.force_login(self.checker)

    def _verify_online_anchor(self):
        return self.client.post("/checker/action", {
            "action": "verified", "session_id": self.fx.online_anchor.id})

    def test_online_verify_fills_sibling_present(self):
        r = self._verify_online_anchor()
        self.assertEqual(r.status_code, 200)
        anchor = Session.objects.get(pk=self.fx.online_anchor.pk)
        sibling = Session.objects.get(pk=self.fx.online_sibling.pk)

        # Anchor genuinely verified -> ACTIVE + ONLINE_MANUAL (its real method).
        self.assertEqual(anchor.status, SessionStatus.ACTIVE)
        self.assertEqual(anchor.checkin_method, CheckinMethod.ONLINE_MANUAL)

        # Sibling merge-filled present across the online group.
        self.assertEqual(sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(sibling.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(sibling.actual_start, anchor.actual_start)

        logs = AuditLog.objects.filter(
            event_type="session.merged_present", target_id=str(sibling.pk))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().payload["merged_from"], anchor.pk)

    def test_merge_filled_sibling_has_no_checker_validation(self):
        # D-09 / CHK-04: the auto-filled sibling gets NO CheckerValidation, so
        # its verified_by_checker stays False (coverage is never inflated). The
        # scanned anchor DID get one (it was genuinely verified).
        self._verify_online_anchor()
        sibling = Session.objects.get(pk=self.fx.online_sibling.pk)
        anchor = Session.objects.get(pk=self.fx.online_anchor.pk)
        self.assertFalse(
            CheckerValidation.objects.filter(session=sibling).exists())
        self.assertFalse(sibling.verified_by_checker)
        self.assertTrue(anchor.verified_by_checker)

    def test_siblings_merge_via_course_code_without_teams_link(self):
        # Both online rows carry an EMPTY teams_link; the merge still fires via
        # the shared course_code (D-01 course arm) in two distinct V-rooms, so
        # there is provably no teams_link dependency (Post-Research Clar. #1).
        self.assertEqual(self.fx.online_anchor.teams_link, "")
        self.assertEqual(self.fx.online_sibling.teams_link, "")
        self.assertEqual(
            self.fx.online_anchor.schedule.course_code,
            self.fx.online_sibling.schedule.course_code)
        self.assertNotEqual(
            self.fx.online_anchor.room_id, self.fx.online_sibling.room_id)

        # Coupling: the seam must fill EXACTLY the pure detector's set.
        candidates = _materialize_candidates(self.fx.online_anchor)
        expected = merged_sibling_ids(self.fx.online_anchor, candidates)
        self.assertEqual(expected, {self.fx.online_sibling.pk})

        self._verify_online_anchor()
        filled = set(
            Session.objects.filter(
                faculty=self.fx.faculty, checkin_method=CheckinMethod.MERGED
            ).values_list("pk", flat=True))
        self.assertEqual(filled, expected)


class MergeCheckerOnlineFlagTests(TestCase):
    """Task 2: one online Flag-not-present fails the whole online group ABSENT."""

    def setUp(self):
        cache.clear()
        self.fx = make_merge_fixture()
        self.checker = _make_online_checker(self.fx)
        self.client.force_login(self.checker)

    def _flag_online_anchor(self, note="No attendees present in the meeting."):
        return self.client.post("/checker/action", {
            "action": "flag_not_present", "session_id": self.fx.online_anchor.id,
            "note": note})

    def test_online_flag_absents_whole_group(self):
        r = self._flag_online_anchor()
        self.assertEqual(r.status_code, 200)
        anchor = Session.objects.get(pk=self.fx.online_anchor.pk)
        sibling = Session.objects.get(pk=self.fx.online_sibling.pk)

        # Anchor absented authoritatively (as today) AND the sibling with it.
        self.assertEqual(anchor.status, SessionStatus.ABSENT)
        self.assertEqual(sibling.status, SessionStatus.ABSENT)

        logs = AuditLog.objects.filter(
            event_type="session.merged_absent", target_id=str(sibling.pk))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().payload["merged_from"], anchor.pk)

    def test_online_flag_absent_respects_status_guard(self):
        # An already-ACTIVE sibling is NOT forced ABSENT (SCHEDULED-only guard).
        self.fx.online_sibling.status = SessionStatus.ACTIVE
        self.fx.online_sibling.save(update_fields=["status"])

        self._flag_online_anchor()
        sibling = Session.objects.get(pk=self.fx.online_sibling.pk)
        self.assertEqual(sibling.status, SessionStatus.ACTIVE)
        self.assertFalse(AuditLog.objects.filter(
            event_type="session.merged_absent",
            target_id=str(sibling.pk)).exists())


class MergeCheckerF2FRecordOnlyTests(TestCase):
    """Task 2: the F2F Checker flag stays RECORD-ONLY -- it writes the flag but
    does NOT force the merged F2F group ABSENT (D-07 F2F; the sweep handles it).

    Driven directly against ``_apply_action`` with ``online=False``: the live F2F
    ``/checker/action`` path is time-gated to an in-window session, but the merge
    fixture is a fixed past date; driving ``_apply_action`` isolates exactly the
    record-only branch this plan must leave unchanged.
    """

    def setUp(self):
        cache.clear()
        self.fx = make_merge_fixture()
        self.checker = User.objects.create(
            username="mmf_f2f_checker", email="mmf_f2f_checker@mcm.edu.ph",
            role=Role.CHECKER, department=self.fx.dept, is_active=True)

    def _req(self):
        request = RequestFactory().post("/checker/action", {})
        request.user = self.checker
        return request

    def test_f2f_flag_leaves_merged_group_scheduled(self):
        _apply_action(
            self._req(), self.fx.anchor, self.fx.anchor.room,
            ValidationAction.FLAG_NOT_PRESENT, note="Room empty at scan.",
            scanned_at=timezone.now())

        anchor = Session.objects.get(pk=self.fx.anchor.pk)
        sibling = Session.objects.get(pk=self.fx.sibling.pk)

        # Record-only: NO status override on the F2F path -- anchor and sibling
        # both stay SCHEDULED, left to the JOB-02 sweep (D-08).
        self.assertEqual(anchor.status, SessionStatus.SCHEDULED)
        self.assertEqual(sibling.status, SessionStatus.SCHEDULED)

        # No group ABSENT fill happened (no merged_absent audit on the F2F path).
        self.assertFalse(
            AuditLog.objects.filter(event_type="session.merged_absent").exists())

        # ...but the flag WAS recorded (record-only still writes the validation).
        self.assertTrue(CheckerValidation.objects.filter(
            session=self.fx.anchor, action="flag_not_present").exists())

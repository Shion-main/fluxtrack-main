"""End-to-end merge-propagation tests for the faculty scan seam (Phase 04.2-02).

Drives ``web.scan._apply`` for the two present-propagating outcomes -- normal
CHECKED_IN and force-handover ROOM_OCCUPIED -- and asserts that a single faculty
check-in flips the whole D-01 merged group present (ACTIVE + MERGED + shared
actual_start + one session.merged_present AuditLog) in one transaction, while the
scanned anchor keeps its REAL checkin_method and non-merged sessions are
untouched. Also proves the seam fills EXACTLY the id set the pure detector
returns (coupling) and that re-application is idempotent.

Imports ``make_merge_fixture`` from scheduling.test_support (the canonical GARAY
graph seeded by Plan 01). ASCII-only by convention (Windows cp1252).
"""
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from accounts.models import Role
from ops.models import AuditLog
from scheduling import resolver as R
from scheduling.merge import _materialize_candidates, merged_sibling_ids
from scheduling.models import (
    CheckinMethod,
    Modality,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.test_support import make_merge_fixture
from web.scan import _apply

User = get_user_model()


def _req(user):
    """A minimal POST request carrying the acting faculty (``_apply`` reads
    ``request.user`` only)."""
    request = RequestFactory().post("/scan", {})
    request.user = user
    return request


class MergeScanCheckedInTests(TestCase):
    """Task 1: a normal faculty CHECKED_IN flips the merged group present."""

    def setUp(self):
        self.fx = make_merge_fixture()

    def _checkin_anchor(self, method=CheckinMethod.QR_SCAN):
        resolution = R.Resolution(R.CHECKED_IN, self.fx.anchor.pk)
        return _apply(_req(self.fx.faculty), resolution, self.fx.anchor.room, method)

    def test_single_scan_fills_sibling_present(self):
        self._checkin_anchor()
        anchor = Session.objects.get(pk=self.fx.anchor.pk)
        sibling = Session.objects.get(pk=self.fx.sibling.pk)

        self.assertEqual(sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(sibling.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(sibling.actual_start, anchor.actual_start)

        logs = AuditLog.objects.filter(
            event_type="session.merged_present", target_id=str(sibling.pk)
        )
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().payload["merged_from"], anchor.pk)

    def test_anchor_keeps_real_method(self):
        self._checkin_anchor(CheckinMethod.QR_SCAN)
        anchor = Session.objects.get(pk=self.fx.anchor.pk)
        self.assertEqual(anchor.status, SessionStatus.ACTIVE)
        self.assertEqual(anchor.checkin_method, CheckinMethod.QR_SCAN)
        self.assertNotEqual(anchor.checkin_method, CheckinMethod.MERGED)

    def test_control_stays_scheduled(self):
        self._checkin_anchor()
        control = Session.objects.get(pk=self.fx.control.pk)
        self.assertEqual(control.status, SessionStatus.SCHEDULED)
        self.assertNotEqual(control.checkin_method, CheckinMethod.MERGED)

    def test_filled_set_equals_detector(self):
        # Compute the pure-detector expectation on the same fixture rows...
        candidates = _materialize_candidates(self.fx.anchor)
        expected = merged_sibling_ids(self.fx.anchor, candidates)
        # ...then drive the seam and read back exactly which rows it MERGED.
        self._checkin_anchor()
        filled = set(
            Session.objects.filter(
                faculty=self.fx.faculty, checkin_method=CheckinMethod.MERGED
            ).values_list("pk", flat=True)
        )
        self.assertEqual(filled, expected)
        self.assertEqual(filled, {self.fx.sibling.pk})


class MergeScanForceHandoverTests(TestCase):
    """Task 2: a confirmed force-handover (ROOM_OCCUPIED) also propagates
    present across the merged group, while the anchor stays FORCE_HANDOVER and
    the displaced prior occupant is not merge-filled."""

    def setUp(self):
        self.fx = make_merge_fixture()
        # A DIFFERENT faculty holds the anchor's room ACTIVE (the occupant the
        # force-handover displaces). It shares neither the acting faculty nor the
        # merged group, so it must never be merge-filled (T-04.2-01 scoping).
        self.occupant = User.objects.create(
            username="mmf_occ", email="mmf_occ@mcm.edu.ph",
            role=Role.FACULTY, department=self.fx.dept, is_active=True,
        )
        anchor_sched = self.fx.anchor.schedule
        occ_sched = Schedule.objects.create(
            term=self.fx.term, course_code="OCC999", section="Z",
            faculty=self.occupant, room=self.fx.anchor.room, day_of_week=0,
            start_time=anchor_sched.start_time, end_time=anchor_sched.end_time,
            modality=Modality.F2F,
        )
        self.prior = Session.objects.create(
            schedule=occ_sched, faculty=self.occupant, room=self.fx.anchor.room,
            date=self.fx.anchor.date,
            scheduled_start=self.fx.anchor.scheduled_start,
            scheduled_end=self.fx.anchor.scheduled_end,
            status=SessionStatus.ACTIVE,
            actual_start=self.fx.anchor.scheduled_start,
        )

    def _handover(self):
        resolution = R.Resolution(
            R.ROOM_OCCUPIED, self.fx.anchor.pk, prior_session_id=self.prior.pk
        )
        return _apply(
            _req(self.fx.faculty), resolution, self.fx.anchor.room,
            CheckinMethod.QR_SCAN,
        )

    def test_force_handover_propagates_present(self):
        self._handover()
        anchor = Session.objects.get(pk=self.fx.anchor.pk)
        sibling = Session.objects.get(pk=self.fx.sibling.pk)
        prior = Session.objects.get(pk=self.prior.pk)

        # Anchor activated via handover, keeps its REAL method (never MERGED).
        self.assertEqual(anchor.status, SessionStatus.ACTIVE)
        self.assertEqual(anchor.checkin_method, CheckinMethod.FORCE_HANDOVER)

        # Sibling filled present across the group.
        self.assertEqual(sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(sibling.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(sibling.actual_start, anchor.actual_start)
        self.assertEqual(
            AuditLog.objects.filter(
                event_type="session.merged_present", target_id=str(sibling.pk)
            ).count(),
            1,
        )

        # Displaced prior occupant: auto-completed, NOT merge-filled.
        self.assertEqual(prior.status, SessionStatus.COMPLETED)
        self.assertNotEqual(prior.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(
            AuditLog.objects.filter(
                event_type="session.merged_present", target_id=str(prior.pk)
            ).count(),
            0,
        )


class MergeScanIdempotencyTests(TestCase):
    """Task 2: re-applying the same merge check-in fills the sibling exactly
    once (the helper's SCHEDULED status-guard makes propagation idempotent)."""

    def setUp(self):
        self.fx = make_merge_fixture()

    def test_repeated_checkin_fills_sibling_once(self):
        resolution = R.Resolution(R.CHECKED_IN, self.fx.anchor.pk)
        _apply(_req(self.fx.faculty), resolution, self.fx.anchor.room,
               CheckinMethod.QR_SCAN)
        first_start = Session.objects.get(pk=self.fx.sibling.pk).actual_start

        # Second application of the identical merge check-in.
        _apply(_req(self.fx.faculty), resolution, self.fx.anchor.room,
               CheckinMethod.QR_SCAN)
        sibling = Session.objects.get(pk=self.fx.sibling.pk)

        self.assertEqual(sibling.actual_start, first_start)
        self.assertEqual(sibling.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(
            AuditLog.objects.filter(
                event_type="session.merged_present",
                target_id=str(self.fx.sibling.pk),
            ).count(),
            1,
        )

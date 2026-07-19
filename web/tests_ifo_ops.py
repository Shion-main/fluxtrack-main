"""IFO operational-action tests: manual room release (IFO-08, plan 07-05).

Its own module rather than another class in web/tests.py, following the
larger-surface convention set by web/tests_ifo_board.py and web/tests_hr.py.

THE LOAD-BEARING TEST IN THIS MODULE is
`test_release_then_sweep_auto_resolves_the_flag`. It is the one that proves the
whole D-11 design end to end: IFO does exactly ONE thing -- release the session
that should not be holding the room -- and the RoomConflictFlag closes on the
next sweep because the CAUSE is gone, not because anything dismissed the
symptom. Every other test here can pass while the design is quietly wrong; that
one cannot. It is also the test that will catch a later "improvement" that adds
a manual flag-close path, which would be a second resolution route capable of
marking a flag resolved while the conflict was still live.

The second-most-skippable assertion is the audit COUNT. `release_room` writes
`session.room_released` itself, so the view must add none; asserting "an audit
row exists" would pass with two. The count is asserted exactly.

The three known pre-existing dev-login / home-redirect failures in web/tests.py
are unrelated to this module and are not chased here.

ASCII-only.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from ops.models import AuditLog, RoomConflictFlag
from scheduling.jobs import detect_room_conflicts
from scheduling.models import Session, SessionStatus
from scheduling.tests import make_session


class _IfoOpsBase(TestCase):
    """One room, one schedule, and however many sessions a test needs on it.

    Built on `scheduling.tests.make_session` for the FK chain (the project's
    factory idiom) and then extended in place: make_session mints its own
    Building/Floor/Room/Term per call, so calling it twice would collide on the
    unique Building code. Calling it once and hanging siblings off the same
    schedule is what actually produces two sessions contending for ONE room --
    which is the shape every test here needs.
    """

    def setUp(self):
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_ops", email="ifo_ops@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.faculty = User.objects.create(
            username="fac_ops", email="fac_ops@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)

        start = timezone.now() - timedelta(minutes=30)
        self.session = make_session(start, start + timedelta(hours=1))
        self.session.status = SessionStatus.ACTIVE
        self.session.save(update_fields=["status"])
        self.room = self.session.room
        self.schedule = self.session.schedule

    def _sibling(self, *, status=SessionStatus.ACTIVE):
        """A SECOND session holding the same room -- the conflict shape."""
        start = self.session.scheduled_start + timedelta(minutes=15)
        return Session.objects.create(
            schedule=self.schedule, faculty=self.session.faculty,
            room=self.room, date=self.session.date,
            scheduled_start=start, scheduled_end=start + timedelta(hours=1),
            status=status)

    def _release(self, session=None):
        session = session or self.session
        return self.client.post(
            reverse("ifo_session_release", args=[session.pk]))

    def _audit_rows(self, session=None):
        session = session or self.session
        return AuditLog.objects.filter(event_type="session.room_released",
                                       target_id=str(session.pk))


class ManualReleaseTests(_IfoOpsBase):
    """The release action itself: it stamps, it audits exactly once, it re-gates."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_release_stamps_room_released_at(self):
        self.assertIsNone(self.session.room_released_at)
        resp = self._release()
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.room_released_at)

    def test_release_writes_exactly_one_audit_row_with_the_ifo_actor(self):
        """`release_room` writes session.room_released itself. If the view adds
        its own AuditLog too, every release double-counts and "how many rooms
        did IFO release last week" stops being answerable. Exactly one."""
        self._release()
        rows = self._audit_rows()
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().actor_id, self.ifo.pk)
        self.assertEqual(rows.first().target_type, "session")

    def test_a_second_release_refuses_at_400_and_changes_nothing(self):
        """The button the operator clicked is a snapshot that may be minutes
        stale on a polled board. The server-side re-gate is the control."""
        self._release()
        self.session.refresh_from_db()
        first_stamp = self.session.room_released_at

        resp = self._release()
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "already released", status_code=400)

        self.session.refresh_from_db()
        self.assertEqual(self.session.room_released_at, first_stamp)
        self.assertEqual(self._audit_rows().count(), 1)

    def test_a_completed_session_is_not_holding_the_room(self):
        """COMPLETED and ABSENT sessions finished with the room on their own.
        Stamping a release instant for them would record an occupancy end that
        did not happen here."""
        self.session.status = SessionStatus.COMPLETED
        self.session.save(update_fields=["status"])

        resp = self._release()
        self.assertEqual(resp.status_code, 400)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)
        self.assertEqual(self._audit_rows().count(), 0)

    def test_a_get_on_the_release_url_is_405(self):
        resp = self.client.get(
            reverse("ifo_session_release", args=[self.session.pk]))
        self.assertEqual(resp.status_code, 405)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_releasing_an_unknown_session_is_a_404(self):
        resp = self.client.post(reverse("ifo_session_release", args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_the_view_never_touches_the_conflict_flag(self):
        """D-11: no manual flag-close anywhere in this plan. The release fixes
        the CAUSE; the sweep closes the flag."""
        self._sibling()
        detect_room_conflicts()
        flag = RoomConflictFlag.objects.get(resolved_at__isnull=True)

        self._release()

        flag.refresh_from_db()
        self.assertIsNone(flag.resolved_at)


class ConflictSurfaceTests(_IfoOpsBase):
    """The open-conflicts page, and the D-11 release-then-sweep handoff."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_the_page_lists_an_open_flag_with_both_contending_sessions(self):
        sibling = self._sibling()
        detect_room_conflicts()

        resp = self.client.get(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.room.code)
        self.assertContains(resp, f'data-session="{self.session.pk}"')
        self.assertContains(resp, f'data-session="{sibling.pk}"')

    def test_release_then_sweep_auto_resolves_the_flag(self):
        """THE D-11 TEST. Two ACTIVE sessions hold one room; the sweep opens a
        flag; IFO releases one of them; the next sweep finds the conflict key
        absent and stamps resolved_at through the EXISTING JOB-02c auto-resolve
        path. No code in plan 07-05 writes resolved_at -- that is the point.
        """
        self._sibling()
        detect_room_conflicts()
        flag = RoomConflictFlag.objects.get(resolved_at__isnull=True)
        self.assertIsNone(flag.resolved_at)

        resp = self._release()
        self.assertEqual(resp.status_code, 200)

        detect_room_conflicts()

        flag.refresh_from_db()
        self.assertIsNotNone(flag.resolved_at)
        self.assertFalse(
            RoomConflictFlag.objects.filter(resolved_at__isnull=True).exists())

    def test_the_page_renders_its_empty_state_when_nothing_is_flagged(self):
        resp = self.client.get(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No open room conflicts")
        self.assertContains(resp, 'data-empty="1"')

    def test_a_post_on_the_conflicts_page_is_405(self):
        resp = self.client.post(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 405)


class IfoOpsAuthzTests(_IfoOpsBase):
    """Three-way authz on both IFO-08 URLs."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.checker = User.objects.create(
            username="chk_ops", email="chk_ops@mcm.edu.ph",
            role=Role.CHECKER, is_active=True)

    def test_ifo_reaches_the_conflicts_page(self):
        self.client.force_login(self.ifo)
        self.assertEqual(
            self.client.get(reverse("ifo_conflicts")).status_code, 200)

    def test_a_non_ifo_authenticated_user_gets_403(self):
        self.client.force_login(self.faculty)
        self.assertEqual(
            self.client.get(reverse("ifo_conflicts")).status_code, 403)
        self.assertEqual(self._release().status_code, 403)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_a_checker_cannot_release_either(self):
        self.client.force_login(self.checker)
        self.assertEqual(self._release().status_code, 403)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_an_anonymous_user_is_redirected_to_login(self):
        for url in (reverse("ifo_conflicts"),
                    reverse("ifo_session_release", args=[self.session.pk])):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login", resp["Location"])

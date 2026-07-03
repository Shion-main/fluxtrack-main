"""Unit tests for the pure Checker decision cores (CHK-01, IFO-06, SRS 6.6).

The gating core and the round-robin distributor are pure: no ORM, no
timezone.now(). Both suites are SimpleTestCase, so any accidental database
access or timezone.now() call inside the cores would error the test.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from verification import resolver as R
from verification.models import AssignmentScope, ValidationAction


def state(id=1, status="active", verified=False):
    """A tiny session_state value double: .id / .status / .verified."""
    return SimpleNamespace(id=id, status=status, verified=verified)


class CheckerResolverTests(SimpleTestCase):
    def test_off_duty_refused(self):
        r = R.resolve_checker_scan([], scanned_floor_id=5, session_state=state(), now=None)
        self.assertEqual(r.outcome, R.OFF_DUTY)
        self.assertFalse(r.actionable)

    def test_wrong_floor_refused(self):
        r = R.resolve_checker_scan([1, 2], scanned_floor_id=5, session_state=state(), now=None)
        self.assertEqual(r.outcome, R.WRONG_FLOOR)
        self.assertFalse(r.actionable)

    def test_no_session_is_actionable_empty(self):
        # No session object at all -> room empty -> Verified empty is actionable.
        r = R.resolve_checker_scan([5], scanned_floor_id=5, session_state=None, now=None)
        self.assertEqual(r.outcome, R.NO_SESSION)
        self.assertTrue(r.actionable)
        # A scheduled (not yet started) session also reads as an empty room.
        r2 = R.resolve_checker_scan([5], scanned_floor_id=5,
                                    session_state=state(status="scheduled"), now=None)
        self.assertEqual(r2.outcome, R.NO_SESSION)
        self.assertTrue(r2.actionable)

    def test_absent_is_excluded(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=7, status="absent"), now=None)
        self.assertEqual(r.outcome, R.ABSENT_EXCLUDED)
        self.assertEqual(r.session_id, 7)
        self.assertFalse(r.actionable)

    def test_already_verified(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=9, status="active", verified=True),
                                   now=None)
        self.assertEqual(r.outcome, R.ALREADY_VERIFIED)
        self.assertEqual(r.session_id, 9)
        self.assertFalse(r.actionable)

    def test_active_unverified_is_actionable(self):
        r = R.resolve_checker_scan([5], scanned_floor_id=5,
                                   session_state=state(id=11, status="active", verified=False),
                                   now=None)
        self.assertEqual(r.outcome, R.ACTIVE_UNVERIFIED)
        self.assertEqual(r.session_id, 11)
        self.assertTrue(r.actionable)


class DistributeTests(SimpleTestCase):
    def test_round_robin_even_split(self):
        # 4 sessions across 2 checkers -> deterministic alternation by input order.
        result = R.distribute_online_sessions([101, 102, 103, 104], [7, 8])
        self.assertEqual(result, {101: 7, 102: 8, 103: 7, 104: 8})

    def test_empty_checkers_returns_empty(self):
        self.assertEqual(R.distribute_online_sessions([101, 102], []), {})


class ModelExtensionTests(SimpleTestCase):
    def test_confirmed_absent_not_in_choices(self):
        values = ValidationAction.values
        self.assertNotIn("confirmed_absent", values)
        self.assertNotIn("confirmed_empty", values)
        self.assertIn("verified_empty", values)  # canonical empty action stays

    def test_assignment_scope_defaults_floor(self):
        self.assertIn("floor", AssignmentScope.values)
        self.assertIn("online", AssignmentScope.values)
        from verification.models import Assignment
        self.assertEqual(
            Assignment._meta.get_field("scope").default, AssignmentScope.FLOOR
        )


# ---------------------------------------------------------------------------
# DB-backed Checker scan surface (CHK-01..05). These drive web/checker.py end
# to end through Django's test Client: an on-duty scan resolves through the pure
# core, Verify/Verified-empty are one tap, flags require a note and notify IFO +
# HR, and every action POST is re-identified + re-gated server-side against
# CURRENT on-duty state before any write (mirrors web/scan.py). RED until the
# checker resolve/action routes exist (03-02 Task 2).
# ---------------------------------------------------------------------------
from datetime import date, time, timedelta  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import TestCase  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import Role  # noqa: E402
from campus.models import Building, Floor, Room  # noqa: E402
from ops.models import AuditLog, Notification  # noqa: E402
from scheduling.models import (AcademicTerm, Modality, Schedule,  # noqa: E402
                               Session, SessionStatus)
from verification.models import (Assignment, CheckerValidation,  # noqa: E402
                                 DutyRole)


class _CheckerFixtureMixin:
    """Shared DB fixtures for the Checker scan tests.

    Each `_room()`/`_faculty()`/`_checker()`/… call mints DISTINCT unique keys
    (username, email, room code, qr_token, manual_code) so one test method can
    persist many rows without tripping a UNIQUE constraint — the same pattern as
    scheduling.tests._JobFixtureMixin.
    """

    def setUp(self):
        self.User = get_user_model()
        self.bldg = Building.objects.create(name="Checker Hall", code="CK")
        self.floor = Floor.objects.create(building=self.bldg, number=1)
        self.other_floor = Floor.objects.create(building=self.bldg, number=2)
        self.term = AcademicTerm.objects.create(
            name="Checker Term", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), is_active=True)
        self._i = 0

    def _next(self):
        self._i += 1
        return self._i

    def _room(self, floor=None):
        i = self._next()
        return Room.objects.create(
            floor=floor or self.floor, code=f"CK{i:03d}",
            qr_token=f"ck-tok-{i}", manual_code=f"7{i:05d}")

    def _faculty(self, photo=""):
        i = self._next()
        return self.User.objects.create(
            username=f"ck_fac_{i}", email=f"ck_fac_{i}@mcm.edu.ph",
            role=Role.FACULTY, first_name="Fac", last_name=f"Ulty{i}",
            profile_photo=photo)

    def _checker(self):
        i = self._next()
        return self.User.objects.create(
            username=f"ck_chk_{i}", email=f"ck_chk_{i}@mcm.edu.ph",
            role=Role.CHECKER, is_active=True)

    def _ifo_admin(self):
        i = self._next()
        return self.User.objects.create(
            username=f"ck_ifo_{i}", email=f"ck_ifo_{i}@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)

    def _hr_admin(self):
        i = self._next()
        return self.User.objects.create(
            username=f"ck_hr_{i}", email=f"ck_hr_{i}@mcm.edu.ph",
            role=Role.HR_ADMIN, is_active=True)

    def _active_floor_assignment(self, checker, floor):
        # A standing FLOOR posting (date NULL) — on duty whenever status active.
        a = Assignment.objects.create(
            user=checker, role=DutyRole.CHECKER, type="standing",
            scope="floor", term=self.term, status="active")
        a.floors.add(floor)
        return a

    def _session(self, room, *, faculty=None, status=SessionStatus.ACTIVE,
                 modality=Modality.F2F, start_delta_min=-10):
        faculty = faculty or self._faculty()
        i = self._next()
        sch = Schedule.objects.create(
            term=self.term, course_code=f"CK{i}", section="A", faculty=faculty,
            room=room, day_of_week=0, start_time=time(8, 0),
            end_time=time(9, 30), modality=modality)
        start = timezone.now() + timedelta(minutes=start_delta_min)
        return Session.objects.create(
            schedule=sch, faculty=faculty, room=room, date=timezone.localdate(),
            scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
            status=status, declared_modality="")

    def _qr(self, room):
        # QR deep-link payload — the resolver's rate-limit-free path.
        return f"?t={room.qr_token}"


class CheckerScanDBTests(_CheckerFixtureMixin, TestCase):
    def test_active_assignment_grants_scan(self):
        # No assignment -> OFF_DUTY; active FLOOR assignment on the room's floor
        # -> ACTIVE_UNVERIFIED; assignment on another floor -> WRONG_FLOOR.
        checker = self._checker()
        room = self._room()
        self._session(room)
        self.client.force_login(checker)

        r = self.client.post("/checker/resolve", {"payload": self._qr(room)})
        self.assertContains(r, 'data-outcome="off-duty"')

        assignment = self._active_floor_assignment(checker, self.floor)
        r = self.client.post("/checker/resolve", {"payload": self._qr(room)})
        self.assertContains(r, 'data-outcome="active-unverified"')

        # Re-point the assignment to a different floor -> wrong-floor refusal.
        assignment.floors.set([self.other_floor])
        r = self.client.post("/checker/resolve", {"payload": self._qr(room)})
        self.assertContains(r, 'data-outcome="wrong-floor"')

    def test_scan_returns_session_and_photo(self):
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        faculty = self._faculty(photo="profile_photos/x.jpg")
        room = self._room()
        self._session(room, faculty=faculty)
        self.client.force_login(checker)

        r = self.client.post("/checker/resolve", {"payload": self._qr(room)})
        self.assertContains(r, 'data-outcome="active-unverified"')
        # The scheduled faculty's photo reference is surfaced for identity match.
        self.assertContains(r, "profile_photos/x.jpg")

    def test_verify_marks_verified(self):
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        r = self.client.post("/checker/action", {
            "action": "verified", "room_id": room.id, "session_id": session.id})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(CheckerValidation.objects.filter(
            session=session, action="verified").exists())
        session.refresh_from_db()
        self.assertTrue(session.verified_by_checker)

    def test_flag_requires_note(self):
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        # Whitespace-only note is rejected server-side; no row, no 500.
        r = self.client.post("/checker/action", {
            "action": "flag_not_present", "room_id": room.id,
            "session_id": session.id, "note": "   "})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "note-required")
        self.assertFalse(CheckerValidation.objects.filter(
            session=session, action="flag_not_present").exists())

    def test_flag_notifies_ifo_and_hr(self):
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        ifo = self._ifo_admin()
        hr = self._hr_admin()
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        r = self.client.post("/checker/action", {
            "action": "flag_identity_mismatch", "room_id": room.id,
            "session_id": session.id, "note": "Face does not match the photo."})
        self.assertEqual(r.status_code, 200)
        cv = CheckerValidation.objects.filter(
            session=session, action="flag_identity_mismatch").first()
        self.assertIsNotNone(cv)
        self.assertFalse(cv.identity_match)  # mismatch -> identity_match False
        self.assertTrue(
            Notification.objects.filter(user=ifo, type="checker_flag").exists())
        self.assertTrue(
            Notification.objects.filter(user=hr, type="checker_flag").exists())

    def test_action_refused_when_no_longer_on_duty(self):
        # After a valid scan, the checker goes off duty. An action POST naming
        # the room is re-gated server-side against CURRENT on-duty state, refused
        # with a clear reason, and writes NO CheckerValidation (T-03-03/05).
        checker = self._checker()
        assignment = self._active_floor_assignment(checker, self.floor)
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        assignment.status = "revoked"
        assignment.save(update_fields=["status"])

        r = self.client.post("/checker/action", {
            "action": "verified", "room_id": room.id, "session_id": session.id})
        self.assertEqual(r.status_code, 200)  # refusal partial, never a 500
        self.assertContains(r, 'data-outcome="off-duty"')
        self.assertFalse(
            CheckerValidation.objects.filter(session=session).exists())

    def test_confirmed_absent_not_in_choices(self):
        # Guard for the 03-01 ValidationAction retirement (VALIDATION.md).
        values = ValidationAction.values
        self.assertNotIn("confirmed_absent", values)
        self.assertNotIn("confirmed_empty", values)
        self.assertIn("verified_empty", values)

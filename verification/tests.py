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
from scheduling.models import (AcademicTerm, CheckinMethod,  # noqa: E402
                               Modality, Schedule, Session, SessionStatus)
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

    def _online_duty_assignment(self, checker):
        # A standing ONLINE-scope CHECKER posting -> on online duty (03-05).
        return Assignment.objects.create(
            user=checker, role=DutyRole.CHECKER, type="standing",
            scope="online", term=self.term, status="active")

    def _owned_online_session(self, checker, *,
                              teams_link="https://teams.microsoft.com/l/meet-x",
                              status=SessionStatus.SCHEDULED, start_delta_min=-20):
        # An online session (schedule.modality=online) owned by `checker`.
        s = self._session(self._room(), modality=Modality.ONLINE, status=status,
                          start_delta_min=start_delta_min)
        s.online_checker = checker
        s.teams_link = teams_link
        s.save(update_fields=["online_checker", "teams_link"])
        return s


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

    def test_room_prefers_active_over_stale_absent(self):
        # CR-01 regression: a room hosting an earlier ABSENT session (8-9am) and a
        # later ACTIVE session (9-10am) — scanned mid-second-session — resolves to
        # the ACTIVE session (verifiable), NOT the stale ABSENT one that sorts
        # first by scheduled_start. Before the fix, _room_session_state returned
        # the earliest non-COMPLETED row (the ABSENT one) and latched off-duty.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        room = self._room()
        self._session(room, status=SessionStatus.ABSENT, start_delta_min=-75)
        active = self._session(room, status=SessionStatus.ACTIVE, start_delta_min=-15)
        self.client.force_login(checker)

        r = self.client.post("/checker/resolve", {"payload": self._qr(room)})
        self.assertContains(r, 'data-outcome="active-unverified"')

        # A Verify targets the genuinely-in-progress ACTIVE session.
        r2 = self.client.post("/checker/action", {
            "action": "verified", "room_id": room.id, "session_id": active.id})
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(CheckerValidation.objects.filter(
            session=active, action="verified").exists())
        active.refresh_from_db()
        self.assertTrue(active.verified_by_checker)

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

    # --- online verification path (03-05, CHK-02/03, ROADMAP #6) -----------
    def test_online_verify_activates_session(self):
        # An online Verify is the analog of a faculty check-in: it moves the
        # session out of SCHEDULED to ACTIVE with actual_start + ONLINE_MANUAL,
        # AND records a CheckerValidation(verified). Posted with session_id only
        # (no room_id) -> the online branch of /checker/action.
        checker = self._checker()
        self._online_duty_assignment(checker)
        session = self._owned_online_session(checker)
        self.client.force_login(checker)

        r = self.client.post("/checker/action", {
            "action": "verified", "session_id": session.id})
        self.assertEqual(r.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatus.ACTIVE)
        self.assertIsNotNone(session.actual_start)
        self.assertEqual(session.checkin_method, CheckinMethod.ONLINE_MANUAL)
        self.assertTrue(CheckerValidation.objects.filter(
            session=session, action="verified").exists())
        self.assertTrue(session.verified_by_checker)

    def test_online_scan_redirects_to_teams(self):
        # Opening an assigned online session surfaces its public teams_link (no
        # room-state card). A foreign checker gets a 404. An empty teams_link
        # surfaces a "no link" state and flags IFO (online_no_link).
        checker = self._checker()
        self._online_duty_assignment(checker)
        ifo = self._ifo_admin()
        session = self._owned_online_session(
            checker, teams_link="https://teams.microsoft.com/l/meet-x")
        self.client.force_login(checker)

        r = self.client.get(f"/checker/online/{session.id}")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "https://teams.microsoft.com/l/meet-x")

        # A different checker cannot open someone else's online session.
        other = self._checker()
        self.client.force_login(other)
        self.assertEqual(
            self.client.get(f"/checker/online/{session.id}").status_code, 404)

        # Empty teams_link -> no-link state + IFO flag.
        self.client.force_login(checker)
        session.teams_link = ""
        session.save(update_fields=["teams_link"])
        r2 = self.client.get(f"/checker/online/{session.id}")
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "No Teams link")
        self.assertTrue(
            Notification.objects.filter(user=ifo, type="online_no_link").exists())

    def test_online_flag_not_present_absent(self):
        # An online Flag-not-present drives the session to ABSENT authoritatively
        # (RESEARCH Open Q2 RESOLVED) and still notifies IFO + HR.
        checker = self._checker()
        self._online_duty_assignment(checker)
        ifo = self._ifo_admin()
        hr = self._hr_admin()
        session = self._owned_online_session(checker)
        self.client.force_login(checker)

        r = self.client.post("/checker/action", {
            "action": "flag_not_present", "session_id": session.id,
            "note": "No one present in the meeting."})
        self.assertEqual(r.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatus.ABSENT)
        self.assertTrue(CheckerValidation.objects.filter(
            session=session, action="flag_not_present").exists())
        self.assertTrue(
            Notification.objects.filter(user=ifo, type="checker_flag").exists())
        self.assertTrue(
            Notification.objects.filter(user=hr, type="checker_flag").exists())


# ---------------------------------------------------------------------------
# Online round-robin distribution (IFO-06) + IFO assignment-create surface.
# DistributeDBTests drive verification.services.assign_online_sessions: it reuses
# the pure R.distribute_online_sessions (03-01) and writes Session.online_checker,
# flags IFO when no online-duty Checker exists, and notifies each assigned Checker
# (CHK-02 write-only). AssignmentCreateTests drive the IFO non-admin create route
# (web/ifo.py). RED until verification.services + the IFO views/routes exist
# (Tasks 2-3): the distribute tests raise ImportError on verification.services,
# the create tests hit a 404 on the unwired route.
# ---------------------------------------------------------------------------
class DistributeDBTests(_CheckerFixtureMixin, TestCase):
    def _online_duty(self, checker):
        # A standing ONLINE-scope CHECKER posting -> eligible for round-robin.
        return Assignment.objects.create(
            user=checker, role=DutyRole.CHECKER, type="standing",
            scope="online", term=self.term, status="active")

    def _online_session(self, status=SessionStatus.SCHEDULED):
        # An online session (schedule.modality online) with no owner yet.
        return self._session(self._room(), modality=Modality.ONLINE, status=status)

    def test_no_checker_leaves_unassigned(self):
        # No online-duty Checker exists for the date -> the online session stays
        # unowned (online_checker NULL) and IFO is flagged via notify().
        from verification.services import assign_online_sessions
        ifo = self._ifo_admin()
        session = self._online_session()

        result = assign_online_sessions(timezone.localdate())

        session.refresh_from_db()
        self.assertIsNone(session.online_checker_id)
        self.assertGreaterEqual(result["unassigned"], 1)
        self.assertEqual(result["assigned"], 0)
        self.assertTrue(
            Notification.objects.filter(user=ifo, type="online_unassigned").exists())

    def test_round_robin_assigns_online_checker(self):
        # 2 online-duty Checkers + 4 online sessions -> a 2/2 round-robin split,
        # each session gets exactly one owner, and each Checker is notified once.
        from verification.services import assign_online_sessions
        c1 = self._checker()
        c2 = self._checker()
        self._online_duty(c1)
        self._online_duty(c2)
        sessions = [self._online_session() for _ in range(4)]

        result = assign_online_sessions(timezone.localdate())

        owners = []
        for s in sessions:
            s.refresh_from_db()
            owners.append(s.online_checker_id)
        self.assertNotIn(None, owners)                 # every session owned
        self.assertEqual(result["assigned"], 4)
        self.assertEqual(result["unassigned"], 0)
        self.assertEqual(owners.count(c1.id), 2)       # deterministic 2/2 split
        self.assertEqual(owners.count(c2.id), 2)
        # Each assigned Checker is notified at pre-assignment time (CHK-02).
        self.assertTrue(
            Notification.objects.filter(user=c1, type="online_assigned").exists())
        self.assertTrue(
            Notification.objects.filter(user=c2, type="online_assigned").exists())


class AssignmentCreateTests(_CheckerFixtureMixin, TestCase):
    def test_ifo_creates_floor_assignment(self):
        # An IFO POST creates a FLOOR-scope Checker assignment on the chosen floor.
        ifo = self._ifo_admin()
        checker = self._checker()
        self.client.force_login(ifo)

        r = self.client.post("/ifo/assignments/create", {
            "user": checker.id, "role": "checker", "type": "shift",
            "scope": "floor", "floors": [self.floor.id]})
        self.assertIn(r.status_code, (200, 302))
        a = Assignment.objects.filter(
            user=checker, role="checker", scope="floor").first()
        self.assertIsNotNone(a)
        self.assertIn(self.floor, list(a.floors.all()))

    def test_ifo_creates_online_duty_assignment(self):
        # scope=online creates an ONLINE assignment with no floor requirement.
        ifo = self._ifo_admin()
        checker = self._checker()
        self.client.force_login(ifo)

        r = self.client.post("/ifo/assignments/create", {
            "user": checker.id, "role": "checker", "type": "standing",
            "scope": "online"})
        self.assertIn(r.status_code, (200, 302))
        a = Assignment.objects.filter(user=checker, scope="online").first()
        self.assertIsNotNone(a)
        self.assertEqual(a.floors.count(), 0)

    def test_non_ifo_forbidden(self):
        # A Checker cannot mint duty grants — the create route is IFO-only (403).
        checker = self._checker()
        victim = self._checker()
        self.client.force_login(checker)

        r = self.client.post("/ifo/assignments/create", {
            "user": victim.id, "role": "checker", "type": "standing",
            "scope": "online"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Assignment.objects.filter(user=victim).exists())


# ---------------------------------------------------------------------------
# CHK-07 floor board (coverage %, priority queue, color cards). These drive the
# htmx-polled floor_rows partial through the test Client: ONE shared queryset
# (exclude ABSENT, F2F/Blended only, scoped to the checker's active floors)
# feeds the cards, the oldest-first priority queue, AND the coverage
# denominator (Pitfall 5) — so the numbers can never disagree. RED until the
# /checker/floor/rows route + floor_rows view exist (03-04 Task 2).
# ---------------------------------------------------------------------------
class FloorBoardTests(_CheckerFixtureMixin, TestCase):
    def _verify(self, session, checker):
        return CheckerValidation.objects.create(
            session=session, room=session.room, checker=checker,
            action="verified", identity_match=True)

    def test_coverage_excludes_absent(self):
        # 2 verified + 1 unverified active on the floor, plus 1 ABSENT session.
        # Coverage = verified / active-excluding-absent; the ABSENT session is
        # neither carded nor in the denominator; fully verifying reads 100.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        v1 = self._session(self._room())
        v2 = self._session(self._room())
        unverified = self._session(self._room())
        absent = self._session(self._room(), status=SessionStatus.ABSENT)
        self._verify(v1, checker)
        self._verify(v2, checker)
        self.client.force_login(checker)

        r = self.client.get("/checker/floor/rows")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["total"], 3)          # ABSENT out of denominator
        self.assertEqual(r.context["verified"], 2)
        self.assertEqual(r.context["coverage"], 67)      # round(100*2/3)
        self.assertNotContains(r, absent.room.code)      # ABSENT never carded

        # Verifying the last active session brings the floor to 100%.
        self._verify(unverified, checker)
        r = self.client.get("/checker/floor/rows")
        self.assertEqual(r.context["verified"], 3)
        self.assertEqual(r.context["coverage"], 100)

    def test_priority_queue_oldest_first(self):
        # Among active-unverified sessions, the queue is oldest-scheduled first
        # (longest-waiting on top).
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        mid = self._session(self._room(), start_delta_min=-20)
        oldest = self._session(self._room(), start_delta_min=-40)
        newest = self._session(self._room(), start_delta_min=-5)
        self.client.force_login(checker)

        r = self.client.get("/checker/floor/rows")
        queue_ids = [s.id for s in r.context["queue"]]
        self.assertEqual(queue_ids, [oldest.id, mid.id, newest.id])

    def test_board_excludes_online(self):
        # An ONLINE session on the floor's rooms is not on the F2F/Blended board.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        f2f = self._session(self._room())
        online = self._session(self._room(), modality=Modality.ONLINE)
        self.client.force_login(checker)

        r = self.client.get("/checker/floor/rows")
        self.assertEqual(r.context["total"], 1)          # only the F2F session
        self.assertContains(r, f2f.room.code)
        self.assertNotContains(r, online.room.code)

    def test_board_scoped_to_active_floor(self):
        # A session on a floor the checker is NOT assigned to does not appear.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        mine = self._session(self._room(self.floor))
        theirs = self._session(self._room(self.other_floor))
        self.client.force_login(checker)

        r = self.client.get("/checker/floor/rows")
        self.assertEqual(r.context["total"], 1)
        self.assertContains(r, mine.room.code)
        self.assertNotContains(r, theirs.room.code)


# ---------------------------------------------------------------------------
# Offline replay (CHK-08). ReplayTests drives POST /checker/replay: each queued
# item is RE-VALIDATED against CURRENT state through the SAME pure gating core
# (never the offline snapshot) — a still-actionable item applies with the
# ORIGINAL scanned_at preserved; a stale item (current state no longer
# actionable) is NOT applied, is recorded via AuditLog(checker.replay_conflict),
# and flags IFO via notify(); a repeated client_uuid never double-applies. RED
# until the /checker/replay route + web.checker.replay view exist (Task 2).
# ---------------------------------------------------------------------------
import json  # noqa: E402
import uuid  # noqa: E402


class ReplayTests(_CheckerFixtureMixin, TestCase):
    def _post_replay(self, items):
        return self.client.post(
            "/checker/replay", data=json.dumps({"items": items}),
            content_type="application/json")

    def test_valid_replay_applies(self):
        # A queued scan whose CURRENT room/session state is still actionable is
        # applied — CheckerValidation(offline_queued=True) with scanned_at ==
        # the original offline timestamp (not now).
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        original_scanned_at = timezone.now() - timedelta(minutes=15)
        client_uuid = str(uuid.uuid4())
        r = self._post_replay([{
            "client_uuid": client_uuid, "token": room.qr_token,
            "action": "verified", "note": "",
            "scanned_at": original_scanned_at.isoformat()}])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["status"], "applied")

        cv = CheckerValidation.objects.filter(
            session=session, action="verified", offline_queued=True).first()
        self.assertIsNotNone(cv)
        self.assertEqual(cv.scanned_at, original_scanned_at)
        session.refresh_from_db()
        self.assertTrue(session.verified_by_checker)

    def test_stale_replay_flags_ifo(self):
        # The session is currently ABSENT (ended/handed-over/already resolved
        # between the offline scan and the replay) -> NOT applied (no verifying
        # CheckerValidation), an AuditLog(checker.replay_conflict) is written,
        # and IFO is notified via notify() — never blindly trusted.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        ifo = self._ifo_admin()
        room = self._room()
        session = self._session(room, status=SessionStatus.ABSENT)
        self.client.force_login(checker)

        client_uuid = str(uuid.uuid4())
        r = self._post_replay([{
            "client_uuid": client_uuid, "token": room.qr_token,
            "action": "verified", "note": "",
            "scanned_at": (timezone.now() - timedelta(minutes=30)).isoformat()}])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["status"], "flagged")

        self.assertFalse(CheckerValidation.objects.filter(
            session=session, action="verified").exists())
        self.assertTrue(AuditLog.objects.filter(
            event_type="checker.replay_conflict").exists())
        self.assertTrue(Notification.objects.filter(
            user=ifo, type="checker_replay_conflict").exists())

    def test_replay_idempotent(self):
        # Posting the same client_uuid twice applies it at most once.
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        room = self._room()
        session = self._session(room)
        self.client.force_login(checker)

        client_uuid = str(uuid.uuid4())
        item = {
            "client_uuid": client_uuid, "token": room.qr_token,
            "action": "verified", "note": "",
            "scanned_at": (timezone.now() - timedelta(minutes=5)).isoformat()}

        r1 = self._post_replay([item])
        r2 = self._post_replay([item])
        self.assertEqual(r1.json()["results"][0]["status"], "applied")
        self.assertEqual(r2.json()["results"][0]["status"], "duplicate")

        self.assertEqual(CheckerValidation.objects.filter(
            session=session, action="verified").count(), 1)

"""Unit tests for the pure scan resolver (SCAN-01/02, §6.6)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from scheduling import resolver as R
from scheduling.resolver import is_no_show_past_grace  # JOB-02a: the single shared no-show predicate


@dataclass
class FakeSchedule:
    modality: str = "f2f"


@dataclass
class FakeSession:
    id: int
    room_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    status: str = "scheduled"
    declared_modality: str = ""
    schedule: FakeSchedule = field(default_factory=FakeSchedule)


T0 = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)  # scheduled start


def sess(**kw):
    defaults = dict(id=1, room_id=10, scheduled_start=T0,
                    scheduled_end=T0 + timedelta(minutes=90))
    defaults.update(kw)
    return FakeSession(**defaults)


def resolve(sessions, room_id=10, occupying=None, now=T0, **kw):
    policy = dict(grace_min=15, early_end_min=15)
    policy.update(kw)
    return R.resolve_faculty_scan(sessions, room_id, occupying, now, **policy)


class FacultyResolverTests(SimpleTestCase):
    def test_checkin_at_start_is_present(self):
        r = resolve([sess()])
        self.assertEqual(r.outcome, R.CHECKED_IN)
        self.assertFalse(r.needs_confirm)

    def test_checkin_within_grace_is_present(self):
        r = resolve([sess()], now=T0 + timedelta(minutes=14))
        self.assertEqual(r.outcome, R.CHECKED_IN)

    def test_checkin_after_grace_is_absent(self):
        r = resolve([sess()], now=T0 + timedelta(minutes=16))
        self.assertEqual(r.outcome, R.ABSENT)

    def test_checkin_slightly_early_is_allowed(self):
        r = resolve([sess()], now=T0 - timedelta(minutes=10))
        self.assertEqual(r.outcome, R.CHECKED_IN)

    def test_checkin_far_too_early(self):
        r = resolve([sess()], now=T0 - timedelta(hours=2))
        self.assertEqual(r.outcome, R.TOO_EARLY)

    def test_no_schedule_in_other_room(self):
        r = resolve([sess()], room_id=99, now=T0 - timedelta(hours=2))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_wrong_room_needs_confirm(self):
        r = resolve([sess(room_id=20)], room_id=10)
        self.assertEqual(r.outcome, R.WRONG_ROOM)
        self.assertTrue(r.needs_confirm)

    def test_room_occupied_needs_confirm_and_carries_prior(self):
        r = resolve([sess()], occupying=77)
        self.assertEqual(r.outcome, R.ROOM_OCCUPIED)
        self.assertTrue(r.needs_confirm)
        self.assertEqual(r.prior_session_id, 77)

    def test_online_session_rejects_qr(self):
        r = resolve([sess(schedule=FakeSchedule(modality="online"))])
        self.assertEqual(r.outcome, R.ONLINE_REJECT)

    def test_declared_modality_overrides_scheduled(self):
        r = resolve([sess(declared_modality="online")])
        self.assertEqual(r.outcome, R.ONLINE_REJECT)

    def test_rescan_active_session_near_end_checks_out(self):
        s = sess(status="active")
        r = resolve([s], now=T0 + timedelta(minutes=80))
        self.assertEqual(r.outcome, R.CHECKED_OUT)

    def test_rescan_active_session_early_needs_confirm(self):
        s = sess(status="active")
        r = resolve([s], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.EARLY_END)
        self.assertTrue(r.needs_confirm)

    def test_active_session_scanning_other_room_is_wrong_room(self):
        s = sess(status="active")
        r = resolve([s], room_id=99, now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.WRONG_ROOM)

    def test_completed_session_gives_no_schedule(self):
        r = resolve([sess(status="completed")], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_absent_session_stays_absent_no_new_start(self):
        r = resolve([sess(status="absent")], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_second_session_of_day_resolves(self):
        s1 = sess(id=1, status="completed")
        s2 = sess(id=2, scheduled_start=T0 + timedelta(hours=3),
                  scheduled_end=T0 + timedelta(hours=4, minutes=30))
        r = resolve([s1, s2], now=T0 + timedelta(hours=3))
        self.assertEqual(r.outcome, R.CHECKED_IN)
        self.assertEqual(r.session_id, 2)


class NoShowPredicateTests(SimpleTestCase):
    """JOB-02a boundary math for the single shared no-show predicate.

    is_no_show_past_grace is True strictly AFTER scheduled_start + grace_min;
    at exactly +grace it is False (mirrors the resolver's `now > start + grace`).
    Pure function of aware datetimes + int minutes — no DB, no policy lookup.
    """

    def test_before_start_is_not_no_show(self):
        self.assertFalse(is_no_show_past_grace(T0, T0 - timedelta(minutes=1), 15))

    def test_within_grace_is_not_no_show(self):
        self.assertFalse(is_no_show_past_grace(T0, T0 + timedelta(minutes=14), 15))

    def test_exactly_at_grace_is_not_no_show(self):
        # Boundary: equal is NOT strictly past grace (mirrors `now > start + grace`).
        self.assertFalse(is_no_show_past_grace(T0, T0 + timedelta(minutes=15), 15))

    def test_one_minute_past_grace_is_no_show(self):
        self.assertTrue(is_no_show_past_grace(T0, T0 + timedelta(minutes=16), 15))

    def test_far_past_grace_is_no_show(self):
        self.assertTrue(is_no_show_past_grace(T0, T0 + timedelta(minutes=120), 15))


class CouplingIntegrityTests(SimpleTestCase):
    """JOB-02a / Phase-2 success criterion #1: scan-time and sweep-time share ONE
    predicate. The resolver returns ABSENT if-and-only-if is_no_show_past_grace is
    True for identical inputs — this test blocks any future drift between the two
    paths (the highest-risk coupling in the phase).
    """

    def test_resolver_absent_iff_predicate_true(self):
        for delta in (-1, 0, 14, 15, 16, 30):
            with self.subTest(delta=delta):
                now = T0 + timedelta(minutes=delta)
                r = resolve([sess()], now=now)  # window contains now, room matches, f2f, unoccupied
                self.assertEqual(
                    r.outcome == R.ABSENT,
                    is_no_show_past_grace(T0, now, 15),
                    "resolver ABSENT decision and predicate must agree for identical inputs",
                )


# ---------------------------------------------------------------------------
# DB-backed MSSQL foundation tests (ENV-01 datetime, ENV-02 import parity).
# Nyquist Wave 0 scaffolding — validates SQL Server runtime behavior, not the
# pure resolver above. FacultyResolverTests stays a SimpleTestCase (no DB).
# ---------------------------------------------------------------------------
from datetime import date, datetime as dt, time  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import TestCase, TransactionTestCase  # noqa: E402

from campus.models import Building, Floor, Room  # noqa: E402
from scheduling.models import AcademicTerm, Schedule, Session  # noqa: E402


def make_session(scheduled_start, scheduled_end=None):
    """Build the minimal FK chain for a single Session (fast — no full seed).

    Returns a persisted Session whose scheduled_start is the given aware
    datetime. Room requires unique qr_token + manual_code (NOT NULL).
    """
    User = get_user_model()
    fac = User.objects.create(username="fac_dt", email="fac_dt@mcm.edu.ph", role="faculty")
    bldg = Building.objects.create(name="R", code="R")
    floor = Floor.objects.create(building=bldg, number=3)
    room = Room.objects.create(floor=floor, code="R399",
                               qr_token="tok-dt-399", manual_code="900399")
    term = AcademicTerm.objects.create(name="TZ Term",
                                       start_date=date(2026, 1, 1),
                                       end_date=date(2026, 12, 31), is_active=True)
    sch = Schedule.objects.create(term=term, course_code="TZ101", section="A",
                                  faculty=fac, room=room, day_of_week=0,
                                  start_time=time(8, 0), end_time=time(9, 30))
    return Session.objects.create(schedule=sch, faculty=fac, room=room,
                                  date=scheduled_start.date(),
                                  scheduled_start=scheduled_start,
                                  scheduled_end=scheduled_end or scheduled_start)


class DatetimeRoundTripTests(TestCase):
    """An aware Asia/Manila instant must round-trip on SQL Server datetime2
    with NO 8-hour drift (Pitfall 2 in 01-RESEARCH)."""

    def test_manila_midnight_instant_survives_roundtrip(self):
        manila = ZoneInfo("Asia/Manila")
        aware = dt(2026, 7, 6, 0, 30, tzinfo=manila)   # 00:30 PHT = 16:30 UTC prev day
        s = make_session(aware)
        s.refresh_from_db()
        self.assertEqual(s.scheduled_start, aware)
        self.assertEqual(s.scheduled_start.astimezone(ZoneInfo("UTC")).hour, 16)

    def test_manila_0800_reads_back_as_0000_utc(self):
        manila = ZoneInfo("Asia/Manila")
        aware = dt(2026, 7, 6, 8, 0, tzinfo=manila)    # 08:00 PHT = 00:00 UTC
        s = make_session(aware)
        s.refresh_from_db()
        self.assertEqual(s.scheduled_start.astimezone(ZoneInfo("UTC")).hour, 0)
        self.assertEqual(s.scheduled_start, aware)


# ---------------------------------------------------------------------------
# Registrar import -> session materialization parity (ENV-02).
# R3ParityTests hits the REAL gitignored PII CSV and is SKIPPED where absent;
# ImportPathTests runs everywhere against a committed anonymized fixture.
# ---------------------------------------------------------------------------
import os  # noqa: E402
from unittest import skipUnless  # noqa: E402

from django.core.management import call_command  # noqa: E402

from accounts.models import Role  # noqa: E402

REAL_CSV = "data/raw/2T-25-26-Course Offerring(Sheet1).csv"
FIXTURE_CSV = "data/fixtures/r3_synthetic.csv"


class ImportPathTests(TransactionTestCase):
    """CI-safe: import + materialize the committed synthetic fixture and assert
    its own known counts (2 sections / 2 rooms / 2 faculty / 3 schedules / 3
    sessions). TransactionTestCase because the commands wrap work in atomic()."""

    def test_synthetic_fixture_import_and_materialize_counts(self):
        call_command("import_offerings", file=FIXTURE_CSV, building="R", floor=3)
        call_command("materialize_sessions", days=7)
        User = get_user_model()
        self.assertEqual(Schedule.objects.count(), 3)
        self.assertEqual(Room.objects.count(), 2)
        self.assertEqual(User.objects.filter(role=Role.FACULTY).count(), 2)
        self.assertEqual(Session.objects.count(), 3)


@skipUnless(os.path.exists(REAL_CSV), "registrar CSV not present (gitignored)")
class R3ParityTests(TransactionTestCase):
    """Full R-floor-3 slice against the real registrar CSV must reproduce the
    validated numbers on MSSQL: 17 sections / 10 rooms / 15 faculty / 18
    schedules / 18 sessions."""

    def test_r3_slice_matches_sqlite_validated_numbers(self):
        call_command("import_offerings", building="R", floor=3)
        call_command("materialize_sessions", days=7)
        User = get_user_model()
        self.assertEqual(Schedule.objects.count(), 18)
        self.assertEqual(Room.objects.count(), 10)
        self.assertEqual(User.objects.filter(role=Role.FACULTY).count(), 15)
        self.assertEqual(Session.objects.count(), 18)
        self.assertEqual(
            Schedule.objects.values("course_code", "section").distinct().count(), 17)


# ---------------------------------------------------------------------------
# JOB-02b status sweep + JOB-02c room-conflict detection (DB-backed).
# SweepTests prove: a still-SCHEDULED F2F/Blended no-show is marked ABSENT by
# the sweep independent of any scan (via the SHARED is_no_show_past_grace
# predicate), backfilled across all past dates, idempotently, with an AuditLog
# per absence; online no-shows are EXCLUDED (Phase-3 hook); the sweep NEVER
# stamps room_released_at (no timer-based auto-release). RoomConflictTests prove
# a single deduped, auto-resolving IFO room-conflict flag via notify().
# ---------------------------------------------------------------------------
from ops.models import AuditLog, Notification, RoomConflictFlag  # noqa: E402
from scheduling.jobs import (detect_room_conflicts,  # noqa: E402
                             sweep_no_shows)
from scheduling.models import Modality, SessionStatus  # noqa: E402

# Fixed sweep "now" — sessions are positioned relative to this aware instant.
NOW = dt(2026, 7, 6, 10, 0, tzinfo=timezone.utc)


class _JobFixtureMixin:
    """Shared DB fixtures for the sweep + conflict tests.

    Each `_session(...)`/`_room()`/`_faculty()` call mints DISTINCT unique keys
    (username, email, room code, qr_token, manual_code) so a single test method
    can persist many sessions without tripping a UNIQUE constraint.
    """

    def setUp(self):
        self.User = get_user_model()
        self.bldg = Building.objects.create(name="Jobs", code="JB")
        self.floor = Floor.objects.create(building=self.bldg, number=1)
        self.term = AcademicTerm.objects.create(
            name="Jobs Term", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), is_active=True)
        self._i = 0

    def _next(self):
        self._i += 1
        return self._i

    def _room(self):
        i = self._next()
        return Room.objects.create(floor=self.floor, code=f"JB{i:03d}",
                                   qr_token=f"jb-tok-{i}", manual_code=f"8{i:05d}")

    def _faculty(self):
        i = self._next()
        return self.User.objects.create(username=f"jb_fac_{i}",
                                        email=f"jb_fac_{i}@mcm.edu.ph",
                                        role="faculty")

    def _ifo_admin(self):
        i = self._next()
        return self.User.objects.create(username=f"jb_ifo_{i}",
                                        email=f"jb_ifo_{i}@mcm.edu.ph",
                                        role="ifo_admin", is_active=True)

    def _session(self, *, now=NOW, start_delta_min=-20, status="scheduled",
                 declared_modality="", schedule_modality="f2f", days_ago=0,
                 room=None):
        room = room or self._room()
        fac = self._faculty()
        i = self._next()
        sch = Schedule.objects.create(
            term=self.term, course_code=f"JB{i}", section="A", faculty=fac,
            room=room, day_of_week=0, start_time=time(8, 0), end_time=time(9, 30),
            modality=schedule_modality)
        start = now + timedelta(minutes=start_delta_min) - timedelta(days=days_ago)
        return Session.objects.create(
            schedule=sch, faculty=fac, room=room, date=start.date(),
            scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
            status=status, declared_modality=declared_modality)


class SweepTests(_JobFixtureMixin, TestCase):
    """JOB-02b: the sweep marks unscanned F2F/Blended no-shows ABSENT."""

    def test_scheduled_f2f_no_show_becomes_absent(self):
        # start = now-20min is past the 15-min grace -> no-show (a).
        s = self._session(start_delta_min=-20)
        marked = sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)
        self.assertEqual(marked, 1)

    def test_past_date_no_show_is_backfilled(self):
        # A SCHEDULED no-show 2 days ago is still swept (backfill/self-heal) (b).
        s = self._session(start_delta_min=-20, days_ago=2)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

    def test_online_no_show_stays_scheduled_declared(self):
        # Online via declared_modality is EXCLUDED from Absent-marking (c).
        s = self._session(start_delta_min=-20, declared_modality=Modality.ONLINE)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)

    def test_online_no_show_stays_scheduled_via_schedule(self):
        # Online via schedule.modality is EXCLUDED too (effective modality) (c).
        s = self._session(start_delta_min=-20, schedule_modality=Modality.ONLINE)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)

    def test_blended_no_show_becomes_absent(self):
        # Blended is NOT online -> swept like F2F.
        s = self._session(start_delta_min=-20, schedule_modality=Modality.BLENDED)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

    def test_within_grace_is_untouched(self):
        # start = now-10min is still within the 15-min grace -> not a no-show.
        s = self._session(start_delta_min=-10)
        marked = sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)
        self.assertEqual(marked, 0)

    def test_idempotent_only_scheduled_to_absent(self):
        # active/completed/already-absent are never touched across a rerun (d).
        no_show = self._session(start_delta_min=-20, status="scheduled")
        active = self._session(start_delta_min=-20, status="active")
        completed = self._session(start_delta_min=-20, status="completed")
        already = self._session(start_delta_min=-20, status="absent")

        first = sweep_no_shows(now=NOW)
        second = sweep_no_shows(now=NOW)

        no_show.refresh_from_db()
        active.refresh_from_db()
        completed.refresh_from_db()
        already.refresh_from_db()
        self.assertEqual(first, 1)
        self.assertEqual(second, 0)  # idempotent: nothing left to mark
        self.assertEqual(no_show.status, SessionStatus.ABSENT)
        self.assertEqual(active.status, SessionStatus.ACTIVE)
        self.assertEqual(completed.status, SessionStatus.COMPLETED)
        self.assertEqual(already.status, SessionStatus.ABSENT)

    def test_marked_absence_writes_auditlog_by_sweep(self):
        # Every sweep-marked absence writes AuditLog(session.marked_absent, by=sweep) (e).
        s = self._session(start_delta_min=-20)
        sweep_no_shows(now=NOW)
        log = AuditLog.objects.filter(event_type="session.marked_absent",
                                      target_id=str(s.pk)).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.payload.get("by"), "sweep")
        self.assertEqual(log.target_type, "session")

    def test_sweep_never_stamps_room_released_at(self):
        # Guard: the sweep is not a timer-based auto-release (f).
        s = self._session(start_delta_min=-20)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)
        self.assertIsNone(s.room_released_at)


class RoomConflictTests(_JobFixtureMixin, TestCase):
    """JOB-02c: contradictory occupancy raises ONE deduped IFO flag."""

    def _active_pair(self):
        """Two ACTIVE sessions holding one room (room_released_at NULL)."""
        room = self._room()
        s1 = self._session(start_delta_min=-30, status="active", room=room)
        s2 = self._session(start_delta_min=-30, status="active", room=room)
        return room, s1, s2

    def test_conflict_raises_one_flag_and_ifo_notifications(self):
        # Two active sessions -> exactly ONE open flag + one notification per IFO (a).
        self._ifo_admin()
        self._ifo_admin()
        room, s1, s2 = self._active_pair()

        flagged = detect_room_conflicts(now=NOW)

        self.assertEqual(flagged, 1)
        self.assertEqual(
            RoomConflictFlag.objects.filter(room=room,
                                            resolved_at__isnull=True).count(), 1)
        self.assertEqual(
            Notification.objects.filter(type="room_conflict").count(), 2)

    def test_second_detection_is_deduped(self):
        # A re-run with the same unresolved conflict creates NO new flag/notification (b).
        self._ifo_admin()
        room, s1, s2 = self._active_pair()

        detect_room_conflicts(now=NOW)
        flagged_again = detect_room_conflicts(now=NOW)

        self.assertEqual(flagged_again, 0)
        self.assertEqual(
            RoomConflictFlag.objects.filter(resolved_at__isnull=True).count(), 1)
        self.assertEqual(
            Notification.objects.filter(type="room_conflict").count(), 1)

    def test_conflict_auto_resolves_when_cleared(self):
        # Once the conflict clears, a detection run stamps resolved_at (c).
        self._ifo_admin()
        room, s1, s2 = self._active_pair()
        detect_room_conflicts(now=NOW)

        # Clear the conflict: one session completes (only one active left).
        s2.status = SessionStatus.COMPLETED
        s2.save(update_fields=["status"])
        detect_room_conflicts(now=NOW)

        flag = RoomConflictFlag.objects.get(room=room)
        self.assertIsNotNone(flag.resolved_at)
        self.assertEqual(
            RoomConflictFlag.objects.filter(resolved_at__isnull=True).count(), 0)

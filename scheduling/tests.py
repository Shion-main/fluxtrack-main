"""Unit tests for the pure scan resolver (SCAN-01/02, §6.6)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

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

    def test_overlapping_windows_prefer_session_in_scanned_room(self):
        """At a back-to-back handoff both scheduled windows include ``now``.

        The earlier row belongs to another room and ends exactly when the next
        class starts in the scanned room.  Room affinity must break the tie so
        the scan checks into the class the faculty is physically standing in.
        """
        earlier_other_room = sess(
            id=1, room_id=20,
            scheduled_start=T0 - timedelta(minutes=90), scheduled_end=T0)
        starting_here = sess(id=2, room_id=10)

        r = resolve([earlier_other_room, starting_here], room_id=10, now=T0)

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
                                       end_date=date(2026, 12, 31),
                                       status=AcademicTerm.Status.ACTIVE)
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
# ImportPathTests runs everywhere against a committed anonymized fixture. The
# old real-registrar R-floor-3 parity test was retired in Phase 04.1: the
# registrar CSV sources were replaced by the .xlsx, so its skip-guard was
# permanently skipped, and its hardcoded numbers were computed under the OLD
# skip-virtual importer. ENV-02 is now carried at FULL-term scale by Plan 01's
# reconcile() test and Plan 03's import-hardening + report tests, which are
# strictly stronger than the old slice.
# ---------------------------------------------------------------------------
from django.core.management import call_command  # noqa: E402

from accounts.models import Role  # noqa: E402

FIXTURE_CSV = "data/fixtures/r3_synthetic.csv"


class ImportPathTests(TransactionTestCase):
    """CI-safe: import + materialize the committed synthetic fixture and assert
    its own known counts (2 sections / 2 rooms / 2 faculty / 3 schedules / 3
    sessions). TransactionTestCase because the commands wrap work in atomic()."""

    def test_synthetic_fixture_import_and_materialize_counts(self):
        term = AcademicTerm.objects.create(
            name="Synthetic Import Term",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ACTIVE,
        )
        call_command(
            "import_offerings",
            file=FIXTURE_CSV,
            building="R",
            floor=3,
            term=str(term.pk),
        )
        call_command("materialize_sessions", days=7)
        User = get_user_model()
        self.assertEqual(Schedule.objects.count(), 3)
        self.assertEqual(Room.objects.count(), 2)
        self.assertEqual(User.objects.filter(role=Role.FACULTY).count(), 2)
        self.assertEqual(Session.objects.count(), 3)


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
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)
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

    def test_batch_of_no_shows_all_marked_absent(self):
        # Regression (MSSQL HY010): the sweep mutates rows INSIDE the candidate
        # loop. With .iterator() streaming an open SELECT cursor, the per-row
        # save()/AuditLog INSERT raised "Function sequence error (SQLFetch)" on
        # SQL Server (single active result set, MARS off). A batch of no-shows
        # exercises the mutate-while-iterate path; all must be marked and the
        # returned count must match.
        sessions = [self._session(start_delta_min=-20) for _ in range(5)]
        marked = sweep_no_shows(now=NOW)
        self.assertEqual(marked, 5)
        for s in sessions:
            s.refresh_from_db()
            self.assertEqual(s.status, SessionStatus.ABSENT)

    def test_online_no_show_declared_now_absent(self):
        # ROADMAP #6 + plan 03-05: the sweep's online exclusion is REMOVED once
        # the online Checker Verify path exists. An un-verified online no-show
        # (declared_modality=online) past grace now falls to ABSENT under the SAME
        # is_no_show_past_grace predicate — a deliberate, coordinated behavior
        # change (online joins JOB-02), NOT a regression. This test previously
        # asserted the session stayed SCHEDULED; that exclusion is gone.
        s = self._session(start_delta_min=-20, declared_modality=Modality.ONLINE)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

    def test_online_no_show_via_schedule_now_absent(self):
        # Same inclusion semantics via schedule.modality=online (effective
        # modality). Rewritten in lockstep with the exclusion removal (03-05).
        s = self._session(start_delta_min=-20, schedule_modality=Modality.ONLINE)
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

    def test_verified_online_not_marked_absent(self):
        # The linchpin of the coupled change (03-05): a genuine online attendee is
        # made ACTIVE by an online Verify, so the sweep (which only touches
        # SCHEDULED) skips it. Only un-verified (still-SCHEDULED) online no-shows
        # fall to Absent — verified/ACTIVE online sessions are never touched.
        s = self._session(start_delta_min=-20, declared_modality=Modality.ONLINE,
                          status="active")
        sweep_no_shows(now=NOW)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ACTIVE)

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


# ---------------------------------------------------------------------------
# ENV-04 scheduler wiring: `runscheduler.build_scheduler()` registers EXACTLY the
# 4 jobs (materialize / sweep / weekly_report / push_outbox) on one BlockingScheduler
# and hands it back UNSTARTED, so a single dedicated `manage.py runscheduler`
# process owns all jobs and nothing double-fires across web workers. push_outbox
# (05-03, NOTIF-02/D-09) runs the web-push send/prune pass here, never in a web
# worker. Import is method-local so only this class goes RED before runscheduler.py
# exists (Task 3).
# ---------------------------------------------------------------------------
class SchedulerWiringTests(TestCase):
    """ENV-04: build_scheduler() wires exactly 4 jobs and returns them unstarted."""

    def test_build_scheduler_registers_exactly_four_jobs_unstarted(self):
        from scheduling.management.commands.runscheduler import build_scheduler
        sched = build_scheduler()
        try:
            self.assertFalse(sched.running)  # never started by build_scheduler()
            self.assertEqual(
                {j.id for j in sched.get_jobs()},
                {"materialize", "sweep", "weekly_report", "push_outbox"})
        finally:
            if getattr(sched, "running", False):
                sched.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Phase-4 shared fixture builder smoke test (04-01 Task 3).
# make_shift_fixture() must wire a Dean + faculty in ONE department so later
# plans' routing (D-09) and department gates resolve correctly. This proves the
# builder saves a valid graph (no IntegrityError) and the routing keys line up.
# ---------------------------------------------------------------------------
from scheduling.test_support import make_shift_fixture  # noqa: E402


class FixtureSmokeTests(TestCase):
    """04-01: make_shift_fixture() seeds a valid, routing-correct object graph."""

    def test_fixture_wires_dean_and_same_department_faculty(self):
        fx = make_shift_fixture()
        self.assertEqual(fx.dean.role, Role.DEAN)
        self.assertEqual(fx.faculty.role, Role.FACULTY)
        self.assertEqual(fx.faculty.department_id, fx.dean.department_id)
        # The in-window F2F session and its online counterpart both persisted.
        self.assertEqual(fx.session.status, SessionStatus.SCHEDULED)
        self.assertEqual(fx.online_session.declared_modality, Modality.ONLINE)
        # The competitor holds room A at the same slot for availability tests.
        self.assertEqual(fx.competitor.room_id, fx.room_a.id)


# ---------------------------------------------------------------------------
# 04-04: modality-shift CREATION-side service (scheduling/services.py).
# Task 1 -- the pure, server-clock lead-time gate (D-02) and deterministic Dean
# routing (D-09). The gate reads modality_shift_lead_days from get_policy (never
# a literal) and computes the cutoff as Manila-midnight of
# (earliest_affected_date - lead_days); routing resolves the requester's active
# department Dean or a safe None on the D-09 edge cases.
# ---------------------------------------------------------------------------
import inspect  # noqa: E402

from scheduling import services  # noqa: E402
from scheduling.services import ModalityShiftError  # noqa: E402

_MANILA = ZoneInfo("Asia/Manila")


def _manila(y, mo, d, h, mi):
    """An Asia/Manila-aware instant for the lead-time boundary assertions."""
    return dt(y, mo, d, h, mi, tzinfo=_MANILA)


class LeadTimeGateTests(TestCase):
    """D-02: whole-calendar-day Manila cutoff = start of (earliest - lead_days).

    The default policy lead is 2, so a Monday 2026-07-06 session has a cutoff of
    Saturday 2026-07-04 00:00 Manila. The gate refuses AT/after that instant and
    allows strictly before it; a windowed request keys off the earliest date.
    """

    SESSION_DATE = date(2026, 7, 6)  # Monday; cutoff = Sat 2026-07-04 00:00 Manila

    def test_refused_at_cutoff_midnight(self):
        now = _manila(2026, 7, 4, 0, 0)  # exactly the Manila-midnight cutoff
        self.assertFalse(services.is_before_lead_cutoff(self.SESSION_DATE, now))

    def test_allowed_the_prior_minute(self):
        now = _manila(2026, 7, 3, 23, 59)  # Fri 23:59 Manila, before the cutoff
        self.assertTrue(services.is_before_lead_cutoff(self.SESSION_DATE, now))

    def test_windowed_request_keys_off_earliest_date(self):
        # The same "now" that refuses the earliest date still allows a later one:
        # the earliest affected date is the binding constraint (D-02 windowed).
        now = _manila(2026, 7, 4, 0, 0)
        self.assertFalse(services.is_before_lead_cutoff(self.SESSION_DATE, now))
        self.assertTrue(services.is_before_lead_cutoff(date(2026, 7, 13), now))

    def test_gate_reads_policy_not_a_literal(self):
        # Overriding the SystemSetting lead moves the cutoff -- proving the gate
        # reads get_policy() rather than a hardcoded 2.
        from ops.models import SystemSetting
        SystemSetting.objects.create(key="modality_shift_lead_days", value="5")
        # lead 5 -> cutoff = 2026-07-01 00:00 Manila. 2026-07-04 now is at/after
        # the default cutoff but a full lead-5 cutoff is earlier, so it is refused.
        now = _manila(2026, 7, 2, 0, 0)  # after 07-01 cutoff -> refused with lead 5
        self.assertFalse(services.is_before_lead_cutoff(self.SESSION_DATE, now))


class DeanRoutingTests(TestCase):
    """D-09: deterministic routing to the requester's active department Dean."""

    def test_routes_to_same_department_dean(self):
        fx = make_shift_fixture()
        self.assertEqual(services.route_to_dean(fx.faculty), fx.dean)

    def test_none_department_returns_none(self):
        fx = make_shift_fixture()
        fx.faculty.department = None
        fx.faculty.save(update_fields=["department"])
        self.assertIsNone(services.route_to_dean(fx.faculty))

    def test_vacant_dean_returns_none(self):
        fx = make_shift_fixture()
        fx.dean.is_active = False
        fx.dean.save(update_fields=["is_active"])
        self.assertIsNone(services.route_to_dean(fx.faculty))


# ---------------------------------------------------------------------------
# 04-04 Task 2 -- in-window scope resolution (D-01/D-19) + submit (atomic ticket).
# submit_modality_shift gathers the in-window sessions, gates on the earliest
# affected date, routes to the Dean, creates ONE ModalityShiftRequest with one
# ModalityShiftItem per schedule, notifies the Dean once, and audits. A time-move
# is accepted only bundled with F2F/Blended (D-16) and never double-books the
# faculty (D-17).
# ---------------------------------------------------------------------------
from datetime import time as _time  # noqa: E402

from scheduling.models import (  # noqa: E402
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
)

# A "now" comfortably before the Sat 2026-07-04 00:00 Manila cutoff so scope
# tests exercise scope/atomicity rather than the lead gate.
_EARLY_NOW = _manila(2026, 6, 1, 8, 0)


def _add_session(schedule, d):
    """Materialize one SCHEDULED session of ``schedule`` on date ``d``."""
    return Session.objects.create(
        schedule=schedule, faculty=schedule.faculty, room=schedule.room, date=d,
        scheduled_start=dt.combine(d, schedule.start_time, tzinfo=_MANILA),
        scheduled_end=dt.combine(d, schedule.end_time, tzinfo=_MANILA),
        status=SessionStatus.SCHEDULED,
    )


class ShiftScopeTests(TestCase):
    """D-01/D-19: in-window scope resolution and the atomic submit ticket."""

    def test_single_session_window_creates_one_item(self):
        fx = make_shift_fixture()
        req = services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
            date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
        )
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)
        self.assertEqual(req.dean, fx.dean)
        self.assertEqual(req.items.count(), 1)
        self.assertEqual(
            [s.pk for s in services.affected_sessions(req)], [fx.session.pk])
        # Dean notified exactly once (MOD-05).
        self.assertEqual(
            Notification.objects.filter(
                user=fx.dean, type="modality_shift_submitted").count(), 1)
        # AuditLog written (T-04-09 provenance).
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.submitted",
            target_id=str(req.pk)).exists())

    def test_recurring_window_resolves_only_in_window_sessions(self):
        fx = make_shift_fixture()
        _add_session(fx.f2f_schedule, date(2026, 7, 13))   # in window
        _add_session(fx.f2f_schedule, date(2026, 7, 20))   # in window (edge)
        out = _add_session(fx.f2f_schedule, date(2026, 7, 27))  # OUT of window
        req = services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
            date(2026, 7, 6), date(2026, 7, 20), now=_EARLY_NOW,
        )
        got = {s.pk for s in services.affected_sessions(req)}
        self.assertEqual(
            got, {fx.session.pk} | set(
                Session.objects.filter(
                    schedule=fx.f2f_schedule,
                    date__in=[date(2026, 7, 13), date(2026, 7, 20)],
                ).values_list("pk", flat=True)))
        # The out-of-window session is untouched (never in the affected set).
        self.assertNotIn(out.pk, got)
        out.refresh_from_db()
        self.assertEqual(out.declared_modality, "")

    def test_multi_schedule_ticket_has_item_per_schedule(self):
        fx = make_shift_fixture()
        tue_schedule = Schedule.objects.create(
            term=fx.term, course_code="MSF102", section="A",
            faculty=fx.faculty, room=fx.room_b, day_of_week=1,
            start_time=_time(8, 0), end_time=_time(9, 30), modality=Modality.F2F,
        )
        _add_session(tue_schedule, date(2026, 7, 7))  # Tuesday, in window
        req = services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule, tue_schedule], Modality.ONLINE,
            date(2026, 7, 6), date(2026, 7, 13), now=_EARLY_NOW,
        )
        self.assertEqual(req.items.count(), 2)
        self.assertEqual(
            set(req.items.values_list("schedule_id", flat=True)),
            {fx.f2f_schedule.pk, tue_schedule.pk})
        self.assertEqual(len(services.affected_sessions(req)), 2)

    def test_time_move_refused_when_target_online(self):
        fx = make_shift_fixture()
        with self.assertRaises(ModalityShiftError):
            services.submit_modality_shift(
                fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
                date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
                time_move=(_time(13, 0), _time(14, 30)),
            )

    def test_time_move_refused_when_double_books_faculty(self):
        fx = make_shift_fixture()
        # Move the 08:00 F2F class onto the 10:00-11:30 slot the faculty already
        # teaches online (fx.online_session) -> D-17 double-book refusal.
        with self.assertRaises(ModalityShiftError):
            services.submit_modality_shift(
                fx.faculty, [fx.f2f_schedule], Modality.F2F,
                date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
                time_move=(_time(10, 0), _time(11, 30)),
            )

    def test_valid_f2f_time_move_creates_time_move_ticket(self):
        fx = make_shift_fixture()
        req = services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule], Modality.F2F,
            date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
            time_move=(_time(13, 0), _time(14, 30)),
        )
        self.assertTrue(req.is_time_move)
        item = req.items.get()
        self.assertEqual(item.new_start_time, _time(13, 0))
        self.assertEqual(item.new_end_time, _time(14, 30))

    def test_too_late_request_refused(self):
        fx = make_shift_fixture()
        with self.assertRaises(ModalityShiftError):
            services.submit_modality_shift(
                fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
                date(2026, 7, 6), date(2026, 7, 6),
                now=_manila(2026, 7, 4, 0, 0),  # at the cutoff -> refused
            )

    def test_missing_dean_refused_at_submit(self):
        fx = make_shift_fixture()
        fx.faculty.department = None
        fx.faculty.save(update_fields=["department"])
        with self.assertRaises(ModalityShiftError):
            services.submit_modality_shift(
                fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
                date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
            )


# ---------------------------------------------------------------------------
# 04-04 Task 3 -- withdraw + reject transitions (ownership + PENDING guards).
# Both re-check the CURRENT status server-side (never an earlier snapshot,
# mirroring the 03-02 re-gate) before any write. Withdraw is silent (D-10/D-11);
# reject records the reason and notifies the requester once (D-11).
# ---------------------------------------------------------------------------
class WithdrawTests(TestCase):
    """MOD-05/D-10/D-11: withdraw (requester+PENDING) and reject (Dean+PENDING)."""

    def _submit(self, fx):
        return services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
            date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW,
        )

    def test_owner_pending_withdraw_succeeds_silently(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        before = Notification.objects.count()
        out = services.withdraw_modality_shift(req, fx.faculty)
        self.assertEqual(out.status, ModalityShiftStatus.WITHDRAWN)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.WITHDRAWN)
        # Withdraw is silent -- no new Notification row (D-10/D-11).
        self.assertEqual(Notification.objects.count(), before)
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.withdrawn",
            target_id=str(req.pk)).exists())

    def test_foreign_user_withdraw_refused_no_state_change(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        with self.assertRaises(ModalityShiftError):
            services.withdraw_modality_shift(req, fx.competitor_faculty)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)

    def test_non_pending_withdraw_refused(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        req.status = ModalityShiftStatus.APPROVED
        req.save(update_fields=["status"])
        with self.assertRaises(ModalityShiftError):
            services.withdraw_modality_shift(req, fx.faculty)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.APPROVED)

    def test_reject_records_reason_and_notifies_requester(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        out = services.reject_modality_shift(req, fx.dean, "no room that day")
        self.assertEqual(out.status, ModalityShiftStatus.REJECTED)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.REJECTED)
        self.assertEqual(req.decision_reason, "no room that day")
        self.assertEqual(req.decided_by, fx.dean)
        self.assertIsNotNone(req.decided_at)
        self.assertEqual(
            Notification.objects.filter(
                user=fx.faculty, type="modality_shift_rejected").count(), 1)
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.rejected",
            target_id=str(req.pk)).exists())

    def test_cross_department_dean_reject_refused(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        other = make_shift_fixture("other")  # a Dean of a DIFFERENT department
        with self.assertRaises(ModalityShiftError):
            services.reject_modality_shift(req, other.dean, "not my call")
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)

    def test_non_pending_reject_refused(self):
        fx = make_shift_fixture()
        req = self._submit(fx)
        services.withdraw_modality_shift(req, fx.faculty)  # now WITHDRAWN
        with self.assertRaises(ModalityShiftError):
            services.reject_modality_shift(req, fx.dean, "too late")
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.WITHDRAWN)


class TransitionLockingTests(SimpleTestCase):
    """Every competing PENDING transition must lock its request row first."""

    def test_withdraw_reject_and_approve_select_request_for_update(self):
        for transition in (
            services.withdraw_modality_shift,
            services.reject_modality_shift,
            services.apply_approval,
        ):
            with self.subTest(transition=transition.__name__):
                source = inspect.getsource(transition)
                self.assertIn(
                    "ModalityShiftRequest.objects.select_for_update()", source)


# ---------------------------------------------------------------------------
# 04-05 -- Dean approval APPLY (the decision-consequence side).
# apply_approval turns an approved request into real room releases (->Online),
# real room assignments (->F2F/Blended), terminal denials (no free room), bundled
# time-moves, reservations for future sessions, and decision/IFO notifications --
# all atomic, TOCTOU-safe, audited. Task 1 covers the ->Online consequence + the
# effective-modality coupling (declared_modality is what the resolver/sweep read).
# ---------------------------------------------------------------------------
from ops.availability import room_is_free  # noqa: E402

# apply_approval does NOT gate on lead time, so any aware "now" serves.
_APPLY_NOW = _manila(2026, 6, 1, 9, 0)


def _pending_request(fx, target, schedules, window_start, window_end, *,
                     preferred=None, time_move=None):
    """Persist a PENDING ModalityShiftRequest with one item per schedule.

    Builds the request directly (bypassing the lead-time gate) so apply tests
    exercise the CONSEQUENCE side in isolation. ``time_move`` is a
    ``(new_start_time, new_end_time)`` pair applied to every item.
    """
    req = ModalityShiftRequest.objects.create(
        requester=fx.faculty, dean=fx.dean, department=fx.dept,
        target_modality=target, window_start=window_start, window_end=window_end,
        is_time_move=bool(time_move), status=ModalityShiftStatus.PENDING,
    )
    nst, net = time_move or (None, None)
    for sch in schedules:
        ModalityShiftItem.objects.create(
            request=req, schedule=sch, preferred_room=preferred,
            new_start_time=nst, new_end_time=net,
        )
    return req


class ApplyOnlineTests(TestCase):
    """MOD-03/D-04: approving a ->Online shift releases the room via release_room
    and flips effective modality via declared_modality on each in-window session;
    out-of-window sessions are untouched. The room FK is NEVER nulled -- the
    release signal is room_released_at (RESEARCH anti-pattern)."""

    def test_online_approval_releases_room_and_flips_modality(self):
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        out = services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        self.assertEqual(out.status, ModalityShiftStatus.APPROVED)
        self.assertEqual(out.decided_by, fx.dean)
        self.assertIsNotNone(out.decided_at)

        fx.session.refresh_from_db()
        self.assertEqual(fx.session.declared_modality, Modality.ONLINE)
        self.assertEqual(fx.session.modality_changed_at, _APPLY_NOW)
        self.assertEqual(fx.session.modality_changed_by, fx.dean)
        # release_room stamped room_released_at ...
        self.assertEqual(fx.session.room_released_at, _APPLY_NOW)
        # ... but never nulled the room FK (session.room stays room_a).
        self.assertEqual(fx.session.room_id, fx.room_a.id)
        # AuditLog: the approval + the room release are both recorded.
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.approved",
            target_id=str(req.pk)).exists())
        self.assertTrue(AuditLog.objects.filter(
            event_type="session.room_released",
            target_id=str(fx.session.pk)).exists())

    def test_out_of_window_session_untouched(self):
        fx = make_shift_fixture()
        out_session = _add_session(fx.f2f_schedule, date(2026, 7, 13))  # out of window
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        out_session.refresh_from_db()
        self.assertEqual(out_session.declared_modality, "")
        self.assertIsNone(out_session.room_released_at)

    def test_approve_refused_for_wrong_dean_or_non_pending(self):
        fx = make_shift_fixture()
        other = make_shift_fixture("oth")  # a Dean of a DIFFERENT department
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        with self.assertRaises(ModalityShiftError):
            services.apply_approval(req, other.dean, now=_APPLY_NOW)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)
        # Non-pending re-gate: an already-approved ticket cannot be re-approved.
        req.status = ModalityShiftStatus.WITHDRAWN
        req.save(update_fields=["status"])
        with self.assertRaises(ModalityShiftError):
            services.apply_approval(req, fx.dean, now=_APPLY_NOW)


class EffectiveModalityCouplingTests(TestCase):
    """MOD-06: after a ->Online apply, the effective modality the resolver/sweep
    read (declared_modality or schedule.modality) is Online for each affected
    session -- the coupling that makes the shift visible to every reader with zero
    changes to them. The availability primitive agrees: a released online session
    holds no physical room."""

    def test_effective_modality_is_online_after_apply(self):
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        fx.session.refresh_from_db()
        # The exact expression every reader uses (scheduling/resolver.py:97,
        # verification/services.py:47, ops/availability.py:56).
        effective = fx.session.declared_modality or fx.session.schedule.modality
        self.assertEqual(effective, Modality.ONLINE)

    def test_released_online_session_no_longer_occupies_its_room(self):
        # A schedule whose ONLY room-holder is the shifted session: after the
        # ->Online release, availability sees the room as free at that slot.
        fx = make_shift_fixture("cpl")
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        fx.session.refresh_from_db()
        # Exclude the competing occupant so this asserts the SHIFTED session's
        # release specifically (the competitor holds room_a independently).
        self.assertTrue(room_is_free(
            fx.room_a, fx.session.scheduled_start, fx.session.scheduled_end,
            exclude_session_id=fx.competitor.pk))


def _occupy_room(fx, room, start_t, end_t, d, *, faculty=None):
    """Persist an F2F occupant holding ``room`` at [start_t, end_t) on ``d``.

    Used to make a room genuinely un-free at approval time so the TOCTOU
    re-resolution / no-room paths are exercised. The occupant is a DIFFERENT
    faculty so it is not a self-double-book.
    """
    faculty = faculty or fx.competitor_faculty
    sch = Schedule.objects.create(
        term=fx.term, course_code="BLK", section="A", faculty=faculty,
        room=room, day_of_week=d.weekday(), start_time=start_t, end_time=end_t,
        modality=Modality.F2F)
    return Session.objects.create(
        schedule=sch, faculty=faculty, room=room, date=d,
        scheduled_start=dt.combine(d, start_t, tzinfo=_MANILA),
        scheduled_end=dt.combine(d, end_t, tzinfo=_MANILA),
        status=SessionStatus.SCHEDULED)


class ApplyF2FTests(TestCase):
    """MOD-04/D-06/D-16/D-18: approving a ->F2F/Blended shift assigns a room
    re-resolved INSIDE the transaction (original if free, else the first free room
    in the building), applies any bundled time-move after a faculty-conflict
    re-check, and reserves the resolved room on the item for future sessions."""

    def test_original_room_free_keeps_original(self):
        # Shift the Online class in room B to F2F: room B is free (an online
        # session holds no physical room) -> the original room is kept.
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.F2F, [fx.online_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        out = services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        self.assertEqual(out.status, ModalityShiftStatus.APPROVED)
        fx.online_session.refresh_from_db()
        self.assertEqual(fx.online_session.room_id, fx.room_b.id)
        self.assertEqual(fx.online_session.declared_modality, Modality.F2F)
        self.assertIsNone(fx.online_session.room_released_at)
        item = req.items.get()
        self.assertEqual(item.assigned_room_id, fx.room_b.id)  # reservation (D-18)

    def test_original_room_taken_assigns_first_free(self):
        # Shift the F2F class in room A (whose slot the competitor already holds)
        # to Blended: original room A is taken -> first free room B is assigned.
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.BLENDED, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        fx.session.refresh_from_db()
        self.assertEqual(fx.session.room_id, fx.room_b.id)
        self.assertEqual(fx.session.declared_modality, Modality.BLENDED)
        self.assertEqual(req.items.get().assigned_room_id, fx.room_b.id)

    def test_time_move_rewrites_scheduled_start_end(self):
        # A bundled time-move (D-16) rewrites the session's slot after the
        # faculty-conflict re-check (D-17); the room is resolved at the NEW slot.
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.F2F, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6),
            time_move=(_time(13, 0), _time(14, 30)))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        fx.session.refresh_from_db()
        self.assertEqual(fx.session.scheduled_start, _manila(2026, 7, 6, 13, 0))
        self.assertEqual(fx.session.scheduled_end, _manila(2026, 7, 6, 14, 30))
        self.assertEqual(fx.session.room_id, fx.room_a.id)  # room A free at 13:00
        self.assertEqual(fx.session.declared_modality, Modality.F2F)


class ApproveRaceTests(TestCase):
    """MOD-04/D-06 TOCTOU: a room free at submit but occupied by ANOTHER session at
    approval is re-resolved INSIDE the transaction to a different free room -- the
    picked/preferred room is never trusted blindly."""

    def test_preferred_room_taken_at_approval_reresolves(self):
        fx = make_shift_fixture()
        # The preferred (and original) room B is free when the request is built ...
        req = _pending_request(
            fx, Modality.F2F, [fx.online_schedule],
            date(2026, 7, 6), date(2026, 7, 6), preferred=fx.room_b)
        # ... but another class grabs room B at that slot before approval.
        _occupy_room(fx, fx.room_b, _time(10, 0), _time(11, 30), date(2026, 7, 6))

        services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        fx.online_session.refresh_from_db()
        # Re-resolved AWAY from the now-taken preferred/original room B to room A.
        self.assertEqual(fx.online_session.room_id, fx.room_a.id)
        self.assertEqual(req.items.get().assigned_room_id, fx.room_a.id)


class ApplyF2FNoRoomTests(TestCase):
    """D-07 REVISED / MOD-04: when NO room is free that day for an affected
    session, the whole ticket is DENIED (terminal, not left pending) and NOTHING
    changes on any session -- all-or-nothing, no silent partial apply (D-19)."""

    def test_no_free_room_denies_terminally_nothing_changed(self):
        fx = make_shift_fixture()
        # Room A is held by the competitor; occupy room B at the same slot so the
        # WHOLE building is full -> no room can be resolved.
        _occupy_room(fx, fx.room_b, _time(8, 0), _time(9, 30), date(2026, 7, 6))
        req = _pending_request(
            fx, Modality.BLENDED, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        out = services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        self.assertEqual(out.status, ModalityShiftStatus.DENIED)
        self.assertTrue(out.decision_reason)
        self.assertEqual(out.decided_by, fx.dean)
        # No partial apply: the session is byte-for-byte unchanged.
        fx.session.refresh_from_db()
        self.assertEqual(fx.session.declared_modality, "")
        self.assertEqual(fx.session.room_id, fx.room_a.id)
        self.assertIsNone(fx.session.room_released_at)
        # Reservation was rolled back too.
        self.assertIsNone(req.items.get().assigned_room_id)
        self.assertEqual(Notification.objects.filter(
            user=fx.faculty, type="modality_shift_denied").count(), 1)
        self.assertTrue(AuditLog.objects.filter(
            event_type="modality_shift.denied", target_id=str(req.pk)).exists())

    def test_time_move_double_book_denies_terminally(self):
        # A bundled time-move onto a slot the faculty already teaches (the online
        # class at 10:00-11:30) is a double-book -> terminal DENY (D-17), nothing
        # changed.
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.F2F, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6),
            time_move=(_time(10, 0), _time(11, 30)))
        out = services.apply_approval(req, fx.dean, now=_APPLY_NOW)

        self.assertEqual(out.status, ModalityShiftStatus.DENIED)
        fx.session.refresh_from_db()
        self.assertEqual(fx.session.declared_modality, "")
        self.assertEqual(fx.session.scheduled_start, _manila(2026, 7, 6, 8, 0))


class ShiftNotifyTests(TestCase):
    """MOD-05/D-11: submit -> Dean; approve -> requester + IFO informational;
    reject -> requester; deny -> requester. All via the single notify() path."""

    def _ifo(self, suffix="1"):
        return get_user_model().objects.create(
            username=f"nfy_ifo_{suffix}", email=f"nfy_ifo_{suffix}@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)

    def test_submit_notifies_dean(self):
        fx = make_shift_fixture()
        services.submit_modality_shift(
            fx.faculty, [fx.f2f_schedule], Modality.ONLINE,
            date(2026, 7, 6), date(2026, 7, 6), now=_EARLY_NOW)
        self.assertEqual(Notification.objects.filter(
            user=fx.dean, type="modality_shift_submitted").count(), 1)

    def test_approve_notifies_requester_and_ifo(self):
        fx = make_shift_fixture()
        ifo = self._ifo()
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)
        self.assertEqual(Notification.objects.filter(
            user=fx.faculty, type="modality_shift_approved").count(), 1)
        self.assertEqual(Notification.objects.filter(
            user=ifo, type="modality_shift_applied").count(), 1)

    def test_reject_notifies_requester(self):
        fx = make_shift_fixture()
        req = _pending_request(
            fx, Modality.ONLINE, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.reject_modality_shift(req, fx.dean, "no room that day")
        self.assertEqual(Notification.objects.filter(
            user=fx.faculty, type="modality_shift_rejected").count(), 1)

    def test_deny_notifies_requester(self):
        fx = make_shift_fixture()
        _occupy_room(fx, fx.room_b, _time(8, 0), _time(9, 30), date(2026, 7, 6))
        req = _pending_request(
            fx, Modality.BLENDED, [fx.f2f_schedule],
            date(2026, 7, 6), date(2026, 7, 6))
        services.apply_approval(req, fx.dean, now=_APPLY_NOW)
        self.assertEqual(Notification.objects.filter(
            user=fx.faculty, type="modality_shift_denied").count(), 1)


# ---------------------------------------------------------------------------
# 04-06 -- JOB-01 born-released / born-assigned hook (materialize_sessions).
# The materializer is the ONLY creator of future sessions. A recurring window
# that extends past the ~14-day horizon must still honor an approved shift on
# the sessions it creates weeks later: born released (->Online) or born in the
# reserved room (->F2F/Blended), including a bundled time-move. A defensive
# no-room guard keeps the original room + notifies IFO and NEVER crashes the
# unattended job (D-04/D-18, Pitfall 1/2). The hook fires only on was_created,
# so re-running materialize is idempotent.
# ---------------------------------------------------------------------------
_FUTURE_MONDAY = date(2026, 7, 13)  # one week past the fixture's IN_WINDOW_DATE


def _approved_request(fx, target, schedule, window_start, window_end, *,
                      assigned_room=None, time_move=None, decided_at=None):
    """Persist an APPROVED ModalityShiftRequest + one item (bypassing apply).

    Mirrors the state 04-05 apply_approval leaves behind: an APPROVED request
    whose item already carries the reserved ``assigned_room`` (D-18) and,
    optionally, a bundled time-move. ``decided_by``/``decided_at`` stamp the
    decision the materialize hook copies onto each born session.
    """
    decided = decided_at or _manila(2026, 6, 1, 9, 0)
    req = ModalityShiftRequest.objects.create(
        requester=fx.faculty, dean=fx.dean, department=fx.dept,
        target_modality=target, window_start=window_start, window_end=window_end,
        is_time_move=bool(time_move), status=ModalityShiftStatus.APPROVED,
        decided_by=fx.dean, decided_at=decided,
    )
    nst, net = time_move or (None, None)
    ModalityShiftItem.objects.create(
        request=req, schedule=schedule, assigned_room=assigned_room,
        new_start_time=nst, new_end_time=net,
    )
    return req


def _materialize_future(days=1, start=_FUTURE_MONDAY):
    """Run JOB-01 for a single future date past the fixture's materialized set."""
    call_command("materialize_sessions", days=days, start=str(start))


class MaterializeCommandTests(TestCase):
    """JOB-01 extraction guard: command behavior stays delegated and idempotent."""

    def test_command_delegates_to_materialize_term_without_inline_loop(self):
        source = Path(
            "scheduling/management/commands/materialize_sessions.py"
        ).read_text(encoding="utf-8")

        self.assertIn("materialize_term(", source)
        self.assertNotIn(".filter(is_active=True).first()", source)
        self.assertNotIn("while d < end", source)

    def test_rerun_still_materializes_future_session_once(self):
        fx = make_shift_fixture("mct")

        _materialize_future()
        _materialize_future()

        self.assertEqual(
            Session.objects.filter(
                schedule=fx.f2f_schedule,
                date=_FUTURE_MONDAY,
            ).count(),
            1,
        )

    def test_approved_online_shift_hook_survives_extraction(self):
        fx = make_shift_fixture("mcs")
        _approved_request(
            fx, Modality.ONLINE, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20))

        _materialize_future()

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.declared_modality, Modality.ONLINE)
        self.assertIsNotNone(born.room_released_at)


class BornReleasedTests(TestCase):
    """MOD-03/D-04/Pitfall 1: a future in-window session materialized AFTER an
    approved ->Online shift is born released -- declared_modality=Online and
    room_released_at stamped -- so the out-of-horizon tail of a recurring window
    still honors the approval. Out-of-window future dates are untouched, and a
    re-run does not re-process an already-created session (idempotent)."""

    def test_future_in_window_session_born_released(self):
        fx = make_shift_fixture()
        _approved_request(
            fx, Modality.ONLINE, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20))
        _materialize_future()

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.declared_modality, Modality.ONLINE)
        self.assertIsNotNone(born.room_released_at)
        self.assertEqual(born.modality_changed_by, fx.dean)
        # The room FK is NEVER nulled -- the release signal is room_released_at.
        self.assertEqual(born.room_id, fx.room_a.id)
        self.assertTrue(AuditLog.objects.filter(
            event_type="session.room_released", target_id=str(born.pk)).exists())

    def test_out_of_window_future_session_not_released(self):
        fx = make_shift_fixture()
        # Window covers only the original in-window date; the future Monday is OUT.
        _approved_request(
            fx, Modality.ONLINE, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 6))
        _materialize_future()

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.declared_modality, "")
        self.assertIsNone(born.room_released_at)

    def test_rerun_is_idempotent(self):
        fx = make_shift_fixture()
        _approved_request(
            fx, Modality.ONLINE, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20))
        _materialize_future()
        _materialize_future()  # second run: session already exists -> hook skipped

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.declared_modality, Modality.ONLINE)
        # Exactly one release event -- the hook fired once (was_created only).
        self.assertEqual(AuditLog.objects.filter(
            event_type="session.room_released",
            target_id=str(born.pk)).count(), 1)


class BornAssignedTests(TestCase):
    """MOD-04/D-18/Pitfall 2: a future in-window session materialized AFTER an
    approved ->F2F/Blended shift is born in the item's already-reserved room --
    materialize APPLIES the reservation, it never re-resolves -- including any
    bundled time-move. The defensive no-room guard keeps the original room and
    notifies IFO without ever raising inside the unattended job."""

    def _ifo(self, suffix="1"):
        return get_user_model().objects.create(
            username=f"mat_ifo_{suffix}", email=f"mat_ifo_{suffix}@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)

    def test_future_in_window_session_born_in_reserved_room(self):
        fx = make_shift_fixture()
        # f2f_schedule.room is room_a; the approval reserved room_b (D-18).
        _approved_request(
            fx, Modality.F2F, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20), assigned_room=fx.room_b)
        _materialize_future()

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.room_id, fx.room_b.id)  # reservation applied, not re-resolved
        self.assertEqual(born.declared_modality, Modality.F2F)
        self.assertEqual(born.modality_changed_by, fx.dean)
        self.assertIsNone(born.room_released_at)

    def test_time_move_born_at_new_slot(self):
        fx = make_shift_fixture()
        _approved_request(
            fx, Modality.F2F, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20), assigned_room=fx.room_b,
            time_move=(_time(13, 0), _time(14, 30)))
        _materialize_future()

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.room_id, fx.room_b.id)
        self.assertEqual(born.scheduled_start, _manila(2026, 7, 13, 13, 0))
        self.assertEqual(born.scheduled_end, _manila(2026, 7, 13, 14, 30))
        self.assertEqual(born.declared_modality, Modality.F2F)

    def test_no_assigned_room_falls_back_to_schedule_room_and_notifies_ifo(self):
        # Contrived defensive case (cannot occur in Phase 4 scope, D-18): an
        # approved ->F2F item with no reserved room. The job must NOT crash --
        # keep the original schedule.room and notify IFO informationally.
        fx = make_shift_fixture()
        ifo = self._ifo()
        _approved_request(
            fx, Modality.BLENDED, fx.f2f_schedule,
            date(2026, 7, 6), date(2026, 7, 20), assigned_room=None)
        _materialize_future()  # must not raise

        born = Session.objects.get(schedule=fx.f2f_schedule, date=_FUTURE_MONDAY)
        self.assertEqual(born.room_id, fx.room_a.id)  # kept the schedule default
        self.assertEqual(
            Notification.objects.filter(
                user=ifo, type="modality_materialize_no_room").count(), 1)

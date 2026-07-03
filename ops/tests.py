"""Tests for ops services (SRS §5).

NOTIF-00 — the single Notification write path `ops.notify.notify`:
- NotifyTests: role fan-out reaches ACTIVE users of a role only, explicit-user
  targeting, empty-target no-op, and that notify() writes no AuditLog.
- SingleWritePathTests: a source guard proving the ad-hoc IFO notifier helper is
  gone from web/scan.py and that no notifier module constructs Notification rows
  inline outside ops/notify.py.

JOB-02c — the room-release single write path `ops.occupancy.release_room`:
- ReleaseRoomTests: release_room(session) stamps Session.room_released_at and
  writes exactly one session.room_released AuditLog; explicit actor/now are
  recorded. The paired "sweep NEVER stamps room_released_at" guard lives in
  Plan 02-03 SweepTests, not here.
"""
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from accounts.models import Role
from ops.models import AuditLog, Notification


class NotifyTests(TestCase):
    """notify(role=...) fans out to ACTIVE users of that role only; notify(users=...)
    targets an explicit iterable; neither target creates nothing (NOTIF-00).

    Guards T-02-03: the recipient query must reproduce the old _notify_ifo filter
    (role match + is_active=True) so inactive/other-role accounts never receive rows.
    """

    def setUp(self):
        User = get_user_model()
        self.ifo1 = User.objects.create(username="ifo1", role=Role.IFO_ADMIN)
        self.ifo2 = User.objects.create(username="ifo2", role=Role.IFO_ADMIN)
        self.ifo_inactive = User.objects.create(
            username="ifo3", role=Role.IFO_ADMIN, is_active=False)
        self.faculty = User.objects.create(username="fac1", role=Role.FACULTY)

    def test_role_fanout_targets_active_users_only(self):
        from ops.notify import notify
        rows = notify(role=Role.IFO_ADMIN, type="room_event", title="t", body="b")
        self.assertEqual(len(rows), 2)
        recipients = {n.user_id for n in Notification.objects.all()}
        self.assertEqual(recipients, {self.ifo1.pk, self.ifo2.pk})
        self.assertNotIn(self.ifo_inactive.pk, recipients)
        self.assertNotIn(self.faculty.pk, recipients)

    def test_role_fanout_sets_fields(self):
        from ops.notify import notify
        notify(role=Role.IFO_ADMIN, type="room_event", title="Room change",
               body="body text", link="/x")
        n = Notification.objects.filter(user=self.ifo1).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.type, "room_event")
        self.assertEqual(n.title, "Room change")
        self.assertEqual(n.body, "body text")
        self.assertEqual(n.link, "/x")

    def test_explicit_users_target_creates_one_row_each(self):
        from ops.notify import notify
        rows = notify(users=[self.faculty], type="x", title="t")
        self.assertEqual(len(rows), 1)
        self.assertEqual(Notification.objects.filter(user=self.faculty).count(), 1)

    def test_no_target_creates_nothing(self):
        from ops.notify import notify
        rows = notify(type="x", title="t")
        self.assertEqual(rows, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_emits_no_auditlog(self):
        from ops.notify import notify
        before = AuditLog.objects.count()
        notify(role=Role.IFO_ADMIN, type="room_event", title="t")
        self.assertEqual(AuditLog.objects.count(), before)


class SingleWritePathTests(TestCase):
    """Source guard (T-02-04): every Notification row is created in exactly one
    place — ops/notify.py. The ad-hoc IFO notifier helper must be gone from
    web/scan.py, and no notifier module may construct Notification rows inline.

    The forbidden tokens are assembled from parts so this guard can never match
    its own source; only named notifier modules (never this test file) are read.
    """

    # Assembled from parts on purpose — keeps the guard from matching itself.
    _CREATE_TOKEN = "Notification.objects" + ".create"
    _HELPER_TOKEN = "_notify" + "_ifo"

    # Modules permitted to be scanned as notifier call sites (never the test file).
    NOTIFIER_MODULES = ["web/scan.py", "scheduling/jobs.py"]

    def _read(self, rel):
        return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")

    def test_adhoc_ifo_notifier_helper_removed_from_scan(self):
        src = self._read("web/scan.py")
        self.assertNotIn("def " + self._HELPER_TOKEN, src,
                         "web/scan.py still defines the ad-hoc IFO notifier helper")

    def test_no_inline_notification_create_outside_notify_module(self):
        for rel in self.NOTIFIER_MODULES:
            path = Path(settings.BASE_DIR) / rel
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn(
                self._CREATE_TOKEN, src,
                f"{rel} constructs Notification rows inline; route through "
                "ops.notify.notify (NOTIF-00 single write path)")


class ReleaseRoomTests(TestCase):
    """JOB-02c: `ops.occupancy.release_room` is the single source of truth for
    releasing a room. Given a Session with room_released_at IS NULL, calling
    release_room(session) stamps room_released_at with an aware datetime and
    writes exactly one AuditLog(event_type="session.room_released"). Guards
    T-02-10 (every release is audited with actor + released_at).

    NOTE: the paired "sweep NEVER stamps room_released_at" guard is enforced in
    Plan 02-03 SweepTests — release_room has zero Phase-2 callers (T-02-11).

    Imports are method-local (mirrors NotifyTests) so this class is the only one
    that goes RED before ops/occupancy.py exists — the 02-02 classes stay green.
    """

    def _session(self):
        # Reuse the scheduling test factory (aware start) to build the FK chain.
        from scheduling.tests import make_session
        aware = datetime(2026, 7, 6, 8, 0, tzinfo=dt_timezone.utc)
        return make_session(aware)

    def test_release_stamps_room_released_at(self):
        from ops.occupancy import release_room
        s = self._session()
        self.assertIsNone(s.room_released_at)  # precondition: not yet released
        release_room(s)
        s.refresh_from_db()
        self.assertIsNotNone(s.room_released_at)
        self.assertIsNotNone(s.room_released_at.tzinfo)  # aware datetime

    def test_release_writes_single_audit_row(self):
        from ops.occupancy import release_room
        s = self._session()
        before = AuditLog.objects.count()
        release_room(s)
        self.assertEqual(AuditLog.objects.count(), before + 1)
        log = AuditLog.objects.filter(
            event_type="session.room_released", target_id=str(s.pk)).get()
        self.assertEqual(log.target_type, "session")
        self.assertIn("released_at", log.payload)

    def test_release_records_explicit_actor(self):
        from ops.occupancy import release_room
        User = get_user_model()
        dean = User.objects.create(username="dean1", role=Role.DEAN)
        s = self._session()
        release_room(s, actor=dean)
        log = AuditLog.objects.filter(
            event_type="session.room_released", target_id=str(s.pk)).get()
        self.assertEqual(log.actor_id, dean.pk)

    def test_release_default_actor_is_none(self):
        from ops.occupancy import release_room
        s = self._session()
        release_room(s)  # system-initiated: actor omitted
        log = AuditLog.objects.filter(
            event_type="session.room_released", target_id=str(s.pk)).get()
        self.assertIsNone(log.actor_id)

    def test_release_records_explicit_now(self):
        from ops.occupancy import release_room
        s = self._session()
        instant = datetime(2026, 7, 6, 10, 30, tzinfo=dt_timezone.utc)
        release_room(s, now=instant)
        s.refresh_from_db()
        self.assertEqual(s.room_released_at, instant)
        log = AuditLog.objects.filter(
            event_type="session.room_released", target_id=str(s.pk)).get()
        self.assertEqual(log.payload["released_at"], instant.isoformat())


# ---------------------------------------------------------------------------
# ENV-04 scheduler observability: run_job / JobRun + no-implicit-scheduler guard.
# run_job wraps every scheduled job: it records a JobRun row per execution and
# notifies System Admins on FAILURE ONLY (never on success/heartbeat), and never
# re-raises so one bad run cannot kill the dedicated BlockingScheduler process.
# NoImplicitSchedulerTests proves the scheduler is constructed only in
# runscheduler.build_scheduler() — never in an AppConfig.ready() (per-worker
# double-fire is the exact failure ENV-04 prohibits). Imports of ops.jobrun /
# JobRun are method-local so ONLY these ENV-04 classes go RED before Task 2.
# ---------------------------------------------------------------------------
from pathlib import Path as _Path  # noqa: E402  (Path already imported above)


class JobRunTests(TestCase):
    """ENV-04: `ops.jobrun.run_job` records a JobRun per run and alerts on failure only.

    A success run records status="ok", rows_affected, a non-null finished_at, and
    writes NO job_failed Notification. A failing run records status="failed" with a
    non-empty detail, creates a job_failed Notification for every active
    SYSTEM_ADMIN, and does NOT re-raise (the scheduler must survive a bad run).
    SYS-04 (Phase 7) will later read the latest JobRun per job_name.

    Imports are method-local (mirrors ReleaseRoomTests) so only the ENV-04 classes
    go RED before ops/jobrun.py + JobRun exist; the 02-02/02-04 classes stay green.
    """

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create(
            username="sysadmin1", email="sa1@mcm.edu.ph",
            role=Role.SYSTEM_ADMIN, is_active=True)
        # An inactive admin and a non-admin must never receive a failure alert.
        self.admin_inactive = User.objects.create(
            username="sysadmin2", email="sa2@mcm.edu.ph",
            role=Role.SYSTEM_ADMIN, is_active=False)
        self.faculty = User.objects.create(
            username="fac_jr", email="fac_jr@mcm.edu.ph", role=Role.FACULTY)

    def test_success_records_ok_rows_and_no_failure_notice(self):
        from ops.jobrun import run_job
        from ops.models import JobRun
        run = run_job("demo", lambda: 7)
        self.assertEqual(run.status, "ok")
        self.assertEqual(run.rows_affected, 7)
        self.assertIsNotNone(run.finished_at)
        row = JobRun.objects.get(pk=run.pk)
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.rows_affected, 7)
        # success/heartbeat runs NEVER notify.
        self.assertEqual(Notification.objects.filter(type="job_failed").count(), 0)

    def test_success_with_none_return_records_zero_rows(self):
        from ops.jobrun import run_job
        run = run_job("demo", lambda: None)
        self.assertEqual(run.status, "ok")
        self.assertEqual(run.rows_affected, 0)

    def test_failure_records_failed_detail_and_notifies_active_sysadmins_only(self):
        from ops.jobrun import run_job
        from ops.models import JobRun

        def boom():
            raise ValueError("kaboom")

        run = run_job("demo", boom)   # must NOT re-raise
        self.assertEqual(run.status, "failed")
        self.assertTrue(run.detail)                 # non-empty detail
        self.assertIn("kaboom", run.detail)
        self.assertIsNotNone(run.finished_at)
        row = JobRun.objects.get(pk=run.pk)
        self.assertEqual(row.status, "failed")
        # Exactly one job_failed notice, to the ACTIVE system admin only.
        notes = Notification.objects.filter(type="job_failed")
        self.assertEqual(notes.count(), 1)
        self.assertEqual(notes.first().user_id, self.admin.pk)

    def test_failure_does_not_reraise(self):
        from ops.jobrun import run_job
        # If run_job re-raised, this call would error the test out.
        run = run_job("demo", lambda: (_ for _ in ()).throw(RuntimeError("x")))
        self.assertEqual(run.status, "failed")


class NoImplicitSchedulerTests(SimpleTestCase):
    """T-02-12 (ENV-04): no project app's `apps.py` may construct or start a
    scheduler. A BlockingScheduler started from an AppConfig.ready() runs once per
    Gunicorn worker -> the exact double-fire ENV-04 forbids. The scheduler is
    constructed ONLY in runscheduler.build_scheduler().

    The searched tokens are assembled from parts so this guard can never match its
    own source text; only the named project apps' apps.py files are read.
    """

    PROJECT_APPS = ["accounts", "campus", "scheduling", "verification", "ops", "web"]
    # Assembled from parts so the guard cannot self-match.
    _FORBIDDEN_TOKENS = ["Blocking" + "Scheduler",
                         "Background" + "Scheduler",
                         "ap" + "scheduler"]

    def test_no_app_config_constructs_or_imports_a_scheduler(self):
        for app in self.PROJECT_APPS:
            path = _Path(settings.BASE_DIR) / app / "apps.py"
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            for token in self._FORBIDDEN_TOKENS:
                self.assertNotIn(
                    token, src,
                    f"{app}/apps.py references '{token}' — the scheduler must be "
                    "constructed only in runscheduler.build_scheduler(), never in "
                    "an AppConfig.ready() (per-worker double-fire, ENV-04)")


# ---------------------------------------------------------------------------
# MOD-04 pre-booking availability primitive: ops/availability.py.
# RoomAvailabilityTests is a property-style suite over the single "is room R free
# for [start,end)?" primitive that the picker (04-07), approval apply (04-05) and
# materialize hook (04-06) all call. Overlap is HALF-OPEN (adjacent slots do not
# collide, D-08); an Online / released / absent / completed session holds no
# physical room; an active Booking occupies; an approved ->F2F reservation
# occupies even before its Session materializes (D-18); faculty_has_conflict vetoes
# a time-move that would double-book the faculty (D-17).
#
# ops.availability imports are METHOD-LOCAL (mirrors ReleaseRoomTests) so this is
# the only class that goes RED before ops/availability.py exists.
# ---------------------------------------------------------------------------
from datetime import datetime as _dt, time as _time, timedelta as _timedelta  # noqa: E402

from scheduling.models import (  # noqa: E402
    Modality as _Modality,
    ModalityShiftItem as _ShiftItem,
    ModalityShiftRequest as _ShiftReq,
    ModalityShiftStatus as _ShiftStatus,
    SessionStatus as _SessionStatus,
)
from scheduling.test_support import MANILA as _MANILA, make_shift_fixture  # noqa: E402


def _mnl(d, hh, mm):
    """Asia/Manila-aware datetime helper, matching the fixture's tz."""
    return _dt(d.year, d.month, d.day, hh, mm, tzinfo=_MANILA)


class RoomAvailabilityTests(TestCase):
    """ops/availability.py: half-open, building-scoped, Booking- and request-aware
    room availability + faculty double-book guard (MOD-04 / D-08 / D-18 / D-17)."""

    def setUp(self):
        self.fx = make_shift_fixture()
        self.date = self.fx.session.date  # IN_WINDOW_DATE Monday (day_of_week=0)
        # The fixture seeds TWO SCHEDULED F2F occupants on room_a for the 08:00-09:30
        # slot: fx.session (the class being moved) and fx.competitor (another
        # faculty). Room B is held only by an Online session -> no physical room.

    # --- Task 1: overlap + building scope + Booking ------------------------
    def test_overlap_makes_room_not_free(self):
        from ops.availability import room_is_free
        self.assertFalse(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_free_when_no_overlap(self):
        from ops.availability import room_is_free
        # 12:00-13:00 does not overlap the 08:00-09:30 occupants.
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 12, 0), _mnl(self.date, 13, 0)))

    def test_adjacent_boundary_is_free(self):
        from ops.availability import room_is_free
        # Occupant ends 09:30; a slot STARTING at 09:30 is adjacent, not overlapping.
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 9, 30), _mnl(self.date, 11, 0)))

    def test_released_session_excluded(self):
        from ops.availability import room_is_free
        for s in (self.fx.session, self.fx.competitor):
            s.room_released_at = _mnl(self.date, 8, 5)
            s.save(update_fields=["room_released_at"])
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_online_session_excluded(self):
        from ops.availability import room_is_free
        # An Online effective modality holds no physical room even on room_a.
        for s in (self.fx.session, self.fx.competitor):
            s.declared_modality = _Modality.ONLINE
            s.save(update_fields=["declared_modality"])
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_absent_and_completed_excluded(self):
        from ops.availability import room_is_free
        self.fx.session.status = _SessionStatus.ABSENT
        self.fx.session.save(update_fields=["status"])
        self.fx.competitor.status = _SessionStatus.COMPLETED
        self.fx.competitor.save(update_fields=["status"])
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_active_booking_occupies(self):
        from ops.availability import room_is_free
        from ops.models import Booking
        # Room B is otherwise free at 08:00-09:30 (its only session is Online).
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))
        Booking.objects.create(
            room=self.fx.room_b, occupant_name="Faculty Senate",
            start_datetime=_mnl(self.date, 8, 0), end_datetime=_mnl(self.date, 9, 30),
            status="active")
        self.assertFalse(
            room_is_free(self.fx.room_b, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_inactive_booking_does_not_occupy(self):
        from ops.availability import room_is_free
        from ops.models import Booking
        Booking.objects.create(
            room=self.fx.room_b, occupant_name="Cancelled",
            start_datetime=_mnl(self.date, 8, 0), end_datetime=_mnl(self.date, 9, 30),
            status="cancelled")
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_exclude_session_id_self_exclusion(self):
        from ops.availability import room_is_free
        # Leave ONLY fx.session holding room_a, then exclude it -> free.
        self.fx.competitor.status = _SessionStatus.COMPLETED
        self.fx.competitor.save(update_fields=["status"])
        self.assertFalse(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))
        self.assertTrue(
            room_is_free(self.fx.room_a, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30),
                         exclude_session_id=self.fx.session.pk))

    def test_free_rooms_in_building_scoped_and_ordered(self):
        from ops.availability import free_rooms_in_building
        from campus.models import Building, Floor, Room
        # A room in a DIFFERENT building must never be returned.
        other_b = Building.objects.create(name="Other Hall", code="OTHER-BLD")
        other_f = Floor.objects.create(building=other_b, number=1)
        Room.objects.create(
            floor=other_f, code="OTHER-A", capacity=10,
            qr_token="other-qr-a", manual_code="OTA001")
        # At 08:00-09:30 room_a is doubly held; room_b (Online only) is free.
        free = free_rooms_in_building(
            self.fx.building, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30))
        codes = [r.code for r in free]
        self.assertEqual(codes, [self.fx.room_b.code])

    def test_free_rooms_prefer_room_first(self):
        from ops.availability import free_rooms_in_building
        # A wholly-free slot: both rooms free; prefer_room floats to the front.
        free = free_rooms_in_building(
            self.fx.building, _mnl(self.date, 14, 0), _mnl(self.date, 15, 0),
            prefer_room=self.fx.room_b)
        self.assertEqual(free[0].code, self.fx.room_b.code)
        self.assertEqual({r.code for r in free},
                         {self.fx.room_a.code, self.fx.room_b.code})

    # --- Task 2: request-aware occupancy + faculty double-book guard -------
    def _approved_reservation(self, target, assigned_room, on_date):
        """Seed an APPROVED ModalityShiftRequest+Item reserving ``assigned_room``
        for ``on_date`` via the fixture's Monday f2f_schedule (08:00-09:30)."""
        req = _ShiftReq.objects.create(
            requester=self.fx.faculty, dean=self.fx.dean, department=self.fx.dept,
            target_modality=target, window_start=on_date, window_end=on_date,
            status=_ShiftStatus.APPROVED)
        return _ShiftItem.objects.create(
            request=req, schedule=self.fx.f2f_schedule, assigned_room=assigned_room)

    def test_approved_f2f_reservation_occupies_before_materialize(self):
        from ops.availability import room_is_free
        future = self.date + _timedelta(days=7)  # next Monday, no Session exists yet
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(future, 8, 0), _mnl(future, 9, 30)))
        self._approved_reservation(_Modality.F2F, self.fx.room_b, future)
        self.assertFalse(
            room_is_free(self.fx.room_b, _mnl(future, 8, 0), _mnl(future, 9, 30)))

    def test_approved_online_request_reserves_nothing(self):
        from ops.availability import room_is_free
        future = self.date + _timedelta(days=7)
        self._approved_reservation(_Modality.ONLINE, self.fx.room_b, future)
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(future, 8, 0), _mnl(future, 9, 30)))

    def test_pending_reservation_does_not_occupy(self):
        from ops.availability import room_is_free
        future = self.date + _timedelta(days=7)
        req = _ShiftReq.objects.create(
            requester=self.fx.faculty, dean=self.fx.dean, department=self.fx.dept,
            target_modality=_Modality.F2F, window_start=future, window_end=future,
            status=_ShiftStatus.PENDING)
        _ShiftItem.objects.create(
            request=req, schedule=self.fx.f2f_schedule, assigned_room=self.fx.room_b)
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(future, 8, 0), _mnl(future, 9, 30)))

    def test_reservation_out_of_window_does_not_occupy(self):
        from ops.availability import room_is_free
        reserved = self.date + _timedelta(days=7)
        other = self.date + _timedelta(days=14)  # a Monday outside the window
        self._approved_reservation(_Modality.F2F, self.fx.room_b, reserved)
        self.assertTrue(
            room_is_free(self.fx.room_b, _mnl(other, 8, 0), _mnl(other, 9, 30)))

    def test_faculty_has_conflict_true(self):
        from ops.availability import faculty_has_conflict
        # fx.faculty owns fx.session (08:00-09:30) on self.date.
        self.assertTrue(faculty_has_conflict(
            self.fx.faculty, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30)))

    def test_faculty_has_conflict_excludes_moved_session(self):
        from ops.availability import faculty_has_conflict
        self.assertFalse(faculty_has_conflict(
            self.fx.faculty, _mnl(self.date, 8, 0), _mnl(self.date, 9, 30),
            exclude_session_id=self.fx.session.pk))

    def test_faculty_has_conflict_false_when_free(self):
        from ops.availability import faculty_has_conflict
        # 14:00-15:00: the faculty teaches nothing then.
        self.assertFalse(faculty_has_conflict(
            self.fx.faculty, _mnl(self.date, 14, 0), _mnl(self.date, 15, 0)))

    # --- Task 3: picker queries -------------------------------------------
    def test_available_rooms_prefers_original_when_free(self):
        from ops.availability import available_rooms_for
        # Clear the competing occupant so the session's own room_a is free.
        self.fx.competitor.status = _SessionStatus.COMPLETED
        self.fx.competitor.save(update_fields=["status"])
        rooms = available_rooms_for(self.fx.session)
        codes = [r.code for r in rooms]
        self.assertEqual(codes[0], self.fx.room_a.code)  # original preferred first
        self.assertEqual(set(codes), {self.fx.room_a.code, self.fx.room_b.code})

    def test_available_rooms_empty_when_preferred_time_full(self):
        from ops.availability import available_rooms_for
        from ops.models import Booking
        # room_a is held by fx.competitor; also fill room_b at the same slot.
        Booking.objects.create(
            room=self.fx.room_b, occupant_name="Seminar",
            start_datetime=_mnl(self.date, 8, 0), end_datetime=_mnl(self.date, 9, 30),
            status="active")
        self.assertEqual(available_rooms_for(self.fx.session), [])

    def test_available_times_offers_alternative_without_double_booking(self):
        from ops.availability import available_times_for
        from ops.models import Booking
        # Preferred time (08:00-09:30) is full in both rooms.
        Booking.objects.create(
            room=self.fx.room_b, occupant_name="Seminar",
            start_datetime=_mnl(self.date, 8, 0), end_datetime=_mnl(self.date, 9, 30),
            status="active")
        slots = available_times_for(self.fx.session)
        self.assertTrue(slots, "expected at least one alternative time slot")
        # The faculty already teaches the Online class 10:00-11:30 -> never offered.
        self.assertNotIn(
            (_mnl(self.date, 10, 0), _mnl(self.date, 11, 30)), slots)
        # A known free, non-conflicting alternative is present.
        self.assertIn(
            (_mnl(self.date, 11, 30), _mnl(self.date, 13, 0)), slots)

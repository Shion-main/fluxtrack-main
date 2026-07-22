"""GRD-04: coalesced floor alerts to on-duty Guards (D-05/D-06/D-21, plan 07-12).

Three suites, each locking a different promise:

  - ``CoalescingTests`` -- the requirement itself. A sweep run that produces
    THREE events on one floor must produce exactly ONE notification for the guard
    posted there. Every count assertion here is an equality, never an
    ``assertGreaterEqual``: "at least one" would pass the exact per-room push
    storm D-06 forbids, which is the whole point of the feature.
  - ``ScopingTests`` -- who must receive nothing: a guard on an unaffected floor,
    a guard whose dated shift does not cover now, and a deactivated account
    (``notify(users=[...])`` does not filter ``is_active``; only this module does).
  - ``SweepReturnCompatibilityTests`` -- the permanent guard on the additive-seam
    promise. ``sweep_no_shows`` and ``detect_room_conflicts`` return scalar ints
    that are asserted at fourteen call sites across ``scheduling/tests.py``,
    ``scheduling/tests_merge_sweep.py`` and both command wrappers. Passing a
    collector must not perturb those integers by so much as one.

The sweep is driven the way the CALLERS drive it (one shared collector into both
functions, then one fan-out), because the caller IS the coalescing boundary --
testing the two service functions in isolation would not exercise the design.

ASCII-only assertions (Windows cp1252).
"""
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from ops.guard_alerts import (
    GUARD_ALERT_LINK,
    KIND_ABSENT,
    KIND_CONFLICT,
    notify_floor_guards,
    summarize_floor_events,
)
from ops.models import Notification
from ops.notifications import GUARD_FLOOR_ALERT
from scheduling.jobs import detect_room_conflicts, sweep_no_shows
from scheduling.models import Session, SessionStatus
from scheduling.tests import make_session
from verification.models import (
    Assignment,
    AssignmentScope,
    AssignmentType,
    DutyRole,
)


class GuardAlertBase(TestCase):
    """Shared fixture: the make_session FK chain plus extra rooms and guards.

    ``scheduling.tests.make_session`` is the project's FK-chain factory, but it
    hardcodes its usernames and room tokens, so it can only be called ONCE per
    test. It is used here to build the term/schedule/faculty spine, and extra
    rooms and sessions are hung off that spine directly.
    """

    def setUp(self):
        # 09:00 local "now"; the seed session starts 60 min earlier so it is well
        # past the 15-minute grace and is a genuine no-show.
        self.now = timezone.now()
        self.seed = make_session(self.now - timedelta(minutes=60))
        self.schedule = self.seed.schedule
        self.faculty = self.seed.faculty
        self.floor1 = self.seed.room.floor            # from make_session
        self.building = self.floor1.building
        self.floor2 = Floor.objects.create(building=self.building, number=9)
        self._room_n = 0

    # -- fixture helpers ---------------------------------------------------

    def _room(self, floor):
        self._room_n += 1
        n = self._room_n
        return Room.objects.create(
            floor=floor, code=f"GA{n:03d}",
            qr_token=f"ga-tok-{n}", manual_code=f"G{n:05d}")

    def _session(self, room, minutes_ago=60, status=SessionStatus.SCHEDULED):
        start = self.now - timedelta(minutes=minutes_ago)
        return Session.objects.create(
            schedule=self.schedule, faculty=self.faculty, room=room,
            date=start.date(), scheduled_start=start,
            scheduled_end=start + timedelta(minutes=90), status=status)

    def _guard(self, username, is_active=True):
        return get_user_model().objects.create(
            username=username, email=f"{username}@mcm.edu.ph",
            role=Role.GUARD, is_active=is_active)

    def _post(self, guard, *floors, standing=True, start=None, end=None,
              on_date=None):
        """Post a guard to floors. Standing by default; a dated SHIFT if given.

        Mirrors the Assignment construction shape web/tests.py
        GuardSurfaceTests._post_guard_to demonstrates.
        """
        a = Assignment.objects.create(
            user=guard, role=DutyRole.GUARD,
            type=AssignmentType.STANDING if standing else AssignmentType.SHIFT,
            scope=AssignmentScope.FLOOR, term=self.schedule.term, status="active",
            date=on_date, start_time=start, end_time=end)
        a.floors.set(floors)
        return a

    def _run_sweep(self):
        """Drive the sweep exactly as both callers do: ONE shared collector into
        both functions, then ONE fan-out afterwards."""
        events = []
        marked = sweep_no_shows(now=self.now, collect=events)
        flagged = detect_room_conflicts(now=self.now, collect=events)
        guards = notify_floor_guards(events, now=self.now)
        return marked, flagged, guards

    def _alerts(self, guard):
        return Notification.objects.filter(user=guard, type=GUARD_FLOOR_ALERT)


class CoalescingTests(GuardAlertBase):
    """D-06: ONE push per on-duty guard per sweep run, never one per event."""

    def test_three_absences_on_one_floor_produce_exactly_one_alert(self):
        # THE requirement. Three separate rooms, three separate swept sessions,
        # one floor, one guard -> exactly ONE notification. An assertGreaterEqual
        # here would happily pass the three-push storm this feature prevents.
        for _ in range(3):
            self._session(self._room(self.floor1))
        guard = self._guard("grd_coalesce")
        self._post(guard, self.floor1)

        marked, _flagged, notified = self._run_sweep()

        self.assertGreaterEqual(marked, 3)      # the 3 + the make_session seed
        self.assertEqual(notified, 1)
        self.assertEqual(self._alerts(guard).count(), 1)

    def test_alert_names_the_batch_and_links_to_the_monitor(self):
        for _ in range(3):
            self._session(self._room(self.floor1))
        guard = self._guard("grd_wording")
        self._post(guard, self.floor1)

        self._run_sweep()

        alert = self._alerts(guard).get()
        self.assertEqual(alert.type, GUARD_FLOOR_ALERT)
        self.assertEqual(alert.link, GUARD_ALERT_LINK)
        # 3 extra rooms + the make_session seed room, all on floor1.
        self.assertIn("4 rooms now free", alert.title)
        self.assertIn(str(self.floor1), alert.title)

    def test_two_floors_one_alert_per_guard_scoped_to_their_own_floors(self):
        # A guard covering only floor1 must not learn about floor2 activity.
        self._session(self._room(self.floor1))
        self._session(self._room(self.floor2))
        g1 = self._guard("grd_f1")
        g2 = self._guard("grd_f2")
        self._post(g1, self.floor1)
        self._post(g2, self.floor2)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 2)
        self.assertEqual(self._alerts(g1).count(), 1)
        self.assertEqual(self._alerts(g2).count(), 1)
        self.assertIn(str(self.floor1), self._alerts(g1).get().title)
        self.assertNotIn(str(self.floor2), self._alerts(g1).get().body)
        self.assertIn(str(self.floor2), self._alerts(g2).get().title)
        self.assertNotIn(str(self.floor1), self._alerts(g2).get().body)

    def test_guard_with_two_postings_still_gets_one_alert(self):
        # Two Assignment rows for one guard must collapse to a single recipient.
        self._session(self._room(self.floor1))
        self._session(self._room(self.floor2))
        guard = self._guard("grd_two_posts")
        self._post(guard, self.floor1)
        self._post(guard, self.floor2)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 1)
        self.assertEqual(self._alerts(guard).count(), 1)
        body = self._alerts(guard).get().body
        self.assertIn(str(self.floor1), body)
        self.assertIn(str(self.floor2), body)

    def test_quiet_run_produces_no_guard_alerts_at_all(self):
        # Nothing past grace, no conflicts -> no rows, and no DB work either.
        Session.objects.all().delete()
        guard = self._guard("grd_quiet")
        self._post(guard, self.floor1)

        marked, flagged, notified = self._run_sweep()

        self.assertEqual((marked, flagged, notified), (0, 0, 0))
        self.assertEqual(self._alerts(guard).count(), 0)

    def test_empty_collection_short_circuits(self):
        self.assertEqual(notify_floor_guards([]), 0)
        self.assertEqual(notify_floor_guards(None), 0)


class IfoBehaviourUnchangedTests(GuardAlertBase):
    """The per-conflict IFO notification is Phase-2 behaviour and stays exactly
    as it was: ONE IFO notification per newly-flagged conflict."""

    def _conflicting_room(self):
        room = self._room(self.floor1)
        for _ in range(2):
            self._session(room, minutes_ago=10, status=SessionStatus.ACTIVE)
        return room

    def test_one_ifo_notification_per_new_conflict(self):
        self._conflicting_room()
        ifo = get_user_model().objects.create(
            username="ifo_grd04", email="ifo_grd04@mcm.edu.ph",
            role=Role.IFO_ADMIN)

        _marked, flagged, _notified = self._run_sweep()

        self.assertEqual(flagged, 1)
        self.assertEqual(
            Notification.objects.filter(
                user=ifo, type="room_conflict").count(), 1)

    def test_conflict_also_reaches_the_floor_guard_once(self):
        self._conflicting_room()
        guard = self._guard("grd_conflict")
        self._post(guard, self.floor1)

        self._run_sweep()

        alert = self._alerts(guard).get()          # exactly one row
        self.assertIn("room conflict", alert.title)


class ScopingTests(GuardAlertBase):
    """T-07-63 / T-07-64: who must receive nothing."""

    def setUp(self):
        super().setUp()
        self._session(self._room(self.floor1))     # activity on floor1 only

    def test_guard_on_unaffected_floor_gets_nothing(self):
        guard = self._guard("grd_offfloor")
        self._post(guard, self.floor2)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 0)
        self.assertEqual(self._alerts(guard).count(), 0)

    def test_guard_whose_shift_does_not_cover_now_gets_nothing(self):
        # A dated shift for today whose window closed before `now`.
        guard = self._guard("grd_offshift")
        local = timezone.localtime(self.now)
        self._post(guard, self.floor1, standing=False, on_date=local.date(),
                   start=time(0, 0), end=time(0, 1))

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 0)
        self.assertEqual(self._alerts(guard).count(), 0)

    def test_guard_on_a_shift_covering_now_is_notified(self):
        # The positive control for the predicate above -- otherwise the off-shift
        # test would also pass if duty resolution were broken entirely.
        guard = self._guard("grd_onshift")
        local = timezone.localtime(self.now)
        self._post(guard, self.floor1, standing=False, on_date=local.date(),
                   start=time(0, 0), end=time(23, 59))

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 1)
        self.assertEqual(self._alerts(guard).count(), 1)

    def test_standing_posting_on_affected_floor_is_notified(self):
        guard = self._guard("grd_standing")
        self._post(guard, self.floor1)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 1)
        self.assertEqual(self._alerts(guard).count(), 1)

    def test_inactive_guard_gets_nothing(self):
        # T-07-64: notify(users=[...]) does NOT filter is_active -- it trusts the
        # caller -- so this module must, or a disabled account collects rows.
        guard = self._guard("grd_disabled", is_active=False)
        self._post(guard, self.floor1)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 0)
        self.assertEqual(self._alerts(guard).count(), 0)

    def test_inactive_assignment_gets_nothing(self):
        guard = self._guard("grd_expired")
        a = self._post(guard, self.floor1)
        Assignment.objects.filter(pk=a.pk).update(status="inactive")

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 0)

    def test_online_scoped_assignment_is_not_a_floor_posting(self):
        guard = self._guard("grd_online")
        a = self._post(guard, self.floor1)
        Assignment.objects.filter(pk=a.pk).update(
            scope=AssignmentScope.ONLINE)

        _marked, _flagged, notified = self._run_sweep()

        self.assertEqual(notified, 0)


class SweepReturnCompatibilityTests(GuardAlertBase):
    """The additive-seam promise, locked.

    `sweep_no_shows` returns a scalar int `marked` and `detect_room_conflicts` a
    scalar int `flagged`. Those returns are load-bearing at fourteen call sites --
    ten assertions across scheduling/tests.py and scheduling/tests_merge_sweep.py
    (the latter self-documents as the guard a future sweep edit must not break)
    plus runscheduler._job_sweep and the run_status_sweep command. Passing a
    collector must change NEITHER value.
    """

    def test_sweep_no_shows_returns_the_same_int_with_and_without_collector(self):
        for _ in range(3):
            self._session(self._room(self.floor1))
        # First run flips every candidate; a second run is a no-op (idempotent),
        # so compare each call against a freshly-seeded, identical state instead.
        events = []
        with_collector = sweep_no_shows(now=self.now, collect=events)
        self.assertEqual(len(events), with_collector)

        # Re-seed the same shape and sweep again WITHOUT a collector.
        Session.objects.filter(status=SessionStatus.ABSENT).update(
            status=SessionStatus.SCHEDULED)
        without_collector = sweep_no_shows(now=self.now)

        self.assertEqual(with_collector, without_collector)
        self.assertIsInstance(without_collector, int)

    def test_detect_room_conflicts_returns_the_same_int_with_and_without(self):
        room = self._room(self.floor1)
        for _ in range(2):
            self._session(room, minutes_ago=10, status=SessionStatus.ACTIVE)

        events = []
        with_collector = detect_room_conflicts(now=self.now, collect=events)
        self.assertEqual(with_collector, 1)
        self.assertEqual(len(events), 1)

        # Clear the open flag so the same conflict is "new" again, then re-run
        # with no collector.
        from ops.models import RoomConflictFlag
        RoomConflictFlag.objects.all().delete()
        without_collector = detect_room_conflicts(now=self.now)

        self.assertEqual(with_collector, without_collector)
        self.assertIsInstance(without_collector, int)

    def test_collector_defaults_to_none_and_is_never_required(self):
        # Both functions must remain callable with their original signatures.
        self.assertIsInstance(sweep_no_shows(), int)
        self.assertIsInstance(detect_room_conflicts(), int)

    def test_collected_kinds_are_the_two_documented_strings(self):
        self._session(self._room(self.floor1))
        room = self._room(self.floor2)
        for _ in range(2):
            self._session(room, minutes_ago=10, status=SessionStatus.ACTIVE)

        events = []
        sweep_no_shows(now=self.now, collect=events)
        detect_room_conflicts(now=self.now, collect=events)

        kinds = {k for k, _ in events}
        self.assertEqual(kinds, {KIND_ABSENT, KIND_CONFLICT})
        self.assertTrue(all(isinstance(f, int) for _, f in events))


class CallerWiringTests(GuardAlertBase):
    """The coalescing lives in the CALLERS, so the callers are what must be
    driven here. Without these, `notify_floor_guards` could be perfectly correct
    and simply never invoked in production -- the failure mode that would look
    like "the feature silently does nothing"."""

    def setUp(self):
        super().setUp()
        for _ in range(3):
            self._session(self._room(self.floor1))
        self.guard = self._guard("grd_caller")
        self._post(self.guard, self.floor1)

    def test_scheduler_sweep_job_emits_one_coalesced_alert(self):
        from scheduling.management.commands.runscheduler import _job_sweep

        rows = _job_sweep()

        # Return contract unchanged: marked + flagged, NOT the guard count.
        self.assertEqual(
            rows, Session.objects.filter(status=SessionStatus.ABSENT).count())
        self.assertEqual(self._alerts(self.guard).count(), 1)

    def test_run_status_sweep_command_emits_one_alert_and_reports_it(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("run_status_sweep", stdout=out)

        text = out.getvalue()
        self.assertIn("notified 1 guards", text)
        self.assertTrue(text.isascii())          # Conventions section 4
        self.assertEqual(self._alerts(self.guard).count(), 1)

    def test_scheduler_still_wires_exactly_four_jobs(self):
        # ENV-04: the coalescing went INSIDE the existing sweep job, not beside
        # it as a fifth job.
        from scheduling.management.commands.runscheduler import build_scheduler

        self.assertEqual(len(build_scheduler().get_jobs()), 4)


class SummaryHelperTests(TestCase):
    """`summarize_floor_events` is pure: no ORM, no clock, no rows."""

    def test_single_floor_absences(self):
        title, body = summarize_floor_events([("R F3", 3, 0)])
        self.assertEqual(title, "3 rooms now free on R F3")
        self.assertEqual(body, "R F3: 3 rooms now free.")

    def test_singular_wording(self):
        title, _ = summarize_floor_events([("R F3", 1, 0)])
        self.assertEqual(title, "1 room now free on R F3")

    def test_conflicts_only(self):
        title, _ = summarize_floor_events([("R F3", 0, 2)])
        self.assertEqual(title, "2 room conflicts detected on R F3")

    def test_mixed_kinds_on_one_floor(self):
        title, body = summarize_floor_events([("R F3", 2, 1)])
        self.assertEqual(
            title, "2 rooms now free and 1 room conflict detected on R F3")
        self.assertIn("2 rooms now free", body)
        self.assertIn("1 room conflict", body)

    def test_multiple_floors_summarized_by_count(self):
        title, body = summarize_floor_events(
            [("R F3", 2, 0), ("R F9", 1, 0)])
        self.assertEqual(title, "3 rooms now free on 2 floors")
        self.assertEqual(body.splitlines(),
                         ["R F3: 2 rooms now free.", "R F9: 1 room now free."])

    def test_empty_tally_says_nothing(self):
        self.assertEqual(summarize_floor_events([]), ("", ""))
        self.assertEqual(summarize_floor_events([("R F3", 0, 0)]), ("", ""))

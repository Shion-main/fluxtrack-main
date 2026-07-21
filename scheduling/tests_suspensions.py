"""Phase 9 (A1) — class-suspension & academic-break attendance excusal.

The core promise: a suspension or holiday NEVER marks the campus Absent, the flip
is auditable and reversible, faculty are notified once, and a cancelled class is not
counted as wasted room-hours. These tests are the guard that a future edit to the
sweep or the utilization math must not break.

ASCII-only by convention (Windows cp1252).
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog, Notification
from ops.policy import get_policy
from scheduling.jobs import sweep_no_shows
from scheduling.models import (AcademicBreak, AcademicTerm, ClassSuspension,
                               Schedule, Session, SessionStatus)
from scheduling.reporting import _session_contribution
from scheduling.suspensions import (excused_checker, lift_suspension,
                                    session_is_calendar_excused, suspend_classes)

User = get_user_model()


def _term():
    return AcademicTerm.objects.create(
        name="SUSP Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)


class SuspensionFixture:
    """Two buildings, one room each, one faculty, and a helper to seed a SCHEDULED
    session on a given date whose start is already past grace (so the sweep would
    otherwise mark it Absent)."""

    def __init__(self, term, prefix="susp"):
        self.term = term
        self.dept = Department.objects.create(
            name=f"{prefix} Dept", code=f"{prefix[:3].upper()}")
        self.faculty = User.objects.create(
            username=f"{prefix}_fac", email=f"{prefix}_fac@mcm.edu.ph",
            role=Role.FACULTY, department=self.dept)
        self.bldg_a = Building.objects.create(
            name=f"{prefix} Alpha", code=f"{prefix[:2].upper()}A")
        self.bldg_b = Building.objects.create(
            name=f"{prefix} Beta", code=f"{prefix[:2].upper()}B")
        self.floor_a = Floor.objects.create(building=self.bldg_a, number=1)
        self.floor_b = Floor.objects.create(building=self.bldg_b, number=1)
        self._seq = 0

    def _room(self, floor):
        self._seq += 1
        return Room.objects.create(
            floor=floor, code=f"{self.dept.code}-R{self._seq:03d}", capacity=40,
            qr_token=f"{self.dept.code}-qr-{self._seq}",
            manual_code=f"{self.dept.code[:2]}{self._seq:04d}"[:6])

    def session(self, on_date, *, floor=None, faculty=None,
                status=SessionStatus.SCHEDULED, minutes_before_now=90):
        floor = floor or self.floor_a
        room = self._room(floor)
        start = timezone.now() - timedelta(minutes=minutes_before_now)
        sch = Schedule.objects.create(
            term=self.term, course_code=f"C{self._seq}", section="A",
            faculty=faculty or self.faculty, room=room,
            day_of_week=on_date.weekday(), start_time=time(8, 0),
            end_time=time(9, 30), enrolled_count=30)
        return Session.objects.create(
            schedule=sch, faculty=faculty or self.faculty, room=room, date=on_date,
            scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
            status=status)


class ExcusalCheckerTests(TestCase):
    def setUp(self):
        self.term = _term()
        self.fx = SuspensionFixture(self.term)
        self.d = timezone.localdate()

    def test_academic_break_excuses_campus_wide(self):
        AcademicBreak.objects.create(term=self.term, start_date=self.d,
                                     end_date=self.d, reason="Founding Day")
        excused = excused_checker(self.term)
        self.assertTrue(excused(self.d, self.fx.bldg_a.pk))
        self.assertTrue(excused(self.d, self.fx.bldg_b.pk))

    def test_campus_wide_suspension_excuses_all_buildings(self):
        ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                       end_date=self.d, reason="Typhoon")
        excused = excused_checker(self.term)
        self.assertTrue(excused(self.d, self.fx.bldg_a.pk))
        self.assertTrue(excused(self.d, self.fx.bldg_b.pk))

    def test_building_scoped_suspension_excuses_only_that_building(self):
        ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                       end_date=self.d, building=self.fx.bldg_a,
                                       reason="Flooded ground floor")
        excused = excused_checker(self.term)
        self.assertTrue(excused(self.d, self.fx.bldg_a.pk))
        self.assertFalse(excused(self.d, self.fx.bldg_b.pk))

    def test_lifted_suspension_does_not_excuse(self):
        s = ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                           end_date=self.d, reason="False alarm")
        s.lifted_at = timezone.now()
        s.save(update_fields=["lifted_at"])
        self.assertFalse(excused_checker(self.term)(self.d, self.fx.bldg_a.pk))

    def test_session_helper_reads_building_from_room(self):
        ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                       end_date=self.d, building=self.fx.bldg_a,
                                       reason="X")
        sess_a = self.fx.session(self.d, floor=self.fx.floor_a)
        sess_b = self.fx.session(self.d, floor=self.fx.floor_b)
        excused = excused_checker(self.term)
        self.assertTrue(session_is_calendar_excused(sess_a, excused))
        self.assertFalse(session_is_calendar_excused(sess_b, excused))


class SweepExcusalTests(TestCase):
    """The core A1 fix: the sweep never Absents an excused-date session."""

    def setUp(self):
        self.term = _term()
        self.fx = SuspensionFixture(self.term)
        self.d = timezone.localdate()

    def test_sweep_skips_a_suspended_session(self):
        ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                       end_date=self.d, reason="Signal 3")
        s = self.fx.session(self.d)  # past grace, SCHEDULED
        sweep_no_shows(now=timezone.now())
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)  # NOT Absent

    def test_sweep_skips_a_break_session(self):
        AcademicBreak.objects.create(term=self.term, start_date=self.d,
                                     end_date=self.d, reason="Holiday")
        s = self.fx.session(self.d)
        sweep_no_shows(now=timezone.now())
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)

    def test_building_suspension_absents_only_the_other_building(self):
        ClassSuspension.objects.create(term=self.term, start_date=self.d,
                                       end_date=self.d, building=self.fx.bldg_a,
                                       reason="Alpha only")
        safe = self.fx.session(self.d, floor=self.fx.floor_a)   # excused
        exposed = self.fx.session(self.d, floor=self.fx.floor_b)  # not excused
        sweep_no_shows(now=timezone.now())
        safe.refresh_from_db()
        exposed.refresh_from_db()
        self.assertEqual(safe.status, SessionStatus.SCHEDULED)
        self.assertEqual(exposed.status, SessionStatus.ABSENT)

    def test_control_unexcused_no_show_still_absent(self):
        s = self.fx.session(self.d)  # no break, no suspension
        sweep_no_shows(now=timezone.now())
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)


class SuspendClassesServiceTests(TestCase):
    def setUp(self):
        self.term = _term()
        self.fx = SuspensionFixture(self.term)
        self.d = timezone.localdate()
        self.ifo = User.objects.create(username="susp_ifo", role=Role.IFO_ADMIN)

    def test_flips_scheduled_sessions_and_stamps_reason(self):
        s = self.fx.session(self.d)
        _, n = suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                               reason="Typhoon Pepito", declared_by=self.ifo)
        self.assertEqual(n, 1)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.CANCELLED)
        self.assertEqual(s.cancelled_reason, "Typhoon Pepito")
        self.assertTrue(AuditLog.objects.filter(
            event_type="session.cancelled", target_id=str(s.pk)).exists())

    def test_leaves_active_and_absent_sessions_untouched(self):
        active = self.fx.session(self.d, status=SessionStatus.ACTIVE)
        absent = self.fx.session(self.d, status=SessionStatus.ABSENT)
        suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                        reason="X", declared_by=self.ifo)
        active.refresh_from_db()
        absent.refresh_from_db()
        self.assertEqual(active.status, SessionStatus.ACTIVE)
        self.assertEqual(absent.status, SessionStatus.ABSENT)

    def test_building_scope_only_flips_that_building(self):
        a = self.fx.session(self.d, floor=self.fx.floor_a)
        b = self.fx.session(self.d, floor=self.fx.floor_b)
        suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                        reason="Alpha", building=self.fx.bldg_a, declared_by=self.ifo)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.status, SessionStatus.CANCELLED)
        self.assertEqual(b.status, SessionStatus.SCHEDULED)

    def test_suspend_classes_filters_same_date_sessions_by_explicit_term(self):
        active = self.fx.session(self.d)
        archived_term = AcademicTerm.objects.create(
            name="SUSP Archived",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        other_fx = SuspensionFixture(archived_term, "othsus")
        archived = other_fx.session(self.d)

        suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                        reason="Active only", declared_by=self.ifo)

        active.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(active.status, SessionStatus.CANCELLED)
        self.assertEqual(archived.status, SessionStatus.SCHEDULED)

    def test_notifies_each_faculty_once_coalesced(self):
        other = User.objects.create(username="susp_fac2", role=Role.FACULTY)
        self.fx.session(self.d)                      # faculty 1, session 1
        self.fx.session(self.d)                      # faculty 1, session 2
        self.fx.session(self.d, faculty=other)       # faculty 2
        suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                        reason="Storm", declared_by=self.ifo)
        notes = Notification.objects.filter(type="class_suspended")
        # Two faculty affected -> exactly two notifications (faculty 1 gets ONE,
        # coalesced, despite two cancelled sessions).
        self.assertEqual(notes.count(), 2)
        self.assertEqual(notes.filter(user=self.fx.faculty).count(), 1)

    def test_lift_reinstates_only_its_own_cancellations(self):
        s = self.fx.session(self.d)
        susp, _ = suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                                  reason="Lifted later", declared_by=self.ifo)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.CANCELLED)
        n = lift_suspension(susp, lifted_by=self.ifo)
        self.assertEqual(n, 1)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)
        self.assertEqual(s.cancelled_reason, "")
        susp.refresh_from_db()
        self.assertIsNotNone(susp.lifted_at)

    def test_lift_suspension_filters_same_date_sessions_by_explicit_term(self):
        s = self.fx.session(self.d)
        archived_term = AcademicTerm.objects.create(
            name="SUSP Lift Archived",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        other_fx = SuspensionFixture(archived_term, "olifts")
        archived = other_fx.session(self.d)
        archived.status = SessionStatus.CANCELLED
        archived.cancelled_reason = "Lifted later"
        archived.save(update_fields=["status", "cancelled_reason"])
        susp, _ = suspend_classes(term=self.term, start_date=self.d, end_date=self.d,
                                  reason="Lifted later", declared_by=self.ifo)

        lift_suspension(susp, lifted_by=self.ifo)

        s.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.SCHEDULED)
        self.assertEqual(archived.status, SessionStatus.CANCELLED)


class CancelledUtilizationTests(TestCase):
    """A CANCELLED session must contribute NO booked room-hours (no fake waste)."""

    def test_cancelled_contributes_zero_booked(self):
        start = timezone.now()
        end = start + timedelta(minutes=90)
        booked, used, running = _session_contribution(
            SessionStatus.CANCELLED, start, end, None, None)
        self.assertEqual((booked, used, running), (0, 0, False))

    def test_absent_still_contributes_booked_as_waste_control(self):
        # The control: ABSENT is still booked-with-zero-used (that zero IS the waste
        # signal), proving the CANCELLED zero is specific, not a blanket change.
        start = timezone.now()
        end = start + timedelta(minutes=90)
        booked, used, running = _session_contribution(
            SessionStatus.ABSENT, start, end, None, None)
        self.assertEqual(booked, 90 * 60)
        self.assertEqual((used, running), (0, False))

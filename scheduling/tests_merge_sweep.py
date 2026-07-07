"""Sweep-confirmation + online-coverage Nyquist tests (Phase 04.2 Plan 04).

This suite proves the SUBTRACTIVE half of the co-scheduled-merge design WITHOUT
touching scheduling/jobs.py: the UNCHANGED JOB-02 sweep already does the right
thing for merged groups, because the merge present-path makes siblings ACTIVE
(and the sweep only ever touches SCHEDULED), while a no-event merged group shares
one scheduled_start and therefore crosses grace together (D-04/D-08).

  - ``MergeSweepConfirmTests`` (Task 1) locks ROADMAP criteria #2 and #4:
    a present merged group is skipped by the sweep, a no-event merged group is
    absented TOGETHER in one run, and a genuinely-missed non-merged control is
    still absented. The assertion IS that the sweep is unchanged.
  - ``MergeCoverageCommandTests`` (Task 2) drives the read-only
    ``audit_merge_coverage`` command, empirically validating D-01 online coverage
    (criterion #3) against the fixture's shared-course online pair.

ASCII-only by convention (Windows cp1252).
"""
from datetime import time, timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from campus.models import Floor, Room
from ops.models import AuditLog
from scheduling.jobs import sweep_no_shows
from scheduling.merge import propagate_merged_present
from scheduling.models import (
    Modality,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.test_support import IN_WINDOW_DATE, _aware, make_merge_fixture


class MergeSweepConfirmTests(TestCase):
    """The UNCHANGED JOB-02 sweep already handles merged groups correctly.

    No production change accompanies this suite: it asserts the invariant that a
    future edit to sweep_no_shows must not break (T-04.2-03). ``now`` is set 20
    minutes past the merged group's shared 15:45 start, well past the 15-minute
    grace, so every still-SCHEDULED session in the fixture is a no-show.
    """

    def setUp(self):
        self.fx = make_merge_fixture(prefix="msw")
        # 20 min past the shared F2F start (15:45) -> past the 15-min grace.
        self.now = self.fx.anchor.scheduled_start + timedelta(minutes=20)

    def test_present_merged_group_skipped_by_sweep(self):
        # Criterion #2: after a merge check-in flips the group ACTIVE, the sweep
        # (SCHEDULED-only) marks 0 of that group Absent -- both siblings survive.
        Session.objects.filter(pk=self.fx.anchor.pk).update(
            status=SessionStatus.ACTIVE, actual_start=self.now)
        filled = propagate_merged_present(self.fx.anchor, self.now, actor=None)
        self.assertEqual(set(filled), {self.fx.sibling.pk})

        marked = sweep_no_shows(now=self.now)

        self.fx.anchor.refresh_from_db()
        self.fx.sibling.refresh_from_db()
        self.assertEqual(self.fx.anchor.status, SessionStatus.ACTIVE)
        self.assertEqual(self.fx.sibling.status, SessionStatus.ACTIVE)
        # 0 of the merged group flipped: neither sibling is ABSENT.
        absent_ids = set(Session.objects.filter(status=SessionStatus.ABSENT)
                         .values_list("pk", flat=True))
        self.assertNotIn(self.fx.anchor.pk, absent_ids)
        self.assertNotIn(self.fx.sibling.pk, absent_ids)
        # Nothing was ABSENT before the sweep, so the returned count must equal
        # the number of rows actually flipped this run.
        self.assertEqual(marked, len(absent_ids))

    def test_no_event_merged_group_absented_together(self):
        # D-08: a merged group left ALL SCHEDULED shares one scheduled_start, so
        # the unchanged sweep crosses grace for BOTH siblings in a single run.
        marked = sweep_no_shows(now=self.now)

        self.fx.anchor.refresh_from_db()
        self.fx.sibling.refresh_from_db()
        self.assertEqual(self.fx.anchor.status, SessionStatus.ABSENT)
        self.assertEqual(self.fx.sibling.status, SessionStatus.ABSENT)
        # Returned count matches the number actually flipped (none ABSENT before).
        absent_count = Session.objects.filter(status=SessionStatus.ABSENT).count()
        self.assertEqual(marked, absent_count)

    def test_non_merged_control_still_absent(self):
        # Criterion #4: a genuinely-missed non-merged SCHEDULED no-show (same
        # faculty + start but a DIFFERENT room AND course, so NOT a sibling) is
        # still marked Absent by the same unchanged sweep run.
        sweep_no_shows(now=self.now)

        self.fx.control.refresh_from_db()
        self.assertEqual(self.fx.control.status, SessionStatus.ABSENT)


class MergeCoverageCommandTests(TestCase):
    """audit_merge_coverage: empirical, READ-ONLY D-01 online coverage (criterion #3)."""

    def setUp(self):
        self.fx = make_merge_fixture(prefix="cov")
        self.floor = Floor.objects.filter(building=self.fx.building).first()
        self._room_n = 0

    def _online_pair(self, start_t, course_a, course_b, same_room):
        """Seed two effective-online sessions sharing faculty + exact start.

        ``same_room`` toggles whether both sessions hold one V-room (D-01 room
        arm) or two distinct rooms; with distinct rooms AND distinct courses the
        pair is a distinct-both group D-01 must report MISSED.
        """
        start = _aware(IN_WINDOW_DATE, start_t)
        end = _aware(IN_WINDOW_DATE, time(start_t.hour + 1, start_t.minute))

        def _room():
            self._room_n += 1
            return Room.objects.create(
                floor=self.floor, code=f"cov-V{self._room_n}", capacity=40,
                qr_token=f"cov-qr-V{self._room_n}",
                manual_code=f"CV{self._room_n:03d}"[:6],
            )

        room_a = _room()
        room_b = room_a if same_room else _room()
        out = []
        for course, room, section in ((course_a, room_a, "V01"),
                                      (course_b, room_b, "V02")):
            sched = Schedule.objects.create(
                term=self.fx.term, course_code=course, section=section,
                faculty=self.fx.faculty, room=room, day_of_week=0,
                start_time=start_t, end_time=time(start_t.hour + 1, start_t.minute),
                modality=Modality.ONLINE,
            )
            out.append(Session.objects.create(
                schedule=sched, faculty=self.fx.faculty, room=room,
                date=IN_WINDOW_DATE, scheduled_start=start, scheduled_end=end,
                status=SessionStatus.SCHEDULED, declared_modality=Modality.ONLINE,
            ))
        return out

    def test_online_pair_reported_caught(self):
        # The fixture's ONL200 online pair shares course_code -> D-01 CAUGHT.
        out = StringIO()
        call_command("audit_merge_coverage", stdout=out)
        text = out.getvalue()
        self.assertIn("fully CAUGHT by D-01: 1", text)
        self.assertIn("distinct-both): 0", text)
        self.assertIn("criterion #3 holds", text)

    def test_command_is_read_only(self):
        # T-04.2-06: the audit mutates no Session row and creates no AuditLog.
        before = dict(Session.objects.values_list("pk", "status"))
        audit_before = AuditLog.objects.count()

        call_command("audit_merge_coverage", stdout=StringIO())

        after = dict(Session.objects.values_list("pk", "status"))
        self.assertEqual(before, after)
        self.assertEqual(AuditLog.objects.count(), audit_before)

    def test_distinct_both_online_pair_is_missed(self):
        # A synthesized online pair sharing NEITHER room NOR course at a fresh
        # start is a real D-01 gap: the command must print a MISSED line and exit
        # non-zero (CommandError), proving it would surface a criterion #3 breach.
        self._online_pair(time(13, 0), "GAPA100", "GAPB200", same_room=False)
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("audit_merge_coverage", stdout=out)
        self.assertIn("MISSED faculty=", out.getvalue())

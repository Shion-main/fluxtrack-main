"""Tests for the shared merge core (Phase 04.2 Plan 01).

Three suites mirror the phase's Nyquist Wave-0 scaffolding:
  - MergeEnumTests (SimpleTestCase): the CheckinMethod.MERGED choice exists.
  - MergeDetectorTests (SimpleTestCase): the pure D-01 detector truth table.
  - MergePropagationTests (TestCase): the atomic ORM propagation helpers on LocalDB.

ASCII-only by convention (Windows cp1252).
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from scheduling.models import CheckinMethod, SessionStatus

# NOTE: scheduling.merge (Task 2/3) and make_merge_fixture (Task 3) are imported
# lazily inside the suites that need them so MergeEnumTests (Task 1) runs before
# those artifacts exist.

MANILA = ZoneInfo("Asia/Manila")


class MergeEnumTests(SimpleTestCase):
    """D-09: CheckinMethod.MERGED is the enum choice the propagation helpers stamp."""

    def test_merged_value_is_merged(self):
        self.assertEqual(CheckinMethod.MERGED, "merged")

    def test_merged_in_values(self):
        self.assertIn("merged", CheckinMethod.values)

    def test_merged_fits_max_length(self):
        # "merged" is 6 chars, well under Session.checkin_method max_length=15.
        self.assertLessEqual(len("merged"), 15)


class MergeDetectorTests(SimpleTestCase):
    """Pure D-01 detector truth table (no DB). Mirrors CouplingIntegrityTests style."""

    # A concrete aware anchor start (Manila) used across rows.
    ANCHOR_START = datetime(2026, 7, 6, 15, 45, tzinfo=MANILA)

    @staticmethod
    def _detector():
        from scheduling.merge import merged_sibling_ids
        return merged_sibling_ids

    def _sess(self, **kw):
        defaults = dict(
            id=1, faculty_id=100, scheduled_start=self.ANCHOR_START,
            room_id=10, course_code="MMA116", is_online=False,
        )
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def test_truth_table(self):
        anchor = self._sess(id=1, room_id=10, course_code="MMA116")
        rows = [
            # (label, candidate kwargs, should_merge)
            ("same-fac same-start diff-room SAME-course -> MERGE (course arm)",
             dict(id=2, room_id=11, course_code="MMA116"), True),
            ("same-fac same-start SAME-room diff-course -> MERGE (room arm)",
             dict(id=3, room_id=10, course_code="ZZZ999"), True),
            ("same-fac same-start diff-room diff-course -> NOT merge",
             dict(id=4, room_id=12, course_code="ZZZ999"), False),
            ("different faculty else same -> NOT merge",
             dict(id=5, faculty_id=999, room_id=10, course_code="MMA116"), False),
            ("start off by 1 minute else same -> NOT merge (exactness)",
             dict(id=6, room_id=10, course_code="MMA116",
                  scheduled_start=self.ANCHOR_START + timedelta(minutes=1)), False),
            ("self (id == anchor.id) -> never merges",
             dict(id=1, room_id=10, course_code="MMA116"), False),
        ]
        for label, kw, should_merge in rows:
            with self.subTest(row=label):
                cand = self._sess(**kw)
                result = self._detector()(anchor, [cand])
                if should_merge:
                    self.assertEqual(result, {cand.id})
                else:
                    self.assertEqual(result, set())

    def test_online_arm(self):
        # D-01 refinement #2: two effective-ONLINE sessions with the same faculty
        # + exact start MERGE even when they share NEITHER room NOR course (online
        # has no room; one instructor = one live presence). A mixed online/F2F
        # pair is NOT "two online sessions" -> falls back to the room/course arm.
        online_anchor = self._sess(id=1, room_id=10, course_code="ONL200",
                                    is_online=True)
        rows = [
            ("both online, diff-room diff-course -> MERGE (online arm, the fix)",
             dict(id=2, room_id=99, course_code="ZZZ999", is_online=True), True),
            ("both online, same course -> MERGE (still)",
             dict(id=3, room_id=99, course_code="ONL200", is_online=True), True),
            ("both online, diff faculty -> NOT merge (faculty scope holds)",
             dict(id=4, faculty_id=777, room_id=99, course_code="ZZZ999",
                  is_online=True), False),
            ("both online, start off by 1 min -> NOT merge (exactness holds)",
             dict(id=5, room_id=99, course_code="ZZZ999", is_online=True,
                  scheduled_start=self.ANCHOR_START + timedelta(minutes=1)), False),
            ("mixed: anchor online, candidate F2F, diff-room diff-course -> NOT merge",
             dict(id=6, room_id=99, course_code="ZZZ999", is_online=False), False),
        ]
        for label, kw, should_merge in rows:
            with self.subTest(row=label):
                cand = self._sess(**kw)
                result = self._detector()(online_anchor, [cand])
                self.assertEqual(result, {cand.id} if should_merge else set())

    def test_mixed_anchor_f2f_candidate_online_uses_room_course_arm(self):
        # Anchor F2F + candidate online (not "two online sessions"): the online
        # arm must NOT fire; a distinct-both pair stays un-merged, a shared-course
        # pair still merges via the F2F/course arm.
        f2f_anchor = self._sess(id=1, room_id=10, course_code="MMA116",
                                is_online=False)
        distinct = self._sess(id=2, room_id=99, course_code="ZZZ999",
                              is_online=True)
        shared_course = self._sess(id=3, room_id=99, course_code="MMA116",
                                   is_online=True)
        self.assertEqual(self._detector()(f2f_anchor, [distinct]), set())
        self.assertEqual(self._detector()(f2f_anchor, [shared_course]), {3})

    def test_manila_exact_instant_boundary(self):
        # Two rows expressing the SAME instant in different representations
        # (Manila-aware vs the identical UTC-aware instant) are equal instants
        # and merge; a 1-minute offset does not.
        anchor = self._sess(id=1, scheduled_start=self.ANCHOR_START)
        same_instant_utc = self.ANCHOR_START.astimezone(dt_timezone.utc)
        merges = self._sess(id=2, room_id=99, course_code="MMA116",
                            scheduled_start=same_instant_utc)
        off_by_min = self._sess(id=3, room_id=99, course_code="MMA116",
                               scheduled_start=same_instant_utc + timedelta(minutes=1))
        result = self._detector()(anchor, [merges, off_by_min])
        self.assertEqual(result, {merges.id})

    def test_multiple_candidates_returns_all_qualifying(self):
        anchor = self._sess(id=1, room_id=10, course_code="MMA116")
        cands = [
            self._sess(id=2, room_id=11, course_code="MMA116"),   # course arm -> in
            self._sess(id=3, room_id=10, course_code="ZZZ"),      # room arm -> in
            self._sess(id=4, room_id=12, course_code="ZZZ"),      # neither -> out
            self._sess(id=5, faculty_id=888, room_id=10, course_code="MMA116"),  # diff fac -> out
        ]
        result = self._detector()(anchor, cands)
        self.assertEqual(result, {2, 3})


class MergePropagationTests(TestCase):
    """Atomic SCHEDULED->ACTIVE/ABSENT sibling fill on LocalDB (D-04/D-05/D-09)."""

    def setUp(self):
        from scheduling.merge import (
            propagate_merged_absent,
            propagate_merged_present,
        )
        from scheduling.test_support import make_merge_fixture
        self._present = propagate_merged_present
        self._absent = propagate_merged_absent
        self.fx = make_merge_fixture()
        self.actor = self.fx.faculty
        self.now = self.fx.anchor.scheduled_start

    def _audit(self, event_type):
        from ops.models import AuditLog
        return AuditLog.objects.filter(event_type=event_type)

    def _activate_anchor(self):
        # The anchor is check-in activated by the seam BEFORE propagation runs.
        self.fx.anchor.status = SessionStatus.ACTIVE
        self.fx.anchor.actual_start = self.now
        self.fx.anchor.checkin_method = CheckinMethod.QR_SCAN
        self.fx.anchor.save(update_fields=["status", "actual_start", "checkin_method"])

    def test_present_fills_scheduled_siblings(self):
        self._activate_anchor()
        filled = self._present(self.fx.anchor, self.now, self.actor)
        self.assertIn(self.fx.sibling.pk, filled)
        self.fx.sibling.refresh_from_db()
        self.assertEqual(self.fx.sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(self.fx.sibling.actual_start, self.now)
        self.assertEqual(self.fx.sibling.checkin_method, CheckinMethod.MERGED)

    def test_anchor_not_restamped_merged(self):
        self._activate_anchor()
        self._present(self.fx.anchor, self.now, self.actor)
        self.fx.anchor.refresh_from_db()
        self.assertEqual(self.fx.anchor.checkin_method, CheckinMethod.QR_SCAN)
        self.assertNotEqual(self.fx.anchor.checkin_method, CheckinMethod.MERGED)

    def test_present_audit_shape(self):
        self._activate_anchor()
        filled = self._present(self.fx.anchor, self.now, self.actor)
        for pk in filled:
            logs = self._audit("session.merged_present").filter(target_id=str(pk))
            self.assertEqual(logs.count(), 1)
            self.assertEqual(logs.first().payload, {"merged_from": self.fx.anchor.pk})
        # No CheckerValidation rows are created for siblings (D-09).
        from verification.models import CheckerValidation
        self.assertEqual(
            CheckerValidation.objects.filter(session_id__in=filled).count(), 0)

    def test_status_guard_leaves_non_scheduled_untouched(self):
        self._activate_anchor()
        # Mark the sibling ABSENT first: the present fill must NOT resurrect it.
        self.fx.sibling.status = SessionStatus.ABSENT
        self.fx.sibling.save(update_fields=["status"])
        filled = self._present(self.fx.anchor, self.now, self.actor)
        self.assertNotIn(self.fx.sibling.pk, filled)
        self.fx.sibling.refresh_from_db()
        self.assertEqual(self.fx.sibling.status, SessionStatus.ABSENT)

    def test_control_never_touched(self):
        self._activate_anchor()
        self._present(self.fx.anchor, self.now, self.actor)
        self.fx.control.refresh_from_db()
        self.assertEqual(self.fx.control.status, SessionStatus.SCHEDULED)

    def test_idempotent_and_status_guard(self):
        self._activate_anchor()
        first = self._present(self.fx.anchor, self.now, self.actor)
        self.assertTrue(first)
        before = self._audit("session.merged_present").count()
        second = self._present(self.fx.anchor, self.now, self.actor)
        self.assertEqual(second, [])
        after = self._audit("session.merged_present").count()
        self.assertEqual(before, after)

    def test_batch_no_hy010(self):
        # Mirror SweepTests.test_batch_of_no_shows_all_marked_absent: N=3 SCHEDULED
        # siblings fill on LocalDB with no HY010 cursor error; all reach ACTIVE.
        self._activate_anchor()
        extra = self.fx.make_extra_siblings(2)  # sibling + 2 = 3 total scheduled
        filled = self._present(self.fx.anchor, self.now, self.actor)
        self.assertEqual(len(filled), 3)
        for s in [self.fx.sibling, *extra]:
            s.refresh_from_db()
            self.assertEqual(s.status, SessionStatus.ACTIVE)

    def test_absent_fills_scheduled_siblings(self):
        # Online D-07 path: SCHEDULED merged siblings -> ABSENT with audit.
        absented = self._absent(self.fx.online_anchor, self.actor)
        self.assertIn(self.fx.online_sibling.pk, absented)
        self.fx.online_sibling.refresh_from_db()
        self.assertEqual(self.fx.online_sibling.status, SessionStatus.ABSENT)
        logs = self._audit("session.merged_absent").filter(
            target_id=str(self.fx.online_sibling.pk))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().payload,
                         {"merged_from": self.fx.online_anchor.pk})

    def test_absent_status_guard(self):
        # An ACTIVE online sibling is left untouched by the absent fill (D-05).
        self.fx.online_sibling.status = SessionStatus.ACTIVE
        self.fx.online_sibling.save(update_fields=["status"])
        absented = self._absent(self.fx.online_anchor, self.actor)
        self.assertNotIn(self.fx.online_sibling.pk, absented)
        self.fx.online_sibling.refresh_from_db()
        self.assertEqual(self.fx.online_sibling.status, SessionStatus.ACTIVE)

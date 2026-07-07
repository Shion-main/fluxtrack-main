"""Tests for the Phase 04.1 Wave-2 supporting commands:

* ``load_room_master`` — materializes the 114 named master rooms with real
  capacities (D3), keying the tab-skip rule SOLELY on ``classify_room`` so only
  the two summary tabs are excluded.
* ``reset_term`` — a reversible, ``--yes``-guarded clean-load precondition (D10).

The DB-backed tests use MSSQL LocalDB (the project's only DB). The
``LoadRoomMasterTests`` are ``skipUnless`` the gitignored room-master ``.xlsx``
is present, so CI without ``data/raw`` skips them cleanly while the dev box runs
them for real. The ``IsRoomTabTests`` are DB-free and always run.
"""
import os
from io import StringIO
from unittest import skipUnless

from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from scheduling.models import (AcademicTerm, ModalityShiftItem,
                               ModalityShiftRequest, Schedule, Session)

User = get_user_model()

ROOM_MASTER_XLSX = "data/raw/2T-25-26-All Physical-RoomScheduleStatisticsTemplate1.xlsx"


# ---------------------------------------------------------------------------
# DB-free: the tab-skip predicate keys SOLELY on classify_room(tab_name).
# ---------------------------------------------------------------------------
class IsRoomTabTests(SimpleTestCase):
    """Every real room-code prefix parses as a room; only the two wordy summary
    tabs are excluded. Crucially, blank name/capacity is NOT a skip signal and
    Unassigned P/U codes + digit-only typos are still real rooms (D4/D9)."""

    def test_every_real_room_prefix_is_a_room_tab(self):
        from scheduling.management.commands.load_room_master import is_room_tab
        for code in ("A101", "A401-A", "R415", "R616", "V301", "GYM1", "GYM2",
                     "U101", "P101", "404", "516"):
            self.assertTrue(is_room_tab(code), f"{code} should parse as a room")

    def test_summary_tabs_are_not_room_tabs(self):
        from scheduling.management.commands.load_room_master import is_room_tab
        self.assertFalse(is_room_tab("Lecture Summary"))
        self.assertFalse(is_room_tab("Lab Summary"))


# ---------------------------------------------------------------------------
# DB-backed: load_room_master against the REAL room-master .xlsx.
# ---------------------------------------------------------------------------
@skipUnless(os.path.exists(ROOM_MASTER_XLSX),
            "room-master .xlsx not present (gitignored data/raw)")
class LoadRoomMasterTests(TransactionTestCase):
    """Run the real command against the real 116-tab master workbook."""

    def _load(self, **kwargs):
        out = StringIO()
        call_command("load_room_master", stdout=out, **kwargs)
        return out.getvalue()

    def test_loads_114_named_rooms_and_five_buildings(self):
        self._load()
        # Exactly the 114 room tabs become rooms; the 2 summary tabs do not.
        self.assertEqual(Room.objects.count(), 114)
        self.assertFalse(Room.objects.filter(code="Lecture Summary").exists())
        self.assertFalse(Room.objects.filter(code="Lab Summary").exists())
        # The five buildings exist via the D4 prefix map.
        for code in ("ACAD", "ADMIN", "GYM", "ONLINE", "UNASSIGNED"):
            self.assertTrue(Building.objects.filter(code=code).exists(),
                            f"building {code} missing")

    def test_spot_room_has_real_name_and_capacity(self):
        self._load()
        a101 = Room.objects.get(code="A101")
        self.assertEqual(a101.name, "Global Classroom")
        self.assertEqual(a101.capacity, 40)
        # A101 lands in the Admin building (A prefix, floor 1).
        self.assertEqual(a101.floor.building.code, "ADMIN")
        self.assertEqual(a101.floor.number, 1)

    def test_room_with_blank_name_or_capacity_still_imported(self):
        self._load()
        # A401-A has capacity 40 but a blank name in the master — still a room.
        blank_named = Room.objects.get(code="A401-A")
        self.assertEqual(blank_named.name, "")
        self.assertEqual(blank_named.capacity, 40)

    def test_reload_is_idempotent_and_preserves_tokens(self):
        self._load()
        a101 = Room.objects.get(code="A101")
        original_token = a101.qr_token
        original_manual = a101.manual_code
        count_before = Room.objects.count()

        self._load()  # re-run
        self.assertEqual(Room.objects.count(), count_before)  # no duplicates
        a101.refresh_from_db()
        self.assertEqual(a101.qr_token, original_token)       # tokens untouched
        self.assertEqual(a101.manual_code, original_manual)
        self.assertEqual(a101.name, "Global Classroom")       # metadata stable

    def test_dry_run_writes_nothing(self):
        before = Room.objects.count()
        out = self._load(dry_run=True)
        self.assertEqual(Room.objects.count(), before)  # unchanged (0)
        self.assertIn("DRY RUN", out)
        self.assertIn("Per building", out)

# ---------------------------------------------------------------------------
# DB-backed: reset_term reversible clean-load guard (D10).
# ---------------------------------------------------------------------------
class ResetTermTests(TransactionTestCase):
    """reset_term clears a term's Schedule/Session behind a --yes guard while
    preserving reusable User/Room/Building rows."""

    def _make_term_with_schedule(self, term_name="Reset Test Term"):
        term = AcademicTerm.objects.create(
            name=term_name,
            start_date=timezone.now().date() - timedelta(days=7),
            end_date=timezone.now().date() + timedelta(days=90),
            is_active=True)
        faculty = User.objects.create(username="reset-fac", role=Role.FACULTY)
        bldg = Building.objects.create(code="ACAD", name="Academic Building")
        floor = Floor.objects.create(building=bldg, number=4)
        room = Room.objects.create(
            code="R415", floor=floor, name="Test Room", capacity=30,
            qr_token="tok-reset-R415", manual_code="100001")
        sched = Schedule.objects.create(
            term=term, course_code="CS100", section="A", faculty=faculty,
            room=room, day_of_week=0, start_time=time(9, 0), end_time=time(10, 30))
        start = timezone.make_aware(
            timezone.datetime.combine(timezone.now().date(), time(9, 0)))
        Session.objects.create(
            schedule=sched, faculty=faculty, room=room,
            date=timezone.now().date(), scheduled_start=start,
            scheduled_end=start + timedelta(minutes=90))
        return term, faculty, room, sched

    def _run(self, **kwargs):
        out = StringIO()
        call_command("reset_term", stdout=out, **kwargs)
        return out.getvalue()

    def test_yes_clears_schedule_and_session_keeps_users_rooms(self):
        term, faculty, room, sched = self._make_term_with_schedule()
        users_before = User.objects.count()
        rooms_before = Room.objects.count()
        buildings_before = Building.objects.count()

        self._run(term_name=term.name, yes=True)

        self.assertEqual(Schedule.objects.filter(term=term).count(), 0)
        self.assertEqual(Session.objects.filter(schedule__term=term).count(), 0)
        # Reusable rows are untouched.
        self.assertEqual(User.objects.count(), users_before)
        self.assertEqual(Room.objects.count(), rooms_before)
        self.assertEqual(Building.objects.count(), buildings_before)

    def test_without_yes_deletes_nothing_and_previews(self):
        term, _f, _r, _s = self._make_term_with_schedule()
        out = self._run(term_name=term.name)  # no yes
        # Nothing deleted.
        self.assertEqual(Schedule.objects.filter(term=term).count(), 1)
        self.assertEqual(Session.objects.filter(schedule__term=term).count(), 1)
        # Preview reports the counts and the guard hint.
        self.assertIn("1", out)
        self.assertIn("--yes", out)

    def test_empty_term_reports_zero_and_exits(self):
        term = AcademicTerm.objects.create(
            name="Empty Term",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=1))
        out = self._run(term_name=term.name, yes=True)
        self.assertEqual(Schedule.objects.filter(term=term).count(), 0)
        self.assertIn("0", out)

    def test_missing_term_does_not_raise(self):
        out = self._run(term_name="No Such Term", yes=True)
        self.assertIn("No Such Term", out)

    def test_schedule_protected_by_modality_item_is_reported_not_crashed(self):
        term, faculty, room, sched = self._make_term_with_schedule()
        req = ModalityShiftRequest.objects.create(
            requester=faculty, target_modality="online",
            window_start=timezone.now().date(),
            window_end=timezone.now().date())
        ModalityShiftItem.objects.create(request=req, schedule=sched)

        # Must not raise ProtectedError; the blocked schedule is reported and
        # skipped, so its row survives.
        out = self._run(term_name=term.name, yes=True)
        self.assertTrue(Schedule.objects.filter(pk=sched.pk).exists())
        self.assertIn(str(sched.pk), out)

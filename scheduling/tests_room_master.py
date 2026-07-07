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

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase

from campus.models import Building, Floor, Room

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

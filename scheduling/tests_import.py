"""DB-free unit tests for the stdlib xlsx reader and the pure import helpers
(Phase 04.1). These are all SimpleTestCase — no database, no Django models
touched except the Modality/DayOfWeek enums the helpers return.

Two flavours of test live here:
  * pure parser/helper tests that run everywhere (no data dependency), and
  * full-file tests that read the REAL gitignored registrar exports under
    data/raw/ and assert the verified counts. Those are guarded with
    skipUnless(os.path.exists(...)) so CI (where data/raw is absent) skips
    them cleanly while the local dev box runs them for real.
"""
import os
from unittest import skipUnless

from django.test import SimpleTestCase

# Real, gitignored source files (present only on the dev box).
OFFERINGS_XLSX = "data/raw/2T-25-26-Course Offerring (1).xlsx"
ROOM_MASTER_XLSX = "data/raw/2T-25-26-All Physical-RoomScheduleStatisticsTemplate1.xlsx"


# ---------------------------------------------------------------------------
# Task 1 — stdlib .xlsx reader (scheduling/xlsx.py)
# ---------------------------------------------------------------------------
@skipUnless(os.path.exists(OFFERINGS_XLSX) and os.path.exists(ROOM_MASTER_XLSX),
            "registrar .xlsx files not present (gitignored data/raw)")
class XlsxReaderTests(SimpleTestCase):
    """The reader must open the real Open-XML archives with only the stdlib
    (zipfile + xml.etree), resolve shared strings, and reconstruct sparse
    column positions from the cell 'r' reference."""

    def test_sheet_names_room_master_has_116_tabs(self):
        from scheduling import xlsx
        names = xlsx.sheet_names(ROOM_MASTER_XLSX)
        self.assertEqual(len(names), 116)
        # 2 summary tabs + 114 room tabs, in document order.
        self.assertEqual(names[0], "Lecture Summary")
        self.assertEqual(names[1], "Lab Summary")
        self.assertIn("R616", names)

    def test_offerings_grid_is_header_plus_1211_rows(self):
        from scheduling import xlsx
        grid = xlsx.read_grid(OFFERINGS_XLSX, "Sheet1")
        self.assertEqual(len(grid), 1212)  # header + 1211 data rows
        header = grid[0]
        for expected in ("Code", "Sec", "Mode", "Enrolled", "Instructor",
                         "Email", "Schedule"):
            self.assertIn(expected, header)

    def test_shared_strings_resolve_and_empty_cells_blank(self):
        from scheduling import xlsx
        grid = xlsx.read_grid(OFFERINGS_XLSX, "Sheet1")
        header = grid[0]
        # First header cell is a shared string, resolved to its text (not "0").
        self.assertEqual(header[0], "Code")
        # Every cell is a string; sparse/missing cells are "" not None.
        for cell in grid[1]:
            self.assertIsInstance(cell, str)
        self.assertNotIn(None, grid[1])

    def test_room_tab_exposes_name_and_capacity_by_index(self):
        from scheduling import xlsx
        grid = xlsx.read_grid(ROOM_MASTER_XLSX, "R616")
        # C4 (name) and O4 (capacity) -> 0-based row 3, cols 2 and 14.
        self.assertTrue(len(grid) > 3)
        self.assertTrue(len(grid[3]) > 14)
        self.assertNotEqual(grid[3][2], "")   # a room name
        self.assertNotEqual(grid[3][14], "")  # a capacity

    def test_no_sheet_arg_returns_first_sheet(self):
        from scheduling import xlsx
        default = xlsx.read_grid(OFFERINGS_XLSX)
        first = xlsx.read_grid(OFFERINGS_XLSX, "Sheet1")
        self.assertEqual(default, first)

    def test_reader_uses_only_stdlib(self):
        import re as _re
        import scheduling.xlsx as x
        src = open(x.__file__, encoding="utf-8").read()
        # Scan for real import statements, not prose mentions in docstrings.
        for banned in ("openpyxl", "pandas", "xlrd", "xlsxwriter"):
            self.assertIsNone(
                _re.search(r"^\s*(import|from)\s+%s\b" % banned, src, _re.M),
                "%s must not be imported by the stdlib reader" % banned,
            )


# ---------------------------------------------------------------------------
# Task 2 — pure parse/classify/normalize/modality helpers (scheduling/importing.py)
# ---------------------------------------------------------------------------
from datetime import time  # noqa: E402


class ImportingHelperTests(SimpleTestCase):
    """Pure SimpleTestCase — no DB, no data/raw dependency. Every case in the
    plan's behavior block for the classify/parse/normalize/modality helpers."""

    # --- prefix -> building map (D4) ------------------------------------
    def test_prefix_building_map(self):
        from scheduling.importing import PREFIX_BUILDING
        self.assertEqual(PREFIX_BUILDING["R"], ("ACAD", "Academic Building"))
        self.assertEqual(PREFIX_BUILDING["A"], ("ADMIN", "Admin Building"))
        self.assertEqual(PREFIX_BUILDING["GYM"], ("GYM", "Gym"))
        self.assertEqual(PREFIX_BUILDING["V"], ("ONLINE", "Online (virtual)"))

    # --- classify_room (D4) --------------------------------------------
    def test_classify_academic_room(self):
        from scheduling.importing import classify_room
        info = classify_room("R415")
        self.assertEqual(info.building_code, "ACAD")
        self.assertEqual(info.floor, 4)
        self.assertTrue(info.scannable)
        self.assertFalse(info.is_virtual)

    def test_classify_virtual_room(self):
        from scheduling.importing import classify_room
        info = classify_room("V301")
        self.assertEqual(info.building_code, "ONLINE")
        self.assertTrue(info.is_virtual)
        self.assertFalse(info.scannable)

    def test_classify_gym_does_not_raise(self):
        from scheduling.importing import classify_room
        info = classify_room("GYM2")  # old parse_room dropped this
        self.assertEqual(info.building_code, "GYM")
        self.assertTrue(info.scannable)

    def test_classify_hyphen_suffix_room(self):
        from scheduling.importing import classify_room
        info = classify_room("A410-A")
        self.assertEqual(info.building_code, "ADMIN")
        self.assertEqual(info.floor, 4)

    def test_classify_digit_only_typos(self):
        from scheduling.importing import classify_room
        for code in ("404", "516"):
            info = classify_room(code)
            self.assertEqual(info.building_code, "UNASSIGNED")
            self.assertTrue(info.is_typo)
            self.assertTrue(info.is_unassigned)

    def test_classify_u_prefix_unassigned_not_typo(self):
        from scheduling.importing import classify_room
        info = classify_room("U102")
        self.assertEqual(info.building_code, "UNASSIGNED")
        self.assertTrue(info.is_unassigned)
        self.assertFalse(info.is_typo)

    def test_classify_tba_placeholder(self):
        from scheduling.importing import classify_room
        info = classify_room("TBA")
        self.assertEqual(info.building_code, "UNASSIGNED")
        self.assertEqual(info.floor, 0)
        self.assertFalse(info.is_virtual)

    def test_classify_never_raises_on_real_sample(self):
        from scheduling.importing import classify_room
        # Representative sample of the 168 real distinct room codes.
        for code in ("R415", "A101", "GYM1", "GYM2", "V301", "U102",
                     "404", "516", "A410-A", "A105", "A298", "TBA"):
            classify_room(code)  # must not raise

    # --- parse_time -----------------------------------------------------
    def test_parse_time_cases(self):
        from scheduling.importing import parse_time
        self.assertEqual(parse_time("7:00AM"), time(7, 0))
        self.assertEqual(parse_time("12:00P"), time(12, 0))
        self.assertEqual(parse_time("12:00A"), time(0, 0))
        self.assertEqual(parse_time("1:15PM"), time(13, 15))
        self.assertIsNone(parse_time("bad"))

    # --- parse_meetings (optional room, D2/D9) --------------------------
    def test_parse_meetings_two_with_rooms(self):
        from scheduling.importing import parse_meetings
        from scheduling.models import DayOfWeek
        meetings = parse_meetings(
            "F [7:00AM-8:15AM] V415,M [7:00AM-8:15AM] R415")
        self.assertEqual(len(meetings), 2)
        self.assertEqual(meetings[0].day, DayOfWeek.FRI)
        self.assertEqual(meetings[0].room_raw, "V415")
        self.assertEqual(meetings[0].start, time(7, 0))
        self.assertEqual(meetings[0].end, time(8, 15))
        self.assertEqual(meetings[1].day, DayOfWeek.MON)
        self.assertEqual(meetings[1].room_raw, "R415")

    def test_parse_meetings_optional_room(self):
        from scheduling.importing import parse_meetings
        from scheduling.models import DayOfWeek
        meetings = parse_meetings("M [7:00AM-8:15AM]")
        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].day, DayOfWeek.MON)
        self.assertEqual(meetings[0].room_raw, "")
        self.assertEqual(meetings[0].start, time(7, 0))

    # --- modality_for_room (D5) -----------------------------------------
    def test_modality_for_room(self):
        from scheduling.importing import classify_room, modality_for_room
        from scheduling.models import Modality
        virtual = classify_room("V415")
        physical = classify_room("R415")
        self.assertEqual(modality_for_room(virtual, "f2f"), Modality.ONLINE)
        self.assertEqual(modality_for_room(physical, "blended"), Modality.BLENDED)

    # --- normalize_name_key (D7) ----------------------------------------
    def test_normalize_name_key_merges_variants(self):
        from scheduling.importing import normalize_name_key
        self.assertEqual(
            normalize_name_key("VILLANUEVA, JUAN P"),
            normalize_name_key("Villanueva,  Juan  P."),
        )
        # Distinct people must not collapse.
        self.assertNotEqual(
            normalize_name_key("SANTOS, MARIA"),
            normalize_name_key("SANTOS, JOSE"),
        )

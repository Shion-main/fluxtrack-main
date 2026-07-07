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

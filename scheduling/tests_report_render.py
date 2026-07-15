"""Unit tests for the pure CSV/PDF render layer (RPT-03).

Covers scheduling/report_render.py: the shared CSV-injection neutralizer
(csv_safe), the stdlib-csv byte builder (build_csv), and the ReportLab
Platypus PDF byte builder (build_pdf). These are pure bytes-in/bytes-out
functions so SimpleTestCase (no DB) is sufficient -- FacultyRow instances
are constructed directly.
"""
from django.test import SimpleTestCase

from scheduling.report_render import build_csv, build_pdf, csv_safe, pdf_title
from scheduling.reporting import FacultyRow


def _row(name, scheduled=4, held=3, absent=1, verified=2, pct=75):
    """Build a FacultyRow with all required fields for render tests."""
    return FacultyRow(
        faculty_id=1,
        name=name,
        scheduled=scheduled,
        held=held,
        absent=absent,
        verified=verified,
        attendance_pct=pct,
        early_ends=0,
        absences=[],
    )


CSV_HEADER = "Faculty,Scheduled,Held,Absent,Attendance %,Checker-verified"


class CsvBuildTests(SimpleTestCase):
    def test_header_then_one_line_per_row(self):
        rows = [_row("Cruz Maria"), _row("Santos Jose")]
        text = build_csv(rows).decode("utf-8")
        lines = text.splitlines()
        self.assertEqual(lines[0], CSV_HEADER)
        # header + 2 data rows
        self.assertEqual(len(lines), 3)
        self.assertIn("Cruz Maria", lines[1])
        self.assertIn("Santos Jose", lines[2])

    def test_returns_bytes(self):
        self.assertIsInstance(build_csv([_row("Cruz Maria")]), bytes)

    def test_empty_list_yields_header_only(self):
        text = build_csv([]).decode("utf-8")
        self.assertEqual(text.splitlines(), [CSV_HEADER])

    def test_counts_and_percent_present(self):
        text = build_csv([_row("Cruz Maria", scheduled=4, held=3, pct=75)]).decode("utf-8")
        data_line = text.splitlines()[1]
        self.assertIn("75%", data_line)
        self.assertIn("4", data_line)


class CsvInjectionTests(SimpleTestCase):
    def test_csv_safe_neutralizes_equals(self):
        self.assertTrue(csv_safe("=SUM(A1)").startswith("'"))

    def test_csv_safe_neutralizes_all_triggers(self):
        for bad in ("=x", "+x", "-x", "@x", "\tx", "\rx"):
            self.assertTrue(
                csv_safe(bad).startswith("'"),
                msg=f"expected {bad!r} to be neutralized",
            )

    def test_csv_safe_leaves_plain_name_unchanged(self):
        self.assertEqual(csv_safe("Cruz, Maria"), "Cruz, Maria")

    def test_build_csv_neutralizes_formula_name(self):
        text = build_csv([_row("=cmd|' /C calc'!A1")]).decode("utf-8")
        data_line = text.splitlines()[1]
        # csv.writer will quote the cell (contains comma/quote); the neutralizing
        # single quote must sit at the front of the field value.
        self.assertIn("'=cmd", data_line)

    def test_comma_name_round_trips_through_csv_quoting(self):
        import csv
        import io

        text = build_csv([_row("Cruz, Maria")]).decode("utf-8")
        parsed = list(csv.reader(io.StringIO(text)))
        # header + one row; the name cell survives as a single field with the comma
        self.assertEqual(parsed[1][0], "Cruz, Maria")


class PdfBuildTests(SimpleTestCase):
    def test_returns_pdf_signature_bytes(self):
        rows = [_row("Cruz Maria"), _row("Santos Jose")]
        pdf = build_pdf(rows, "2026-07-13", "2026-07-19", None)
        self.assertIsInstance(pdf, bytes)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 500)

    def test_empty_rows_still_valid_pdf(self):
        pdf = build_pdf([], "2026-07-13", "2026-07-19", None)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 300)


class PdfTitleTests(SimpleTestCase):
    """ME-01: the PDF title labels the ACTUAL range, not a hardcoded 'week of'."""

    def test_range_label_reflects_both_bounds(self):
        # A Dean's ad-hoc, non-weekly range must read as "{start} to {end}".
        title = pdf_title("2026-07-06", "2026-08-31", None)
        self.assertEqual(
            title, "Attendance Report - All - 2026-07-06 to 2026-08-31")
        self.assertNotIn("week of", title)

    def test_department_code_in_title(self):
        class _Dept:
            code = "CCS"
        title = pdf_title("2026-07-06", "2026-07-12", _Dept())
        self.assertIn("CCS", title)
        self.assertIn("2026-07-06 to 2026-07-12", title)

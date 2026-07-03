"""DOC-01 smoke tests: assert the SRS Markdown carries its v1.2 markers and that
FluxTrack_SRS.docx regenerates cleanly from it via the management command.

Concept-based assertions (requirement IDs + the policy key + a revision row),
not brittle whole-line matches. Lives in its own module (tests_srs.py) so it never
contends with scheduling/tests.py; Django test discovery picks up test*.py.
"""
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase


def _srs_md_path() -> Path:
    return Path(settings.BASE_DIR) / "FluxTrack_SRS.md"


def _srs_docx_path() -> Path:
    return Path(settings.BASE_DIR) / "FluxTrack_SRS.docx"


class SrsV12DocTests(SimpleTestCase):
    def test_md_has_v12_markers(self):
        text = _srs_md_path().read_text(encoding="utf-8")

        # New modality-shift requirement area (MOD-01..MOD-06) and the Dean dashboard row.
        self.assertIn("MOD-01", text)
        self.assertIn("MOD-06", text)
        self.assertIn("DEAN-04", text)

        # Policy register key (D-14) and a v1.2 Revision History row.
        self.assertIn("modality_shift_lead_days", text)
        self.assertIn("| 1.2 |", text)

        # CHK-06 auto-Absent override requirement row is removed (Absent is final).
        # The Revision History may mention "CHK-06 removed" in prose; only the table
        # row form "| CHK-06 |" is forbidden.
        self.assertNotIn("| CHK-06 |", text)

    def test_regenerate_srs_docx_writes_nonempty(self):
        call_command("regenerate_srs_docx")
        docx = _srs_docx_path()
        self.assertTrue(docx.exists(), "FluxTrack_SRS.docx was not produced")
        self.assertGreater(docx.stat().st_size, 0, "FluxTrack_SRS.docx is empty")

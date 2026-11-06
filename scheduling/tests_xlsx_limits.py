"""Small malformed archives must fail before dense grid allocation."""
import io
import zipfile
from unittest.mock import patch

from django.test import SimpleTestCase
from scheduling.xlsx import read_grid


def workbook(row="1", cell="A1", text="ok"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" r:id="r1"/></sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", f'<worksheet><sheetData><row r="{row}"><c r="{cell}" t="inlineStr"><is><t>{text}</t></is></c></row></sheetData></worksheet>')
    buffer.seek(0)
    return buffer


class SpreadsheetLimitTests(SimpleTestCase):
    def test_valid_sparse_sheet_still_preserves_coordinates(self):
        self.assertEqual(read_grid(workbook("2", "B2")), [["", ""], ["", "ok"]])

    def test_coordinate_limits_reject_before_dense_allocation(self):
        for row, cell in (("100001", "A100001"), ("1", "ZZZZZZ1"), ("0", "A0")):
            with self.assertRaises(ValueError):
                read_grid(workbook(row, cell))

    def test_expanded_member_limit(self):
        with patch("scheduling.xlsx.MAX_MEMBER_BYTES", 256):
            with self.assertRaises(ValueError):
                read_grid(workbook(text="x"*1024))

    def test_entity_declarations_are_rejected(self):
        buffer = workbook()
        with zipfile.ZipFile(buffer, "a") as archive:
            archive.writestr("xl/sharedStrings.xml", '<!DOCTYPE s [<!ENTITY x "test">]><sst><si><t>&x;</t></si></sst>')
        buffer.seek(0)
        with self.assertRaises(ValueError):
            read_grid(buffer)

    def test_utf16_entity_declarations_are_rejected(self):
        buffer = workbook()
        with zipfile.ZipFile(buffer, "a") as archive:
            archive.writestr("xl/sharedStrings.xml", '<!DOCTYPE s [<!ENTITY x "test">]><sst><si><t>&x;</t></si></sst>'.encode("utf-16"))
        buffer.seek(0)
        with self.assertRaises(ValueError):
            read_grid(buffer)

    def test_xml_depth_is_bounded_before_building_tree(self):
        buffer = workbook()
        with zipfile.ZipFile(buffer, "a") as archive:
            archive.writestr("xl/sharedStrings.xml", "<a>"*65+"</a>"*65)
        buffer.seek(0)
        with self.assertRaises(ValueError):
            read_grid(buffer)

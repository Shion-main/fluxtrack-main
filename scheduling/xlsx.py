"""Minimal, dependency-free Open-XML (.xlsx) spreadsheet reader (D1).

Reads registrar exports using ONLY the Python standard library — ``zipfile``
to open the ``.xlsx`` container and ``xml.etree.ElementTree`` to parse its
parts. There is deliberately NO third-party spreadsheet dependency
(openpyxl / pandas): the phase acceptance criteria forbid one, and the whole
point of D1 is to read the real files with the stdlib alone.

Public API
----------
``sheet_names(path) -> list[str]``
    Worksheet tab names in workbook (document) order.

``read_grid(path, sheet=None) -> list[list[str]]``
    A dense grid of cell *strings* for one worksheet. Row/column positions are
    reconstructed from each cell's ``r`` reference (e.g. ``"O4"`` -> row 4,
    column 14) so sparse rows keep correct columns and missing cells become
    ``""``. Shared strings and inline strings are resolved to their text.

Security note (T-04.1-01): the archive members are parsed directly with
``xml.etree.ElementTree`` and no external DTD/entity resolution is enabled, so
there is no XXE / external-entity surface. The reader only ever opens the
explicit ``path`` it is given.
"""
import re
import zipfile
import xml.etree.ElementTree as ET

# OOXML relationships namespace used for the r:id attribute on <sheet>.
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_MEMBERS = 512
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ROWS = 20000
MAX_COLUMNS = 256
MAX_GRID_CELLS = 1000000
MAX_XML_DEPTH = 64


class _BoundedTreeBuilder(ET.TreeBuilder):
    """Reject declarations and limit nodes before building them, any encoding."""
    def __init__(self):
        super().__init__()
        self.nodes = self.depth = 0

    def doctype(self, name, pubid, system):
        raise ValueError("Spreadsheet entity declarations are not supported")

    def start(self, tag, attrs):
        self.nodes += 1
        self.depth += 1
        if self.nodes > MAX_GRID_CELLS or self.depth > MAX_XML_DEPTH:
            raise ValueError("Spreadsheet XML exceeds complexity limit")
        return super().start(tag, attrs)

    def end(self, tag):
        self.depth -= 1
        return super().end(tag)


def _validate_archive(zf):
    members = zf.infolist()
    if (len(members) > MAX_MEMBERS
            or sum(member.file_size for member in members) > MAX_EXPANDED_BYTES
            or any(member.file_size > MAX_MEMBER_BYTES for member in members)):
        raise ValueError("Spreadsheet exceeds expanded archive limits")


def _localname(tag):
    """Strip the ``{namespace}`` prefix ElementTree prepends to tags."""
    return tag.rsplit("}", 1)[-1]


def _parse(zf, member):
    """Parse an archive member into an Element, or return None if absent.

    Parses the bytes directly; no external DTD or entity resolution is enabled,
    so there is no XXE / billion-laughs surface from untrusted registrar files.
    """
    try:
        info = zf.getinfo(member)
        if info.file_size > MAX_MEMBER_BYTES:
            raise ValueError("Spreadsheet member exceeds size limit")
        with zf.open(info) as stream:
            data = stream.read(MAX_MEMBER_BYTES + 1)
        if len(data) > MAX_MEMBER_BYTES:
            raise ValueError("Spreadsheet member exceeds size limit")
    except KeyError:
        return None
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Spreadsheet entity declarations are not supported")
    return ET.fromstring(data, parser=ET.XMLParser(target=_BoundedTreeBuilder()))


def _col_index(cell_ref):
    """'O4' -> 14 (0-based). Column letters are base-26 (A=1); we subtract 1."""
    letters = re.match(r"[A-Za-z]+", cell_ref or "")
    if not letters:
        return 0
    col = 0
    for ch in letters.group(0).upper():
        col = col * 26 + (ord(ch) - ord("A") + 1)
        if col > MAX_COLUMNS:
            raise ValueError("Spreadsheet column exceeds limit")
    return col - 1


def _load_shared_strings(zf):
    """Return the sharedStrings table as a list of resolved text strings."""
    root = _parse(zf, "xl/sharedStrings.xml")
    if root is None:
        return []
    out = []
    for si in root:
        if _localname(si.tag) != "si":
            continue
        out.append(_si_text(si))
    return out


def _si_text(si):
    """Concatenate all <t> descendants of a shared-string <si> (handles rich
    text runs split across multiple <r><t>...</t></r> elements)."""
    parts = []
    for node in si.iter():
        if _localname(node.tag) == "t" and node.text:
            parts.append(node.text)
    return "".join(parts)


def _workbook_sheets(zf):
    """Return [(name, rId), ...] for <sheet> elements in document order."""
    root = _parse(zf, "xl/workbook.xml")
    if root is None:
        return []
    sheets = []
    for sheets_el in root:
        if _localname(sheets_el.tag) != "sheets":
            continue
        for sheet in sheets_el:
            if _localname(sheet.tag) != "sheet":
                continue
            name = sheet.get("name", "")
            rid = sheet.get("{%s}id" % _R_NS)
            sheets.append((name, rid))
    return sheets


def _rels_map(zf):
    """Map relationship Id -> worksheet-part path (normalised to 'xl/...')."""
    root = _parse(zf, "xl/_rels/workbook.xml.rels")
    if root is None:
        return {}
    out = {}
    for rel in root:
        rid = rel.get("Id")
        target = rel.get("Target", "")
        if not rid or not target:
            continue
        if not target.startswith("xl/"):
            target = "xl/" + target.lstrip("/")
        out[rid] = target
    return out


def sheet_names(path):
    """Return worksheet tab names in workbook (document) order."""
    with zipfile.ZipFile(path) as zf:
        _validate_archive(zf)
        return [name for name, _rid in _workbook_sheets(zf)]


def _worksheet_part(zf, sheet):
    """Resolve the worksheet part path for ``sheet`` (name or None=first)."""
    sheets = _workbook_sheets(zf)
    if not sheets:
        return None
    rels = _rels_map(zf)
    if sheet is None:
        _name, rid = sheets[0]
        return rels.get(rid)
    for name, rid in sheets:
        if name == sheet:
            return rels.get(rid)
    return None


def _cell_text(cell, shared):
    """Resolve a <c> element to its display string."""
    ctype = cell.get("t")
    if ctype == "s":  # shared string: <v> is an index into the table
        for child in cell:
            if _localname(child.tag) == "v" and child.text is not None:
                try:
                    return shared[int(child.text)]
                except (ValueError, IndexError):
                    return ""
        return ""
    if ctype == "inlineStr":  # inline: <is><t>text</t></is>
        return _si_text(cell)
    if ctype == "str":  # formula string result
        for child in cell:
            if _localname(child.tag) == "v":
                return child.text or ""
        return ""
    # number / boolean / date-serial: return the raw <v> text.
    for child in cell:
        if _localname(child.tag) == "v":
            return child.text or ""
    return ""


def read_grid(path, sheet=None):
    """Read one worksheet into a dense list of rows, each a list of strings.

    Row and column positions are taken from the cell ``r`` reference so the
    grid is addressable by absolute position (e.g. ``grid[3][14]`` is cell
    ``O4``). Missing cells and gaps are ``""``.
    """
    with zipfile.ZipFile(path) as zf:
        _validate_archive(zf)
        shared = _load_shared_strings(zf)
        part = _worksheet_part(zf, sheet)
        if part is None:
            return []
        root = _parse(zf, part)
        if root is None:
            return []

        # Collect cells as {row_index: {col_index: text}} while tracking extent.
        cells = {}
        max_row = -1
        max_col = -1
        for sheetdata in root:
            if _localname(sheetdata.tag) != "sheetData":
                continue
            for ri, row in enumerate(sheetdata):
                if _localname(row.tag) != "row":
                    continue
                r_attr = row.get("r")
                row_idx = int(r_attr) - 1 if r_attr else ri
                if not 0 <= row_idx < MAX_ROWS:
                    raise ValueError("Spreadsheet row exceeds limit")
                for cell in row:
                    if _localname(cell.tag) != "c":
                        continue
                    ref = cell.get("r")
                    col_idx = _col_index(ref) if ref else 0
                    text = _cell_text(cell, shared)
                    cells.setdefault(row_idx, {})[col_idx] = text
                    if col_idx > max_col:
                        max_col = col_idx
                if row_idx > max_row:
                    max_row = row_idx
                if (max_row + 1) * (max_col + 1) > MAX_GRID_CELLS:
                    raise ValueError("Spreadsheet grid exceeds cell limit")

    if max_row < 0:
        return []
    width = max_col + 1
    grid = []
    for r in range(max_row + 1):
        rowcells = cells.get(r, {})
        grid.append([rowcells.get(c, "") for c in range(width)])
    return grid

"""Pure CSV/PDF render layer for the consolidated report (RPT-03).

Turns ``FacultyRow`` aggregates from :mod:`scheduling.reporting` into downloadable
bytes. These functions are pure -- dataclasses in, ``bytes`` out: NO ORM access,
NO ``default_storage``, NO ``HttpResponse`` (building the download response is the
caller's job in 06-05 / 06-06 / 06-07). Keeping the render side effect-free means
the stored weekly report, the ad-hoc Dean export, and the HR payroll CSV can all
reuse the same byte builders and can never disagree.

Security (RPT-03 / T-06-02, OWASP CSV-injection): :func:`csv_safe` is the single
neutralizer that prefixes a leading quote to any text cell beginning with a
formula trigger (``= + - @`` or a leading tab / carriage-return). It is imported by
BOTH the weekly-report CSV (06-05) and the HR payroll CSV (06-07) so a
user-controlled faculty display name can never become an executable Excel formula.
Quoting/escaping of commas and quotes is delegated to the stdlib ``csv`` module,
never hand-rolled string joins.
"""
import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# The eight-column contract shared by the CSV and PDF renderers (RPT-03 + A3/D-03).
# Column order is Faculty, then the status counts, the attendance %, the honest
# checker-verified count, and the two lateness cells derived from the Plan-01
# aggregate fields (avg minutes late + a terse chronic flag). This is the ONE shared
# render-layer HEADER; web.hr.CSV_HEADER is a SEPARATE payroll contract (Pitfall 5).
# The chronic cell stays TERSE ("Yes"/"") so the landscape-A4 table absorbs 8 short
# columns without overflow (Pitfall 4).
HEADER = [
    "Faculty", "Scheduled", "Held", "Absent", "Attendance %", "Checker-verified",
    "Avg min late", "Chronic late",
]

# Excel/Sheets treat a cell as a formula when it opens with one of these; a leading
# tab or CR can also smuggle a formula past a naive importer (OWASP CSV-injection).
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")

# Brand navy (matches the app theme-color / UI-SPEC) for the PDF header fill.
_NAVY = colors.HexColor("#001c43")
_ZEBRA = colors.HexColor("#f4f6fa")


def csv_safe(value):
    """Neutralize a formula-triggering text cell (T-06-02, CSV-injection control).

    Coerces ``value`` to ``str`` and, if the result starts with a formula trigger
    (``= + - @`` or a leading tab / carriage-return), prefixes a single quote so a
    spreadsheet renders it as literal text instead of evaluating it. A normal name
    is returned unchanged -- commas and quotes are handled by ``csv`` quoting, not
    here. This is the ONE neutralizer reused by every CSV export in the phase.
    """
    text = str(value)
    if text.startswith(_FORMULA_TRIGGERS):
        return "'" + text
    return text


def build_csv(rows):
    """RPT-03: consolidated report as CSV bytes (header + one line per FacultyRow).

    Uses the stdlib ``csv`` module into a ``StringIO`` for correct quoting/escaping;
    the faculty name is run through :func:`csv_safe` first. Returns UTF-8 ``bytes``
    only -- the caller wraps them in a download response. An empty ``rows`` yields
    just the header line (no crash).
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADER)
    for r in rows:
        writer.writerow([
            csv_safe(r.name),
            r.scheduled,
            r.held,
            r.absent,
            f"{r.attendance_pct}%",
            r.verified,
            r.minutes_late_avg,
            "Yes" if r.chronic_late else "",
        ])
    return buf.getvalue().encode("utf-8")


def pdf_title(period_start, period_end, department):
    """The PDF header title for a report over [period_start, period_end] (RPT-03).

    Names the department code (or ``All`` when ``department`` is ``None``) and the
    ACTUAL date range as ``{start} to {end}`` -- accurate for both a Mon-Sun weekly
    report and a Dean's ad-hoc multi-week range (the old hardcoded "week of {start}"
    mislabeled any non-weekly export, code-review ME-01). Pure: strings in, str out,
    unit-testable without building a whole PDF.
    """
    dept_label = department.code if department is not None else "All"
    return f"Attendance Report - {dept_label} - {period_start} to {period_end}"


def build_pdf(rows, period_start, period_end, department):
    """RPT-03: consolidated report as a printable PDF via ReportLab Platypus.

    Renders a landscape-A4 ``SimpleDocTemplate`` over an in-memory ``BytesIO``: a
    title (see :func:`pdf_title`) naming the department code (or ``All`` when
    ``department`` is ``None``) and the ACTUAL ``period_start`` to ``period_end``
    range, then a ``Table`` with a repeating header row (``repeatRows=1``) styled with
    the brand-navy header fill, a thin grid, and zebra data rows. Bounded to one
    department / one range (T-06-09 accepts in-memory), so no streaming is needed.
    Empty ``rows`` render the title plus a single "No data" line -- never a zero-row
    table that would error. Returns ``bytes`` starting with the ``%PDF`` signature.

    Both bounds are passed (not just the start) so a Dean's ad-hoc range -- which is
    NOT clamped to 7 days -- is labeled honestly instead of "week of {start}".
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4))
    styles = getSampleStyleSheet()

    story = [
        Paragraph(
            pdf_title(period_start, period_end, department),
            styles["Title"],
        ),
        Spacer(1, 12),
    ]

    if not rows:
        story.append(Paragraph("No data for this range.", styles["Normal"]))
        doc.build(story)
        return buf.getvalue()

    data = [HEADER] + [
        [r.name, r.scheduled, r.held, r.absent, f"{r.attendance_pct}%", r.verified,
         r.minutes_late_avg, "Yes" if r.chronic_late else ""]
        for r in rows
    ]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ZEBRA]),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)
    return buf.getvalue()

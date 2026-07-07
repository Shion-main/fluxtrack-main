"""Pure, DB-free parsing / classification / reconciliation helpers (Phase 04.1).

These are the reusable primitives every later plan in this phase depends on:
D4 (prefix->building map), D5 (per-meeting modality), D7 (instructor name
dedup key), and the reconciliation partition that proves "nothing is silently
dropped". Nothing here touches the database or imports Django models beyond the
``Modality`` / ``DayOfWeek`` enums used as return values, so the whole module
is unit-testable as a plain ``SimpleTestCase``.
"""
import re
from dataclasses import dataclass, field
from datetime import time

from scheduling.models import DayOfWeek, Modality

# --------------------------------------------------------------------------
# Static maps (single definition — the importer + room loader both import these)
# --------------------------------------------------------------------------

# D4: leading room-code prefix -> (building_code, building_name). Anything not
# listed here falls through to the Unassigned building and is flagged loudly.
PREFIX_BUILDING = {
    "R": ("ACAD", "Academic Building"),
    "A": ("ADMIN", "Admin Building"),
    "GYM": ("GYM", "Gym"),
    "V": ("ONLINE", "Online (virtual)"),
}
UNASSIGNED_BUILDING = ("UNASSIGNED", "Unassigned")

DAY_MAP = {
    "M": DayOfWeek.MON, "T": DayOfWeek.TUE, "W": DayOfWeek.WED,
    "TH": DayOfWeek.THU, "F": DayOfWeek.FRI, "S": DayOfWeek.SAT,
    "SU": DayOfWeek.SUN,
}

MODE_MAP = {
    "online": Modality.ONLINE, "blended": Modality.BLENDED,
    "f2f": Modality.F2F, "rotation": Modality.BLENDED,
}

# Trailing room token is OPTIONAL ([A-Za-z0-9\-]*) so day/time-only meetings are
# captured with an empty room instead of being silently dropped (D2/D9).
MEET_RE = re.compile(
    r"([A-Z]{1,2})\s*\[([0-9: APM]+)-([0-9: APM]+)\]\s*([A-Za-z0-9\-]*)"
)


# --------------------------------------------------------------------------
# Dataclasses
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RoomInfo:
    raw_code: str
    prefix: str
    building_code: str
    building_name: str
    floor: int
    is_virtual: bool
    is_unassigned: bool
    is_typo: bool
    scannable: bool


@dataclass(frozen=True)
class MeetingParse:
    day: object          # DayOfWeek int, or None if the day token was unknown
    start: object        # datetime.time, or None
    end: object          # datetime.time, or None
    room_raw: str        # "" when the meeting had no trailing room token


# --------------------------------------------------------------------------
# Time / meeting parsing
# --------------------------------------------------------------------------
def parse_time(raw):
    """'7:00AM' / '12:00P' / '12:00A' / '1:15PM' -> datetime.time, or None."""
    t = (raw or "").strip().replace(" ", "")
    m = re.match(r"(\d{1,2}):(\d{2})([AP])M?$", t, re.IGNORECASE)
    if not m:
        return None
    hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "P" and hh != 12:
        hh += 12
    if ap == "A" and hh == 12:
        hh = 0
    if hh > 23 or mm > 59:
        return None
    return time(hh, mm)


def parse_meetings(schedule_str):
    """Parse a compound 'DAY [START-END] ROOM' schedule cell into meetings.

    The schedule cell is comma-separated, e.g.
        "F [7:00AM-8:15AM] V415,M [7:00AM-8:15AM] R415".
    The trailing room token is OPTIONAL: a "M [7:00AM-8:15AM]" part yields a
    meeting with ``room_raw == ""`` rather than being dropped (D2/D9). Returns a
    list of ``MeetingParse``; ``day`` is a ``DayOfWeek`` int or None, ``start`` /
    ``end`` are ``parse_time`` results or None.
    """
    meetings = []
    for part in (schedule_str or "").split(","):
        m = MEET_RE.search(part)
        if not m:
            continue
        day_tok, st_raw, en_raw, room_raw = m.groups()
        meetings.append(MeetingParse(
            day=DAY_MAP.get(day_tok),
            start=parse_time(st_raw),
            end=parse_time(en_raw),
            room_raw=(room_raw or "").strip(),
        ))
    return meetings


# --------------------------------------------------------------------------
# Room classification (D4) + floor derivation
# --------------------------------------------------------------------------
def derive_floor(code):
    """First digit-run after the leading letters -> its leading digit.

    R415 -> 4, A101 -> 1, A410-A -> 4 (hyphen suffix tolerated). GYM-prefixed
    codes are all floor 1 (GYM1, GYM2 -> 1). No digit run (TBA, bare letters)
    -> 0.
    """
    c = (code or "").strip().upper()
    if c.startswith("GYM"):
        return 1
    lead = re.match(r"[A-Z]*", c).group(0)
    rest = c[len(lead):]
    dm = re.match(r"(\d+)", rest)
    if not dm:
        return 0
    return int(dm.group(1)[0])


def classify_room(code):
    """Classify a raw room code into a :class:`RoomInfo` (D4).

    Never raises and never silently drops: unknown / typo codes land in the
    Unassigned building flagged (``is_unassigned`` / ``is_typo``) rather than
    being discarded.
    """
    c = (code or "").strip()
    cu = c.upper()
    is_virtual = is_unassigned = is_typo = False

    if cu.startswith("GYM"):
        prefix = "GYM"
        building_code, building_name = PREFIX_BUILDING["GYM"]
    elif cu[:1] == "V":
        prefix = "V"
        building_code, building_name = PREFIX_BUILDING["V"]
        is_virtual = True
    elif cu[:1] == "R":
        prefix = "R"
        building_code, building_name = PREFIX_BUILDING["R"]
    elif cu[:1] == "A":
        prefix = "A"
        building_code, building_name = PREFIX_BUILDING["A"]
    else:
        # P / U / digit-only / unknown letter -> Unassigned, flagged.
        prefix = re.match(r"[A-Z]*", cu).group(0)
        building_code, building_name = UNASSIGNED_BUILDING
        is_unassigned = True
        # A typo is a code with no leading alphabetic prefix (e.g. 404, 516).
        if not cu[:1].isalpha():
            is_typo = True

    return RoomInfo(
        raw_code=c,
        prefix=prefix,
        building_code=building_code,
        building_name=building_name,
        floor=derive_floor(cu),
        is_virtual=is_virtual,
        is_unassigned=is_unassigned,
        is_typo=is_typo,
        scannable=not is_virtual,
    )


# --------------------------------------------------------------------------
# Modality (D5) + instructor dedup key (D7)
# --------------------------------------------------------------------------
def modality_for_room(room_info, course_mode):
    """Per-meeting modality: virtual rooms force ONLINE, else the course mode.

    A blended course therefore yields ONLINE for its virtual-day meeting and
    BLENDED for its physical-day meeting (D5).
    """
    if room_info is not None and room_info.is_virtual:
        return Modality.ONLINE
    return MODE_MAP.get((course_mode or "").strip().lower(), Modality.F2F)


def normalize_name_key(name):
    """Case/comma/spacing/initial-insensitive dedup key for instructor names.

    Uppercases, drops commas and periods, collapses whitespace, and removes any
    standalone single-letter token (a middle initial) so that
    'VILLANUEVA, JUAN P' and 'Villanueva,  Juan  P.' collapse to one key (D7).
    """
    cleaned = (name or "").upper().replace(",", " ").replace(".", " ")
    tokens = [t for t in cleaned.split() if len(t) > 1]
    return " ".join(tokens)

"""Pure, DB-free parsing / classification / reconciliation helpers (Phase 04.1).

These are the reusable primitives every later plan in this phase depends on:
D4 (prefix->building map), D5 (per-meeting modality), D7 (instructor name
dedup key), and the reconciliation partition that proves "nothing is silently
dropped". Nothing here touches the database or imports Django models beyond the
``Modality`` / ``DayOfWeek`` enums used as return values, so the whole module
is unit-testable as a plain ``SimpleTestCase``.
"""
import re
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Reconciliation:
    """The four-bucket partition of every offering row + derived stats. This is
    the single source of truth the importer report (Plan 03) and the run/verify
    assertions (Plan 04) both consume."""
    total_rows: int
    no_schedule: int
    intact_rows: int
    roomless_tba_rows: int
    online_no_room_rows: int
    total_meetings: int
    flagged_unassigned: list        # unassigned room codes (U-prefix, etc.)
    flagged_typo: list              # digit-only / no-prefix typo codes (404, 516)
    distinct_rooms: int             # distinct real room codes seen
    distinct_instructors: int       # distinct (email OR normalized-name) keys
    emailless_instructor_keys: list  # normalized-name keys carrying no email


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


# --------------------------------------------------------------------------
# Reconciliation (the four-bucket partition — "nothing silently dropped", D9)
# --------------------------------------------------------------------------
def _row_cell(row, col, name):
    """Read a named column from a raw row list, tolerating short/sparse rows."""
    i = col.get(name)
    if i is None or i >= len(row):
        return ""
    return (row[i] or "").strip()


def _is_real_room(room_raw, sec):
    """A non-empty room token is a REAL room unless it is a section label.

    A token equal to the row's Sec that does NOT resolve to a real building
    (e.g. an Unassigned ``C110``) is a section number, not a room (D9's
    A151/C110 guard). Typo / unassigned tokens that are NOT the section label
    (e.g. ``404``, ``U102``) still count as rooms — they are flagged loudly,
    never silently dropped — and a real building room whose code happens to
    equal the Sec (e.g. ``A298``) is kept.
    """
    if not room_raw:
        return False
    if (room_raw.strip().upper() == (sec or "").strip().upper()
            and classify_room(room_raw).is_unassigned):
        return False
    return True


def reconcile(rows, col):
    """Partition every offering row into exactly one of four buckets.

    ``rows`` are the data rows (header excluded); ``col`` is the
    ``header -> index`` map. Each row lands in exactly one of: ``no_schedule``
    (blank Schedule cell), ``intact_rows`` (>=1 meeting with a real room + valid
    weekday + non-zero time), ``online_no_room_rows`` (has meetings but no real
    room and the course Mode is online), or ``roomless_tba_rows`` (has meetings
    but no real room, non-online mode -> routed to the TBA placeholder by Plan
    03). ``total_meetings`` counts every real-room meeting across the intact
    rows. The partition is exhaustive and disjoint by construction, so the
    identity ``total_rows == intact + roomless_tba + online_no_room +
    no_schedule`` always holds — nothing is ever silently dropped.
    """
    no_schedule = intact = roomless = online = 0
    total_meetings = 0
    flagged_unassigned = set()
    flagged_typo = set()
    distinct_rooms = set()
    email_keys = set()
    name_email = {}  # normalized-name key -> True if it ever carried an email

    for row in rows:
        # Instructor stats run for every row (D7 dedup: email, then name).
        inst = _row_cell(row, col, "Instructor")
        email = _row_cell(row, col, "Email")
        nk = normalize_name_key(inst)
        if email:
            email_keys.add(email.lower())
            if nk:
                name_email[nk] = True
        elif nk:
            name_email.setdefault(nk, False)

        sched = _row_cell(row, col, "Schedule")
        if not sched:
            no_schedule += 1
            continue

        sec = _row_cell(row, col, "Sec")
        mode = _row_cell(row, col, "Mode").lower()
        real = []
        for m in parse_meetings(sched):
            # A meeting requires a valid weekday + a non-zero time slot.
            if m.day is None or not m.start or not m.end or m.start == m.end:
                continue
            if not _is_real_room(m.room_raw, sec):
                continue
            real.append(m)
            info = classify_room(m.room_raw)
            code = m.room_raw.strip().upper()
            distinct_rooms.add(code)
            if info.is_typo:
                flagged_typo.add(code)
            elif info.is_unassigned:
                flagged_unassigned.add(code)

        total_meetings += len(real)
        if real:
            intact += 1
        elif mode == "online":
            online += 1
        else:
            roomless += 1

    emailless = sorted(k for k, has in name_email.items() if not has)
    distinct_instructors = len(email_keys) + len(emailless)

    return Reconciliation(
        total_rows=len(rows),
        no_schedule=no_schedule,
        intact_rows=intact,
        roomless_tba_rows=roomless,
        online_no_room_rows=online,
        total_meetings=total_meetings,
        flagged_unassigned=sorted(flagged_unassigned),
        flagged_typo=sorted(flagged_typo),
        distinct_rooms=len(distinct_rooms),
        distinct_instructors=distinct_instructors,
        emailless_instructor_keys=emailless,
    )

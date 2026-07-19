"""
Load the room MASTER (names + real capacities) from the registrar's
``.xlsx`` room-schedule statistics template (Phase 04.1, D3).

The master workbook has 116 worksheet tabs: two summary tabs
(``Lecture Summary`` / ``Lab Summary``) and 114 real room tabs. Per room tab
the authoritative code is the TAB NAME (cell B4 may be a ``#NAME?`` error, so
we never trust it), the human name is cell C4, and the capacity is cell O4.

D3 requires the full room master to exist as named ``Room`` rows BEFORE
offerings are imported, so rooms carry real names + capacities and the
importer (Plan 03) only attaches schedules to existing rooms.

Tab-skip rule (D4, tightened): a tab is skipped **if and only if its name is
not a parseable room code**, decided SOLELY from ``classify_room(tab_name)``.
That excludes exactly the two summary tabs. It explicitly does NOT gate on the
presence of a name (C4) or capacity (O4): 9 master rooms have a blank name and
3 have no capacity, and a real room with a blank name/capacity is still a room
and is still imported (name='' / capacity=0). Unassigned P/U codes and
digit-only typos ARE real rooms and are kept (flagged, never dropped).

Usage:
    py -3.12 manage.py load_room_master --dry-run     # parse + report only
    py -3.12 manage.py load_room_master               # load / refresh master
    py -3.12 manage.py load_room_master --file <path>
"""
import secrets

from django.core.management.base import BaseCommand
from django.db import transaction

from campus.codes import generate_manual_code

from campus.models import Building, Floor, Room
from scheduling import xlsx
from scheduling.importing import (PREFIX_BUILDING, UNASSIGNED_BUILDING,
                                  classify_room)

DEFAULT_FILE = "data/raw/2T-25-26-All Physical-RoomScheduleStatisticsTemplate1.xlsx"

# Per room tab, the authoritative cells (0-based grid positions):
#   C4 -> row 3, col 2  (room name)
#   O4 -> row 3, col 14 (capacity)
NAME_ROW, NAME_COL = 3, 2
CAP_ROW, CAP_COL = 3, 14


def is_room_tab(tab_name):
    """True iff ``tab_name`` is a parseable room code (D4 skip rule).

    Keys SOLELY on ``classify_room(tab_name)`` output — never on C4/O4:

    * a known building prefix (R/A/V/GYM) -> always a room;
    * an Unassigned bucket tab is a room iff it is a digit-only typo
      (e.g. ``404``) OR carries a floor digit (``U101`` / ``P101`` -> floor 1).

    The only tabs that fall through are the wordy summary tabs
    (``Lecture Summary`` / ``Lab Summary``): Unassigned, not a typo, floor 0.
    """
    info = classify_room(tab_name)
    if not info.is_unassigned:
        return True
    return info.is_typo or info.floor > 0


def _cell(grid, row, col):
    """Read grid[row][col] tolerating short/sparse rows (missing -> '')."""
    if len(grid) > row and len(grid[row]) > col:
        return grid[row][col] or ""
    return ""


def _parse_capacity(raw):
    """'40.0' / '40' -> 40; blank / non-numeric -> 0 (a real room may lack one)."""
    s = (raw or "").strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


class Command(BaseCommand):
    help = ("Load the 114 named master rooms (real capacities) from the "
            "room-master .xlsx (D3). Idempotent; supports --dry-run.")

    def add_arguments(self, p):
        p.add_argument("--file", default=DEFAULT_FILE,
                       help="Room-master .xlsx path (default the 2T master).")
        p.add_argument("--dry-run", action="store_true",
                       help="Parse + report only; write nothing.")

    def handle(self, *args, **o):
        path = o["file"]

        # --- Parse phase: build the full list of (code, name, capacity, info)
        # tuples BEFORE any write, so we never interleave a live sheet read
        # with DB writes (pyodbc single-active-result-set / HY010). ---
        parsed = []
        skipped_tabs = []
        for tab in xlsx.sheet_names(path):
            if not is_room_tab(tab):
                skipped_tabs.append(tab)
                continue
            grid = xlsx.read_grid(path, tab)
            code = tab.strip()
            name = _cell(grid, NAME_ROW, NAME_COL).strip()
            capacity = _parse_capacity(_cell(grid, CAP_ROW, CAP_COL))
            parsed.append((code, name, capacity, classify_room(code)))

        if o["dry_run"]:
            self._report(parsed, skipped_tabs, created=0, updated=0,
                         per_building=self._preview_buildings(parsed),
                         dry_run=True)
            return

        created = updated = 0
        per_building = {}

        @transaction.atomic
        def run():
            nonlocal created, updated
            # Ensure all five buildings exist from the D4 prefix map, even ones
            # with no room in THIS (physical-only) master — the Online building
            # must exist so Plan 03's virtual placeholders can attach later.
            for bcode, bname in list(PREFIX_BUILDING.values()) + [UNASSIGNED_BUILDING]:
                Building.objects.get_or_create(code=bcode, defaults={"name": bname})
            for code, name, capacity, info in parsed:
                bldg, _ = Building.objects.get_or_create(
                    code=info.building_code,
                    defaults={"name": info.building_name})
                floor, _ = Floor.objects.get_or_create(
                    building=bldg, number=info.floor)
                room, was_created = Room.objects.get_or_create(
                    code=code,
                    defaults={
                        "floor": floor,
                        "name": name,
                        "capacity": capacity,
                        "qr_token": secrets.token_urlsafe(24),
                        # Collision-retrying mint — a bare randbelow() against
                        # the unique column fails ~2.3% of full-term loads.
                        "manual_code": generate_manual_code(),
                    })
                if was_created:
                    created += 1
                else:
                    # Refresh metadata from the master on a re-run, but NEVER
                    # regenerate the opaque tokens (rotating them would break
                    # printed QR/manual codes).
                    changed = []
                    if name and room.name != name:
                        room.name = name
                        changed.append("name")
                    if capacity and room.capacity != capacity:
                        room.capacity = capacity
                        changed.append("capacity")
                    if changed:
                        room.save(update_fields=changed)
                    updated += 1
                per_building[info.building_code] = \
                    per_building.get(info.building_code, 0) + 1

        run()
        self._report(parsed, skipped_tabs, created=created, updated=updated,
                     per_building=per_building, dry_run=False)

    def _preview_buildings(self, parsed):
        counts = {}
        for _code, _name, _cap, info in parsed:
            counts[info.building_code] = counts.get(info.building_code, 0) + 1
        return counts

    def _report(self, parsed, skipped_tabs, created, updated, per_building,
                dry_run):
        w = self.stdout.write
        head = "DRY RUN — nothing written" if dry_run else "Room master loaded"
        w(self.style.SUCCESS(f"\n{head}"))
        w(f"  Room tabs parsed  : {len(parsed)}")
        if not dry_run:
            w(f"  Rooms created     : {created}")
            w(f"  Rooms updated     : {updated}")
        w("  Per building:")
        for code in sorted(per_building):
            w(f"    {code:<12}: {per_building[code]}")
        w(f"  Skipped (not room codes): {len(skipped_tabs)} "
          f"-> {', '.join(skipped_tabs) if skipped_tabs else 'none'}")
        # A tab that parsed as a room but landed in Unassigned is flagged, never
        # silently dropped.
        unassigned = [c for c, _n, _cap, info in parsed if info.is_unassigned]
        if unassigned:
            w(self.style.WARNING(
                f"  Flagged Unassigned rooms: {', '.join(sorted(unassigned))}"))

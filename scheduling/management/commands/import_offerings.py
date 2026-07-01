"""
Import schedules from the MMCM "Course Offering" CSV (IFO-03).

The reliable source is the `Schedule` text column, e.g.:
    F [7:00AM-8:15AM] V415,M [7:00AM-8:15AM] R415,W [7:00AM-8:15AM] R415
Each comma-separated part is "DAY [START-END] ROOM". V-prefix rooms are virtual
(online) and skipped; R/A/G/U are physical. One physical meeting -> one Schedule row.

Usage:
    py -3.12 manage.py import_offerings --building R --floor 3           # a slice
    py -3.12 manage.py import_offerings --dry-run                        # parse only
    py -3.12 manage.py import_offerings                                  # whole file
"""
import csv
import re
import secrets
from datetime import time, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Role
from campus.models import Building, Floor, Room
from scheduling.models import (AcademicTerm, DayOfWeek, Modality, Schedule,
                               ScheduleStatus)

User = get_user_model()

DEFAULT_FILE = "data/raw/2T-25-26-Course Offerring(Sheet1).csv"
MEET_RE = re.compile(r"([A-Z]{1,2})\s*\[([0-9: APM]+)-([0-9: APM]+)\]\s*([A-Za-z0-9\-]+)")
DAY_MAP = {"M": DayOfWeek.MON, "T": DayOfWeek.TUE, "W": DayOfWeek.WED,
           "TH": DayOfWeek.THU, "F": DayOfWeek.FRI, "S": DayOfWeek.SAT, "SU": DayOfWeek.SUN}
MODE_MAP = {"online": Modality.ONLINE, "blended": Modality.BLENDED,
            "f2f": Modality.F2F, "rotation": Modality.BLENDED}


def parse_time(raw):
    """'7:00AM' / '12:00P' / '10:45A' / '1:15PM' -> datetime.time, or None."""
    t = raw.strip().replace(" ", "")
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


def parse_room(code):
    """'R415' -> ('R', 4, 'R415'); '' or 'V...' or malformed -> None (skip)."""
    code = code.strip()
    if not code or not code[0].isalpha() or code[0].upper() == "V":
        return None
    if len(code) < 2 or not code[1].isdigit():
        return None
    return code[0].upper(), int(code[1]), code


class Command(BaseCommand):
    help = "Import rooms, faculty, and schedules from the Course Offering CSV."

    def add_arguments(self, p):
        p.add_argument("--file", default=DEFAULT_FILE)
        p.add_argument("--building", help="Filter to a building letter, e.g. R")
        p.add_argument("--floor", type=int, help="Filter to a floor number")
        p.add_argument("--limit", type=int, help="Max sections to import")
        p.add_argument("--term-name", default="2nd Term SY 2025-2026")
        p.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        with open(o["file"], encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
        header, data = rows[0], rows[1:]
        col = {c: i for i, c in enumerate(header)}

        stats = {"sections": 0, "rooms": set(), "faculty": set(), "schedules": 0,
                 "skip_no_schedule": 0, "skip_virtual": 0, "skip_bad_time": 0,
                 "skip_filtered": 0}

        term = None
        if not o["dry_run"]:
            term, _ = AcademicTerm.objects.get_or_create(
                name=o["term_name"],
                defaults={"start_date": timezone.now().date() - timedelta(days=14),
                          "end_date": timezone.now().date() + timedelta(days=100),
                          "is_active": True})
            # Enforce "exactly one active term" (§5): make this the sole active one.
            AcademicTerm.objects.exclude(pk=term.pk).update(is_active=False)
            if not term.is_active:
                term.is_active = True
                term.save(update_fields=["is_active"])

        @transaction.atomic
        def run():
            for r in data:
                if o["limit"] and stats["sections"] >= o["limit"]:
                    break
                sched_str = r[col["Schedule"]].strip()
                if not sched_str:
                    stats["skip_no_schedule"] += 1
                    continue

                meetings = []
                for part in sched_str.split(","):
                    m = MEET_RE.search(part)
                    if not m:
                        continue
                    day_tok, st_raw, en_raw, room_raw = m.groups()
                    parsed = parse_room(room_raw)
                    if parsed is None:
                        stats["skip_virtual"] += 1
                        continue
                    if o["building"] and parsed[0] != o["building"].upper():
                        stats["skip_filtered"] += 1
                        continue
                    if o["floor"] is not None and parsed[1] != o["floor"]:
                        stats["skip_filtered"] += 1
                        continue
                    st, en = parse_time(st_raw), parse_time(en_raw)
                    if st is None or en is None or day_tok not in DAY_MAP:
                        stats["skip_bad_time"] += 1
                        continue
                    meetings.append((DAY_MAP[day_tok], st, en, parsed))

                if not meetings:
                    continue
                stats["sections"] += 1
                if o["dry_run"]:
                    for _d, _s, _e, (_b, _f, rc) in meetings:
                        stats["rooms"].add(rc)
                        stats["schedules"] += 1
                    stats["faculty"].add(r[col["Email"]].strip() or r[col["Instructor"]])
                    continue

                faculty = self._faculty(r[col["Instructor"]], r[col["Email"]])
                stats["faculty"].add(faculty.username)
                mode = MODE_MAP.get(r[col["Mode"]].strip().lower(), Modality.F2F)
                enrolled = int(r[col["Enrolled"]]) if r[col["Enrolled"]].isdigit() else 0
                for day, st, en, (b, f, rc) in meetings:
                    room = self._room(b, f, rc)
                    stats["rooms"].add(rc)
                    _, created = Schedule.objects.get_or_create(
                        term=term, course_code=r[col["Code"]], section=r[col["Sec"]],
                        day_of_week=day, room=room, start_time=st,
                        defaults={"faculty": faculty, "end_time": en, "modality": mode,
                                  "enrolled_count": enrolled, "status": ScheduleStatus.ACTIVE})
                    if created:
                        stats["schedules"] += 1

        run()
        self._report(stats, o)

    def _faculty(self, name, email):
        email = email.strip()
        if email:
            uname = email.split("@")[0]
            u, created = User.objects.get_or_create(
                email=email, defaults={"username": uname, "role": Role.FACULTY})
        else:
            uname = f"fac-{slugify(name)[:24]}" or f"fac-{secrets.token_hex(3)}"
            u, created = User.objects.get_or_create(
                username=uname, defaults={"role": Role.FACULTY})
        if created:
            parts = [p.strip() for p in name.split(",")]
            u.last_name = parts[0].title() if parts else ""
            u.first_name = parts[1].title() if len(parts) > 1 else ""
            u.set_unusable_password()
            u.save()
        return u

    def _room(self, b, f, code):
        bldg, _ = Building.objects.get_or_create(code=b, defaults={"name": f"Building {b}"})
        floor, _ = Floor.objects.get_or_create(building=bldg, number=f)
        room, created = Room.objects.get_or_create(code=code, defaults={
            "floor": floor, "qr_token": secrets.token_urlsafe(24),
            "manual_code": f"{secrets.randbelow(1000000):06d}"})
        return room

    def _report(self, s, o):
        w = self.stdout.write
        head = "DRY RUN — nothing written" if o["dry_run"] else "Import complete"
        w(self.style.SUCCESS(f"\n{head}"))
        flt = " ".join(f for f in [f"building={o['building']}" if o["building"] else "",
                                   f"floor={o['floor']}" if o["floor"] is not None else ""] if f)
        w(f"  Filter: {flt or 'none (whole file)'}")
        w(f"  Sections imported : {s['sections']}")
        w(f"  Rooms             : {len(s['rooms'])}")
        w(f"  Faculty           : {len(s['faculty'])}")
        w(f"  Schedule rows     : {s['schedules']}")
        w(f"  Skipped — no schedule string : {s['skip_no_schedule']}")
        w(f"  Skipped — virtual/other room : {s['skip_virtual']}")
        w(f"  Skipped — off-filter meeting : {s['skip_filtered']}")
        w(f"  Skipped — bad time/day       : {s['skip_bad_time']}")

"""
Import schedules from the MMCM "Course Offering" export (IFO-03, Phase 04.1).

Reads the real offerings ``.xlsx`` by default (D1) and consumes the shared,
DB-free helpers in ``scheduling.importing`` (D4/D5/D7/D9) so the loader, the
reconciliation report, and the tests all use ONE parsing/classification
implementation — never a second private copy.

What it does now (vs. the old CSV-only importer that dropped 1,215 meetings):
  * D1  — dispatches by extension: ``.csv`` is read via ``csv.reader`` (keeps the
          r3_synthetic fixture + ``--building/--floor`` regression, ImportPathTests);
          anything else is read via the stdlib ``scheduling.xlsx.read_grid``.
  * D2  — keeps virtual (V) and gym meetings; the old skip-virtual branch and the
          GYM-dropping second-char-digit rule are gone.
  * D4  — rooms are created via the prefix->building map (``classify_room``);
          unknown/typo/P/U/digit-only codes land in the flagged "Unassigned"
          building, never silently dropped.
  * D5  — each meeting's modality is stamped by its room (``modality_for_room``):
          a virtual room forces Online; a physical room keeps the course mode. A
          blended course therefore yields BOTH a scannable physical schedule and
          an Online schedule.
  * D7  — instructors dedup by email, then by ``normalize_name_key`` — the 57
          blank-email rows collapse to ~10 Users, never one per row.
  * D9  — roomless PHYSICAL sections load against a single shared "TBA" placeholder
          Room in the Unassigned building (section labels are never treated as
          rooms); roomless ONLINE sections get an Online placeholder room.
  * D8  — still sets ``Schedule.faculty``; materialize_sessions copies it onto
          Session.faculty unchanged (that path is NOT touched here).
  * D6  — the AcademicTerm window stays centered on TODAY, exactly one active term.

Usage:
    py -3.12 manage.py import_offerings --dry-run                       # parse + report
    py -3.12 manage.py import_offerings                                 # whole term (xlsx)
    py -3.12 manage.py import_offerings --file data/fixtures/r3_synthetic.csv \
        --building R --floor 3                                          # a CSV slice
"""
import csv
import os
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from accounts.models import Role
from campus.models import Building, Floor, Room
from scheduling import xlsx
from scheduling.importing import (classify_room, modality_for_room,
                                  normalize_name_key, parse_meetings, reconcile)
from scheduling.importing import _is_real_room as is_real_room  # shared D9 rule
from scheduling.models import (AcademicTerm, Modality, Schedule,
                               ScheduleStatus)

User = get_user_model()

DEFAULT_FILE = "data/raw/2T-25-26-Course Offerring (1).xlsx"
DEFAULT_SHEET = "Sheet1"

# Shared roomless placeholders (D9). "TBA" -> Unassigned building (physical
# sections with a day/time but no room); "VTBA" -> Online building (roomless
# online sections). Both are get_or_created once and reused by every roomless row.
TBA_ROOM_CODE = "TBA"
ONLINE_TBA_ROOM_CODE = "VTBA"


class Command(BaseCommand):
    help = "Import rooms, faculty, and schedules from the Course Offering export."

    def add_arguments(self, p):
        p.add_argument("--file", default=DEFAULT_FILE)
        p.add_argument("--sheet", default=DEFAULT_SHEET,
                       help="Worksheet name for .xlsx input (default Sheet1).")
        p.add_argument("--building", help="Filter to a building prefix, e.g. R")
        p.add_argument("--floor", type=int, help="Filter to a floor number")
        p.add_argument("--limit", type=int, help="Max sections to import")
        p.add_argument("--term-name", default="2nd Term SY 2025-2026")
        p.add_argument("--dry-run", action="store_true")

    # ------------------------------------------------------------------
    # Input: extension dispatch (D1). Returns a list of row lists so the
    # write loop iterates a plain Python list (never a live cursor -> no
    # pyodbc HY010 single-active-result-set error).
    # ------------------------------------------------------------------
    def _read_rows(self, path, sheet):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            with open(path, encoding="utf-8-sig", newline="") as fh:
                return list(csv.reader(fh))
        return xlsx.read_grid(path, sheet)

    @staticmethod
    def _cell(row, col, name):
        """Read a named column tolerating short/sparse rows (missing -> '')."""
        i = col.get(name)
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    def handle(self, *args, **o):
        rows = self._read_rows(o["file"], o["sheet"])
        if not rows:
            self.stdout.write(self.style.ERROR(f"No rows read from {o['file']}"))
            return
        header, data = rows[0], rows[1:]
        col = {(c or "").strip(): i for i, c in enumerate(header)}

        stats = {"sections": 0, "rooms": set(), "faculty": set(), "schedules": 0,
                 "skip_no_schedule": 0, "skip_bad_time": 0, "skip_filtered": 0,
                 "tba_rows": 0, "online_no_room_rows": 0}

        term = None
        if not o["dry_run"]:
            term, _ = AcademicTerm.objects.get_or_create(
                name=o["term_name"],
                defaults={"start_date": timezone.now().date() - timedelta(days=14),
                          "end_date": timezone.now().date() + timedelta(days=100),
                          "is_active": True})
            # D6: enforce "exactly one active term" — make this the sole active one.
            AcademicTerm.objects.exclude(pk=term.pk).update(is_active=False)
            if not term.is_active:
                term.is_active = True
                term.save(update_fields=["is_active"])

        filtered = bool(o["building"]) or o["floor"] is not None
        name_cache = {}  # normalized-name key -> User (blank-email dedup, D7)

        @transaction.atomic
        def run():
            for r in data:
                if o["limit"] and stats["sections"] >= o["limit"]:
                    break
                sched_str = self._cell(r, col, "Schedule")
                if not sched_str:
                    stats["skip_no_schedule"] += 1
                    continue

                sec = self._cell(r, col, "Sec")
                course_mode = self._cell(r, col, "Mode")

                real_meetings = []      # (day, start, end, room_info)
                roomless_meetings = []  # (day, start, end) valid slot, no real room
                for m in parse_meetings(sched_str):
                    if m.day is None or not m.start or not m.end or m.start == m.end:
                        stats["skip_bad_time"] += 1
                        continue
                    if is_real_room(m.room_raw, sec):
                        info = classify_room(m.room_raw)
                        if o["building"] and info.prefix != o["building"].upper():
                            stats["skip_filtered"] += 1
                            continue
                        if o["floor"] is not None and info.floor != o["floor"]:
                            stats["skip_filtered"] += 1
                            continue
                        real_meetings.append((m.day, m.start, m.end, info))
                    else:
                        roomless_meetings.append((m.day, m.start, m.end))

                # Resolve the row's meetings to (room_info | placeholder-kind).
                # An explicit building/floor filter scopes OUT roomless rows (the
                # TBA/Online placeholders live in other buildings).
                if real_meetings:
                    plan = [(info, modality_for_room(info, course_mode), d, s, e)
                            for (d, s, e, info) in real_meetings]
                elif filtered:
                    continue
                elif course_mode.strip().lower() == "online":
                    stats["online_no_room_rows"] += 1
                    plan = [(None, Modality.ONLINE, d, s, e)
                            for (d, s, e) in roomless_meetings]
                    _placeholder = ONLINE_TBA_ROOM_CODE
                else:
                    stats["tba_rows"] += 1
                    plan = [(None, modality_for_room(None, course_mode), d, s, e)
                            for (d, s, e) in roomless_meetings]
                    _placeholder = TBA_ROOM_CODE

                if not plan:
                    continue
                stats["sections"] += 1

                if o["dry_run"]:
                    for info, _mode, _d, _s, _e in plan:
                        code = info.raw_code if info else _placeholder
                        stats["rooms"].add(code.upper())
                        stats["schedules"] += 1
                    stats["faculty"].add(self._faculty_key(r, col))
                    continue

                faculty = self._faculty(self._cell(r, col, "Instructor"),
                                        self._cell(r, col, "Email"), name_cache)
                stats["faculty"].add(faculty.username)
                enrolled_raw = self._cell(r, col, "Enrolled")
                enrolled = int(enrolled_raw) if enrolled_raw.isdigit() else 0
                course_code = self._cell(r, col, "Code")
                for info, mode, day, st, en in plan:
                    room = (self._room_for(info) if info is not None
                            else self._placeholder_room(_placeholder))
                    stats["rooms"].add(room.code.upper())
                    _, created = Schedule.objects.get_or_create(
                        term=term, course_code=course_code, section=sec,
                        day_of_week=day, room=room, start_time=st,
                        defaults={"faculty": faculty, "end_time": en,
                                  "modality": mode, "enrolled_count": enrolled,
                                  "status": ScheduleStatus.ACTIVE})
                    if created:
                        stats["schedules"] += 1

        run()
        self._report(stats, o, data, col, term)

    # ------------------------------------------------------------------
    # Instructor dedup (D7): email, then normalized name.
    # ------------------------------------------------------------------
    def _faculty_key(self, r, col):
        """The dry-run dedup key mirroring _faculty (email, else name key)."""
        email = self._cell(r, col, "Email")
        if email:
            return "e:" + email.lower()
        return "n:" + normalize_name_key(self._cell(r, col, "Instructor"))

    def _faculty(self, name, email, name_cache):
        email = email.strip()
        if email:
            uname = email.split("@")[0]
            u, created = User.objects.get_or_create(
                email=email, defaults={"username": uname, "role": Role.FACULTY})
        else:
            key = normalize_name_key(name)
            if key in name_cache:
                return name_cache[key]
            uname = f"fac-{slugify(key)[:24]}" or f"fac-{secrets.token_hex(3)}"
            u, created = User.objects.get_or_create(
                username=uname, defaults={"role": Role.FACULTY})
            name_cache[key] = u
        if created:
            parts = [p.strip() for p in name.split(",")]
            u.last_name = parts[0].title() if parts else ""
            u.first_name = parts[1].title() if len(parts) > 1 else ""
            u.set_unusable_password()
            u.save()
        return u

    # ------------------------------------------------------------------
    # Room creation (D4): prefix->building via classify_room / RoomInfo.
    # ------------------------------------------------------------------
    def _room_for(self, info):
        bldg, _ = Building.objects.get_or_create(
            code=info.building_code, defaults={"name": info.building_name})
        floor, _ = Floor.objects.get_or_create(building=bldg, number=info.floor)
        room, _ = Room.objects.get_or_create(code=info.raw_code, defaults={
            "floor": floor, "qr_token": secrets.token_urlsafe(24),
            "manual_code": f"{secrets.randbelow(1000000):06d}"})
        return room

    def _placeholder_room(self, code):
        """Shared roomless placeholder (D9): TBA (Unassigned) / VTBA (Online)."""
        return self._room_for(classify_room(code))

    # ------------------------------------------------------------------
    # Reconciliation report (D4/D7/D9): prove the four-bucket partition and
    # flag every Unassigned/typo room + email-less instructor so a silent drop
    # can never hide. Driven by the SAME scheduling.importing.reconcile the
    # Plan 04 run/verify consumes — one source of truth.
    # ------------------------------------------------------------------
    def _report(self, s, o, data, col, term):
        w = self.stdout.write
        head = "DRY RUN — nothing written" if o["dry_run"] else "Import complete"
        w(self.style.SUCCESS(f"\n{head}"))
        flt = " ".join(f for f in [f"building={o['building']}" if o["building"] else "",
                                   f"floor={o['floor']}" if o["floor"] is not None else ""] if f)
        w(f"  Filter: {flt or 'none (whole file)'}")

        # Importer's own tally of what it loaded (per-meeting).
        w("  Loaded:")
        w(f"    Sections imported : {s['sections']}")
        w(f"    Rooms             : {len(s['rooms'])}")
        w(f"    Faculty           : {len(s['faculty'])}")
        w(f"    Schedule rows     : {s['schedules']}")
        w(f"    Roomless -> TBA rows  : {s['tba_rows']}")
        w(f"    Online (no room) rows : {s['online_no_room_rows']}")
        w(f"    Skipped — off-filter  : {s['skip_filtered']}")
        w(f"    Skipped — bad time/day: {s['skip_bad_time']}")

        # The authoritative reconciliation partition over EVERY offering row.
        rec = reconcile(data, col)
        bucket_sum = (rec.intact_rows + rec.roomless_tba_rows
                      + rec.online_no_room_rows + rec.no_schedule)
        balanced = bucket_sum == rec.total_rows
        w("  Reconciliation (every offering row lands in exactly one bucket):")
        w(f"    intact (real room)    : {rec.intact_rows}")
        w(f"    roomless -> TBA       : {rec.roomless_tba_rows}")
        w(f"    online (no room)      : {rec.online_no_room_rows}")
        w(f"    no schedule string    : {rec.no_schedule}")
        identity = (f"{rec.intact_rows} + {rec.roomless_tba_rows} + "
                    f"{rec.online_no_room_rows} + {rec.no_schedule} = {bucket_sum}")
        w(f"    IDENTITY: {identity} == total_rows ({rec.total_rows})  "
          f"[{'OK' if balanced else 'MISMATCH'}]")
        w(f"    Total meetings (real) : {rec.total_meetings}  (target 2021)")
        w(f"    Distinct rooms        : {rec.distinct_rooms}")
        w(f"    Distinct instructors  : {rec.distinct_instructors}")

        # Flagged lists — visible warning markers; nothing is silently dropped.
        w("  Flagged (D4/D7 — never silently dropped):")
        typo = ", ".join(rec.flagged_typo) or "none"
        unassigned = ", ".join(rec.flagged_unassigned) or "none"
        w(self.style.WARNING(f"    ! Typo rooms (no building prefix): {typo}"))
        w(self.style.WARNING(f"    ! Unassigned rooms (P/U/unknown): {unassigned}"))
        emailless = rec.emailless_instructor_keys
        w(self.style.WARNING(
            f"    ! Email-less instructors: {len(emailless)} "
            f"(cannot authenticate via Entra until an email is supplied)"))
        for k in emailless:
            w(self.style.WARNING(f"        - {k}"))

        # A single loud line whenever the identity fails to balance.
        if not balanced:
            w(self.style.ERROR(
                f"  WARNING: reconciliation identity does NOT balance "
                f"({bucket_sum} != {rec.total_rows}) — a row was lost or "
                f"double-counted."))

        # Real run: show live DB counts next to the reconciliation targets so a
        # human can eyeball parity (same report shape as --dry-run otherwise).
        if not o["dry_run"] and term is not None:
            live_sched = Schedule.objects.filter(term=term).count()
            live_rooms = Room.objects.count()
            live_faculty = User.objects.filter(role=Role.FACULTY).count()
            w("  Live DB counts (eyeball parity vs. targets above):")
            w(f"    Schedules (this term) : {live_sched}")
            w(f"    Rooms                 : {live_rooms}")
            w(f"    Faculty               : {live_faculty}")

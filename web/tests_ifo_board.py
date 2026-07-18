"""IFO room-board tests (IFO-07 + IFO-11, merged surface).

The board replaced the old session-list "Live today". Its one piece of real
logic is _room_tile: deriving a room's live state from today's sessions relative
to `now`. These tests lock that derivation, because every colour on the board and
every "needs attention" count hangs off it.

  - RoomTileStateTests: each of the six states from the condition that produces
    it, including the two that are easy to get wrong -- ONLINE (the room is free
    because the class shifted, D-05/MOD-01) and the past-grace no-show (the board
    must call it Absent BEFORE the sweep job stamps the row, or IFO sees a lie
    for up to a sweep interval).
  - RoomBoardScopeTests: scope=live hides idle rooms and counts them as hidden;
    scope=all keeps them. Problem states sort to the front of their group.
  - IfoBoardViewTests: the gate, the merged-nav redirect, and the slide-over.

ASCII-only.
"""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from scheduling.models import (AcademicTerm, Modality, Schedule, ScheduleStatus,
                               Session, SessionStatus)
from web.ifo import _room_board, _room_tile, _room_timetable

GRACE = timedelta(minutes=15)


def _aware(d, hh, mm):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hh, mm))


class _BoardBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name="T", start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=30), is_active=True)
        self.building = Building.objects.create(name="Academic", code="ACAD")
        self.floor = Floor.objects.create(building=self.building, number=3)
        self.faculty = User.objects.create(
            username="fac_board", email="fac_board@mcm.edu.ph", role=Role.FACULTY,
            last_name="Santos", is_active=True)
        self._room_n = 0

    def _room(self):
        self._room_n += 1
        n = self._room_n
        return Room.objects.create(
            floor=self.floor, code=f"R30{n}", qr_token=f"tok{n}", manual_code=f"MC{n:04d}")

    def _session(self, room, start=(10, 0), end=(11, 0), status=SessionStatus.SCHEDULED,
                 modality=Modality.F2F, declared=""):
        return self._session_at(
            room, _aware(self.today, *start), _aware(self.today, *end),
            status=status, modality=modality, declared=declared)

    def _live_session(self, room, **kwargs):
        """A session whose window spans the real `now`.

        View-level tests go through the view, which reads timezone.now() -- so a
        fixed 10:00 AM window only lands "in session" if the suite happens to run
        mid-morning. Anchoring to now keeps these green at any hour.
        """
        now = timezone.now()
        return self._session_at(
            room, now - timedelta(minutes=10), now + timedelta(minutes=50), **kwargs)

    def _session_at(self, room, start, end, status=SessionStatus.SCHEDULED,
                    modality=Modality.F2F, declared=""):
        local_start, local_end = timezone.localtime(start), timezone.localtime(end)
        schedule = Schedule.objects.create(
            term=self.term, course_code="IT301", section="A", faculty=self.faculty,
            room=room, day_of_week=local_start.weekday(),
            start_time=local_start.time(), end_time=local_end.time(), modality=modality)
        return Session.objects.create(
            schedule=schedule, faculty=self.faculty, room=room,
            date=local_start.date(), scheduled_start=start, scheduled_end=end,
            status=status, declared_modality=declared)


class RoomTileStateTests(_BoardBase):
    """The six states, each from the condition that produces it."""

    def test_active_session_is_in_session(self):
        room = self._room()
        s = self._session(room, status=SessionStatus.ACTIVE)
        tile = _room_tile(room, [s], _aware(self.today, 10, 30), GRACE)
        self.assertEqual(tile["state"], "in_session")

    def test_scheduled_within_grace_is_starting_not_absent(self):
        """Inside the grace window a no-check-in is normal. Calling it Absent here
        would make the board cry wolf on every class that starts a minute late."""
        room = self._room()
        s = self._session(room, status=SessionStatus.SCHEDULED)
        tile = _room_tile(room, [s], _aware(self.today, 10, 10), GRACE)
        self.assertEqual(tile["state"], "starting")

    def test_scheduled_past_grace_is_absent_before_the_sweep_job(self):
        """The row is still SCHEDULED (the sweep has not run), but past grace with
        nobody checked in IS a no-show and the board must say so immediately."""
        room = self._room()
        s = self._session(room, status=SessionStatus.SCHEDULED)
        tile = _room_tile(room, [s], _aware(self.today, 10, 20), GRACE)
        self.assertEqual(tile["state"], "absent")

    def test_absent_status_is_absent(self):
        room = self._room()
        s = self._session(room, status=SessionStatus.ABSENT)
        tile = _room_tile(room, [s], _aware(self.today, 10, 30), GRACE)
        self.assertEqual(tile["state"], "absent")

    def test_declared_online_frees_the_room(self):
        """A modality shift to Online means the room is legitimately empty. Without
        a distinct state this reads as an unexplained empty booked room."""
        room = self._room()
        s = self._session(room, status=SessionStatus.SCHEDULED, declared=Modality.ONLINE)
        tile = _room_tile(room, [s], _aware(self.today, 10, 30), GRACE)
        self.assertEqual(tile["state"], "online")

    def test_natively_online_schedule_is_online(self):
        room = self._room()
        s = self._session(room, status=SessionStatus.SCHEDULED, modality=Modality.ONLINE)
        tile = _room_tile(room, [s], _aware(self.today, 10, 30), GRACE)
        self.assertEqual(tile["state"], "online")

    def test_online_wins_over_past_grace(self):
        """An online class must never be reported as a no-show against its room."""
        room = self._room()
        s = self._session(room, status=SessionStatus.SCHEDULED, declared=Modality.ONLINE)
        tile = _room_tile(room, [s], _aware(self.today, 10, 45), GRACE)
        self.assertEqual(tile["state"], "online")

    def test_completed_inside_window_frees_the_room(self):
        room = self._room()
        s = self._session(room, status=SessionStatus.COMPLETED)
        tile = _room_tile(room, [s], _aware(self.today, 10, 45), GRACE)
        self.assertEqual(tile["state"], "free")

    def test_between_classes_is_free_and_points_at_the_next(self):
        room = self._room()
        early = self._session(room, start=(8, 0), end=(9, 0), status=SessionStatus.COMPLETED)
        later = self._session(room, start=(13, 0), end=(14, 0))
        tile = _room_tile(room, [early, later], _aware(self.today, 10, 0), GRACE)
        self.assertEqual(tile["state"], "free")
        self.assertEqual(tile["next"], later)

    def test_no_sessions_today_is_idle(self):
        room = self._room()
        tile = _room_tile(room, [], _aware(self.today, 10, 0), GRACE)
        self.assertEqual(tile["state"], "idle")
        self.assertIsNone(tile["next"])


class RoomBoardScopeTests(_BoardBase):
    """scope=live is the landing view; idle rooms are inventory, not news."""

    def test_live_scope_hides_idle_rooms_and_counts_them(self):
        busy = self._room()
        self._live_session(busy, status=SessionStatus.ACTIVE)
        self._room()  # idle

        board = _room_board(scope="live")
        codes = [t["room"].code for g in board["groups"] for t in g["tiles"]]
        self.assertEqual(codes, [busy.code])
        self.assertEqual(board["totals"]["hidden"], 1)

    def test_all_scope_keeps_idle_rooms(self):
        busy = self._room()
        self._live_session(busy, status=SessionStatus.ACTIVE)
        idle = self._room()

        board = _room_board(scope="all")
        codes = {t["room"].code for g in board["groups"] for t in g["tiles"]}
        self.assertEqual(codes, {busy.code, idle.code})
        self.assertEqual(board["totals"]["hidden"], 0)

    def test_problem_rooms_sort_to_the_front_of_their_group(self):
        """Problems must never hide below the fold behind a wall of free rooms."""
        ok = self._room()
        self._live_session(ok, status=SessionStatus.ACTIVE)
        bad = self._room()
        self._live_session(bad, status=SessionStatus.ABSENT)

        board = _room_board(scope="live")
        tiles = board["groups"][0]["tiles"]
        self.assertEqual(tiles[0]["room"].code, bad.code)
        self.assertEqual(board["totals"]["problems"], 1)
        self.assertEqual(board["groups"][0]["problems"], 1)


class IfoBoardViewTests(_BoardBase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_board", email="ifo_board@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)

    def test_board_requires_ifo(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(reverse("ifo_rooms")).status_code, 403)

    def test_ifo_gets_the_board(self):
        self.client.force_login(self.ifo)
        room = self._room()
        self._live_session(room, status=SessionStatus.ACTIVE)
        resp = self.client.get(reverse("ifo_rooms"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, room.code)
        self.assertContains(resp, "In session")

    def test_live_url_redirects_to_the_merged_board(self):
        """/ifo/live is gone as a surface; bookmarks and the cached PWA shell
        must not 404 (D-01)."""
        self.client.force_login(self.ifo)
        resp = self.client.get("/ifo/live")
        self.assertEqual(resp.status_code, 301)
        self.assertEqual(resp["Location"], reverse("ifo_rooms"))

    def test_room_panel_reports_who_is_in_the_room(self):
        self.client.force_login(self.ifo)
        room = self._room()
        self._live_session(room, status=SessionStatus.ACTIVE)
        resp = self.client.get(reverse("ifo_room_panel", args=[room.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Right now")
        self.assertContains(resp, self.faculty.last_name)

    def test_room_panel_names_the_online_shift(self):
        """The panel must explain WHY a booked room is empty."""
        self.client.force_login(self.ifo)
        room = self._room()
        self._live_session(room, status=SessionStatus.SCHEDULED, declared=Modality.ONLINE)
        resp = self.client.get(reverse("ifo_room_panel", args=[room.code]))
        self.assertContains(resp, "Class is online")
        self.assertContains(resp, "meeting online")


class RoomTimetableTests(_BoardBase):
    """The room week as a day-by-time grid (IFO-11), modelled on MMCM's printed
    schedule form. A flat list says what is booked; the grid says when the room
    is FREE, which is the facilities question."""

    def _sched(self, room, day, start, end, course="IT301", section="A"):
        return Schedule.objects.create(
            term=self.term, course_code=course, section=section,
            faculty=self.faculty, room=room, day_of_week=day,
            start_time=start, end_time=end, modality=Modality.F2F,
            status=ScheduleStatus.ACTIVE)

    def test_rows_are_the_campus_ladder_not_just_this_rooms_times(self):
        """Every room prints on the same grid, so two printouts line up and a
        free slot is a visible empty cell rather than a missing row."""
        mine, other = self._room(), self._room()
        self._sched(mine, 0, "10:00", "11:00")
        self._sched(other, 1, "14:00", "15:00")     # only the OTHER room uses this

        tt = _room_timetable(mine, self.term)
        times = [r["time"].strftime("%H:%M") for r in tt["rows"]]
        self.assertEqual(times, ["10:00", "14:00"])

    def test_a_class_fills_every_block_it_covers(self):
        """A double-length class fills both rows, as it does on the paper form."""
        room = self._room()
        self._sched(room, 0, "10:00", "13:00", course="LONG")
        self._sched(room, 1, "11:30", "12:30", course="MID")   # creates a 11:30 rung

        tt = _room_timetable(room, self.term)
        by_time = {r["time"].strftime("%H:%M"): r["cells"] for r in tt["rows"]}
        self.assertEqual(by_time["10:00"][0].course_code, "LONG")
        self.assertEqual(by_time["11:30"][0].course_code, "LONG")   # still running

    def test_a_slot_at_the_end_boundary_is_free(self):
        """Half-open windows: a class ending at 11:00 does not occupy 11:00."""
        room = self._room()
        self._sched(room, 0, "10:00", "11:00")
        self._sched(room, 1, "11:00", "12:00", course="NEXT")

        tt = _room_timetable(room, self.term)
        by_time = {r["time"].strftime("%H:%M"): r["cells"] for r in tt["rows"]}
        self.assertIsNone(by_time["11:00"][0])      # Monday is free at 11:00

    def test_all_seven_days_are_columns(self):
        room = self._room()
        self._sched(room, 0, "10:00", "11:00")
        tt = _room_timetable(room, self.term)
        self.assertEqual(len(tt["days"]), 7)
        self.assertEqual(len(tt["rows"][0]["cells"]), 7)

    def test_free_slots_are_none_and_counted(self):
        room = self._room()
        self._sched(room, 0, "10:00", "11:00")
        tt = _room_timetable(room, self.term)
        self.assertEqual(tt["used"], 1)
        self.assertEqual(tt["capacity"], 7)          # 1 rung x 7 days
        self.assertEqual(sum(1 for c in tt["rows"][0]["cells"] if c is None), 6)

    def test_no_active_term_yields_no_timetable(self):
        AcademicTerm.objects.update(is_active=False)
        self.assertIsNone(_room_timetable(self._room(), None))

    def test_page_renders_the_grid_and_a_print_masthead(self):
        User = get_user_model()
        ifo = User.objects.create(
            username="ifo_tt", email="ifo_tt@mcm.edu.ph", role=Role.IFO_ADMIN)
        self.client.force_login(ifo)
        room = self._room()
        self._sched(room, 0, "10:00", "11:00")
        resp = self.client.get(reverse("ifo_room_detail", args=[room.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="tt"')
        self.assertContains(resp, "pr-head")
        self.assertContains(resp, "Room schedule")

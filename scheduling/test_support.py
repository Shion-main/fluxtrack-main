"""Reusable Phase-4 test fixture builder (make_shift_fixture).

This is a plain helper, NOT a TestCase, so Django's test runner never executes
it as a test. Later Phase-4 plans (ops/availability, scheduling/services,
materialize, web) import make_shift_fixture() to seed the minimal object graph a
modality-shift request needs: a routed Dean + faculty in one Department, two
rooms in one building, an active term, an in-window F2F session, an Online
session, and a competing occupant for availability conflict cases.

ASCII-only by convention (Windows cp1252).
"""
from datetime import date, datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import Booking
from scheduling.models import (
    AcademicTerm,
    CheckinMethod,
    Modality,
    Schedule,
    Session,
    SessionStatus,
)
from verification.models import CheckerValidation, ValidationAction

MANILA = ZoneInfo("Asia/Manila")

# A concrete in-window Monday (day_of_week=0) used for the materialized sessions.
IN_WINDOW_DATE = date(2026, 7, 6)


def _aware(d, t):
    """Build an Asia/Manila-aware datetime from a date + time."""
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=MANILA)


def make_shift_fixture(prefix="msf"):
    """Seed and return the minimal Phase-4 object graph.

    Every unique column (username, email, room code, qr_token, manual_code,
    building/department code) is namespaced by ``prefix`` so two calls inside one
    test do not collide on a UNIQUE constraint.

    Returns a SimpleNamespace keyed by role:
        dept, dean, faculty, building, room_a, room_b, term,
        f2f_schedule, session, online_schedule, online_session, competitor
    """
    User = get_user_model()

    dept = Department.objects.create(name=f"{prefix} Department", code=f"{prefix}-DEP")

    dean = User.objects.create(
        username=f"{prefix}_dean", email=f"{prefix}_dean@mcm.edu.ph",
        role=Role.DEAN, department=dept, is_active=True,
    )
    faculty = User.objects.create(
        username=f"{prefix}_fac", email=f"{prefix}_fac@mcm.edu.ph",
        role=Role.FACULTY, department=dept, is_active=True,
    )
    # A second faculty owns the competing occupant so the room-A conflict is not a
    # faculty self-double-book (D-17).
    competitor_fac = User.objects.create(
        username=f"{prefix}_cfac", email=f"{prefix}_cfac@mcm.edu.ph",
        role=Role.FACULTY, department=dept, is_active=True,
    )

    building = Building.objects.create(name=f"{prefix} Hall", code=f"{prefix}-BLD")
    floor_1 = Floor.objects.create(building=building, number=1)
    floor_2 = Floor.objects.create(building=building, number=2)
    room_a = Room.objects.create(
        floor=floor_1, code=f"{prefix}-A", capacity=40,
        qr_token=f"{prefix}-qr-a", manual_code=f"{prefix[:2]}A001"[:6],
    )
    room_b = Room.objects.create(
        floor=floor_2, code=f"{prefix}-B", capacity=40,
        qr_token=f"{prefix}-qr-b", manual_code=f"{prefix[:2]}B002"[:6],
    )

    term = AcademicTerm.objects.create(
        name=f"{prefix} Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), is_active=True,
    )

    # F2F schedule in room A: a Monday 08:00-09:30 slot with one in-window session.
    f2f_start = time(8, 0)
    f2f_end = time(9, 30)
    f2f_schedule = Schedule.objects.create(
        term=term, course_code=f"{prefix}101", section="A",
        faculty=faculty, room=room_a, day_of_week=0,
        start_time=f2f_start, end_time=f2f_end, modality=Modality.F2F,
    )
    session = Session.objects.create(
        schedule=f2f_schedule, faculty=faculty, room=room_a, date=IN_WINDOW_DATE,
        scheduled_start=_aware(IN_WINDOW_DATE, f2f_start),
        scheduled_end=_aware(IN_WINDOW_DATE, f2f_end),
        status=SessionStatus.SCHEDULED,
    )

    # Online schedule in room B (born-released / online cases).
    online_start = time(10, 0)
    online_end = time(11, 30)
    online_schedule = Schedule.objects.create(
        term=term, course_code=f"{prefix}201", section="A",
        faculty=faculty, room=room_b, day_of_week=0,
        start_time=online_start, end_time=online_end, modality=Modality.ONLINE,
    )
    online_session = Session.objects.create(
        schedule=online_schedule, faculty=faculty, room=room_b, date=IN_WINDOW_DATE,
        scheduled_start=_aware(IN_WINDOW_DATE, online_start),
        scheduled_end=_aware(IN_WINDOW_DATE, online_end),
        status=SessionStatus.SCHEDULED, declared_modality=Modality.ONLINE,
    )

    # Competing occupant: a second F2F session holding room A at an overlapping
    # slot, usable by availability conflict tests (D-08).
    competitor_schedule = Schedule.objects.create(
        term=term, course_code=f"{prefix}301", section="A",
        faculty=competitor_fac, room=room_a, day_of_week=0,
        start_time=f2f_start, end_time=f2f_end, modality=Modality.F2F,
    )
    competitor = Session.objects.create(
        schedule=competitor_schedule, faculty=competitor_fac, room=room_a,
        date=IN_WINDOW_DATE,
        scheduled_start=_aware(IN_WINDOW_DATE, f2f_start),
        scheduled_end=_aware(IN_WINDOW_DATE, f2f_end),
        status=SessionStatus.SCHEDULED,
    )

    return SimpleNamespace(
        dept=dept,
        dean=dean,
        faculty=faculty,
        competitor_faculty=competitor_fac,
        building=building,
        room_a=room_a,
        room_b=room_b,
        term=term,
        f2f_schedule=f2f_schedule,
        session=session,
        online_schedule=online_schedule,
        online_session=online_session,
        competitor=competitor,
    )


def make_merge_fixture(prefix="mmf"):
    """Seed and return the canonical GARAY co-scheduled ("merged sections") graph.

    Mirrors make_shift_fixture's ``_aware`` + prefix-namespacing idiom (Phase
    04.2, D-01/D-02). ASCII-only. Every unique column is namespaced by ``prefix``
    so two calls in one test never collide on a UNIQUE constraint.

    Object graph (one cdgaray-shaped faculty owns them all):
      - F2F merged pair at 15:45 (Monday): ``anchor`` = MMA116 section A301 in
        room A408-A, ``sibling`` = MMA116 section A302 in room A408-B. Same
        faculty + exact start + SAME course -> they merge (D-01 course arm).
      - ``control``: same faculty + same 15:45 start but a DIFFERENT room AND a
        DIFFERENT course, so it is NOT a merge sibling (negative case).
      - Online merged pair at 10:00 sharing course_code ONL200 in two distinct
        V-rooms (modality online): ``online_anchor`` + ``online_sibling``, for
        the propagate_merged_absent (online D-07) path. A separate start keeps
        the online group independent of the F2F anchor's candidate set.

    Also returns ``make_extra_siblings(count)`` -> list: seeds ``count`` more
    SCHEDULED MMA116 siblings sharing the anchor's faculty + exact start (each in
    its own room/section) for the HY010 batch test.

    Returns a SimpleNamespace: dept, faculty, building, term, anchor, sibling,
    control, online_anchor, online_sibling, make_extra_siblings.
    """
    User = get_user_model()

    dept = Department.objects.create(name=f"{prefix} Department", code=f"{prefix}-DEP")
    faculty = User.objects.create(
        username=f"{prefix}_cdgaray", email=f"{prefix}_cdgaray@mcm.edu.ph",
        role=Role.FACULTY, department=dept, is_active=True,
    )
    building = Building.objects.create(name=f"{prefix} Hall", code=f"{prefix}-BLD")
    floor = Floor.objects.create(building=building, number=4)
    term = AcademicTerm.objects.create(
        name=f"{prefix} Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), is_active=True,
    )

    f2f_start_t, f2f_end_t = time(15, 45), time(17, 15)
    onl_start_t, onl_end_t = time(10, 0), time(11, 30)
    f2f_start = _aware(IN_WINDOW_DATE, f2f_start_t)
    f2f_end = _aware(IN_WINDOW_DATE, f2f_end_t)
    onl_start = _aware(IN_WINDOW_DATE, onl_start_t)
    onl_end = _aware(IN_WINDOW_DATE, onl_end_t)

    counter = {"n": 0}

    def _room(tag):
        counter["n"] += 1
        return Room.objects.create(
            floor=floor, code=f"{prefix}-{tag}", capacity=40,
            qr_token=f"{prefix}-qr-{tag}",
            manual_code=f"{prefix[:2].upper()}{counter['n']:03d}"[:6],
        )

    def _schedule(course, section, room, start_t, end_t, modality):
        return Schedule.objects.create(
            term=term, course_code=course, section=section, faculty=faculty,
            room=room, day_of_week=0, start_time=start_t, end_time=end_t,
            modality=modality,
        )

    def _session(schedule, room, start, end, declared=""):
        return Session.objects.create(
            schedule=schedule, faculty=faculty, room=room, date=IN_WINDOW_DATE,
            scheduled_start=start, scheduled_end=end,
            status=SessionStatus.SCHEDULED, declared_modality=declared,
        )

    # F2F merged pair (course arm): MMA116 in two different rooms, same start.
    room_a = _room("A408-A")
    room_b = _room("A408-B")
    anchor_sched = _schedule("MMA116", "A301", room_a, f2f_start_t, f2f_end_t, Modality.F2F)
    sibling_sched = _schedule("MMA116", "A302", room_b, f2f_start_t, f2f_end_t, Modality.F2F)
    anchor = _session(anchor_sched, room_a, f2f_start, f2f_end)
    sibling = _session(sibling_sched, room_b, f2f_start, f2f_end)

    # Control: same faculty + same start, DIFFERENT room AND DIFFERENT course.
    room_c = _room("A408-C")
    control_sched = _schedule("GEC010", "C101", room_c, f2f_start_t, f2f_end_t, Modality.F2F)
    control = _session(control_sched, room_c, f2f_start, f2f_end)

    # Online merged pair (course arm) at a distinct start, two V-rooms.
    vroom_1 = _room("V-1")
    vroom_2 = _room("V-2")
    onl_anchor_sched = _schedule("ONL200", "V01", vroom_1, onl_start_t, onl_end_t, Modality.ONLINE)
    onl_sibling_sched = _schedule("ONL200", "V02", vroom_2, onl_start_t, onl_end_t, Modality.ONLINE)
    online_anchor = _session(onl_anchor_sched, vroom_1, onl_start, onl_end, declared=Modality.ONLINE)
    online_sibling = _session(onl_sibling_sched, vroom_2, onl_start, onl_end, declared=Modality.ONLINE)

    def make_extra_siblings(count):
        created = []
        for i in range(count):
            r = _room(f"X{i}")
            sch = _schedule("MMA116", f"A31{i}", r, f2f_start_t, f2f_end_t, Modality.F2F)
            created.append(_session(sch, r, f2f_start, f2f_end))
        return created

    return SimpleNamespace(
        dept=dept,
        faculty=faculty,
        building=building,
        term=term,
        anchor=anchor,
        sibling=sibling,
        control=control,
        online_anchor=online_anchor,
        online_sibling=online_sibling,
        make_extra_siblings=make_extra_siblings,
    )


def make_reporting_fixture(prefix="rpt"):
    """Seed and return the canonical Phase-6 reporting object graph (RPT-01/04/05).

    Mirrors make_shift_fixture's ``_aware`` + prefix-namespacing idiom so two calls
    in one test never collide on a UNIQUE constraint. ASCII-only.

    Two Departments (``dept_a`` with ``faculty_a``, ``dept_b`` with ``faculty_b``)
    over ONE active term, all sessions inside the known Mon-Sun week beginning
    ``IN_WINDOW_DATE`` (2026-07-06, a Monday). ``faculty_a`` carries one session of
    every reporting-relevant shape so the aggregates are exercised end to end:

      - ``s_scheduled``  : SCHEDULED, dated the coming Wednesday (future vs an
        ``as_of`` of the Monday) -> counts in ``scheduled`` but not ``held``.
      - ``s_active``     : ACTIVE   -> held.
      - ``s_completed``  : COMPLETED -> held.
      - ``s_absent``     : ABSENT   -> absent (itemized), never held.
      - ``s_verified``   : ACTIVE + a ``verified`` CheckerValidation -> held AND
        checker-verified.
      - ``s_merged``     : ACTIVE + ``checkin_method=MERGED`` + NO validation ->
        held but NOT verified (merge-filled siblings stay honest, 04.2 D-09).
      - ``s_early``      : COMPLETED + ``ended_early=True`` -> held + early-end.
      - ``s_online``     : ACTIVE + ``declared_modality=ONLINE`` over an F2F
        schedule -> held, counted ONLINE in the effective-modality breakdown.

    ``faculty_a`` totals over the full week (no ``as_of``): scheduled 8, held 6,
    absent 1, verified 1, early_ends 1, attendance_pct 75.

    ``faculty_b`` carries one ACTIVE (``s_b_active``) and one ABSENT
    (``s_b_absent``) so department scoping visibly changes the result set.

    ``add_session(faculty, date, status, **kwargs)`` seeds one more session (its own
    fresh schedule/room) for boundary/edge tests.

    Returns a SimpleNamespace keyed by role/object/date/session.
    """
    User = get_user_model()
    counter = {"n": 0}

    def _next():
        counter["n"] += 1
        return counter["n"]

    week_start = IN_WINDOW_DATE          # 2026-07-06 (Monday)
    tue = date(2026, 7, 7)
    wed = date(2026, 7, 8)
    sun = date(2026, 7, 12)
    next_monday = date(2026, 7, 13)

    term = AcademicTerm.objects.create(
        name=f"{prefix} Term", start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31), is_active=True,
    )
    dept_a = Department.objects.create(name=f"{prefix} Dept A", code=f"{prefix}-DA")
    dept_b = Department.objects.create(name=f"{prefix} Dept B", code=f"{prefix}-DB")

    building = Building.objects.create(name=f"{prefix} Hall", code=f"{prefix}-BLD")
    floor = Floor.objects.create(building=building, number=1)

    def _room():
        n = _next()
        return Room.objects.create(
            floor=floor, code=f"{prefix}-R{n}", capacity=40,
            qr_token=f"{prefix}-qr-{n}",
            manual_code=f"{prefix[:1].upper()}{n:05d}"[:6],
        )

    room_a = _room()
    room_b = _room()

    faculty_a = User.objects.create(
        username=f"{prefix}_fa", email=f"{prefix}_fa@mcm.edu.ph",
        first_name="Ana", last_name="Alvarez",
        role=Role.FACULTY, department=dept_a, is_active=True,
    )
    faculty_b = User.objects.create(
        username=f"{prefix}_fb", email=f"{prefix}_fb@mcm.edu.ph",
        first_name="Ben", last_name="Bautista",
        role=Role.FACULTY, department=dept_b, is_active=True,
    )
    checker = User.objects.create(
        username=f"{prefix}_chk", email=f"{prefix}_chk@mcm.edu.ph",
        role=Role.CHECKER, department=dept_a, is_active=True,
    )

    teach_start, teach_end = time(8, 0), time(9, 30)

    def _mk(faculty, room, d, status, *, modality=Modality.F2F, declared="",
            ended_early=False, checkin_method=""):
        n = _next()
        sched = Schedule.objects.create(
            term=term, course_code=f"{prefix}{n:03d}", section="A",
            faculty=faculty, room=room, day_of_week=0,
            start_time=teach_start, end_time=teach_end, modality=modality,
        )
        return Session.objects.create(
            schedule=sched, faculty=faculty, room=room, date=d,
            scheduled_start=_aware(d, teach_start),
            scheduled_end=_aware(d, teach_end),
            status=status, declared_modality=declared,
            ended_early=ended_early, checkin_method=checkin_method,
        )

    # faculty_a: one session of every reporting-relevant shape.
    s_scheduled = _mk(faculty_a, room_a, wed, SessionStatus.SCHEDULED)
    s_active = _mk(faculty_a, room_a, week_start, SessionStatus.ACTIVE)
    s_completed = _mk(faculty_a, room_a, week_start, SessionStatus.COMPLETED)
    s_absent = _mk(faculty_a, room_a, tue, SessionStatus.ABSENT)
    s_verified = _mk(faculty_a, room_a, week_start, SessionStatus.ACTIVE)
    s_merged = _mk(
        faculty_a, room_a, week_start, SessionStatus.ACTIVE,
        checkin_method=CheckinMethod.MERGED,
    )
    s_early = _mk(
        faculty_a, room_a, tue, SessionStatus.COMPLETED, ended_early=True,
    )
    s_online = _mk(
        faculty_a, room_a, week_start, SessionStatus.ACTIVE,
        modality=Modality.F2F, declared=Modality.ONLINE,
    )

    # Verified session gets a real CheckerValidation; the MERGED sibling gets none.
    CheckerValidation.objects.create(
        session=s_verified, room=room_a, checker=checker,
        action=ValidationAction.VERIFIED,
    )

    # faculty_b (dept_b): one held + one absent, to prove department scoping.
    s_b_active = _mk(faculty_b, room_b, week_start, SessionStatus.ACTIVE)
    s_b_absent = _mk(faculty_b, room_b, tue, SessionStatus.ABSENT)

    def add_session(faculty, d, status, **kwargs):
        """Seed one more session (fresh schedule/room) for boundary/edge tests."""
        room = room_a if faculty.department_id == dept_a.id else room_b
        return _mk(faculty, room, d, status, **kwargs)

    return SimpleNamespace(
        term=term,
        dept_a=dept_a,
        dept_b=dept_b,
        faculty_a=faculty_a,
        faculty_b=faculty_b,
        checker=checker,
        building=building,
        room_a=room_a,
        room_b=room_b,
        week_start=week_start,
        tue=tue,
        wed=wed,
        sun=sun,
        next_monday=next_monday,
        s_scheduled=s_scheduled,
        s_active=s_active,
        s_completed=s_completed,
        s_absent=s_absent,
        s_verified=s_verified,
        s_merged=s_merged,
        s_early=s_early,
        s_online=s_online,
        s_b_active=s_b_active,
        s_b_absent=s_b_absent,
        add_session=add_session,
    )

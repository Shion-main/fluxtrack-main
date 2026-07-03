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
    Modality,
    Schedule,
    Session,
    SessionStatus,
)

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

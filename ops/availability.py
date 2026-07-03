"""Pre-booking room-availability primitive (MOD-04).

This is the ONE canonical answer to "is room R free for [start, end)?" that the
faculty picker (04-07), the Dean approval apply (04-05), and the born-assigned
materialize hook (04-06) all call. Defining "free" in a single place is the whole
point: overlap + request-aware semantics must never diverge between the surface
that OFFERS a room and the path that COMMITS it.

Semantics (all half-open, D-08):
  - Overlap is O.start < end AND start < O.end. Adjacent slots (O.end == start)
    do NOT collide.
  - A same-room occupant is a scheduling.Session that is SCHEDULED/ACTIVE, has
    room_released_at IS NULL, and whose EFFECTIVE modality (declared_modality or
    schedule.modality) is not Online. Online / released / absent / completed
    sessions hold no physical room. The effective-modality read is IDENTICAL to
    verification/services.py so availability can never disagree with the resolver
    / sweep.
  - An active ops.Booking overlapping the interval also occupies the room.
  - An approved ->F2F/Blended ModalityShiftItem reservation occupies the room for
    its in-window slot even before its Session materializes (D-18, request-aware):
    a reserved room cannot be taken before the session exists. A ->Online approval
    frees rooms and so reserves nothing.
  - exclude_session_id removes the session being moved from the occupant set so it
    never blocks itself.

MSSQL guard (T-04-HY010): every candidate queryset is list()-materialized before
evaluation. pyodbc keeps only one active result set per connection (MARS off), so
a streaming cursor kept open across a follow-up query raises HY010; mirror
scheduling/jobs.py and materialize candidates up front.
"""
from datetime import datetime

from django.utils import timezone

from campus.models import Room
from ops.models import Booking
from scheduling.models import (
    Modality,
    ModalityShiftItem,
    ModalityShiftStatus,
    Session,
    SessionStatus,
)

_OCCUPYING_STATUSES = (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)


def _effective_modality(session):
    """declared_modality overrides schedule.modality (mirror verification/services.py)."""
    return session.declared_modality or session.schedule.modality


def _local_date(start):
    """Calendar date of an aware datetime in the project timezone (Asia/Manila)."""
    return timezone.localtime(start).date()


def _session_occupants(room, start, end, exclude_session_id):
    """Materialized SCHEDULED/ACTIVE, room-holding sessions overlapping [start,end)."""
    qs = (
        Session.objects.filter(
            room=room,
            status__in=_OCCUPYING_STATUSES,
            room_released_at__isnull=True,
            scheduled_start__lt=end,      # half-open overlap: O.start < end ...
            scheduled_end__gt=start,      # ... AND start < O.end
        )
        .select_related("schedule")
    )
    if exclude_session_id is not None:
        qs = qs.exclude(pk=exclude_session_id)
    return list(qs)  # HY010 guard: close the SELECT before any follow-up query


def _reservation_occupies(room, start, end):
    """D-18: an APPROVED non-Online ModalityShiftItem reserves ``room`` for its
    in-window slot even before the Session materializes. True when such a
    reservation overlaps [start, end).

    The reserved slot is the item's time-move slot (new_start_time/new_end_time)
    when set, else the schedule's own start/end, combined with the queried date
    via timezone.make_aware. The item's schedule.day_of_week must match the queried
    date's weekday, and the request window must contain that date.
    """
    local_date = _local_date(start)
    items = list(
        ModalityShiftItem.objects.filter(
            assigned_room=room,
            request__status=ModalityShiftStatus.APPROVED,
            request__window_start__lte=local_date,
            request__window_end__gte=local_date,
            schedule__day_of_week=local_date.weekday(),
        )
        .exclude(request__target_modality=Modality.ONLINE)
        .select_related("request", "schedule")
    )  # HY010 guard: materialize before the overlap loop
    for item in items:
        st = item.new_start_time or item.schedule.start_time
        et = item.new_end_time or item.schedule.end_time
        r_start = timezone.make_aware(datetime.combine(local_date, st))
        r_end = timezone.make_aware(datetime.combine(local_date, et))
        if r_start < end and start < r_end:  # half-open overlap
            return True
    return False


def room_is_free(room, start, end, *, exclude_session_id=None):
    """True iff nothing occupies ``room`` in the half-open interval [start, end).

    Occupied by any of: a SCHEDULED/ACTIVE non-Online, un-released same-room
    Session (excluding ``exclude_session_id``); an active Booking; or an approved
    ->F2F/Blended reservation (D-18). All candidate querysets are materialized
    before evaluation (HY010 guard).
    """
    for s in _session_occupants(room, start, end, exclude_session_id):
        if _effective_modality(s) != Modality.ONLINE:
            return False

    bookings = list(
        Booking.objects.filter(
            room=room,
            status="active",
            start_datetime__lt=end,
            end_datetime__gt=start,
        )
    )
    if bookings:
        return False

    if _reservation_occupies(room, start, end):
        return False

    return True


def faculty_has_conflict(faculty, start, end, *, exclude_session_id=None):
    """True when ``faculty`` already has another SCHEDULED/ACTIVE Session overlapping
    [start, end) (excluding ``exclude_session_id``) — a time-move must never
    double-book the requesting faculty (D-17)."""
    qs = Session.objects.filter(
        faculty=faculty,
        status__in=_OCCUPYING_STATUSES,
        scheduled_start__lt=end,
        scheduled_end__gt=start,
    )
    if exclude_session_id is not None:
        qs = qs.exclude(pk=exclude_session_id)
    return bool(list(qs))  # HY010 guard: materialize before returning


def free_rooms_in_building(building, start, end, *, exclude_session_id=None, prefer_room=None):
    """The free rooms in ``building`` for [start, end), deterministically ordered.

    Candidates are ordered by ``code``; ``prefer_room`` (when free) is floated to
    the front so the picker/approval can offer the original room first (D-06/D-15).
    """
    candidates = list(Room.objects.filter(floor__building=building).order_by("code"))
    free = [
        r for r in candidates
        if room_is_free(r, start, end, exclude_session_id=exclude_session_id)
    ]
    if prefer_room is not None and any(r.pk == prefer_room.pk for r in free):
        free = (
            [r for r in free if r.pk == prefer_room.pk]
            + [r for r in free if r.pk != prefer_room.pk]
        )
    return free

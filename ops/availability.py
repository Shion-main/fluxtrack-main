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
  - exclude_session_id removes the session being moved from the occupant set so it
    never blocks itself.

MSSQL guard (T-04-HY010): every candidate queryset is list()-materialized before
evaluation. pyodbc keeps only one active result set per connection (MARS off), so
a streaming cursor kept open across a follow-up query raises HY010; mirror
scheduling/jobs.py and materialize candidates up front.
"""
from campus.models import Room
from ops.models import Booking
from scheduling.models import Modality, Session, SessionStatus

_OCCUPYING_STATUSES = (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)


def _effective_modality(session):
    """declared_modality overrides schedule.modality (mirror verification/services.py)."""
    return session.declared_modality or session.schedule.modality


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


def room_is_free(room, start, end, *, exclude_session_id=None):
    """True iff nothing occupies ``room`` in the half-open interval [start, end).

    Occupied by either a SCHEDULED/ACTIVE non-Online, un-released same-room Session
    (excluding ``exclude_session_id``) or an active Booking. All candidate
    querysets are materialized before evaluation (HY010 guard).
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

    return True


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

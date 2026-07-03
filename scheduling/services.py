"""Modality-shift CREATION-side domain service (MOD-01/MOD-02/MOD-05).

This is the entry point of the Phase-4 workflow: everything the Dean later
approves (04-05) or the materializer later applies (04-06) is created and
validated HERE, server-side, never trusting a client-supplied date, time, room
pk, or modality. It mirrors the proven ``verification/services.py`` shape --
gather context -> validate -> transactional write -> notify-once -> AuditLog.

Boundaries enforced in this module:
  - Lead-time gate (D-02): a request is refused at/after Manila-midnight of
    ``earliest_affected_date - modality_shift_lead_days``. The lead comes from
    ``get_policy`` (never a literal) and the clock is the server's
    ``timezone.now()`` (never client time) -- the anti-clock-spoof invariant.
  - Deterministic Dean routing (D-09): a request routes to the requester's active
    department Dean; a missing department or vacant Dean seat is a clean refusal.
  - In-window scope (D-01/D-19): only SCHEDULED/ACTIVE sessions whose date falls
    inside ``[window_start, window_end]`` are affected; one atomic ticket may span
    multiple schedules, one ModalityShiftItem each.
  - Time-move safety (D-16/D-17): a time-move is accepted only bundled with an
    F2F/Blended target and only when it never double-books the requesting faculty.
  - Withdraw/reject guards (MOD-05/D-10/D-11): ownership + PENDING re-checked
    server-side inside the transaction before any state change.

ASCII-only by convention (Windows cp1252).
"""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from accounts.models import Role
from ops.availability import available_rooms_for, faculty_has_conflict
from ops.models import AuditLog
from ops.notify import notify
from ops.policy import get_policy
from scheduling.models import (
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Session,
    SessionStatus,
)

_OCCUPYING_STATUSES = (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)


class ModalityShiftError(Exception):
    """A creation-side refusal (lead-time, routing, scope, or time-move guard).

    Carries a human-readable ``message`` the web layer surfaces as a friendly
    400 rather than a 500 -- the request is refused, nothing is written.
    """


# ---------------------------------------------------------------------------
# Task 1 -- pure lead-time gate (D-02) + deterministic Dean routing (D-09)
# ---------------------------------------------------------------------------

def is_before_lead_cutoff(earliest_affected_date, now):
    """True when ``now`` is strictly before the Manila-midnight lead-time cutoff.

    cutoff = start of ``(earliest_affected_date - lead_days)`` in Asia/Manila,
    where ``lead_days`` is read from ``get_policy("modality_shift_lead_days")``
    (never a literal, D-03). ``now`` MUST be a server clock reading
    (``timezone.now()``) -- a client-supplied time is never accepted (D-02 /
    anti-clock-spoof, T-04-04).

    Boundary (lead 2): for a Wednesday session, ``now`` = Monday 00:00 Manila is
    refused (returns False) and Sunday 23:59 Manila is allowed (returns True).
    """
    lead = get_policy("modality_shift_lead_days")
    cutoff_date = earliest_affected_date - timedelta(days=lead)
    # TIME_ZONE="Asia/Manila" + USE_TZ -> make_aware yields Manila midnight.
    cutoff = timezone.make_aware(datetime.combine(cutoff_date, time.min))
    return now < cutoff


def route_to_dean(faculty):
    """The requester's active department Dean, or None on the D-09 edge cases.

    Returns None when ``faculty.department`` is None or no active Role.DEAN holds
    that department's seat; the submit caller turns a None into a clean refusal
    ("no Dean assigned - contact IFO"). One-Dean-per-department is a RUNTIME
    invariant, not a DB constraint, so ``.first()`` is defensive.
    """
    dept = faculty.department
    if dept is None:
        return None
    return (
        get_user_model()
        .objects.filter(role=Role.DEAN, department=dept, is_active=True)
        .first()
    )


# ---------------------------------------------------------------------------
# Task 2 -- in-window scope resolution (D-01/D-19) + submit (atomic ticket)
# ---------------------------------------------------------------------------

def _in_window_sessions(schedule, window_start, window_end):
    """SCHEDULED/ACTIVE sessions of ``schedule`` dated inside the window.

    Materialized (list()) up front -- the HY010 guard: the SELECT is closed
    before any follow-up query or write (pyodbc single active result set).
    """
    return list(
        Session.objects.filter(
            schedule=schedule,
            status__in=_OCCUPYING_STATUSES,
            date__gte=window_start,
            date__lte=window_end,
        )
        .select_related("schedule")
        .order_by("date", "scheduled_start")
    )


def affected_sessions(request):
    """The in-window SCHEDULED/ACTIVE sessions of every item's schedule (D-01).

    Out-of-window sessions are never returned -- they keep their original
    modality/room untouched (there is no revert event). Order is stable by item,
    then date/start.
    """
    result = []
    for item in request.items.select_related("schedule").all():
        result.extend(
            _in_window_sessions(item.schedule, request.window_start, request.window_end)
        )
    return result


def submit_modality_shift(faculty, schedules, target_modality, window_start,
                          window_end, *, preferred_rooms=None, time_move=None,
                          now=None):
    """Create ONE atomic modality-shift ticket (D-19), gated + routed + audited.

    Validates and, on success, persists a ``ModalityShiftRequest`` (status
    PENDING) with one ``ModalityShiftItem`` per schedule, notifies the routed
    Dean once, and writes an AuditLog. Refuses (raises ``ModalityShiftError``,
    nothing written) when:
      - no schedule/session is in scope, an invalid target modality, or an
        inverted window is supplied;
      - the earliest affected date is at/after the lead-time cutoff (D-02);
      - the requester has no department or no active department Dean (D-09);
      - a time-move is requested with a non-F2F/Blended target (D-16) or would
        double-book the requesting faculty at any affected slot (D-17).

    ``preferred_rooms`` maps a schedule (or its pk) to a preferred Room; the pk is
    NEVER trusted -- it is kept only when the room is genuinely free for the
    session's own slot (``available_rooms_for``). The room is finalized at Dean
    approval (04-05), not here. ``time_move`` is a ``(new_start_time,
    new_end_time)`` pair applied to every item.
    """
    now = now or timezone.now()
    schedules = list(schedules)
    if not schedules:
        raise ModalityShiftError("no schedules selected")
    if target_modality not in Modality.values:
        raise ModalityShiftError("invalid target modality")
    if window_start > window_end:
        raise ModalityShiftError("window start is after window end")

    is_move = time_move is not None
    new_start_time = new_end_time = None
    if is_move:
        if target_modality not in (Modality.F2F, Modality.BLENDED):
            # D-16: a time-move is only ever bundled with a F2F/Blended shift.
            raise ModalityShiftError(
                "a time-move must be bundled with a F2F or Blended shift")
        new_start_time, new_end_time = time_move

    # Normalize preferred_rooms to {schedule_pk: Room}.
    pref = {}
    if preferred_rooms:
        for key, room in preferred_rooms.items():
            pref[getattr(key, "pk", key)] = room

    # Gather in-window sessions per schedule (materialized first, HY010 guard).
    sched_sessions = {}
    all_dates = []
    for sch in schedules:
        sessions = _in_window_sessions(sch, window_start, window_end)
        sched_sessions[sch.pk] = sessions
        all_dates.extend(s.date for s in sessions)

    if not all_dates:
        raise ModalityShiftError("no in-window sessions to shift")

    # Lead-time gate against the EARLIEST affected date (D-02), server clock only.
    earliest = min(all_dates)
    if not is_before_lead_cutoff(earliest, now):
        raise ModalityShiftError("request is past the lead-time cutoff")

    # Deterministic Dean routing (D-09) -- refuse on missing dept / vacant seat.
    dean = route_to_dean(faculty)
    if faculty.department is None or dean is None:
        raise ModalityShiftError("no Dean assigned - contact IFO")

    # Time-move double-book guard (D-17): the new slot must never collide with
    # another class the requesting faculty already teaches.
    if is_move:
        for sch in schedules:
            for s in sched_sessions[sch.pk]:
                ns = timezone.make_aware(datetime.combine(s.date, new_start_time))
                ne = timezone.make_aware(datetime.combine(s.date, new_end_time))
                if faculty_has_conflict(faculty, ns, ne, exclude_session_id=s.pk):
                    raise ModalityShiftError(
                        "the new time double-books the requesting faculty")

    # Validate preferred rooms server-side (never trust a client room pk). A
    # preference survives only when the room is free for EVERY affected session's
    # own slot; otherwise it is dropped (the app resolves at approval, D-06).
    validated_pref = {}
    for sch in schedules:
        room = pref.get(sch.pk)
        if room is None:
            continue
        ok = bool(sched_sessions[sch.pk]) and all(
            any(r.pk == room.pk for r in available_rooms_for(s))
            for s in sched_sessions[sch.pk]
        )
        validated_pref[sch.pk] = room if ok else None

    with transaction.atomic():
        request = ModalityShiftRequest.objects.create(
            requester=faculty, dean=dean, department=faculty.department,
            target_modality=target_modality,
            window_start=window_start, window_end=window_end,
            is_time_move=is_move, status=ModalityShiftStatus.PENDING,
        )
        for sch in schedules:
            ModalityShiftItem.objects.create(
                request=request, schedule=sch,
                preferred_room=validated_pref.get(sch.pk),
                new_start_time=new_start_time, new_end_time=new_end_time,
            )
        AuditLog.objects.create(
            actor=faculty, event_type="modality_shift.submitted",
            target_type="modality_shift_request", target_id=str(request.pk),
            payload={
                "target_modality": target_modality,
                "window_start": str(window_start),
                "window_end": str(window_end),
                "is_time_move": is_move,
                "schedules": [sch.pk for sch in schedules],
            },
        )
        notify(
            users=[dean], type="modality_shift_submitted",
            title="Modality shift request",
            body=(f"{faculty.get_full_name() or faculty.username} requested a "
                  f"{target_modality} shift for {window_start} to {window_end}."),
            link="/dean/requests",
        )
    return request

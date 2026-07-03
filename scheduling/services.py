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
from ops.availability import (
    available_rooms_for,
    faculty_has_conflict,
    free_rooms_in_building,
    room_is_free,
)
from ops.models import AuditLog
from ops.notify import notify
from ops.occupancy import release_room
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


# ---------------------------------------------------------------------------
# Task 3 -- withdraw + reject transitions (ownership + PENDING re-gate)
# ---------------------------------------------------------------------------

def withdraw_modality_shift(request, actor):
    """Faculty pulls a still-PENDING ticket (MOD-05/D-10). Silent -- no notify.

    Succeeds only when ``actor`` is the requester AND the CURRENT status (re-read
    from the DB inside the transaction, never an earlier snapshot -- 03-02
    re-gate) is PENDING. Flips to WITHDRAWN and writes an AuditLog. Any guard
    failure raises ``ModalityShiftError`` and leaves the state untouched. No
    Notification is written: decision notices are Dean actions (D-11).
    """
    with transaction.atomic():
        req = ModalityShiftRequest.objects.get(pk=request.pk)
        if req.requester_id != actor.pk:
            raise ModalityShiftError("only the requester may withdraw this request")
        if req.status != ModalityShiftStatus.PENDING:
            raise ModalityShiftError("only a pending request may be withdrawn")
        req.status = ModalityShiftStatus.WITHDRAWN
        req.save(update_fields=["status"])
        AuditLog.objects.create(
            actor=actor, event_type="modality_shift.withdrawn",
            target_type="modality_shift_request", target_id=str(req.pk), payload={},
        )
    return req


def reject_modality_shift(request, dean, reason):
    """The routed Dean rejects a PENDING ticket with a reason (MOD-02/D-11).

    Succeeds only when ``dean`` holds Role.DEAN AND is the request's department
    Dean AND the CURRENT status is PENDING (re-read inside the transaction).
    Sets REJECTED + ``decision_reason``/``decided_by``/``decided_at``, writes an
    AuditLog, and notifies the requester exactly once (D-11). Any guard failure
    raises ``ModalityShiftError`` and leaves the state untouched.
    """
    now = timezone.now()
    with transaction.atomic():
        req = ModalityShiftRequest.objects.get(pk=request.pk)
        if dean.role != Role.DEAN or req.department_id != dean.department_id:
            raise ModalityShiftError(
                "only the routed department Dean may reject this request")
        if req.status != ModalityShiftStatus.PENDING:
            raise ModalityShiftError("only a pending request may be rejected")
        req.status = ModalityShiftStatus.REJECTED
        req.decision_reason = reason
        req.decided_by = dean
        req.decided_at = now
        req.save(update_fields=[
            "status", "decision_reason", "decided_by", "decided_at"])
        AuditLog.objects.create(
            actor=dean, event_type="modality_shift.rejected",
            target_type="modality_shift_request", target_id=str(req.pk),
            payload={"reason": reason},
        )
        notify(
            users=[req.requester], type="modality_shift_rejected",
            title="Modality shift rejected",
            body=f"Your modality shift request was rejected: {reason}",
            link="/faculty/modality/mine",
        )
    return req


# ---------------------------------------------------------------------------
# 04-05 -- Dean approval APPLY (the decision-consequence side, MOD-03..06).
#
# apply_approval turns an approved PENDING ticket into reality inside ONE atomic
# transaction that re-gates the Dean and re-checks availability at write time
# (TOCTOU-safe, D-06). The consequence depends on target_modality:
#   - ->Online (D-04/MOD-03): each in-window session flips to declared_modality=
#     Online and its room is released via release_room() (room_released_at stamped;
#     the room FK is NEVER nulled -- RESEARCH anti-pattern). The freed room becomes
#     bookable and every effective-modality reader (resolver/sweep/round-robin)
#     sees Online with zero changes to them (the MOD-06 coupling).
#   - ->F2F/Blended (Task 2): a real room is re-resolved inside the transaction.
#   - no free room / double-booking time-move (Task 3): terminal DENY, all-or-
#     nothing rollback (D-07 REVISED).
# ---------------------------------------------------------------------------

class _NoRoomAvailable(Exception):
    """Internal sentinel raised inside the apply savepoint when a ->F2F/Blended
    resolution finds no free room, or a bundled time-move would double-book the
    faculty (D-17). It forces the savepoint to roll back ALL session/item writes so
    ``apply_approval`` can set a terminal DENIED with nothing changed (D-07
    REVISED). Carries the human-readable ``reason`` surfaced to the requester.
    """

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def resolve_shift_room(item, at_start, at_end, *, exclude_session_id=None):
    """The room to assign for ``item`` at [at_start, at_end): the original
    ``schedule.room`` when it is free, else the first free room in the same
    building (faculty preference floated first when still free), else None.

    ``None`` is the no-room signal that drives the terminal DENY (D-07 REVISED).
    Room selection is ALWAYS server-side (never a client-supplied pk): the
    availability re-check runs against CURRENT state at write time (TOCTOU, D-06).
    """
    original = item.schedule.room
    if room_is_free(original, at_start, at_end, exclude_session_id=exclude_session_id):
        return original
    building = original.floor.building
    free = free_rooms_in_building(
        building, at_start, at_end,
        exclude_session_id=exclude_session_id, prefer_room=item.preferred_room)
    return free[0] if free else None


def _apply_f2f(request, sessions, dean, now):
    """MOD-04/D-06/D-16/D-18: assign a re-resolved room to each in-window session.

    Iterates items (mapping each session back to its item for the reservation and
    the time-move slot). For each affected session: if the item carries a time-move
    (D-16) the new [start, end) is re-checked against ``faculty_has_conflict``
    (D-17) and rewritten; the room is re-resolved INSIDE the transaction via
    ``resolve_shift_room`` (TOCTOU, D-06). A ``None`` resolution or a failed
    conflict re-check raises ``_NoRoomAvailable`` (the all-or-nothing DENY, Task 3).
    The resolved room is stored on ``item.assigned_room`` as the reservation for
    future in-window sessions (D-18). Items are ``list()``-materialized (HY010).
    """
    for item in list(request.items.select_related("schedule").all()):
        item_sessions = _in_window_sessions(
            item.schedule, request.window_start, request.window_end)
        resolved_room = None
        is_move = item.new_start_time is not None and item.new_end_time is not None
        for session in item_sessions:
            if is_move:
                new_start = timezone.make_aware(
                    datetime.combine(session.date, item.new_start_time))
                new_end = timezone.make_aware(
                    datetime.combine(session.date, item.new_end_time))
                if faculty_has_conflict(
                        session.faculty, new_start, new_end,
                        exclude_session_id=session.pk):
                    raise _NoRoomAvailable(
                        "the new time double-books the requesting faculty")
                at_start, at_end = new_start, new_end
            else:
                at_start, at_end = session.scheduled_start, session.scheduled_end

            room = resolve_shift_room(
                item, at_start, at_end, exclude_session_id=session.pk)
            if room is None:
                raise _NoRoomAvailable("No room available that day.")

            session.room = room
            session.declared_modality = request.target_modality
            session.modality_changed_at = now
            session.modality_changed_by = dean
            fields = ["room", "declared_modality",
                      "modality_changed_at", "modality_changed_by"]
            if is_move:
                session.scheduled_start = at_start
                session.scheduled_end = at_end
                fields += ["scheduled_start", "scheduled_end"]
            session.save(update_fields=fields)
            resolved_room = room

        if resolved_room is not None:
            item.assigned_room = resolved_room
            item.save(update_fields=["assigned_room"])


def _apply_online(request, sessions, dean, now):
    """MOD-03/D-04: flip each in-window session to Online and release its room.

    Sets ``declared_modality=Online`` (+ ``modality_changed_at``/``_by``) so the
    resolver, sweep, and online round-robin all read the shift unchanged, then
    calls the single-source-of-truth ``release_room()`` which stamps
    ``room_released_at`` and self-audits. ``session.room`` is deliberately left set
    (the release signal is ``room_released_at``, not a null FK).
    """
    for session in sessions:
        session.declared_modality = Modality.ONLINE
        session.modality_changed_at = now
        session.modality_changed_by = dean
        session.save(update_fields=[
            "declared_modality", "modality_changed_at", "modality_changed_by"])
        release_room(session, actor=dean, now=now)


def apply_approval(request, dean, *, now=None):
    """Apply an approved modality shift atomically (MOD-03..06).

    Re-gates inside ``transaction.atomic()``: ``dean`` must hold Role.DEAN, be the
    request's department Dean, and the CURRENT status (re-read from the DB, never
    an earlier snapshot -- 03-02 re-gate) must be PENDING. The in-window affected
    sessions are ``list()``-materialized before the write loop (HY010 guard). For a
    ->Online target the ``_apply_online`` consequence runs; the request becomes
    APPROVED with ``decided_by``/``decided_at`` and an AuditLog is written.
    (->F2F/Blended, terminal DENY, and notifications land in the following tasks.)
    """
    now = now or timezone.now()
    with transaction.atomic():
        req = ModalityShiftRequest.objects.get(pk=request.pk)
        if dean.role != Role.DEAN or req.department_id != dean.department_id:
            raise ModalityShiftError(
                "only the routed department Dean may approve this request")
        if req.status != ModalityShiftStatus.PENDING:
            raise ModalityShiftError("only a pending request may be approved")

        sessions = list(affected_sessions(req))  # HY010: materialize before writes

        # Apply the consequence inside a SAVEPOINT so a no-room / double-book
        # aborts ALL session + item writes (all-or-nothing, D-07 REVISED / D-19).
        deny_reason = None
        try:
            with transaction.atomic():
                if req.target_modality == Modality.ONLINE:
                    _apply_online(req, sessions, dean, now)
                else:
                    _apply_f2f(req, sessions, dean, now)
        except _NoRoomAvailable as exc:
            deny_reason = exc.reason  # savepoint rolled back -> sessions untouched

        if deny_reason is not None:
            # D-07 REVISED: terminal DENIED (never left pending), nothing changed.
            req.status = ModalityShiftStatus.DENIED
            req.decision_reason = deny_reason
            req.decided_by = dean
            req.decided_at = now
            req.save(update_fields=[
                "status", "decision_reason", "decided_by", "decided_at"])
            AuditLog.objects.create(
                actor=dean, event_type="modality_shift.denied",
                target_type="modality_shift_request", target_id=str(req.pk),
                payload={"reason": deny_reason},
            )
            notify(
                users=[req.requester], type="modality_shift_denied",
                title="Modality shift denied",
                body=f"Your modality shift request was denied: {deny_reason}",
                link="/faculty/modality/mine",
            )
            return req

        req.status = ModalityShiftStatus.APPROVED
        req.decided_by = dean
        req.decided_at = now
        req.save(update_fields=["status", "decided_by", "decided_at"])
        AuditLog.objects.create(
            actor=dean, event_type="modality_shift.approved",
            target_type="modality_shift_request", target_id=str(req.pk),
            payload={"target_modality": req.target_modality},
        )

        # Decision -> requester; applied -> IFO informational (D-11, not a gate).
        notify(
            users=[req.requester], type="modality_shift_approved",
            title="Modality shift approved",
            body=(f"Your {req.target_modality} shift for {req.window_start} to "
                  f"{req.window_end} was approved."),
            link="/faculty/modality/mine",
        )
        if req.target_modality == Modality.ONLINE:
            ifo_body = (f"{len(sessions)} session(s) moved online for "
                        f"{req.window_start} to {req.window_end}.")
        else:
            rooms = sorted({
                item.assigned_room.code
                for item in req.items.select_related("assigned_room").all()
                if item.assigned_room_id is not None
            })
            ifo_body = (f"{req.target_modality} shift assigned room(s) "
                        f"{', '.join(rooms) or '-'} for {req.window_start} to "
                        f"{req.window_end}.")
        notify(
            role=Role.IFO_ADMIN, type="modality_shift_applied",
            title="Modality shift applied", body=ifo_body, link="/ifo",
        )
    return req

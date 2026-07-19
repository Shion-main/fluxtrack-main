"""Shared, role-neutral derivation of a room's live state.

Consumed by BOTH `web/ifo.py` (the IFO room board, IFO-07/IFO-11) and
`web/guard.py` (the Guard floor monitor and per-room schedule, GRD-01/GRD-02).
It lives outside either role module because a role module must never import a
private name from another role module -- that inverts the dependency and makes
an unversioned contract out of an implementation detail.

This module holds NO role gating of its own. Authorization -- which rooms a
caller may see at all -- stays in the calling role module (IFO sees campus-wide,
a Guard sees only floors they are posted to right now).
"""
from scheduling.models import DayOfWeek, Modality, ScheduleStatus, SessionStatus
from scheduling.reporting import campus_block_ladder

# Five states, derived per room from the sessions that actually OCCUPY it today
# (see `occupies`), relative to `now`. Every state carries colour + icon + text
# label (never colour alone, PRODUCT.md):
#
#   absent      no-show: marked ABSENT, or still SCHEDULED past the grace window
#   starting    class window opened, still inside grace -- watch, not yet a problem
#   in_session  faculty checked in, class running
#   free        nothing running now, but the room has classes later today
#   idle        nothing scheduled in this room today
#
# Sort order puts problems first so they can never hide below the fold.
ROOM_STATE_ORDER = {
    "absent": 0, "starting": 1, "in_session": 2, "free": 3, "idle": 4,
}
ROOM_PROBLEM_STATES = ("absent", "starting")


def occupies(session, room):
    """True when `session` actually uses `room`.

    An ONLINE class does not occupy a physical room -- nobody is in it, so it
    must not appear in that room's schedule or affect its state; the room is
    simply free. In a VIRTUAL room the online class is the whole point, so it
    counts normally and its attendance (in session / absent) still matters to
    the checker who verifies online duty.

    This is what replaced the old dedicated `online` tile state. That state
    existed to explain why a booked room looked empty; once an online class no
    longer books a physical room, there is nothing left to explain.
    """
    if room.is_virtual:
        return True
    effective = session.declared_modality or session.schedule.modality
    return effective != Modality.ONLINE


def room_tile(room, sessions, now, grace):
    """Derive one room's live tile from the sessions that occupy it today.

    `sessions` must be today's sessions for THIS room, ordered by start; online
    classes in a physical room are dropped here, so they neither show in the
    room's list nor drive its state.
    """
    sessions = [s for s in sessions if occupies(s, room)]
    current = next(
        (s for s in sessions if s.scheduled_start <= now < s.scheduled_end), None
    )
    upcoming = [s for s in sessions if s.scheduled_start > now]
    tile = {
        "room": room,
        "session": current,
        "next": upcoming[0] if upcoming else None,
        "count": len(sessions),
    }

    if current is None:
        tile["state"] = "free" if sessions else "idle"
        return tile

    if current.status == SessionStatus.ACTIVE:
        tile["state"] = "in_session"
    elif current.status == SessionStatus.ABSENT:
        tile["state"] = "absent"
    elif current.status == SessionStatus.COMPLETED:
        # Ended (possibly early) but the scheduled window is still open: the room
        # is genuinely available, which is what IFO needs to know.
        tile["state"] = "free"
    elif now > current.scheduled_start + grace:
        # Past grace with nobody checked in. The sweep job will mark this ABSENT;
        # the board must not wait for the job to tell the truth.
        tile["state"] = "absent"
    else:
        tile["state"] = "starting"
    return tile


def room_timetable(room, term):
    """The room's week as a day-by-time grid, matching MMCM's printed schedule form.

    A flat list of classes answers "what is booked here"; the grid answers "when
    is this room FREE", which is the question a facilities office actually asks,
    and it is the layout staff already recognise from the paper form.

    Rows are the campus-wide block ladder for the term (every distinct start time
    in use), not just this room's own times -- so a free slot shows as an empty
    cell instead of vanishing, every room prints on the same grid, and two
    printouts can be compared side by side. That ladder is derived ONCE, by
    `scheduling.reporting.campus_block_ladder`, and shared with the room
    utilization aggregates so the printed grid and the dashboard can never
    disagree about what a slot is (D-06).

    A class occupies EVERY slot its window covers (half-open: start <= slot <
    end), so a double-length class fills two rows exactly as it does on the paper
    form, with no rowspan bookkeeping.
    """
    if term is None:
        return None
    blocks = campus_block_ladder(term)
    if not blocks:
        return None
    slots = [b.start for b in blocks]

    scheds = list(room.schedules
                  .filter(status=ScheduleStatus.ACTIVE, term=term)
                  .select_related("faculty"))
    # An online class does not use a physical room, so it is not part of that
    # room's timetable -- the slot reads free, which is the truth. In a virtual
    # room the online classes ARE the timetable.
    if not room.is_virtual:
        scheds = [s for s in scheds if s.modality != Modality.ONLINE]
    rows = []
    for slot in slots:
        cells = []
        for day_value, _label in DayOfWeek.choices:
            cells.append(next(
                (s for s in scheds
                 if s.day_of_week == day_value and s.start_time <= slot < s.end_time),
                None))
        rows.append({"time": slot, "cells": cells})
    return {"days": DayOfWeek.choices, "rows": rows,
            "used": sum(1 for r in rows for c in r["cells"] if c is not None),
            "capacity": len(rows) * len(DayOfWeek.choices)}

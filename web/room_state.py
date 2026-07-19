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
from scheduling.models import Modality, SessionStatus

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

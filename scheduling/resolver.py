"""
Scan resolver core (SCAN-01/02) — pure functions, no queries, no side effects,
unit-testable in isolation (SRS §6.6). The web layer fetches the context
(today's sessions, room occupancy) and applies the returned outcome.

Faculty outcomes (SCAN-02): checked-in, absent, too-early, wrong-room (confirm),
room-occupied (confirm), checked-out, early-end (confirm), online-reject,
no-schedule.
"""
from dataclasses import dataclass, field
from datetime import timedelta

# Outcome identifiers
CHECKED_IN = "checked-in"
CHECKED_OUT = "checked-out"
ABSENT = "absent"
TOO_EARLY = "too-early"
WRONG_ROOM = "wrong-room"
ROOM_OCCUPIED = "room-occupied"
EARLY_END = "early-end"
ONLINE_REJECT = "online-reject"
NO_SCHEDULE = "no-schedule"

# Outcomes that require a second, explicit confirmation (SCAN-04)
CONFIRM_OUTCOMES = {WRONG_ROOM, ROOM_OCCUPIED, EARLY_END}


@dataclass
class Resolution:
    outcome: str
    session_id: int | None = None
    prior_session_id: int | None = None  # occupying session for force handover
    needs_confirm: bool = field(init=False)

    def __post_init__(self):
        self.needs_confirm = self.outcome in CONFIRM_OUTCOMES


def resolve_faculty_scan(sessions_today, scanned_room_id, occupying_session_id,
                         now, *, grace_min, early_end_min, open_min=15):
    """
    sessions_today: the faculty member's Session objects for today
                    (any status), ordered by scheduled_start.
    scanned_room_id: pk of the room whose QR/code was scanned.
    occupying_session_id: pk of another faculty's ACTIVE session currently
                          holding the scanned room, or None.
    now: aware datetime.
    grace_min: minutes after start during which check-in counts Present (FAC-03/04).
    early_end_min: checkout earlier than this before end needs a reason (FAC-06).
    open_min: minutes before start when the check-in window opens.
    """
    grace = timedelta(minutes=grace_min)
    early_end = timedelta(minutes=early_end_min)
    open_lead = timedelta(minutes=open_min)

    # An active session takes priority: re-scan means checkout (FAC-05).
    for s in sessions_today:
        if s.status == "active":
            if s.room_id == scanned_room_id:
                if now < s.scheduled_end - early_end:
                    return Resolution(EARLY_END, s.id)
                return Resolution(CHECKED_OUT, s.id)
            return Resolution(WRONG_ROOM, s.id)

    # Otherwise find a scheduled session whose window contains now.
    candidate = None
    for s in sessions_today:
        if s.status != "scheduled":
            continue
        if s.scheduled_start - open_lead <= now <= s.scheduled_end:
            candidate = s
            break

    if candidate is None:
        # Upcoming session later today in the scanned room -> too early.
        for s in sessions_today:
            if (s.status == "scheduled" and s.room_id == scanned_room_id
                    and now < s.scheduled_start - open_lead):
                return Resolution(TOO_EARLY, s.id)
        return Resolution(NO_SCHEDULE)

    modality = candidate.declared_modality or candidate.schedule.modality
    if modality == "online":
        return Resolution(ONLINE_REJECT, candidate.id)

    if candidate.room_id != scanned_room_id:
        return Resolution(WRONG_ROOM, candidate.id)

    if now > candidate.scheduled_start + grace:
        return Resolution(ABSENT, candidate.id)

    if occupying_session_id is not None:
        return Resolution(ROOM_OCCUPIED, candidate.id,
                          prior_session_id=occupying_session_id)

    return Resolution(CHECKED_IN, candidate.id)

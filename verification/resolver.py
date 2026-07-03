"""Checker verification decision cores (CHK-01, IFO-06) - pure functions.

Mirrors scheduling/resolver.py: no ORM, no wall-clock read, no writes. The web
layer fetches context (the checker's active floor assignments, the scanned
room's floor, the room's current session state) and applies the returned
outcome. Keeping the decision pure lets the live checker scan and the offline
replay reach provably identical decisions (SRS 6.6, the same coupling guarantee
Phase 2 enforced between scan and sweep).

Checker gating outcomes (CHK-01):
  off-duty, wrong-floor, no-session, active-unverified, already-verified,
  absent-excluded.
"""
from dataclasses import dataclass, field

# Outcome identifiers
OFF_DUTY = "off-duty"                   # no active floor assignment at all
WRONG_FLOOR = "wrong-floor"            # on duty, but not on the scanned floor
NO_SESSION = "no-session"             # room empty / not yet started -> Verified empty
ACTIVE_UNVERIFIED = "active-unverified"  # active session awaiting Verify/Flag
ALREADY_VERIFIED = "already-verified"    # session already checker-verified
ABSENT_EXCLUDED = "absent-excluded"      # session is Absent -> not actionable

# Outcomes on which the checker can act (Verify / Flag / Verified empty).
ACTIONABLE = {ACTIVE_UNVERIFIED, NO_SESSION}


@dataclass
class CheckerResolution:
    outcome: str
    session_id: int | None = None
    actionable: bool = field(init=False)

    def __post_init__(self):
        self.actionable = self.outcome in ACTIONABLE


def resolve_checker_scan(active_floor_ids, scanned_floor_id, session_state, now):
    """Decide the outcome of a Checker scanning a room (CHK-01).

    active_floor_ids: floor pks the checker is on duty for (empty => off duty).
    scanned_floor_id: floor pk of the scanned room.
    session_state: a small value object exposing .id, .status (lowercase status
                   string) and .verified (bool), or None when the room has no
                   session at all.
    now: aware datetime, passed for parity with the faculty resolver and
         reserved for future grace use. NOT read here - the core stays pure
         (no wall-clock read, no ORM, no writes).
    """
    if not active_floor_ids:
        return CheckerResolution(OFF_DUTY)
    if scanned_floor_id not in active_floor_ids:
        return CheckerResolution(WRONG_FLOOR)
    if session_state is None or session_state.status == "scheduled":
        return CheckerResolution(NO_SESSION)          # room empty -> Verified empty
    if session_state.status == "absent":
        return CheckerResolution(ABSENT_EXCLUDED, session_state.id)
    if session_state.verified:
        return CheckerResolution(ALREADY_VERIFIED, session_state.id)
    return CheckerResolution(ACTIVE_UNVERIFIED, session_state.id)


def distribute_online_sessions(session_ids, checker_ids):
    """Deterministic round-robin of online sessions to online-duty checkers.

    Returns {session_id: checker_id}, assigning by input order so the result is
    reproducible. Empty checker_ids -> {} (the caller flags those sessions to
    IFO as unassigned rather than guessing). Pure: no ORM, no writes.
    """
    if not checker_ids:
        return {}
    return {sid: checker_ids[i % len(checker_ids)]
            for i, sid in enumerate(session_ids)}

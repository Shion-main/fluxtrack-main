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

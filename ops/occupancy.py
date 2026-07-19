"""Room occupancy lifecycle: the single source of truth for releasing a room.

JOB-02c — `release_room()` stamps `Session.room_released_at` and writes the
`session.room_released` AuditLog.

TWO legitimate callers, and only two:

  1. MOD-03 (Phase 4) — an approved ->Online modality shift frees the room the
     class no longer needs (`scheduling/services.py`, `materialize_sessions`).
  2. IFO-08 (Phase 7) — an IFO admin manually releases a room a session is
     still holding, from the console (`web/ifo.py session_release`). This is
     the human counterpart of (1): a room the system cannot know is free
     because the person who left it never told anything.

Both are DELIBERATE acts with a decision behind them. That is the actual rule,
and it is what the next prohibition is protecting.

The status sweep (JOB-02b) must NEVER call this: timer-based automatic room
release was CUT on 2026-07-03. A room is freed by a decision, never by a timer
noticing that a class ran long. The paired "sweep never stamps
room_released_at" guard lives in Plan 02-03 SweepTests and still holds.

Historical note: this helper shipped in Phase 2 with zero callers by design —
the machinery was built before either surface that needed it. That was a
statement about Phase 2, not a standing prohibition on ever calling it.
"""
from django.utils import timezone

from ops.models import AuditLog


def release_room(session, *, actor=None, now=None):
    """Release the room held by `session`, stamping `room_released_at` and
    auditing it — the single source of truth for room release (JOB-02c).

    INVOKED BY EXACTLY TWO CALLERS: MOD-03 (Phase 4) on an approved ->Online
    shift, and IFO-08 (Phase 7) on an IFO manual release from the console. The
    status sweep must NEVER call this (no timer-based auto-release, decided
    2026-07-03).

    Per Conventions rule 2 (every state change writes an AuditLog), each release
    records a `session.room_released` row with the actor and release instant.
    THIS FUNCTION IS THE ONLY WRITER OF THAT ROW — a caller must not add its
    own audit entry, or every release double-counts.

    `actor=None` denotes a system-initiated release. MOD-03 passes the deciding
    dean; IFO-08 always passes the acting IFO user, so an operator-initiated
    release is never anonymous.
    """
    now = now or timezone.now()
    session.room_released_at = now
    session.save(update_fields=["room_released_at"])
    AuditLog.objects.create(
        actor=actor,
        event_type="session.room_released",
        target_type="session",
        target_id=str(session.pk),
        payload={"released_at": now.isoformat()},
    )

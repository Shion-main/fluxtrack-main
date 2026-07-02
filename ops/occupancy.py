"""Room occupancy lifecycle: the single source of truth for releasing a room.

JOB-02c — `release_room()` stamps `Session.room_released_at` and writes the
`session.room_released` AuditLog. Built and fully tested in Phase 2, but its
ONLY caller is MOD-03 (Phase 4) on an approved ->Online modality shift.

The status sweep (JOB-02b) must NEVER call this: timer-based automatic room
release was CUT on 2026-07-03. A room is freed only through the modality-shift
approval flow, so this helper has zero Phase-2 callers by design (the paired
"sweep never stamps room_released_at" guard lives in Plan 02-03 SweepTests).
"""
from django.utils import timezone

from ops.models import AuditLog


def release_room(session, *, actor=None, now=None):
    """Release the room held by `session`, stamping `room_released_at` and
    auditing it — the single source of truth for room release (JOB-02c).

    INVOKED ONLY by MOD-03 (Phase 4) on an approved ->Online shift; the status
    sweep must NEVER call this (no timer-based auto-release, decided 2026-07-03).
    Per Conventions rule 2 (every state change writes an AuditLog), each release
    records a `session.room_released` row with the actor and release instant.
    `actor=None` denotes a system-initiated release.
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

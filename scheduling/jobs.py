"""
Status-sweep service functions (JOB-02b / JOB-02c).

`sweep_no_shows` marks every still-SCHEDULED F2F/Blended no-show ABSENT
independent of any scan, using the SAME `is_no_show_past_grace` predicate the
scan resolver uses (Phase-2 success criterion #1: scan-time and sweep-time can
never disagree). It backfills ALL past-date no-shows (self-heals after a
scheduler outage), is idempotent (only SCHEDULED -> ABSENT), writes an AuditLog
per absence, and NEVER stamps `room_released_at` (no timer-based auto-release;
room lifecycle is owned by MOD-03 in Phase 4).

`detect_room_conflicts` is the room-conflict safety net (JOB-02c): contradictory
occupancy (2+ ACTIVE sessions holding one room with `room_released_at` NULL)
raises ONE deduped IFO notification via the shared `notify()` write path, backed
by an open `RoomConflictFlag`, and auto-resolves when the conflict clears.

Both are thin service functions returning counts; the `run_status_sweep`
management command (and the Phase-2.5 scheduler) call them.

GRD-04 (07-12) added an OPTIONAL `collect=` keyword to both. The scalar integer
returns are UNCHANGED and must stay that way: they are asserted at fourteen call
sites (ten assertions across `scheduling/tests.py` and
`scheduling/tests_merge_sweep.py` -- the latter documents itself as the guard a
future edit to `sweep_no_shows` must not break -- plus both command wrappers).
When `collect` is not None each function appends `(kind, floor_id)` tuples for
the events it produced, read off rows the loop is ALREADY iterating. The guard
fan-out itself happens in the CALLER, after both functions have run, so one guard
gets one push per run rather than one per event (D-06).
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from accounts.models import Role
from campus.models import Room
from ops.guard_alerts import KIND_ABSENT, KIND_CONFLICT
from ops.models import AuditLog, RoomConflictFlag
from ops.notify import notify
from ops.policy import get_policy
from scheduling.models import Session, SessionStatus
from scheduling.resolver import is_no_show_past_grace
from scheduling.suspensions import excused_checker, session_is_calendar_excused


def sweep_no_shows(now=None, collect=None):
    """JOB-02b: mark unscanned no-shows ABSENT. Returns count marked.

    Idempotent (only SCHEDULED -> ABSENT), backfilled across all past dates, and
    audited. Online is now INCLUDED (03-05): the Phase-3 online Verify path sets a
    genuinely-attended online session to ACTIVE (the online analog of a room
    check-in), so the sweep — which only touches SCHEDULED — naturally skips it.
    Only an un-verified online no-show past grace falls to Absent, under the SAME
    `is_no_show_past_grace` predicate as F2F/Blended (ROADMAP #6). The exclusion
    guard that previously skipped all online sessions was removed in lockstep with
    that Verify path; removing it alone would mark every online session Absent.

    `collect` (GRD-04, optional) is a list the caller may pass to receive a
    `(KIND_ABSENT, floor_id)` tuple per session actually flipped. It is purely
    additive: the return value is the same integer with or without it, which
    `SweepReturnCompatibilityTests` locks. The floor id is read off `s.room`,
    which `select_related` already loaded for exactly this reason -- do NOT
    collect room ids and resolve floors afterwards. This function backfills all
    past-date no-shows, so after a multi-day scheduler outage on a full term one
    run can flip hundreds or low thousands of rows; a `pk__in` over that batch is
    a live MSSQL 2100-parameter exposure, the 04.1-04 failure class.
    """
    now = now or timezone.now()
    grace_min = get_policy("grace_minutes")
    # DB pre-filter derived from the SAME grace value the predicate re-affirms.
    cutoff = now - timedelta(minutes=grace_min)
    marked = 0
    # Calendar excusal (Phase 9, A1): a date+building covered by an academic break
    # or an active class suspension must NEVER be marked Absent. Built ONCE here
    # (two small queries) and answered from memory per candidate -- the whole point
    # is that a typhoon/holiday day does not mass-poison the record.
    excused = excused_checker()
    # MSSQL/pyodbc allows only ONE active result set per connection (MARS off by
    # default). Streaming with .iterator() keeps the SELECT cursor open, so the
    # save()/AuditLog INSERT below would raise HY010 "Function sequence error".
    # Fully materialize the candidate set first (cursor closed) before mutating.
    # room__floor is select_related so the excusal check reads building_id with no
    # extra query.
    candidates = list(Session.objects.filter(status=SessionStatus.SCHEDULED,
                                             scheduled_start__lt=cutoff)
                      .select_related("schedule", "room", "room__floor"))
    for s in candidates:
        # Re-affirm via the shared predicate so the ORM cutoff and the
        # authoritative no-show rule are provably ONE rule (coupling guarantee).
        if not is_no_show_past_grace(s.scheduled_start, now, grace_min):
            continue
        # A suspended/holiday session is not a no-show -- skip it entirely.
        if session_is_calendar_excused(s, excused):
            continue
        with transaction.atomic():
            # Idempotency guard mirrors web/scan.py _apply: only SCHEDULED->ABSENT,
            # enforced as a status-guarded filtered .update() (audit M7) so a
            # check-in that committed between the materialize above and this write
            # is never overwritten with ABSENT — the stale in-memory instance is
            # not trusted. NOTE: room_released_at is deliberately never touched.
            flipped = (Session.objects
                       .filter(pk=s.pk, status=SessionStatus.SCHEDULED)
                       .update(status=SessionStatus.ABSENT))
            if not flipped:
                continue  # raced by a live check-in: it wins, no audit row
            AuditLog.objects.create(
                actor=None, event_type="session.marked_absent",
                target_type="session", target_id=str(s.pk),
                payload={"by": "sweep"})
        marked += 1
        if collect is not None:
            # Read off the already-loaded related row: zero extra queries, and
            # no room-id batch that a later floor lookup could turn into an IN
            # list. Session.room is NOT NULL, so floor_id is always present.
            collect.append((KIND_ABSENT, s.room.floor_id))
    return marked


def detect_room_conflicts(now=None, collect=None):
    """JOB-02c: flag contradictory room occupancy once, auto-resolve on clear.

    A conflict is 2+ ACTIVE sessions holding one room (`room_released_at` NULL).
    Each newly-detected conflict creates an open `RoomConflictFlag` (dedup key
    `room:{room_id}`) and notifies IFO once; open flags whose conflict has
    cleared are stamped `resolved_at`. Returns the count of NEW conflicts flagged.

    `collect` (GRD-04, optional) receives a `(KIND_CONFLICT, floor_id)` tuple per
    NEWLY-flagged conflict, read off the `Room` this loop already fetches for its
    label. The IFO `notify()` below is untouched: IFO gets one notification per
    conflict, which is Phase-2 behaviour with its own tests. The floor-Guard
    alert is NOT emitted here -- the caller coalesces it once per run (D-06).
    """
    now = now or timezone.now()
    # Current conflict set: rooms with 2+ ACTIVE sessions still holding the room.
    conflicting_room_ids = [
        row["room_id"] for row in
        (Session.objects.filter(status=SessionStatus.ACTIVE,
                                room_released_at__isnull=True)
         .values("room_id").annotate(n=Count("id")).filter(n__gt=1))
    ]
    current_keys = {f"room:{rid}": rid for rid in conflicting_room_ids}

    # Auto-resolve open flags whose conflict has cleared (key no longer present).
    # Materialize first (list) so the save() below doesn't write while the SELECT
    # cursor is still open — MSSQL HY010 guard, same as sweep_no_shows above.
    for flag in list(RoomConflictFlag.objects.filter(resolved_at__isnull=True)):
        if flag.conflict_key not in current_keys:
            flag.resolved_at = now
            flag.save(update_fields=["resolved_at"])

    # Raise a flag + notify IFO once per newly-detected conflict (dedup on open flag).
    flagged = 0
    for key, room_id in current_keys.items():
        if RoomConflictFlag.objects.filter(conflict_key=key,
                                           resolved_at__isnull=True).exists():
            continue  # an open flag already covers this conflict -> no re-notify
        room = Room.objects.filter(pk=room_id).first()
        room_label = room.code if room else f"#{room_id}"
        with transaction.atomic():
            RoomConflictFlag.objects.create(room_id=room_id, conflict_key=key)
            notify(role=Role.IFO_ADMIN, type="room_conflict",
                   title="Room conflict detected",
                   body=f"Two or more active sessions are holding room "
                        f"{room_label}. Please resolve the occupancy conflict.")
        flagged += 1
        if collect is not None and room is not None:
            collect.append((KIND_CONFLICT, room.floor_id))
    return flagged

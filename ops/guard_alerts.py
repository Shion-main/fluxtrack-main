"""GRD-04 floor-alert fan-out: recipient resolution + batch summary (D-05/D-06).

This module exists so `scheduling/jobs.py` gains ZERO notification logic. The
sweep functions only append `(kind, floor_id)` tuples into a caller-supplied
collector; the caller -- which already runs `sweep_no_shows` and
`detect_room_conflicts` back to back in one job run -- hands the collected batch
here ONCE at the end of the run.

That placement IS the debounce (D-06). Both GRD-04 triggers already fire inside
the same five-minute sweep, so "one push per on-duty Guard per run" needs no
timer, no `last_alerted_at` column and no new policy knob. Putting the notify()
inside either sweep loop would produce one push per event -- the exact spam D-06
forbids -- so it deliberately lives out here instead.

Two things this module does NOT do, both on purpose:
  - It does not touch the per-conflict `notify(role=Role.IFO_ADMIN, ...)` inside
    `detect_room_conflicts`. IFO wants one notification per conflict; that is
    Phase-2 behaviour with its own tests.
  - It does not optimize `notify(users=[...])`'s per-recipient INSERT loop. N is
    the number of ON-DUTY guards (single digit), and changing it would mean
    editing the single Notification write path every other feature depends on.

ASCII-only output (Windows console is cp1252) per Conventions section 4.
"""
from django.utils import timezone

from ops.notifications import GUARD_FLOOR_ALERT
from ops.notify import notify
from verification.models import Assignment, AssignmentScope, DutyRole
from verification.resolver import assignment_covers_now

# Collector event kinds. `scheduling/jobs.py` imports these rather than repeating
# string literals, so a typo is an ImportError instead of a silently-dropped
# event that never reaches a guard.
KIND_ABSENT = "absent"        # a session was swept to ABSENT -> the room is free
KIND_CONFLICT = "conflict"    # a RoomConflictFlag opened on the room

# Where the alert lands. The Guard monitor is the one surface that shows the
# whole posted floor, which is what a coalesced batch alert is about.
GUARD_ALERT_LINK = "/guard/monitor"


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def summarize_floor_events(rows):
    """Pure: turn a per-floor tally into (title, body). No ORM, no wall-clock.

    `rows` is a sequence of `(floor_label, absent_count, conflict_count)`, already
    ordered by the caller. Kept pure and separate from the notification path so
    the wording can be unit-tested without building duty data or writing rows.

    The title is the at-a-glance line a locked phone shows; the body carries the
    per-floor breakdown for the bell. Returns ("", "") for an empty tally so the
    caller can treat it as "nothing to say".
    """
    rows = [r for r in rows if r[1] or r[2]]
    if not rows:
        return "", ""

    total_absent = sum(r[1] for r in rows)
    total_conflict = sum(r[2] for r in rows)

    parts = []
    if total_absent:
        parts.append(f"{_plural(total_absent, 'room')} now free")
    if total_conflict:
        parts.append(f"{_plural(total_conflict, 'room conflict')} detected")

    if len(rows) == 1:
        where = rows[0][0]
    else:
        where = _plural(len(rows), "floor")
    title = f"{' and '.join(parts)} on {where}"

    lines = []
    for label, absent, conflict in rows:
        detail = []
        if absent:
            detail.append(f"{_plural(absent, 'room')} now free")
        if conflict:
            detail.append(f"{_plural(conflict, 'room conflict')}")
        lines.append(f"{label}: {', '.join(detail)}.")
    return title, "\n".join(lines)


def notify_floor_guards(events, now=None):
    """Emit ONE coalesced GRD-04 alert per on-duty Guard. Returns guards notified.

    `events` is the collector the sweep functions filled: an iterable of
    `(kind, floor_id)` tuples. An empty collection is the common case (a quiet
    sweep run) and short-circuits before touching the database at all.

    Recipient rules, each one load-bearing:
      - ONE query for every active FLOOR-scoped GUARD assignment, filtering on
        scalar equality only. There is deliberately no `pk__in` anywhere in this
        path: `sweep_no_shows` backfills ALL past no-shows and self-heals after a
        scheduler outage, so a single run's batch is unbounded and an `IN` list
        built from it is a real MSSQL 2100-parameter exposure (the 04.1-04
        `reset_term` failure class), visible only AFTER downtime.
      - The queryset is materialized with `list()` before the emit loop. This
        function writes Notification rows while iterating and pyodbc runs with
        MARS off, so writing inside a live cursor raises HY010 "Function sequence
        error". Both existing sweep functions carry the same guard.
      - Floors are read with a comprehension over `a.floors.all()`, NOT
        `values_list`, which bypasses the prefetch cache and re-queries per
        assignment.
      - `is_active` is checked explicitly: `notify(role=...)` filters inactive
        users but `notify(users=[...])` does NOT -- it trusts the caller -- so a
        deactivated guard would otherwise get a row on a disabled account.
      - On-duty is decided by `verification.resolver.assignment_covers_now` on the
        LOCAL date/time. Do not write a fourth copy of that predicate; its
        docstring exists so the existing copies can never drift again.
    """
    tally = {}
    for kind, floor_id in events or ():
        if floor_id is None:
            continue
        counts = tally.setdefault(floor_id, {KIND_ABSENT: 0, KIND_CONFLICT: 0})
        if kind in counts:
            counts[kind] += 1
    if not tally:
        return 0

    local = timezone.localtime(now or timezone.now())
    today, now_t = local.date(), local.time()

    # Scalar-equality filter only; floors (and their buildings, for the label)
    # prefetched so the loop below issues no per-assignment query.
    assignments = list(
        Assignment.objects
        .filter(role=DutyRole.GUARD, scope=AssignmentScope.FLOOR,
                status="active")
        .select_related("user")
        .prefetch_related("floors__building"))

    # user -> {floor_id: Floor}. Django models hash/compare by pk, so two
    # assignments for one guard collapse onto a single recipient -- which is what
    # makes "one push per guard" hold even for a guard with several postings.
    per_user = {}
    for a in assignments:
        if not a.user.is_active:
            continue
        if not assignment_covers_now(a, today, now_t):
            continue
        for floor in a.floors.all():
            if floor.pk in tally:
                per_user.setdefault(a.user, {})[floor.pk] = floor

    notified = 0
    for user, floors in per_user.items():
        rows = [(str(floor), tally[fid][KIND_ABSENT], tally[fid][KIND_CONFLICT])
                for fid, floor in sorted(floors.items(),
                                         key=lambda kv: str(kv[1]))]
        title, body = summarize_floor_events(rows)
        if not title:
            continue
        # notify() is the single Notification write path (NOTIF-00, enforced by a
        # source-grep test in ops/tests.py). Never construct a Notification here.
        notify(users=[user], type=GUARD_FLOOR_ALERT, title=title, body=body,
               link=GUARD_ALERT_LINK)
        notified += 1
    return notified

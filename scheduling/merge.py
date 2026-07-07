"""Co-scheduled "merged sections" core (Phase 04.2, D-01/D-02).

FluxTrack imports co-scheduled sections: the SAME instructor teaching two
sections at the SAME instant in different rooms (or the same room, different
course). Left alone, the JOB-02 sweep would falsely mark the un-scanned sibling
Absent. This module is the shared merge core the whole phase builds on:

  - `merged_sibling_ids` is the PURE D-01 detector. Like
    `scheduling.resolver.is_no_show_past_grace` (resolver.py:39-52), it takes
    plain Session-like objects and returns a decision with NO ORM query and NO
    `timezone.now()`, so it is unit-testable in isolation and coupling-tested
    against the live call-sites the same way the sweep re-affirms the shared
    no-show predicate.

D-03: detection is dynamic from existing Session fields at check-in/verify/sweep
time -- no merge-group model, no grouping migration, no roster/data merge.

ASCII-only by convention (Windows cp1252).
"""


def merged_sibling_ids(anchor, candidates):
    """Return the set of candidate ids that merge with `anchor` under D-01.

    A candidate merges when it is a DIFFERENT row with:
      - same faculty_id, AND
      - same scheduled_start (exact aware instant), AND
      - (same room_id OR same course_code).

    Pure: `anchor` and `candidates` are Session-like objects exposing
    ``.id`` / ``.faculty_id`` / ``.scheduled_start`` / ``.room_id`` /
    ``.course_code``. The caller materializes them (``select_related("schedule")``)
    and supplies ``course_code``. No ORM query and no ``timezone.now()`` inside --
    mirrors the "pure, no now()" convention of
    ``scheduling.resolver.is_no_show_past_grace``.

    scheduled_start is compared as the full aware DateTime (the exact instant),
    NEVER truncated to a date or time-of-day, so a 1-minute offset disqualifies.
    """
    out = set()
    for c in candidates:
        if c.id == anchor.id:
            continue
        if c.faculty_id != anchor.faculty_id:
            continue
        if c.scheduled_start != anchor.scheduled_start:
            continue
        if c.room_id == anchor.room_id or c.course_code == anchor.course_code:
            out.add(c.id)
    return out

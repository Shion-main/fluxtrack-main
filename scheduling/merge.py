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

  - `propagate_merged_present` / `propagate_merged_absent` are the impure ORM
    seams that call the pure detector, then flip ONLY status=SCHEDULED siblings
    in one atomic, MSSQL-safe filtered `.update()` + `bulk_create` audit write
    (mirrors scheduling/jobs.py:sweep_no_shows materialize-before-mutate).

D-03: detection is dynamic from existing Session fields at check-in/verify/sweep
time -- no merge-group model, no grouping migration, no roster/data merge.

ASCII-only by convention (Windows cp1252).
"""
from django.db import transaction
from django.utils import timezone

from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.models import (AcademicTerm, CheckinMethod, Modality, Session,
                               SessionStatus)
from scheduling.resolver import is_no_show_past_grace
from scheduling.term_scope import require_writable_term


def merged_sibling_ids(anchor, candidates):
    """Return the set of candidate ids that merge with `anchor` under D-01.

    A candidate merges when it is a DIFFERENT row with the same faculty_id and
    the same scheduled_start (exact aware instant), AND -- per-modality:

      - ONLINE arm (D-01 refinement #2): when BOTH the anchor and the candidate
        are effectively online, faculty + exact start alone is enough. An online
        class has no room, and one instructor cannot be live in two different
        online classes at the same instant, so all their same-start online
        sessions are one presence event. (Empirically, the room-OR-course key
        missed ~32% of real online groups -- see 04.2-VERIFICATION.md.)
      - F2F / mixed arm (unchanged, the GARAY case): otherwise the candidate
        merges only when it shares the same room_id OR the same course_code.

    Pure: `anchor` and `candidates` are Session-like objects exposing
    ``.id`` / ``.faculty_id`` / ``.scheduled_start`` / ``.room_id`` /
    ``.course_code`` / ``.is_online``. The caller materializes them
    (``select_related("schedule")``) and supplies ``course_code`` + ``is_online``.
    No ORM query and no ``timezone.now()`` inside -- mirrors the "pure, no now()"
    convention of ``scheduling.resolver.is_no_show_past_grace``.

    scheduled_start is compared as the full aware DateTime (the exact instant),
    NEVER truncated to a date or time-of-day, so a 1-minute offset disqualifies.
    ``is_online`` defaults to False (F2F) when unset, so a caller that omits it
    keeps the pre-refinement room-OR-course behavior.
    """
    anchor_online = getattr(anchor, "is_online", False)
    out = set()
    for c in candidates:
        if c.id == anchor.id:
            continue
        if c.faculty_id != anchor.faculty_id:
            continue
        if c.scheduled_start != anchor.scheduled_start:
            continue
        if anchor_online and getattr(c, "is_online", False):
            out.add(c.id)  # online arm: faculty + exact start is sufficient
        elif c.room_id == anchor.room_id or c.course_code == anchor.course_code:
            out.add(c.id)  # F2F / mixed arm: same room OR same course
    return out


def _effective_is_online(session):
    """True when the session is effectively online (declared wins, else schedule).

    Mirrors ``audit_merge_coverage._effective_modality`` (SCAN-01 rule): a
    per-session ``declared_modality`` (set by a Phase-4 modality shift) overrides
    the ``schedule.modality`` default.
    """
    return (session.declared_modality or session.schedule.modality) == Modality.ONLINE


def _materialize_candidates(anchor):
    """Fetch + annotate the anchor's same-faculty/same-start rows.

    Materializes the queryset to a list (cursor closed) BEFORE any write, so the
    later filtered ``.update()`` / ``bulk_create`` never fires an INSERT while a
    SELECT cursor is still open -- the MSSQL HY010 guard from
    ``scheduling.jobs.sweep_no_shows``. Attaches ``course_code`` and ``is_online``
    (effective modality) onto the anchor and each candidate so the pure detector
    can read both merge arms.
    """
    candidates = list(
        Session.objects.filter(
            faculty_id=anchor.faculty_id,
            scheduled_start=anchor.scheduled_start,
            schedule__term_id=anchor.schedule.term_id,
        )
        .exclude(pk=anchor.pk)
        .select_related("schedule")
    )
    anchor.course_code = anchor.schedule.course_code
    anchor.is_online = _effective_is_online(anchor)
    for c in candidates:
        c.course_code = c.schedule.course_code
        c.is_online = _effective_is_online(c)
    return candidates


def propagate_merged_present(anchor, now, actor):
    """Atomic SCHEDULED->ACTIVE fill for the anchor's merged siblings (D-04/D-05).

    After the anchor has itself been activated (check-in), flip every SCHEDULED
    merged sibling to ACTIVE, sharing the anchor's ``actual_start`` (== ``now``)
    and stamping ``checkin_method=MERGED``; write one ``session.merged_present``
    AuditLog per filled row with payload ``{"merged_from": anchor.pk}``. The
    anchor itself is never re-stamped (helper only touches siblings). Returns the
    list of filled pks (``[]`` when nothing qualifies -> idempotent).

    Faculty-scoped (T-04.2-01) and status-guarded (T-04.2-02): the ``.update()``
    is filtered to ``status=SCHEDULED`` so an already-ACTIVE/ABSENT/COMPLETED
    sibling is left untouched. One filtered ``.update()`` + ``bulk_create`` inside
    a single ``transaction.atomic()`` avoids a half-flipped group and the HY010
    mutate-while-iterate trap (T-04.2-03).
    """
    with transaction.atomic():
        anchor = (
            Session.objects.select_for_update()
            .select_related("schedule__term")
            .get(pk=anchor.pk)
        )
        term = AcademicTerm.objects.select_for_update().get(
            pk=anchor.schedule.term_id)
        require_writable_term(term)
        candidates = _materialize_candidates(anchor)
        sib_ids = merged_sibling_ids(anchor, candidates)
        fill_ids = list(
            Session.objects.filter(pk__in=sib_ids, status=SessionStatus.SCHEDULED)
            .values_list("pk", flat=True)
        )
        if not fill_ids:
            return []
        Session.objects.filter(pk__in=fill_ids).update(
            status=SessionStatus.ACTIVE,
            actual_start=now,
            checkin_method=CheckinMethod.MERGED,
        )
        AuditLog.objects.bulk_create([
            AuditLog(
                actor=actor,
                event_type="session.merged_present",
                target_type="session",
                target_id=str(pk),
                payload={"merged_from": anchor.pk},
            )
            for pk in fill_ids
        ])
        return fill_ids


def propagate_merged_absent(anchor, actor, now=None):
    """Atomic SCHEDULED->ABSENT fill for the anchor's merged siblings (online D-07).

    The online counterpart of ``propagate_merged_present``: when the anchor is
    resolved Absent (online Flag-not-present / un-verified no-show), flip every
    SCHEDULED merged sibling to ABSENT and write one ``session.merged_absent``
    AuditLog per row with payload ``{"merged_from": anchor.pk}``. Same
    faculty-scoping, status-guard, atomicity, and HY010 safety as the present
    path. Returns the list of absented pks (``[]`` when nothing qualifies).

    Grace gate (2026-07-19 audit H2): siblings are absented ONLY when the group
    is already past the shared no-show grace window. ABSENT is terminal -- a
    flag placed minutes after start would otherwise permanently block a
    within-grace faculty start (or the sibling's own checker Verify) on every
    sibling. The anchor is the CALLER's authoritative decision and is not
    touched here; within grace the siblings are simply left SCHEDULED for the
    JOB-02 sweep, which applies the same ``is_no_show_past_grace`` predicate.
    Merge candidates share ``scheduled_start`` exactly (the D-01 key), so the
    anchor's start speaks for the whole group.
    """
    now = now or timezone.now()
    grace_min = get_policy("grace_minutes")
    if not is_no_show_past_grace(anchor.scheduled_start, now, grace_min):
        return []
    with transaction.atomic():
        anchor = (
            Session.objects.select_for_update()
            .select_related("schedule__term")
            .get(pk=anchor.pk)
        )
        term = AcademicTerm.objects.select_for_update().get(
            pk=anchor.schedule.term_id)
        require_writable_term(term)
        candidates = _materialize_candidates(anchor)
        sib_ids = merged_sibling_ids(anchor, candidates)
        fill_ids = list(
            Session.objects.filter(pk__in=sib_ids, status=SessionStatus.SCHEDULED)
            .values_list("pk", flat=True)
        )
        if not fill_ids:
            return []
        Session.objects.filter(pk__in=fill_ids).update(status=SessionStatus.ABSENT)
        AuditLog.objects.bulk_create([
            AuditLog(
                actor=actor,
                event_type="session.merged_absent",
                target_type="session",
                target_id=str(pk),
                payload={"merged_from": anchor.pk},
            )
            for pk in fill_ids
        ])
        return fill_ids

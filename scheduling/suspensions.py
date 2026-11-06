"""Class-suspension & academic-break calendar excusal (Phase 9, A1).

This is the shared core that keeps a suspension or holiday from ever poisoning the
attendance record. It answers one question -- "is this (date, building) excused from
attendance?" -- for the two readers that must agree (the JOB-02 sweep and JOB-01
materialize), and it owns the two write services (declare a suspension, lift one).

Mirrors the ``scheduling.merge`` discipline: pure-ish read helpers with no baked-in
``timezone.now()`` where avoidable, and mutating helpers that flip ONLY the rows they
must, in one atomic, audited, faculty-scoped, MSSQL-2100-param-safe pass.

ASCII-only by convention (Windows cp1252).
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from ops.models import AuditLog
from ops.locking import serialized_write
from ops.notify import notify
from ops.policy import get_policy
from scheduling.models import (AcademicBreak, AcademicTerm, ClassSuspension,
                               Session, SessionStatus)
from scheduling.term_scope import require_writable_term

# Batch size for the SCHEDULED->CANCELLED flip: an `id__in` over more than the
# MSSQL 2100-parameter limit is the 04.1-04 failure class. A whole-campus typhoon
# day can cover ~2,000 sessions, so chunk the id list.
_FLIP_CHUNK = 900


def excused_checker(term=None):
    """Return a callable ``excused(local_date, building_id) -> bool`` that is True
    when that date+building is covered by an academic break OR an active suspension.

    Materializes the term's breaks and active suspensions ONCE (two small queries),
    then answers from memory -- so the sweep can test hundreds of candidate sessions
    with zero extra queries. ``term`` defaults to the active term.
    """
    term = term or AcademicTerm.objects.filter(
        status=AcademicTerm.Status.ACTIVE).first()
    if term is None:
        return lambda d, building_id=None: False
    breaks = [(b.start_date, b.end_date) for b in term.breaks.all()]
    suspensions = list(term.suspensions.filter(lifted_at__isnull=True))

    def excused(d, building_id=None):
        if any(s <= d <= e for (s, e) in breaks):
            return True
        return any(sp.covers(d, building_id) for sp in suspensions)

    return excused


def session_is_calendar_excused(session, excused=None):
    """True when ``session``'s date+building is excused (break or suspension).

    ``session`` must have ``date`` and a ``room`` whose ``floor.building_id`` is
    loaded (the sweep select_relates ``room__floor``). Pass a reusable ``excused``
    callable from ``excused_checker`` to avoid rebuilding it per session.
    """
    excused = excused or excused_checker()
    building_id = session.room.floor.building_id
    return excused(session.date, building_id)


def _cancel_sessions(qs, *, reason, actor, payload):
    """Flip SCHEDULED sessions in ``qs`` to CANCELLED; return (pk, faculty_id) rows.

    Materializes before mutating so no SELECT cursor is open when the UPDATE fires
    (MSSQL HY010), and so faculty fan-out reads a stable set.
    """
    rows = list(qs.filter(status=SessionStatus.SCHEDULED)
                .values_list("pk", "faculty_id"))
    ids = [pk for pk, _ in rows]
    for i in range(0, len(ids), _FLIP_CHUNK):
        chunk = ids[i:i + _FLIP_CHUNK]
        Session.objects.filter(pk__in=chunk).update(
            status=SessionStatus.CANCELLED, cancelled_reason=reason[:200])
        AuditLog.objects.bulk_create([
            AuditLog(actor=actor, event_type="session.cancelled",
                     target_type="session", target_id=str(pk),
                     payload={"reason": reason, **payload})
            for pk in chunk])
    return rows


def _notify_cancelled(rows, *, title, start_date, scope, reason):
    """One notification per affected faculty (coalesced), never one per session."""
    counts = {}
    for _, fid in rows:
        counts[fid] = counts.get(fid, 0) + 1
    faculty_by_id = get_user_model().objects.in_bulk(counts.keys())
    for fid, n in counts.items():
        user = faculty_by_id.get(fid)
        if user is None:
            continue
        notify(users=[user], type="class_suspended", title=title,
               body=(f"{n} of your class session(s) on {start_date} "
                     f"({scope}) are cancelled -- {reason}. No check-in needed."))


def _reinstate_upcoming(qs, *, actor, now, payload):
    """Return still-upcoming CANCELLED sessions to SCHEDULED; return the count.

    A class past its no-show point stays CANCELLED. Nobody could have held it, so
    reinstating it would only hand it to the sweep to mark Absent.
    """
    cutoff = now - timedelta(minutes=get_policy("grace_minutes"))
    ids = list(qs.filter(scheduled_start__gte=cutoff).values_list("pk", flat=True))
    for i in range(0, len(ids), _FLIP_CHUNK):
        chunk = ids[i:i + _FLIP_CHUNK]
        Session.objects.filter(pk__in=chunk).update(
            status=SessionStatus.SCHEDULED, cancelled_reason="")
        AuditLog.objects.bulk_create([
            AuditLog(actor=actor, event_type="session.suspension_lifted",
                     target_type="session", target_id=str(pk), payload=payload)
            for pk in chunk])
    return len(ids)


@serialized_write
def suspend_classes(*, term, start_date, end_date, reason, building=None,
                    declared_by=None, now=None):
    """Declare a class suspension and flip its already-materialized sessions.

    Creates a ``ClassSuspension`` row, flips every still-SCHEDULED session on a
    covered date (and, if ``building`` is set, in that building) to CANCELLED with
    ``cancelled_reason``, writes one ``session.cancelled`` AuditLog per flip, and
    notifies each affected faculty ONCE (coalesced, D-04). Returns
    ``(suspension, cancelled_count)``.

    Only SCHEDULED sessions are touched -- an ACTIVE/COMPLETED/ABSENT session is a
    record that already happened and is left alone (the status guard mirrors the
    sweep and the merge helpers). Idempotent in effect: a second identical call
    creates a second suspension row but flips nothing new.
    """
    now = now or timezone.now()
    term = AcademicTerm.objects.select_for_update().get(pk=term.pk)
    require_writable_term(term)
    suspension = ClassSuspension.objects.create(
        term=term, start_date=start_date, end_date=end_date, building=building,
        reason=reason, declared_by=declared_by)

    qs = Session.objects.filter(
        schedule__term=term, date__gte=start_date, date__lte=end_date)
    if building is not None:
        qs = qs.filter(room__floor__building=building)

    rows = _cancel_sessions(qs, reason=reason, actor=declared_by,
                            payload={"suspension": suspension.pk})
    _notify_cancelled(
        rows, title="Classes suspended", start_date=start_date, reason=reason,
        scope=building.code if building is not None else "all campuses")
    return suspension, len(rows)


@serialized_write
def lift_suspension(suspension, *, lifted_by=None, now=None):
    """Reverse a suspension: reinstate the upcoming sessions IT cancelled that are
    still CANCELLED with its exact reason. Returns the reinstated count.

    Only rows still CANCELLED-with-this-reason are touched, so a session that was
    independently changed after the suspension (or cancelled by a different
    declaration) is never resurrected. A class whose time already passed stays
    CANCELLED: faculty were told not to come, so it must not become Absent. Marks
    the suspension lifted so the sweep and materialize stop excusing its dates.
    """
    now = now or timezone.now()
    suspension = (
        ClassSuspension.objects.select_for_update()
        .select_related("term")
        .get(pk=suspension.pk)
    )
    require_writable_term(suspension.term)
    if suspension.lifted_at is not None:
        return 0
    qs = Session.objects.filter(
        schedule__term=suspension.term,
        status=SessionStatus.CANCELLED, cancelled_reason=suspension.reason[:200],
        date__gte=suspension.start_date, date__lte=suspension.end_date)
    if suspension.building_id is not None:
        qs = qs.filter(room__floor__building_id=suspension.building_id)

    reinstated = _reinstate_upcoming(qs, actor=lifted_by, now=now,
                                     payload={"suspension": suspension.pk})
    suspension.lifted_at = now
    suspension.lifted_by = lifted_by
    suspension.save(update_fields=["lifted_at", "lifted_by"])
    return reinstated


@serialized_write
def declare_break(*, term, start_date, end_date, reason, declared_by=None):
    """Add a holiday/break and cancel the sessions already created for it.

    Sessions are materialized ahead of time, so excusing the date alone would leave
    them open for check-in and stuck SCHEDULED. Returns ``(break, cancelled_count)``.
    """
    term = AcademicTerm.objects.select_for_update().get(pk=term.pk)
    require_writable_term(term)
    reason = reason[:120]
    brk = AcademicBreak.objects.create(
        term=term, start_date=start_date, end_date=end_date, reason=reason)
    AuditLog.objects.create(
        actor=declared_by, event_type="academicbreak.created",
        target_type="term", target_id=str(term.pk),
        payload={"start": str(start_date), "end": str(end_date), "reason": reason})
    rows = _cancel_sessions(
        Session.objects.filter(schedule__term=term, date__gte=start_date,
                               date__lte=end_date),
        reason=reason, actor=declared_by, payload={"break": brk.pk})
    _notify_cancelled(rows, title="Holiday declared", start_date=start_date,
                      scope="all campuses", reason=reason)
    return brk, len(rows)


@serialized_write
def remove_break(brk, *, removed_by=None, now=None):
    """Delete a holiday/break, restoring its upcoming classes. Returns the count.

    Same rule as lifting a suspension: a class whose time passed stays CANCELLED.
    """
    now = now or timezone.now()
    require_writable_term(brk.term)
    reinstated = _reinstate_upcoming(
        Session.objects.filter(
            schedule__term=brk.term, status=SessionStatus.CANCELLED,
            cancelled_reason=brk.reason[:200], date__gte=brk.start_date,
            date__lte=brk.end_date),
        actor=removed_by, now=now, payload={"break": brk.pk})
    AuditLog.objects.create(
        actor=removed_by, event_type="academicbreak.deleted",
        target_type="term", target_id=str(brk.term_id),
        payload={"start": str(brk.start_date), "end": str(brk.end_date),
                 "reason": brk.reason})
    brk.delete()
    return reinstated

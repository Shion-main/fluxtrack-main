"""Mid-term single-schedule operations (Phase 10, A9).

Registrar reality: a class gets a new instructor, moves rooms, changes its time,
or a section is dropped after the term is underway. Before this, individual
Schedule rows were editable only in Django admin. These services let IFO do it
from the console, safely.

THE SAFETY RULE, everywhere in this module: a write only ever touches **future
SCHEDULED** sessions (``date >= today``, ``status = SCHEDULED``). A session that
already happened -- ACTIVE, COMPLETED, ABSENT, or CANCELLED -- is a record, and a
schedule edit never rewrites history. Past attendance stands exactly as it was.

Cancellation reuses the Phase 9 ``CANCELLED`` status so a dropped class reads the
same as a suspended one (not Absent, not held, not booked).

Room/time moves are checked across every remaining weekly occurrence before any
write, including dates beyond the materialization horizon. ``day_of_week`` is
intentionally NOT editable here: changing the meeting day would strand every
already-materialized session on the old weekday, which is a delete-and-
rematerialize operation, not an edit.

ASCII-only by convention (Windows cp1252).
"""
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ops.availability import room_is_free
from ops.models import AuditLog
from scheduling.models import (Modality, Schedule, ScheduleStatus, Session,
                               SessionStatus)
from scheduling.suspensions import excused_checker
from scheduling.term_scope import require_writable_term


class ScheduleConflictError(ValueError):
    """The proposed room/time would collide with another room occupant."""


def _future_scheduled(schedule, today):
    return Session.objects.filter(schedule=schedule, status=SessionStatus.SCHEDULED,
                                  date__gte=today)


def _assert_occurrences_free(schedule, room, start_time, end_time, today):
    """Refuse a room/time edit that collides on any remaining weekly date."""
    if schedule.modality == Modality.ONLINE:
        return
    existing = {
        session.date: session
        for session in list(Session.objects.filter(
            schedule=schedule, date__gte=today).order_by("date"))
    }
    excused = excused_checker(schedule.term)
    offset = (schedule.day_of_week - today.weekday()) % 7
    occurrence_date = today + timedelta(days=offset)
    occurrence_dates = {
        session.date for session in existing.values()
        if session.status == SessionStatus.SCHEDULED
    }
    while occurrence_date <= schedule.term.end_date:
        occurrence_dates.add(occurrence_date)
        occurrence_date += timedelta(days=7)

    for occurrence_date in sorted(occurrence_dates):
        own_session = existing.get(occurrence_date)
        if own_session is not None and own_session.status != SessionStatus.SCHEDULED:
            continue
        if excused(occurrence_date, room.floor.building_id):
            continue
        at_start = timezone.make_aware(
            timezone.datetime.combine(occurrence_date, start_time))
        at_end = timezone.make_aware(
            timezone.datetime.combine(occurrence_date, end_time))
        if not room_is_free(
            room, at_start, at_end,
            exclude_session_id=(own_session.pk if own_session else None),
            exclude_schedule_id=schedule.pk,
        ):
            raise ScheduleConflictError(
                f"The room is occupied on {occurrence_date} during that time.")


@transaction.atomic
def update_schedule(schedule, *, faculty=None, room=None, start_time=None,
                    end_time=None, enrolled_count=None, actor=None, today=None):
    """Apply an edit to a schedule and propagate it to future SCHEDULED sessions.

    Any of faculty / room / start_time / end_time / enrolled_count may be given;
    those left None are unchanged. Future SCHEDULED sessions have their faculty and
    room updated and their ``scheduled_start``/``scheduled_end`` recomputed from the
    new times on their existing date (same weekday, so the date is untouched).
    Returns the count of future sessions updated.
    """
    today = today or timezone.localdate()
    schedule = (
        Schedule.objects.select_for_update()
        .select_related("term")
        .get(pk=schedule.pk)
    )
    require_writable_term(schedule.term)
    before = {"faculty": schedule.faculty_id, "room": schedule.room_id,
              "start_time": str(schedule.start_time),
              "end_time": str(schedule.end_time),
              "enrolled_count": schedule.enrolled_count}
    target_room = room or schedule.room
    target_start = start_time or schedule.start_time
    target_end = end_time or schedule.end_time
    if (target_room.pk != schedule.room_id
            or target_start != schedule.start_time
            or target_end != schedule.end_time):
        _assert_occurrences_free(
            schedule, target_room, target_start, target_end, today)
    if faculty is not None:
        schedule.faculty = faculty
    if room is not None:
        schedule.room = room
    if start_time is not None:
        schedule.start_time = start_time
    if end_time is not None:
        schedule.end_time = end_time
    if enrolled_count is not None:
        schedule.enrolled_count = enrolled_count
    schedule.save(update_fields=["faculty", "room", "start_time", "end_time",
                                 "enrolled_count"])

    # Propagate to future SCHEDULED sessions. Materialize the id list first
    # (cursor closed) before per-row saves -- MSSQL HY010 discipline.
    sessions = list(_future_scheduled(schedule, today))
    for s in sessions:
        s.faculty = schedule.faculty
        s.room = schedule.room
        s.scheduled_start = timezone.make_aware(
            timezone.datetime.combine(s.date, schedule.start_time))
        s.scheduled_end = timezone.make_aware(
            timezone.datetime.combine(s.date, schedule.end_time))
        s.save(update_fields=["faculty", "room", "scheduled_start",
                              "scheduled_end"])
    AuditLog.objects.create(
        actor=actor, event_type="schedule.updated",
        target_type="schedule", target_id=str(schedule.pk),
        payload={"before": before, "future_sessions_updated": len(sessions)})
    return len(sessions)


@transaction.atomic
def cancel_schedule(schedule, *, actor=None, reason="", today=None):
    """Archive a schedule and cancel its future SCHEDULED sessions (A9 + Phase 9).

    The schedule goes ARCHIVED (materialize stops creating sessions for it -- it
    filters status=ACTIVE), and every future SCHEDULED session becomes CANCELLED
    with ``cancelled_reason`` so a dropped class is not swept Absent. Past sessions
    are untouched. Returns the count of sessions cancelled.
    """
    today = today or timezone.localdate()
    schedule = (
        Schedule.objects.select_for_update()
        .select_related("term")
        .get(pk=schedule.pk)
    )
    require_writable_term(schedule.term)
    reason = (reason or "Class no longer offered").strip()[:200]
    schedule.status = ScheduleStatus.ARCHIVED
    schedule.save(update_fields=["status"])

    ids = list(_future_scheduled(schedule, today).values_list("pk", flat=True))
    if ids:
        Session.objects.filter(pk__in=ids).update(
            status=SessionStatus.CANCELLED, cancelled_reason=reason)
        AuditLog.objects.bulk_create([
            AuditLog(actor=actor, event_type="session.cancelled",
                     target_type="session", target_id=str(pk),
                     payload={"reason": reason, "schedule": schedule.pk})
            for pk in ids])
    AuditLog.objects.create(
        actor=actor, event_type="schedule.archived",
        target_type="schedule", target_id=str(schedule.pk),
        payload={"reason": reason, "sessions_cancelled": len(ids)})
    return len(ids)

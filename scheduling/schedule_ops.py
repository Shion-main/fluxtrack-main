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
from ops.locking import serialized_write
from campus.models import Room
from scheduling.models import (AcademicTerm, Modality, Schedule, ScheduleStatus, Session,
                               SessionStatus)
from scheduling.suspensions import excused_checker
from scheduling.term_scope import require_writable_term


class ScheduleConflictError(ValueError):
    """The proposed room/time would collide with another room occupant."""


def _future_scheduled(schedule, today):
    return Session.objects.filter(schedule=schedule, status=SessionStatus.SCHEDULED,
                                  date__gte=today)


def _assert_occurrences_free(schedule, room, start_time, end_time, today, faculty=None):
    """Refuse a room/time edit that collides on any remaining weekly date."""
    faculty = faculty or schedule.faculty
    if room.out_of_service and schedule.modality != Modality.ONLINE:
        raise ScheduleConflictError("The room is out of service.")
    existing = {
        session.date: session
        for session in list(Session.objects.filter(
            schedule_id=schedule.pk, date__gte=today).order_by("date"))
    }
    excused = excused_checker(schedule.term)
    first_day = max(today, schedule.term.start_date)
    offset = (schedule.day_of_week - first_day.weekday()) % 7
    occurrence_date = first_day + timedelta(days=offset)
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
        merged = _faculty_conflicts(schedule, faculty, room, at_start, at_end)
        excluded = merged | ({schedule.pk} if schedule.pk is not None else set())
        if (schedule.term.status == AcademicTerm.Status.DRAFT
                and schedule.modality != Modality.ONLINE):
            _assert_draft_room_free(schedule, room, at_start, at_end, excluded)
        if schedule.modality != Modality.ONLINE and not room_is_free(
            room, at_start, at_end,
            exclude_session_id=(own_session.pk if own_session else None),
            exclude_schedule_id=excluded,
        ):
            raise ScheduleConflictError(
                f"The room is occupied on {occurrence_date} during that time.")


def _assert_draft_room_free(anchor, room, start, end, excluded):
    """Draft timetables reserve rooms within their own term before activation.

    Public availability intentionally considers only the active term. Validate
    this separate planning scope without making drafts reserve operational rooms.
    """
    day = timezone.localtime(start).date()
    candidates = list(Schedule.objects.filter(term=anchor.term,
        status=ScheduleStatus.ACTIVE).exclude(pk__in=excluded)
        .select_related("room__floor"))
    excused = excused_checker(anchor.term)
    for candidate in candidates:
        session = Session.objects.filter(schedule=candidate, date=day).first()
        if session:
            if (session.status not in (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)
                    or session.room_released_at is not None):
                continue
            candidate_start, candidate_end = session.scheduled_start, session.scheduled_end
            candidate_room = session.room_id
            online = (session.declared_modality or candidate.modality) == Modality.ONLINE
        else:
            if candidate.day_of_week != day.weekday():
                continue
            if excused(day, candidate.room.floor.building_id):
                continue
            shift = candidate.modality_items.filter(request__status="approved",
                request__window_start__lte=day, request__window_end__gte=day
            ).select_related("request").order_by("-request__decided_at", "-pk").first()
            candidate_room = (shift.assigned_room_id if shift else None) or candidate.room_id
            online = (shift.request.target_modality if shift else candidate.modality) == Modality.ONLINE
            moved = (shift is not None and shift.assigned_room_id is not None
                     and shift.new_start_time is not None and shift.new_end_time is not None)
            candidate_start = timezone.make_aware(timezone.datetime.combine(day,
                shift.new_start_time if moved else candidate.start_time))
            candidate_end = timezone.make_aware(timezone.datetime.combine(day,
                shift.new_end_time if moved else candidate.end_time))
        if (not online and candidate_room == room.pk
                and candidate_start < end and start < candidate_end):
            raise ScheduleConflictError(f"The room is occupied on {day} during that time.")


def _faculty_conflicts(anchor, faculty, room, start, end):
    """Return valid merge schedules or refuse faculty overlap, beyond horizon."""
    day = timezone.localtime(start).date()
    candidates = list(Schedule.objects.filter(term=anchor.term, faculty=faculty,
        status=ScheduleStatus.ACTIVE).exclude(pk=anchor.pk).select_related("room__floor"))
    merged = set()
    for candidate in candidates:
        session = Session.objects.filter(schedule=candidate, date=day).first()
        if session:
            if session.status not in (SessionStatus.SCHEDULED, SessionStatus.ACTIVE):
                continue
            candidate_start, candidate_end = session.scheduled_start, session.scheduled_end
            candidate_room = session.room_id
            online = (session.declared_modality or candidate.modality) == Modality.ONLINE
        else:
            if candidate.day_of_week != day.weekday():
                continue
            if excused_checker(anchor.term)(day, candidate.room.floor.building_id):
                continue
            shift = candidate.modality_items.filter(request__status="approved",
                request__window_start__lte=day, request__window_end__gte=day
            ).select_related("request").order_by("-request__decided_at", "-pk").first()
            candidate_start = timezone.make_aware(timezone.datetime.combine(day,
                (shift.new_start_time if shift else None) or candidate.start_time))
            candidate_end = timezone.make_aware(timezone.datetime.combine(day,
                (shift.new_end_time if shift else None) or candidate.end_time))
            candidate_room = (shift.assigned_room_id if shift else None) or candidate.room_id
            online = (shift.request.target_modality if shift else candidate.modality) == Modality.ONLINE
        if not (candidate_start < end and start < candidate_end):
            continue
        if candidate_start == start and (
            (online and anchor.modality == Modality.ONLINE)
            or (candidate_room == room.pk and
                (anchor.pk is None or room.pk == anchor.room_id))
            or candidate.course_code == anchor.course_code):
            merged.add(candidate.pk)
        else:
            raise ScheduleConflictError(f"The faculty member has another class on {day} during that time.")
    return merged


def _validate_fields(day_of_week, enrolled_count, start_time, end_time):
    if day_of_week not in range(7):
        raise ScheduleConflictError("Select a valid day of week.")
    if not isinstance(enrolled_count, int) or not 0 <= enrolled_count <= 2147483647:
        raise ScheduleConflictError("Enrollment must be a nonnegative whole number.")
    if end_time <= start_time:
        raise ScheduleConflictError("The end time must be after the start time.")


@serialized_write
def create_schedule(*, term, faculty, room, course_code, section, day_of_week,
                    start_time, end_time, enrolled_count=0, modality=Modality.F2F,
                    actor=None, today=None):
    term.refresh_from_db()
    require_writable_term(term)
    room = Room.objects.select_related("floor").get(pk=room.pk)
    _validate_fields(day_of_week, enrolled_count, start_time, end_time)
    schedule = Schedule(term=term, faculty=faculty, room=room,
        course_code=course_code, section=section, day_of_week=day_of_week,
        start_time=start_time, end_time=end_time, enrolled_count=enrolled_count,
        modality=modality, status=ScheduleStatus.ACTIVE)
    _assert_occurrences_free(schedule, room, start_time, end_time,
                             today or timezone.localdate(), faculty)
    schedule.save()
    AuditLog.objects.create(actor=actor, event_type="schedule.created",
        target_type="schedule", target_id=str(schedule.pk),
        payload={"course": course_code, "section": section, "room": room.code})
    return schedule


@serialized_write
def update_schedule(schedule, *, faculty=None, room=None, start_time=None,
                    end_time=None, enrolled_count=None, actor=None, today=None):
    """Apply an edit to a schedule and propagate it to future SCHEDULED sessions.

    Any of faculty / room / start_time / end_time / enrolled_count may be given;
    those left None are unchanged. Future SCHEDULED sessions follow the new
    instructor, room and times on their existing date (same weekday, so the date
    is untouched). A session that already differs from the old schedule carries an
    approved move, so it keeps its own room and time and takes only the instructor.
    Returns the count of future sessions actually changed.
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
    old_room_id = schedule.room_id
    old_start, old_end = schedule.start_time, schedule.end_time
    target_room = Room.objects.select_related("floor").get(pk=(room or schedule.room).pk)
    target_start = start_time or schedule.start_time
    target_end = end_time or schedule.end_time
    _validate_fields(schedule.day_of_week,
        enrolled_count if enrolled_count is not None else schedule.enrolled_count,
        target_start, target_end)
    if (target_room.pk != schedule.room_id
            or (faculty is not None and faculty.pk != schedule.faculty_id)
            or target_start != schedule.start_time
            or target_end != schedule.end_time):
        _assert_occurrences_free(
            schedule, target_room, target_start, target_end, today, faculty or schedule.faculty)
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
    sessions = list(_future_scheduled(schedule, today).select_for_update())
    updated = 0
    for s in sessions:
        changes = {}
        if s.faculty_id != schedule.faculty_id:
            changes["faculty"] = schedule.faculty
        if (s.room_id == old_room_id
                and timezone.localtime(s.scheduled_start).time() == old_start
                and timezone.localtime(s.scheduled_end).time() == old_end):
            new_start = timezone.make_aware(
                timezone.datetime.combine(s.date, schedule.start_time))
            new_end = timezone.make_aware(
                timezone.datetime.combine(s.date, schedule.end_time))
            if s.room_id != schedule.room_id:
                changes["room"] = schedule.room
            if s.scheduled_start != new_start or s.scheduled_end != new_end:
                changes["scheduled_start"] = new_start
                changes["scheduled_end"] = new_end
        if changes:
            updated += Session.objects.filter(
                pk=s.pk, status=SessionStatus.SCHEDULED).update(**changes)
    AuditLog.objects.create(
        actor=actor, event_type="schedule.updated",
        target_type="schedule", target_id=str(schedule.pk),
        payload={"before": before, "future_sessions_updated": updated})
    return updated


@serialized_write
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

    ids = list(_future_scheduled(schedule, today).select_for_update().values_list("pk", flat=True))
    if ids:
        Session.objects.filter(pk__in=ids, status=SessionStatus.SCHEDULED).update(
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

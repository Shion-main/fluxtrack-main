"""Explicit-term session materialization service."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from accounts.models import Role
from ops.notify import notify
from ops.occupancy import release_room
from scheduling.models import (
    AcademicTerm,
    Modality,
    ModalityShiftItem,
    ModalityShiftStatus,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from scheduling.suspensions import excused_checker


class MaterializationError(RuntimeError):
    """Raised when a term cannot be materialized through this entry point."""


@dataclass(frozen=True)
class MaterializationResult:
    created: int
    existing: int
    skipped: int


def _apply_approved_shift(session, schedule, date):
    """Apply an approved modality shift to a newly materialized session."""
    items = list(
        ModalityShiftItem.objects.filter(
            request__status=ModalityShiftStatus.APPROVED,
            schedule=schedule,
            request__window_start__lte=date,
            request__window_end__gte=date,
        )
        .select_related("request", "assigned_room")
        .order_by("-request__decided_at")
    )
    if not items:
        return

    item = items[0]
    request = item.request
    when = request.decided_at or timezone.now()

    if request.target_modality == Modality.ONLINE:
        session.declared_modality = Modality.ONLINE
        session.modality_changed_at = request.decided_at
        session.modality_changed_by = request.decided_by
        session.save(update_fields=[
            "declared_modality", "modality_changed_at", "modality_changed_by"])
        release_room(session, actor=request.decided_by, now=when)
        return

    if item.assigned_room is None:
        notify(
            role=Role.IFO_ADMIN, type="modality_materialize_no_room",
            title="Modality shift: no reserved room at materialize",
            body=(f"Session for {schedule} on {date} was born in its original "
                  f"room -- the approved shift had no reserved room."),
            link="/ifo",
        )
        session.declared_modality = request.target_modality
        session.modality_changed_at = request.decided_at
        session.modality_changed_by = request.decided_by
        session.save(update_fields=[
            "declared_modality", "modality_changed_at", "modality_changed_by"])
        return

    session.room = item.assigned_room
    session.declared_modality = request.target_modality
    session.modality_changed_at = request.decided_at
    session.modality_changed_by = request.decided_by
    fields = ["room", "declared_modality",
              "modality_changed_at", "modality_changed_by"]
    if item.new_start_time is not None and item.new_end_time is not None:
        session.scheduled_start = timezone.make_aware(
            datetime.combine(date, item.new_start_time))
        session.scheduled_end = timezone.make_aware(
            datetime.combine(date, item.new_end_time))
        fields += ["scheduled_start", "scheduled_end"]
    session.save(update_fields=fields)


def _validate_term(term, *, allow_draft):
    if term is None or term.pk is None:
        raise MaterializationError("materialization requires a persisted term")
    if term.status == AcademicTerm.Status.ARCHIVED:
        raise MaterializationError("ARCHIVED terms cannot be materialized")
    if term.status == AcademicTerm.Status.DRAFT and not allow_draft:
        raise MaterializationError("DRAFT terms cannot be materialized publicly")
    if term.status not in (AcademicTerm.Status.ACTIVE, AcademicTerm.Status.DRAFT):
        raise MaterializationError("term status cannot be materialized")


def materialize_term(term, *, start, days, allow_draft=False):
    """Create dated sessions for one explicit term.

    Public callers must pass an ACTIVE term. Lifecycle activation may pass its
    locked DRAFT with ``allow_draft=True`` so readiness setup can commit atomically
    with the status change.
    """
    _validate_term(term, allow_draft=allow_draft)
    if days < 1:
        raise MaterializationError("materialization days must be positive")

    raw_end = start + timedelta(days=days)
    current = max(start, term.start_date)
    end = min(raw_end, term.end_date + timedelta(days=1))
    if current >= end:
        return MaterializationResult(created=0, existing=0, skipped=0)

    excused = excused_checker(term)
    schedules = list(
        term.schedules.filter(status=ScheduleStatus.ACTIVE)
        .select_related("faculty", "room", "room__floor")
    )
    created = existing = skipped = 0

    while current < end:
        for schedule in schedules:
            if schedule.day_of_week != current.weekday():
                continue
            if excused(current, schedule.room.floor.building_id):
                skipped += 1
                continue
            scheduled_start = timezone.make_aware(
                datetime.combine(current, schedule.start_time))
            scheduled_end = timezone.make_aware(
                datetime.combine(current, schedule.end_time))
            session, was_created = Session.objects.get_or_create(
                schedule=schedule,
                date=current,
                defaults={
                    "faculty": schedule.faculty,
                    "room": schedule.room,
                    "scheduled_start": scheduled_start,
                    "scheduled_end": scheduled_end,
                    "status": SessionStatus.SCHEDULED,
                },
            )
            if was_created:
                _apply_approved_shift(session, schedule, current)
                created += 1
            else:
                existing += 1
        current += timedelta(days=1)

    return MaterializationResult(
        created=created,
        existing=existing,
        skipped=skipped,
    )

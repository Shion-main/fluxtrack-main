"""
Materialize dated Sessions from active Schedules (JOB-01 core logic).

For the active term, create one Session per Schedule per matching weekday within
the window, skipping dates inside an AcademicBreak and outside the term bounds.
Idempotent: re-running only fills gaps.

Usage:
    py -3.12 manage.py materialize_sessions --days 7
    py -3.12 manage.py materialize_sessions --from 2026-07-06 --days 14
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role
from ops.notify import notify
from ops.occupancy import release_room
from scheduling.models import (AcademicTerm, Modality, ModalityShiftItem,
                               ModalityShiftStatus, ScheduleStatus, Session,
                               SessionStatus)
from scheduling.suspensions import excused_checker


def _apply_approved_shift(session, schedule, date):
    """Born-released / born-assigned hook (MOD-03/MOD-04, D-04/D-18, Pitfall 1).

    The materializer is the ONLY creator of future sessions, so an approved
    modality-shift whose window extends past the ~14-day horizon must be applied
    HERE, at create time, to every out-of-horizon in-window session it covers.
    Called right after ``get_or_create`` ONLY when the session was just created
    (was_created True) -- re-running materialize never re-processes an existing
    session, so the hook is idempotent by construction.

    Looks up the APPROVED ModalityShiftItem covering ``(schedule, date)`` (its
    request status APPROVED and ``window_start <= date <= window_end``). Candidate
    items are ``list()``-materialized before any write (pyodbc single active
    result set, HY010). The latest decision wins on the (rare) overlap.

    ->Online (D-04): the session is born released -- ``declared_modality=Online``,
    ``modality_changed_at``/``_by`` from the decision, and ``release_room()``
    stamps ``room_released_at`` (the room FK is never nulled).

    ->F2F/Blended (D-18): the session is born in the item's already-reserved
    ``assigned_room`` (materialize APPLIES the reservation, it never re-resolves);
    a bundled time-move rewrites ``scheduled_start``/``_end`` to the new slot.
    Defensive guard (cannot fire in Phase 4 scope, Pitfall 2/A1): a missing
    ``assigned_room`` keeps the session in its original ``schedule.room`` and
    notifies IFO informationally -- the unattended job never raises.
    """
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

    # ->F2F / ->Blended: apply the reserved room (D-18), never re-resolve.
    if item.assigned_room is None:
        # Defensive guard (Pitfall 2/A1): keep the original room, notify IFO,
        # and continue -- an unattended materialize run must never crash.
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


class Command(BaseCommand):
    help = "Create dated sessions from active schedules (skips breaks)."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=7, help="Horizon in days (default 7)")
        p.add_argument("--from", dest="start", help="Start date YYYY-MM-DD (default today)")

    def handle(self, *args, **o):
        term = AcademicTerm.objects.filter(is_active=True).first()
        if not term:
            self.stderr.write(self.style.ERROR("No active term. Import first."))
            return

        start = (datetime.strptime(o["start"], "%Y-%m-%d").date()
                 if o["start"] else timezone.localdate())
        end = start + timedelta(days=o["days"])
        # Calendar excusal (Phase 9, A1): breaks AND active suspensions both
        # suppress materialization. `excused(d, building_id)` is the SAME shared
        # helper the sweep uses, so the two can never disagree on whether a date
        # is a class day. A building-scoped suspension only suppresses that
        # building's rooms, hence the per-schedule building_id check below.
        excused = excused_checker(term)

        schedules = (term.schedules.filter(status=ScheduleStatus.ACTIVE)
                     .select_related("faculty", "room", "room__floor"))
        created = existing = 0
        d = start
        while d < end:
            in_term = term.start_date <= d <= term.end_date
            if in_term:
                for sch in schedules:
                    if sch.day_of_week != d.weekday():
                        continue
                    if excused(d, sch.room.floor.building_id):
                        continue
                    ss = timezone.make_aware(datetime.combine(d, sch.start_time))
                    se = timezone.make_aware(datetime.combine(d, sch.end_time))
                    session, was_created = Session.objects.get_or_create(
                        schedule=sch, date=d,
                        defaults={"faculty": sch.faculty, "room": sch.room,
                                  "scheduled_start": ss, "scheduled_end": se,
                                  "status": SessionStatus.SCHEDULED})
                    if was_created:
                        # Born-released / born-assigned per any approved shift
                        # covering this (schedule, date) -- Pitfall 1 (D-04/D-18).
                        _apply_approved_shift(session, sch, d)
                    created += was_created
                    existing += not was_created
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"Materialized {start} -> {end}: {created} new sessions "
            f"({existing} already existed) from {schedules.count()} active schedules "
            f"in term '{term.name}'."))

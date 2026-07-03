"""Assignment apply layer (IFO-06): round-robin online-session pre-assignment.

Thin apply over the pure ``verification.resolver.distribute_online_sessions``
(03-01): gather a date's unowned online sessions and the active online-duty
Checkers, call the pure round-robin core, and write ``Session.online_checker``
(audited per assignment). The round-robin itself is NOT reimplemented here — the
decision is the pure core's; this module only fetches context and applies.

When no online-duty Checker exists for the date the sessions stay unowned
(``online_checker`` NULL) and IFO is flagged once via ``notify()`` rather than
guessing an owner (T-03-10). Each newly-assigned Checker is notified ONCE at
pre-assignment time — a write-only ``notify(users=[checker], type=online_assigned)``
that satisfies the amended CHK-02: the Notification row is written now; the read
surface that shows it to the Checker lands in Phase 5 (03-05's "Online to verify"
pull-list is the interim work queue).

MSSQL guard (T-03-11): candidate sessions are materialized with ``list()`` before
the write loop (never a streaming cursor), so the SELECT is closed before any
``save()``/AuditLog INSERT — mirroring ``scheduling/jobs.py`` (pyodbc single
active result set / HY010 "Function sequence error").
"""
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Role
from ops.models import AuditLog
from ops.notify import notify
from scheduling.models import Modality, Session
from verification import resolver as R
from verification.models import Assignment, AssignmentScope, DutyRole


def _candidate_online_sessions(target_date):
    """Unowned online sessions for ``target_date`` — MATERIALIZED (HY010 guard).

    Effective modality mirrors the resolver/sweep: ``declared_modality`` overrides
    ``schedule.modality``. ``online_checker`` NULL only (already-owned sessions are
    left alone so re-runs don't reshuffle). Ordered for a reproducible round-robin.
    """
    sessions = list(
        Session.objects.filter(date=target_date, online_checker__isnull=True)
        .select_related("schedule")
        .order_by("scheduled_start", "id"))
    return [s for s in sessions
            if (s.declared_modality or s.schedule.modality) == Modality.ONLINE]


def _online_duty_checker_ids(target_date):
    """Distinct, ordered user ids of active online-duty Checkers for ``target_date``.

    An ONLINE-scope CHECKER assignment is eligible when it is a standing posting
    (``date`` NULL) or dated to ``target_date``. Ordered by user id so the pure
    round-robin is deterministic across runs.
    """
    return list(
        Assignment.objects
        .filter(role=DutyRole.CHECKER, scope=AssignmentScope.ONLINE, status="active")
        .filter(Q(date__isnull=True) | Q(date=target_date))
        .order_by("user_id")
        .values_list("user_id", flat=True)
        .distinct())


def assign_online_sessions(target_date, now=None):
    """Round-robin online sessions for ``target_date`` to online-duty Checkers.

    Returns ``{"assigned": int, "unassigned": int}``. Empty online roster with
    candidate sessions -> leave ``online_checker`` NULL, flag IFO once, and count
    them unassigned. Otherwise write each owner (audited) and notify each assigned
    Checker once. Pure round-robin is delegated to ``R.distribute_online_sessions``.
    """
    now = now or timezone.now()
    sessions = _candidate_online_sessions(target_date)   # materialized first
    if not sessions:
        return {"assigned": 0, "unassigned": 0}

    checker_ids = _online_duty_checker_ids(target_date)
    mapping = R.distribute_online_sessions([s.id for s in sessions], checker_ids)

    if not mapping:
        # No online-duty Checker -> do not guess an owner. Leave NULL, flag IFO.
        notify(role=Role.IFO_ADMIN, type="online_unassigned",
               title="Online sessions unassigned",
               body=f"{len(sessions)} online session(s) for {target_date} have no "
                    f"online-duty Checker. Assign online duty to cover them.")
        return {"assigned": 0, "unassigned": len(sessions)}

    assigned_counts = {}   # checker_id -> number of sessions assigned this run
    for s in sessions:
        checker_id = mapping.get(s.id)
        if checker_id is None:
            continue
        with transaction.atomic():
            s.online_checker_id = checker_id
            s.save(update_fields=["online_checker"])
            AuditLog.objects.create(
                actor=None, event_type="session.online_checker_assigned",
                target_type="session", target_id=str(s.pk),
                payload={"checker_id": checker_id})
        assigned_counts[checker_id] = assigned_counts.get(checker_id, 0) + 1

    # One summary Notification per Checker (write-only CHK-02; read surface Phase 5).
    User = get_user_model()
    for checker_id, count in assigned_counts.items():
        checker = User.objects.filter(pk=checker_id).first()
        if checker is None:
            continue
        notify(users=[checker], type="online_assigned",
               title="Online sessions to verify",
               body=f"{count} online session(s) assigned to you for {target_date}",
               link="/checker/online")

    assigned = sum(assigned_counts.values())
    return {"assigned": assigned, "unassigned": len(sessions) - assigned}

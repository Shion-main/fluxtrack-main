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


def _online_duty_assignments(target_date):
    """Active ONLINE-scope CHECKER assignments in play for ``target_date``.

    A standing posting (``date`` NULL) or one dated to ``target_date``. Ordered by
    user id so the derived round-robin pool is deterministic across runs. The
    shift window (``start_time``/``end_time``) is intentionally NOT filtered here:
    per-session eligibility is applied against each session's ``scheduled_start``
    in ``assign_online_sessions`` (CR-05), mirroring ``web/checker._is_online_on_duty``.
    """
    return list(
        Assignment.objects
        .filter(role=DutyRole.CHECKER, scope=AssignmentScope.ONLINE, status="active")
        .filter(Q(date__isnull=True) | Q(date=target_date))
        .order_by("user_id"))


def assign_online_sessions(target_date):
    """Round-robin online sessions for ``target_date`` to online-duty Checkers.

    Returns ``{"assigned": int, "unassigned": int}``. Eligibility is window-aware
    (CR-05): a session is only assignable to a Checker whose ONLINE posting covers
    that session's ``scheduled_start`` — a standing posting covers all, a dated
    shift only its window — mirroring the real-time ``_is_online_on_duty`` gate so
    a Checker is never handed a session they could never verify. Sessions no
    Checker's window covers stay unowned (``online_checker`` NULL) so the sweep /
    IFO path still surfaces them rather than silently owning them.

    Empty roster (no covering Checker at all) -> leave NULL, flag IFO once, count
    them unassigned. Otherwise write each owner (audited) and notify each assigned
    Checker once. Pure round-robin is delegated to ``R.distribute_online_sessions``.
    """
    sessions = _candidate_online_sessions(target_date)   # materialized first
    if not sessions:
        return {"assigned": 0, "unassigned": 0}

    assignments = _online_duty_assignments(target_date)

    # Per-session eligible-checker pools by shift window, then round-robin WITHIN
    # each identical pool (grouping keeps the pure distributor's determinism and
    # even split). A session whose pool is empty is left unowned.
    mapping = {}
    groups = {}   # ordered eligible-id tuple -> [session_id, ...] in input order
    for s in sessions:
        s_local = timezone.localtime(s.scheduled_start)
        s_day, s_t = s_local.date(), s_local.time()
        eligible = tuple(sorted(
            {a.user_id for a in assignments
             if R.assignment_covers_now(a, s_day, s_t)}))
        groups.setdefault(eligible, []).append(s.id)
    for eligible, session_ids in groups.items():
        if not eligible:
            continue                                 # no covering Checker -> NULL
        mapping.update(R.distribute_online_sessions(session_ids, list(eligible)))

    if not mapping:
        # No Checker's window covers any session -> do not guess an owner. Leave
        # NULL, flag IFO once (preserves the empty-roster behavior).
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

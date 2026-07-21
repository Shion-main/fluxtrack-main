"""Transactional academic-term lifecycle services."""

from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import Role
from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.materialization import materialize_term
from scheduling.models import AcademicTerm, Session, SessionStatus


@dataclass(frozen=True)
class TermPreflight:
    action: str
    candidate_name: str = ""
    term_id: int | None = None
    term_name: str = ""
    start_date: object | None = None
    end_date: object | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)


class TermLifecycleError(RuntimeError):
    def __init__(self, message, *, blockers=(), warnings=(), preflight=None):
        super().__init__(message)
        self.blockers = tuple(blockers)
        self.warnings = tuple(warnings)
        self.preflight = preflight


def _normalize_name(name):
    return " ".join((name or "").split())


def _authorize(actor):
    if actor is None:
        raise TermLifecycleError("term lifecycle action requires an actor",
                                 blockers=("unauthorized",))
    if getattr(actor, "is_superuser", False):
        return
    if getattr(actor, "role", None) == Role.IFO_ADMIN:
        return
    raise TermLifecycleError("only IFO Admins can manage academic terms",
                             blockers=("unauthorized",))


def _creation_preflight_from_rows(*, name, start_date, end_date, rows):
    normalized = _normalize_name(name)
    blockers = []
    counts = {
        "duplicate_terms": 0,
        "overlapping_terms": 0,
        "schedule_count": 0,
        "session_count": 0,
    }

    if not normalized:
        blockers.append("name_required")
    if start_date is None or end_date is None:
        blockers.append("dates_required")
    elif end_date < start_date:
        blockers.append("date_order")

    if normalized:
        duplicate_terms = [
            term for term in rows
            if _normalize_name(term.name).casefold() == normalized.casefold()
        ]
        counts["duplicate_terms"] = len(duplicate_terms)
        if duplicate_terms:
            blockers.append("duplicate_name")

    if start_date is not None and end_date is not None:
        overlapping_terms = [
            term for term in rows
            if term.start_date <= end_date and term.end_date >= start_date
        ]
        counts["overlapping_terms"] = len(overlapping_terms)
        if overlapping_terms:
            blockers.append("overlapping_term")

    return TermPreflight(
        action="create",
        candidate_name=normalized,
        start_date=start_date,
        end_date=end_date,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=(),
        counts=counts,
    )


def preflight_term_creation(*, actor, name, start_date, end_date):
    _authorize(actor)
    rows = list(AcademicTerm.objects.all())
    return _creation_preflight_from_rows(
        name=name, start_date=start_date, end_date=end_date, rows=rows
    )


def create_term(*, actor, name, start_date, end_date, confirmation_name):
    with transaction.atomic():
        _authorize(actor)
        rows = list(AcademicTerm.objects.select_for_update().all())
        preflight = _creation_preflight_from_rows(
            name=name, start_date=start_date, end_date=end_date, rows=rows
        )
        normalized_confirmation = _normalize_name(confirmation_name)
        if normalized_confirmation != preflight.candidate_name:
            blockers = preflight.blockers + ("confirmation_mismatch",)
            raise TermLifecycleError(
                "confirmation must exactly match the proposed term name",
                blockers=blockers,
                preflight=preflight,
            )
        if preflight.blockers:
            raise TermLifecycleError(
                "term creation preflight has blockers",
                blockers=preflight.blockers,
                preflight=preflight,
            )

        term = AcademicTerm.objects.create(
            name=preflight.candidate_name,
            start_date=start_date,
            end_date=end_date,
            status=AcademicTerm.Status.DRAFT,
        )
        schedule_count = term.schedules.count()
        session_count = Session.objects.filter(schedule__term=term).count()
        AuditLog.objects.create(
            actor=actor,
            event_type="term.created",
            target_type="academic_term",
            target_id=str(term.pk),
            payload={
                "reason": None,
                "before": None,
                "after": AcademicTerm.Status.DRAFT,
                "name": term.name,
                "start_date": term.start_date.isoformat(),
                "end_date": term.end_date.isoformat(),
                "schedule_count": schedule_count,
                "session_count": session_count,
            },
        )
        return term


def _term_counts(term):
    schedule_count = term.schedules.count()
    sessions = Session.objects.filter(schedule__term=term)
    return {
        "schedule_count": schedule_count,
        "session_count": sessions.count(),
        "active_session_count": sessions.filter(status=SessionStatus.ACTIVE).count(),
        "scheduled_session_count": sessions.filter(
            status=SessionStatus.SCHEDULED
        ).count(),
    }


def _action_preflight(term, *, action, today):
    counts = _term_counts(term)
    blockers = []
    warnings = []

    if action == "close":
        if term.status != AcademicTerm.Status.ACTIVE:
            blockers.append("not_active")
        if today < term.end_date:
            blockers.append("before_end_date")
        if counts["active_session_count"]:
            blockers.append("active_sessions")
        if counts["scheduled_session_count"]:
            warnings.append("scheduled_sessions_present")
    elif action == "reopen":
        if term.status != AcademicTerm.Status.ARCHIVED:
            blockers.append("not_archived")
        active_successor_exists = AcademicTerm.objects.filter(
            status=AcademicTerm.Status.ACTIVE
        ).exclude(pk=term.pk).exists()
        if active_successor_exists:
            warnings.append("active_successor_exists")
    elif action == "activate":
        if term.status != AcademicTerm.Status.DRAFT:
            blockers.append("not_draft")
        if term.end_date < term.start_date:
            blockers.append("date_order")
        another_active = AcademicTerm.objects.filter(
            status=AcademicTerm.Status.ACTIVE
        ).exclude(pk=term.pk).exists()
        if another_active:
            blockers.append("another_active")
        if counts["schedule_count"] == 0:
            warnings.append("empty_schedule_set")
    else:
        blockers.append("unknown_action")

    return TermPreflight(
        action=action,
        term_id=term.pk,
        term_name=term.name,
        start_date=term.start_date,
        end_date=term.end_date,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        counts=counts,
    )


def preflight_term_action(term_id, action, actor, today=None):
    _authorize(actor)
    today = today or timezone.localdate()
    term = AcademicTerm.objects.get(pk=term_id)
    return _action_preflight(term, action=action, today=today)


def _validate_common_action_inputs(term, *, preflight, confirmation_name, reason,
                                   acknowledged_warnings):
    blockers = list(preflight.blockers)
    if (confirmation_name or "") != term.name:
        blockers.append("confirmation_mismatch")
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        blockers.append("reason_required")

    acknowledged = set(acknowledged_warnings or ())
    current = set(preflight.warnings)
    if acknowledged != current:
        blockers.append("warnings_unacknowledged")

    if blockers:
        raise TermLifecycleError(
            "term lifecycle action has blockers",
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=preflight.warnings,
            preflight=preflight,
        )
    return normalized_reason, tuple(preflight.warnings)


def _validate_activation_inputs(term, *, preflight, confirmation_name,
                                acknowledged_warnings):
    blockers = list(preflight.blockers)
    if (confirmation_name or "") != term.name:
        blockers.append("confirmation_mismatch")

    acknowledged = set(acknowledged_warnings or ())
    current = set(preflight.warnings)
    if acknowledged != current:
        blockers.append("warnings_unacknowledged")

    if blockers:
        raise TermLifecycleError(
            "term activation has blockers",
            blockers=tuple(dict.fromkeys(blockers)),
            warnings=preflight.warnings,
            preflight=preflight,
        )
    return tuple(preflight.warnings)


def close_term(term_id, *, actor, confirmation_name, reason,
               acknowledged_warnings=(), today=None):
    today = today or timezone.localdate()
    with transaction.atomic():
        _authorize(actor)
        term = AcademicTerm.objects.select_for_update().get(pk=term_id)
        preflight = _action_preflight(term, action="close", today=today)
        normalized_reason, acknowledged = _validate_common_action_inputs(
            term,
            preflight=preflight,
            confirmation_name=confirmation_name,
            reason=reason,
            acknowledged_warnings=acknowledged_warnings,
        )

        before = term.status
        term.status = AcademicTerm.Status.ARCHIVED
        term.save(update_fields=["status"])
        AuditLog.objects.create(
            actor=actor,
            event_type="term.archived",
            target_type="academic_term",
            target_id=str(term.pk),
            payload={
                "reason": normalized_reason,
                "before": before,
                "after": AcademicTerm.Status.ARCHIVED,
                "schedule_count": preflight.counts["schedule_count"],
                "session_count": preflight.counts["session_count"],
                "active_session_count": preflight.counts["active_session_count"],
                "acknowledged_warning_keys": list(acknowledged),
            },
        )
        return term


def reopen_term(term_id, *, actor, confirmation_name, reason,
                acknowledged_warnings=(), today=None):
    today = today or timezone.localdate()
    with transaction.atomic():
        _authorize(actor)
        term = AcademicTerm.objects.select_for_update().get(pk=term_id)
        preflight = _action_preflight(term, action="reopen", today=today)
        normalized_reason, acknowledged = _validate_common_action_inputs(
            term,
            preflight=preflight,
            confirmation_name=confirmation_name,
            reason=reason,
            acknowledged_warnings=acknowledged_warnings,
        )

        before = term.status
        term.status = AcademicTerm.Status.DRAFT
        term.save(update_fields=["status"])
        AuditLog.objects.create(
            actor=actor,
            event_type="term.reopened",
            target_type="academic_term",
            target_id=str(term.pk),
            payload={
                "reason": normalized_reason,
                "before": before,
                "after": AcademicTerm.Status.DRAFT,
                "schedule_count": preflight.counts["schedule_count"],
                "session_count": preflight.counts["session_count"],
                "active_session_count": preflight.counts["active_session_count"],
                "acknowledged_warning_keys": list(acknowledged),
            },
        )
        return term


def activate_term(term_id, *, actor, confirmation_name,
                  acknowledged_warnings=(), today=None):
    today = today or timezone.localdate()
    try:
        with transaction.atomic():
            _authorize(actor)
            term = AcademicTerm.objects.select_for_update().get(pk=term_id)
            list(
                AcademicTerm.objects.select_for_update()
                .filter(status=AcademicTerm.Status.ACTIVE)
                .exclude(pk=term.pk)
            )
            preflight = _action_preflight(term, action="activate", today=today)
            acknowledged = _validate_activation_inputs(
                term,
                preflight=preflight,
                confirmation_name=confirmation_name,
                acknowledged_warnings=acknowledged_warnings,
            )

            horizon_days = int(get_policy("materialization_horizon_days"))
            materialization_start = max(today, term.start_date)
            result = materialize_term(
                term,
                start=materialization_start,
                days=horizon_days,
                allow_draft=True,
            )

            before = term.status
            term.status = AcademicTerm.Status.ACTIVE
            term.save(update_fields=["status"])
            AuditLog.objects.create(
                actor=actor,
                event_type="term.activated",
                target_type="academic_term",
                target_id=str(term.pk),
                payload={
                    "reason": None,
                    "before": before,
                    "after": AcademicTerm.Status.ACTIVE,
                    "horizon_days": horizon_days,
                    "materialization_start": materialization_start.isoformat(),
                    "materialization": {
                        "created": result.created,
                        "existing": result.existing,
                        "skipped": result.skipped,
                    },
                    "schedule_count": preflight.counts["schedule_count"],
                    "session_count": (
                        preflight.counts["session_count"] + result.created
                    ),
                    "acknowledged_warning_keys": list(acknowledged),
                },
            )
            return term
    except IntegrityError as exc:
        if AcademicTerm.objects.filter(
            status=AcademicTerm.Status.ACTIVE
        ).exclude(pk=term_id).exists():
            raise TermLifecycleError(
                "another academic term is already active",
                blockers=("another_active",),
            ) from exc
        raise

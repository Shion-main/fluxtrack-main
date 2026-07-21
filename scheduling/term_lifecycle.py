"""Transactional academic-term lifecycle services."""

from dataclasses import dataclass, field

from django.db import transaction

from accounts.models import Role
from ops.models import AuditLog
from scheduling.models import AcademicTerm, Session


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

"""Authoritative academic-term scope primitives."""

from scheduling.models import AcademicTerm


class NoActiveTermError(RuntimeError):
    """Raised when a caller requires the single ACTIVE term and none exists."""


class ArchivedTermError(RuntimeError):
    """Raised when a caller attempts to write through an archived term."""


def get_active_term():
    """Return the unique ACTIVE term, or None when no term is active."""
    try:
        return AcademicTerm.objects.get(status=AcademicTerm.Status.ACTIVE)
    except AcademicTerm.DoesNotExist:
        return None


def require_active_term():
    term = get_active_term()
    if term is None:
        raise NoActiveTermError("no active academic term")
    return term


def require_writable_term(term):
    if term.status == AcademicTerm.Status.ARCHIVED:
        raise ArchivedTermError("archived academic terms are read-only")
    return term

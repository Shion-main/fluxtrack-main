"""Django Admin guards for term-owned records."""

from django.core.exceptions import PermissionDenied

from scheduling.models import AcademicTerm
from scheduling.term_scope import ArchivedTermError, require_writable_term


def owning_term(obj, *, mapper=None):
    """Return an object's AcademicTerm, refusing ambiguous ownership."""
    if mapper is not None:
        term = mapper(obj)
    elif isinstance(obj, AcademicTerm):
        term = obj
    elif hasattr(obj, "term_id"):
        term = obj.term if obj.term_id else None
    elif hasattr(obj, "schedule_id"):
        term = obj.schedule.term if obj.schedule_id else None
    elif hasattr(obj, "session_id"):
        term = obj.session.schedule.term if obj.session_id else None
    else:
        raise PermissionDenied("This record has no configured academic-term owner.")

    if term is None:
        raise PermissionDenied("This record has no unambiguous academic-term owner.")
    return term


def require_admin_writable_object(obj, *, mapper=None):
    """Refuse Admin mutation when the object's owning term is archived."""
    try:
        return require_writable_term(owning_term(obj, mapper=mapper))
    except ArchivedTermError as exc:
        raise PermissionDenied("Archived academic-term records are read-only.") from exc


class TermOwnedAdminGuardMixin:
    """Guard Admin save, single-delete, and bulk-delete mutation seams."""

    term_owner_mapper = None

    def _require_writable(self, obj):
        return require_admin_writable_object(obj, mapper=self.term_owner_mapper)

    def save_model(self, request, obj, form, change):
        self._require_writable(obj)
        return super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        self._require_writable(obj)
        return super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        objects = list(queryset)
        for obj in objects:
            self._require_writable(obj)
        return super().delete_queryset(
            request, queryset.filter(pk__in=[obj.pk for obj in objects])
        )

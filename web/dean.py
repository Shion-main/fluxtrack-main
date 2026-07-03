"""Dean approval surface (MOD-02, D-12): a department-scoped pending-approval
queue with approve/reject POST actions wired to the 04-05 apply/reject services.

The queue is scoped strictly to the Dean's OWN department (D-09/D-12): a request
routed to another department is never listed here. Every decision is POST-only
and re-gated server-side INSIDE the service transaction -- ``apply_approval`` and
``reject_modality_shift`` each re-check Role.DEAN + request.department ==
dean.department + status == PENDING before any write (Pitfall 6 / 03-02 re-gate,
T-04-01/T-04-03). The view NEVER mutates state directly: the service owns the
transaction, the availability re-check, the audit, and the notifications. A
no-room ->F2F approval is surfaced by the service as a terminal DENIED (D-07
REVISED); the view simply re-renders the queue with the returned outcome message.

Clones the established web/ifo.py role-gate + validated-POST shape and mirrors the
04-07 faculty surface (web/faculty.py) for consistency. ASCII-only by convention
(Windows cp1252).
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from accounts.models import Role
from scheduling.models import ModalityShiftRequest, ModalityShiftStatus


def dean_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.DEAN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _queue_ctx(user, *, error=None, message=None):
    """Context for the department-scoped pending-approval queue (D-12).

    Scoped strictly to PENDING requests of the Dean's OWN department -- a request
    routed to another department is NEVER listed (MOD-02/D-09). Each row carries
    the requester, target modality, window, affected schedules (with any bundled
    time-move) and the faculty's preferred room, prefetched so the template makes
    no per-row queries.
    """
    requests = (
        ModalityShiftRequest.objects
        .filter(status=ModalityShiftStatus.PENDING, department=user.department)
        .select_related("requester", "department")
        .prefetch_related("items__schedule__room", "items__preferred_room")
        .order_by("created_at")
    )
    return {"requests": requests, "error": error, "message": message}


@dean_required
def queue(request):
    """The Dean's department-scoped pending-approval queue (MOD-02/D-12).

    Read-only list behind the dean_required gate; the decision actions are the
    separate POST-only approve/reject views. Requests from any other department
    are excluded server-side (never merely hidden)."""
    return render(request, "dean/queue.html", _queue_ctx(request.user))

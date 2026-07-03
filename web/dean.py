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
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from scheduling.models import ModalityShiftRequest, ModalityShiftStatus
from scheduling.services import (
    ModalityShiftError,
    apply_approval,
    reject_modality_shift,
)


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


@dean_required
@require_http_methods(["POST"])
def approve(request, pk):
    """Approve a PENDING request, applying the room release/assign consequence.

    POST-only; the guard is DELEGATED to ``apply_approval`` which re-fetches the
    request inside ``transaction.atomic()`` and re-checks Dean role + same
    department + PENDING before any write (never an earlier snapshot -- the IDOR /
    TOCTOU re-gate, T-04-01/T-04-03). A cross-department or non-pending approve
    raises ``ModalityShiftError`` and re-renders the queue at 400 with nothing
    changed. A ->F2F approval with no free room returns a terminal DENIED request
    (D-07 REVISED): the queue re-renders with the denial reason and the session is
    provably unchanged -- never surfaced as success (T-04-07). The view NEVER
    mutates state itself: the service owns the transaction, audit, and notifies."""
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    error = None
    message = None
    try:
        result = apply_approval(req, request.user)
    except ModalityShiftError as exc:
        error = str(exc)
    else:
        if result.status == ModalityShiftStatus.DENIED:
            message = (result.decision_reason
                       or "No room available that day - request denied.")
        else:
            message = "Request approved."
    ctx = _queue_ctx(request.user, error=error, message=message)
    return render(request, "dean/_queue.html", ctx,
                  status=400 if error else 200)


@dean_required
@require_http_methods(["POST"])
def reject(request, pk):
    """Reject a PENDING request with a required reason (MOD-02/D-10/D-11).

    POST-only; a non-empty reason is required (rendered at 400 otherwise -- the
    T-04-05v input-validation guard, mirroring ifo.assignment_create). The guard is
    delegated to ``reject_modality_shift`` which re-checks Dean role + same
    department + PENDING inside its transaction and notifies the requester once;
    the view never mutates state itself."""
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    reason = (request.POST.get("reason") or "").strip()
    error = None
    message = None
    if not reason:
        error = "A reason is required to reject a request."
    else:
        try:
            reject_modality_shift(req, request.user, reason)
        except ModalityShiftError as exc:
            error = str(exc)
        else:
            message = "Request rejected."
    ctx = _queue_ctx(request.user, error=error, message=message)
    return render(request, "dean/_queue.html", ctx,
                  status=400 if error else 200)

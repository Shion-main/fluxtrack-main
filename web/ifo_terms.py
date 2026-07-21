"""High-friction IFO academic-term lifecycle controllers."""

from django.contrib import messages
from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from scheduling.models import AcademicTerm
from scheduling.term_lifecycle import (
    TermLifecycleError,
    activate_term,
    close_term,
    create_term,
    preflight_term_action,
    preflight_term_creation,
    reopen_term,
)
from web.ifo import ifo_required


_STATUS_ORDER = Case(
    When(status=AcademicTerm.Status.ACTIVE, then=Value(0)),
    When(status=AcademicTerm.Status.DRAFT, then=Value(1)),
    When(status=AcademicTerm.Status.ARCHIVED, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)

_BLOCKER_COPY = {
    "not_active": "Only the Active term can be closed.",
    "before_end_date": "The term cannot close before its end date.",
    "active_sessions": "Active sessions must finish before this term can close.",
    "not_archived": "Only an Archived term can be reopened.",
    "not_draft": "Only a Draft term can be activated.",
    "date_order": "The term dates are not ordered.",
    "another_active": "Another term is Active. Close it in a separate request first.",
    "confirmation_mismatch": "The typed name does not exactly match this term.",
    "reason_required": "A reason is required for this action.",
    "warnings_unacknowledged": "Every current warning must be acknowledged.",
}
_WARNING_COPY = {
    "empty_schedule_set": "This Draft has no recurring schedules.",
    "scheduled_sessions_present": "Scheduled sessions remain and will be preserved.",
    "active_successor_exists": "A newer term is Active and will remain unchanged.",
}


def _term_queryset():
    return AcademicTerm.objects.annotate(
        schedule_count=Count("schedules", distinct=True),
        session_count=Count("schedules__sessions", distinct=True),
    )


def _creation_fields(request):
    return {
        "name": request.POST.get("name", ""),
        "start_date": request.POST.get("start_date", ""),
        "end_date": request.POST.get("end_date", ""),
    }


def _creation_preflight(request, fields):
    return preflight_term_creation(
        actor=request.user,
        name=fields["name"],
        start_date=parse_date(fields["start_date"]),
        end_date=parse_date(fields["end_date"]),
    )


@ifo_required
@require_http_methods(["GET"])
def terms_list(request):
    terms = _term_queryset().order_by(_STATUS_ORDER, "-start_date", "-pk")
    return render(request, "ifo/terms.html", {"terms": terms})


@ifo_required
@require_http_methods(["GET", "POST"])
def term_create(request):
    if request.method == "GET":
        return render(request, "ifo/term_form.html", {"form": {}})

    fields = _creation_fields(request)
    step = request.POST.get("step", "details")
    if step != "confirm":
        preflight = _creation_preflight(request, fields)
        return render(request, "ifo/term_form.html", {
            "form": fields,
            "preflight": preflight,
            "confirmation_name": "",
        })

    try:
        term = create_term(
            actor=request.user,
            name=fields["name"],
            start_date=parse_date(fields["start_date"]),
            end_date=parse_date(fields["end_date"]),
            confirmation_name=request.POST.get("confirmation_name", ""),
        )
    except TermLifecycleError as exc:
        preflight = _creation_preflight(request, fields)
        return render(request, "ifo/term_form.html", {
            "form": fields,
            "preflight": preflight,
            "confirmation_name": "",
            "error": str(exc),
            "refusal_blockers": exc.blockers,
        }, status=400)
    except RuntimeError:
        # The service transaction has already rolled back the term when its
        # atomic audit write fails. Keep the operator on a fresh, read-only
        # preflight and never expose backend exception text.
        preflight = _creation_preflight(request, fields)
        return render(request, "ifo/term_form.html", {
            "form": fields,
            "preflight": preflight,
            "confirmation_name": "",
            "error": "The term could not be committed. No term was created.",
        }, status=400)

    messages.success(request, f"Draft term {term.name} created.")
    return redirect("ifo_term_detail", pk=term.pk)


@ifo_required
@require_http_methods(["GET"])
def term_detail(request, pk):
    term = get_object_or_404(_term_queryset(), pk=pk)
    actions = []
    if term.status == AcademicTerm.Status.DRAFT:
        actions.append(("Activate", "activate"))
    elif term.status == AcademicTerm.Status.ACTIVE:
        actions.append(("Close and archive", "close"))
    elif term.status == AcademicTerm.Status.ARCHIVED:
        actions.append(("Reopen as Draft", "reopen"))
    return render(request, "ifo/term_detail.html", {
        "term": term,
        "actions": actions,
    })


def _action_context(term, action, preflight, *, error="", refusal_blockers=()):
    return {
        "term": term,
        "action": action,
        "action_label": {
            "activate": "Activate term",
            "close": "Close and archive term",
            "reopen": "Reopen as Draft",
        }[action],
        "preflight": preflight,
        "needs_reason": action in {"close", "reopen"},
        "blocker_rows": [
            (key, _BLOCKER_COPY.get(key, key.replace("_", " ")))
            for key in preflight.blockers
        ],
        "warning_rows": [
            (key, _WARNING_COPY.get(key, key.replace("_", " ")))
            for key in preflight.warnings
        ],
        "error": error,
        "refusal_rows": [
            (key, _BLOCKER_COPY.get(key, key.replace("_", " ")))
            for key in refusal_blockers
        ],
    }


def _term_action(request, pk, action):
    term = get_object_or_404(AcademicTerm, pk=pk)
    preflight = preflight_term_action(pk, action, actor=request.user)
    if request.method == "GET":
        return render(
            request,
            "ifo/term_action.html",
            _action_context(term, action, preflight),
        )

    common = {
        "actor": request.user,
        "confirmation_name": request.POST.get("confirmation_name", ""),
        "acknowledged_warnings": request.POST.getlist("acknowledged_warnings"),
    }
    try:
        if action == "activate":
            changed = activate_term(pk, **common)
        elif action == "close":
            changed = close_term(pk, reason=request.POST.get("reason", ""), **common)
        else:
            changed = reopen_term(pk, reason=request.POST.get("reason", ""), **common)
    except TermLifecycleError as exc:
        # Display state is never authority. Re-run the service preflight after
        # every refusal so the 400 page reflects the state that blocked POST.
        term.refresh_from_db()
        fresh = preflight_term_action(pk, action, actor=request.user)
        return render(request, "ifo/term_action.html", _action_context(
            term,
            action,
            fresh,
            error=str(exc),
            refusal_blockers=exc.blockers,
        ), status=400)

    messages.success(request, {
        "activate": f"{changed.name} is now Active.",
        "close": f"{changed.name} was closed and archived.",
        "reopen": f"{changed.name} was reopened as Draft.",
    }[action])
    return redirect("ifo_term_detail", pk=changed.pk)


@ifo_required
@require_http_methods(["GET", "POST"])
def term_activate(request, pk):
    return _term_action(request, pk, "activate")


@ifo_required
@require_http_methods(["GET", "POST"])
def term_close(request, pk):
    return _term_action(request, pk, "close")


@ifo_required
@require_http_methods(["GET", "POST"])
def term_reopen(request, pk):
    return _term_action(request, pk, "reopen")

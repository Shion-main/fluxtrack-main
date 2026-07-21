"""High-friction IFO academic-term lifecycle controllers."""

from django.contrib import messages
from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from scheduling.models import AcademicTerm
from scheduling.term_lifecycle import (
    TermLifecycleError,
    create_term,
    preflight_term_creation,
)
from web.ifo import ifo_required


_STATUS_ORDER = Case(
    When(status=AcademicTerm.Status.ACTIVE, then=Value(0)),
    When(status=AcademicTerm.Status.DRAFT, then=Value(1)),
    When(status=AcademicTerm.Status.ARCHIVED, then=Value(2)),
    default=Value(3),
    output_field=IntegerField(),
)


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

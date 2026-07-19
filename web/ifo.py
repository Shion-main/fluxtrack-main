"""IFO Admin surfaces: rooms list, per-room schedule (IFO-11), QR poster (IFO-01),
and a live 'today' view (IFO-07, htmx-polled)."""
import io
from datetime import timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.codes import new_room_credentials
from campus.models import Floor, Room
from campus.services import room_delete_blockers
from ops.models import AuditLog, WeeklyReport
from ops.policy import get_policy
from scheduling.models import (AcademicTerm, DayOfWeek, Modality, Schedule,
                                ScheduleStatus, Session)
from scheduling.report_render import build_csv
from scheduling.reporting import (dept_summary, faculty_attendance,
                                  faculty_scorecard, safe_card)
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 DutyRole)
from verification.services import assign_online_sessions
from web.pagination import paginate
from web.room_state import (ROOM_PROBLEM_STATES, ROOM_STATE_ORDER, occupies,
                            room_tile)
from web.reporting_common import reporting_range as _reporting_range


def ifo_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.IFO_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


# --- Live room board (IFO-07 + IFO-11, merged) ------------------------------
# The board replaces the old session-list "Live today" surface. A session list
# grows unbounded and mixes finished classes with running ones, so it answers
# "what happened today" instead of "is anything wrong right now". Rooms are the
# fixed, physically-managed entity, so the room is the tile and the session is
# what flows through it.
#
# The five-state derivation itself lives in `web/room_state.py` because the Guard
# surfaces (GRD-01/GRD-02) derive the same states from the same rules; see that
# module for the state list, the online-occupancy rule and the grace rule.


def _room_board(scope="live"):
    """Build the grouped room board. Two queries regardless of room count."""
    now = timezone.now()
    grace = timedelta(minutes=int(get_policy("grace_minutes")))

    rooms = list(Room.objects.select_related("floor__building")
                 .order_by("floor__building__code", "floor__number", "code"))
    by_room = {}
    for s in (Session.objects.filter(date=timezone.localdate())
              .select_related("schedule", "faculty")
              .order_by("scheduled_start")):
        by_room.setdefault(s.room_id, []).append(s)

    groups, buildings, totals = [], [], {"rooms": 0, "problems": 0, "hidden": 0}
    for room in rooms:
        tile = room_tile(room, by_room.get(room.id, []), now, grace)
        # "Live" hides rooms with nothing on today; "All" is the full inventory
        # (QR posters, capacity) and keeps them.
        if scope == "live" and tile["state"] == "idle":
            totals["hidden"] += 1
            continue

        building = room.floor.building
        label = f"{building.code} · Floor {room.floor.number}"
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "building": building.code,
                           "floor": room.floor.number, "tiles": [],
                           "problems": 0})
        groups[-1]["tiles"].append(tile)
        totals["rooms"] += 1
        if tile["state"] in ROOM_PROBLEM_STATES:
            groups[-1]["problems"] += 1
            totals["problems"] += 1
        if building.code not in buildings:
            buildings.append(building.code)

    for g in groups:
        g["tiles"].sort(key=lambda t: (ROOM_STATE_ORDER[t["state"]], t["room"].code))

    return {"groups": groups, "buildings": buildings, "totals": totals,
            "scope": scope, "now": timezone.localtime(now)}


def _board_scope(request):
    return "all" if request.GET.get("scope") == "all" else "live"


@ifo_required
def rooms_list(request):
    """The room board shell: filter bar + Live/All toggle. The tiles themselves
    live in the polled `_board.html` partial so filters survive a poll swap."""
    scope = _board_scope(request)
    ctx = _room_board(scope)
    ctx["poll_ms"] = int(get_policy("poll_interval_seconds")) * 1000
    ctx["total_rooms"] = Room.objects.count()
    return render(request, "ifo/rooms.html", ctx)


@ifo_required
def rooms_board(request):
    """Polled board body (IFO-07)."""
    return render(request, "ifo/_board.html", _room_board(_board_scope(request)))


@ifo_required
def room_panel(request, code):
    """Slide-over detail for one room: what is happening right now, today's
    timeline, and the recurring weekly schedule. Loaded into the board's panel
    target so the board keeps polling behind it."""
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    now = timezone.now()
    grace = timedelta(minutes=int(get_policy("grace_minutes")))
    today = list(room.sessions.filter(date=timezone.localdate())
                 .select_related("schedule", "faculty")
                 .order_by("scheduled_start"))
    tile = room_tile(room, today, now, grace)
    # Same rule as the tile: an online class is not in this physical room, so it
    # is not in its day either.
    today = [s for s in today if occupies(s, room)]

    term = AcademicTerm.objects.filter(is_active=True).first()
    schedules = list(
        room.schedules.filter(status=ScheduleStatus.ACTIVE, term=term)
        .select_related("faculty").order_by("day_of_week", "start_time")
        if term else [])
    if not room.is_virtual:
        schedules = [s for s in schedules if s.modality != Modality.ONLINE]
    return render(request, "ifo/_room_panel.html", {
        "room": room, "tile": tile, "today": today, "schedules": schedules,
        "term": term, "now": timezone.localtime(now),
    })


def _room_timetable(room, term):
    """The room's week as a day-by-time grid, matching MMCM's printed schedule form.

    A flat list of classes answers "what is booked here"; the grid answers "when
    is this room FREE", which is the question a facilities office actually asks,
    and it is the layout staff already recognise from the paper form.

    Rows are the campus-wide block ladder for the term (every distinct start time
    in use), not just this room's own times -- so a free slot shows as an empty
    cell instead of vanishing, every room prints on the same grid, and two
    printouts can be compared side by side.

    A class occupies EVERY slot its window covers (half-open: start <= slot <
    end), so a double-length class fills two rows exactly as it does on the paper
    form, with no rowspan bookkeeping.
    """
    if term is None:
        return None
    slots = sorted(set(
        Schedule.objects
        .filter(term=term, status=ScheduleStatus.ACTIVE)
        .values_list("start_time", flat=True)))
    if not slots:
        return None

    scheds = list(room.schedules
                  .filter(status=ScheduleStatus.ACTIVE, term=term)
                  .select_related("faculty"))
    # An online class does not use a physical room, so it is not part of that
    # room's timetable -- the slot reads free, which is the truth. In a virtual
    # room the online classes ARE the timetable.
    if not room.is_virtual:
        scheds = [s for s in scheds if s.modality != Modality.ONLINE]
    rows = []
    for slot in slots:
        cells = []
        for day_value, _label in DayOfWeek.choices:
            cells.append(next(
                (s for s in scheds
                 if s.day_of_week == day_value and s.start_time <= slot < s.end_time),
                None))
        rows.append({"time": slot, "cells": cells})
    return {"days": DayOfWeek.choices, "rows": rows,
            "used": sum(1 for r in rows for c in r["cells"] if c is not None),
            "capacity": len(rows) * len(DayOfWeek.choices)}


@ifo_required
def room_detail(request, code):
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    term = AcademicTerm.objects.filter(is_active=True).first()
    schedules = list(
        room.schedules.filter(status=ScheduleStatus.ACTIVE, term=term)
        .select_related("faculty").order_by("day_of_week", "start_time")
        if term else [])
    upcoming = [s for s in room.sessions.filter(date__gte=timezone.localdate())
                .select_related("schedule", "faculty")
                .order_by("date", "scheduled_start")[:40]
                if occupies(s, room)][:10]
    if not room.is_virtual:
        schedules = [s for s in schedules if s.modality != Modality.ONLINE]
    return render(request, "ifo/room_detail.html", {
        "room": room, "schedules": schedules, "upcoming": upcoming, "term": term,
        "timetable": _room_timetable(room, term),
        "printed_on": timezone.localtime(),
    })


def live(request):
    """/ifo/live merged into the room board. Kept as a permanent redirect so
    bookmarks, the PWA shell cache, and any pinned tab keep working."""
    return redirect("ifo_rooms", permanent=True)


# --- QR poster (IFO-01) ---
def _deep_link(request, room):
    # A real URL (SCAN-07): the phone camera opens the scan flow, which
    # signs the user in if needed and auto-resolves the token.
    return request.build_absolute_uri(f"/scan?t={room.qr_token}")


@ifo_required
def room_qr(request, code):
    import qrcode
    room = get_object_or_404(Room, code=code)
    img = qrcode.make(_deep_link(request, room))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


@ifo_required
def room_poster(request, code):
    room = get_object_or_404(Room.objects.select_related("floor__building"), code=code)
    return render(request, "ifo/poster.html", {"room": room})


# --- Room CRUD (IFO-01b) ----------------------------------------------------
# Rooms used to be creatable only through the Django admin or the offering
# importer, which meant a facilities officer needed a superuser account to add
# the one room a typo left out. These three views are the non-admin surface.
#
# Two rules hold this section together and neither is negotiable:
#
#   1. Scan credentials are MINTED IN EXACTLY ONE PLACE — campus.codes
#      (`new_room_credentials`). `Room.manual_code` is a six-digit value in a
#      UNIQUE column, and minting it inline has already been observed producing
#      a real `IntegrityError` in the importer. A second minter here would
#      reintroduce that on a routine IFO action.
#   2. A delete is REFUSED and NAMED, never cascaded and never soft-flagged
#      (D-17). See `room_delete`.


def _room_form_ctx(*, room=None, error=None, form=None):
    """Choice data + sticky values for the room create/edit form.

    Mirrors `_assignment_form_ctx`: the floor list is the identical
    `select_related("building")` query, so the two forms present floors the
    same way. `form` carries the operator's own submitted values back into a
    400 re-render so a rejected form is corrected, not retyped.
    """
    floors = (Floor.objects.select_related("building")
              .order_by("building__code", "number"))
    return {"room": room, "floors": floors, "error": error,
            "form": form or {}, "is_edit": room is not None}


def _room_form_fields(request):
    """Read the four posted room fields.

    The code is uppercased here and nowhere else. `Room.code` sits in the
    database's ordinary case-INSENSITIVE collation, so `r301` and `R301` are
    already the same key to a UNIQUE index -- normalising on the way in means
    the stored value matches the printed convention instead of whichever case
    the operator happened to type first.
    """
    return {
        "code": (request.POST.get("code") or "").strip().upper(),
        "name": (request.POST.get("name") or "").strip(),
        "floor": (request.POST.get("floor") or "").strip(),
        "capacity": (request.POST.get("capacity") or "").strip(),
    }


def _room_field_errors(fields, *, editing=None):
    """Validate the posted room fields; return an error string or None.

    ORDERING IS DELIBERATE (CR-04, the same trap `assignment_create` documents
    at its own ladder): FORMAT and pk-numericness are checked BEFORE anything
    touches the ORM. A non-numeric floor pk reaches `Floor.objects.filter(pk=...)`
    as an unhandled `ValidationError` (a 500), and a non-numeric capacity does
    the same at INSERT time against a PositiveIntegerField. Both must be a
    friendly 400 instead.

    `editing` is the Room being edited, or None on create. Code identity is
    only validated on create -- `room_edit` never rewrites the code, because
    the code is what is printed on the door.
    """
    if editing is None:
        if not fields["code"]:
            return "Enter a room code."
        if len(fields["code"]) > 30:
            return "A room code is at most 30 characters."
        # Case-insensitive: the column collation already treats R301/r301 as one
        # key, so a near-duplicate is an operator error worth naming up front
        # rather than surfacing as a UNIQUE violation.
        if Room.objects.filter(code__iexact=fields["code"]).exists():
            return f"Room {fields['code']} already exists."
    if not fields["floor"].isdigit():
        return "Select a floor."
    # `.isdigit()` rejects "", "abc" and "-5" in one test, so it covers both the
    # numeric and the non-negative half of the capacity rule.
    if fields["capacity"] and not fields["capacity"].isdigit():
        return "Capacity must be a whole number of seats (0 or more)."
    if len(fields["name"]) > 120:
        return "A room name is at most 120 characters."
    return None


@ifo_required
@require_http_methods(["GET", "POST"])
def room_new(request):
    """IFO-01b: create a room from the console (GET form, POST create).

    The new room is born SCANNABLE. `qr_token` and `manual_code` come from
    `campus.codes.new_room_credentials()` -- the single minter -- so the room
    can be postered and scanned the moment it exists, and so the six-digit
    collision retry that module owns applies here too. Nothing is minted
    inline in this view; see the section header above.

    Invalid input re-renders the form at 400 with the submitted values intact,
    never a 500 (T-07-11).
    """
    if request.method == "GET":
        return render(request, "ifo/room_form.html", _room_form_ctx())

    fields = _room_form_fields(request)
    error = _room_field_errors(fields)
    floor = None
    if error is None:
        floor = (Floor.objects.select_related("building")
                 .filter(pk=fields["floor"]).first())
        if floor is None:
            error = "Select a floor."
    if error:
        return render(request, "ifo/room_form.html",
                      _room_form_ctx(error=error, form=fields), status=400)

    qr_token, manual_code = new_room_credentials()
    room = Room.objects.create(
        code=fields["code"], name=fields["name"], floor=floor,
        capacity=int(fields["capacity"] or 0),
        qr_token=qr_token, manual_code=manual_code)

    AuditLog.objects.create(
        actor=request.user, event_type="room.created",
        target_type="room", target_id=str(room.pk),
        payload={"code": room.code, "name": room.name, "floor": floor.pk,
                 "floor_label": str(floor), "capacity": room.capacity})
    return redirect("ifo_room_detail", code=room.code)


@ifo_required
@require_http_methods(["GET", "POST"])
def room_edit(request, code):
    """IFO-01b: edit a room's name, capacity and floor (GET form, POST update).

    EDITING NEVER TOUCHES `qr_token` OR `manual_code`. That is the whole
    contract of this view. A room's credentials are printed on a poster taped
    to its door; silently reminting them because someone corrected a seat count
    would kill that poster with no warning and no reprint prompt, and the
    failure would only surface when a faculty member could not check in.
    Rotating a room's codes is a separate, deliberate, confirmed act that lands
    the operator on the reprint page (IFO-02, plan 07-04).

    The room CODE is likewise immutable here -- it is the identifier printed on
    the door and referenced by every schedule. Renaming a room means creating
    the new one and deleting the old, which the refusal in `room_delete` will
    correctly stop if the old code carries history.
    """
    room = get_object_or_404(
        Room.objects.select_related("floor__building"), code=code)
    if request.method == "GET":
        return render(request, "ifo/room_form.html", _room_form_ctx(room=room))

    fields = _room_form_fields(request)
    error = _room_field_errors(fields, editing=room)
    floor = None
    if error is None:
        floor = (Floor.objects.select_related("building")
                 .filter(pk=fields["floor"]).first())
        if floor is None:
            error = "Select a floor."
    if error:
        return render(request, "ifo/room_form.html",
                      _room_form_ctx(room=room, error=error, form=fields),
                      status=400)

    # Before-values are captured for the audit payload: "capacity changed" is
    # not an answerable question later unless the previous value is recorded.
    before = {"name": room.name, "capacity": room.capacity,
              "floor": room.floor_id}
    room.name = fields["name"]
    room.capacity = int(fields["capacity"] or 0)
    room.floor = floor
    room.save(update_fields=["name", "capacity", "floor"])

    changed = {f: before[f] for f, now in
               (("name", room.name), ("capacity", room.capacity),
                ("floor", room.floor_id))
               if before[f] != now}
    AuditLog.objects.create(
        actor=request.user, event_type="room.updated",
        target_type="room", target_id=str(room.pk),
        payload={"code": room.code, "changed": sorted(changed),
                 "before": changed})
    return redirect("ifo_room_detail", code=room.code)


# --- Duty assignments (IFO-06) ---------------------------------------------
def _assignment_form_ctx():
    """Choice data for the assignment create form (Checkers/Guards + floors)."""
    duty_users = (get_user_model().objects
                  .filter(role__in=[Role.CHECKER, Role.GUARD], is_active=True)
                  .order_by("role", "last_name", "username"))
    floors = (Floor.objects.select_related("building")
              .order_by("building__code", "number"))
    return {"duty_users": duty_users, "floors": floors,
            "roles": DutyRole.choices, "types": AssignmentType.choices,
            "scopes": AssignmentScope.choices}


def _active_assignments():
    return (Assignment.objects.filter(status="active")
            .select_related("user").prefetch_related("floors__building")
            .order_by("role", "scope", "user__last_name"))


@ifo_required
def assignments_list(request):
    """IFO-06: active duty roster + the create form (non-admin UI)."""
    ctx = {"assignments": _active_assignments(), **_assignment_form_ctx()}
    return render(request, "ifo/assignments.html", ctx)


@ifo_required
@require_http_methods(["POST"])
def assignment_create(request):
    """IFO-06: create a floor or online-duty assignment from validated POST fields.

    The Assignment is built server-side from the choice fields (never trusting a
    forged scope/floor); every create writes an AuditLog (T-03-08/09). Creating
    ONLINE duty immediately round-robins that date's unowned online sessions so a
    newly-online-duty Checker picks them up. Invalid input renders a friendly
    error partial (status 400), never a 500.
    """
    User = get_user_model()
    user = User.objects.filter(pk=request.POST.get("user"),
                               role__in=[Role.CHECKER, Role.GUARD]).first()
    role = request.POST.get("role")
    type_ = request.POST.get("type")
    scope = request.POST.get("scope")
    floor_ids = request.POST.getlist("floors")
    date_raw = (request.POST.get("date") or "").strip()
    start_raw = (request.POST.get("start_time") or "").strip()
    end_raw = (request.POST.get("end_time") or "").strip()

    error = None
    if user is None:
        error = "Select a Checker or Guard."
    elif role not in DutyRole.values:
        error = "Select a valid duty role."
    elif type_ not in AssignmentType.values:
        error = "Select shift or standing."
    elif scope not in AssignmentScope.values:
        error = "Select floor or online scope."
    elif scope == AssignmentScope.FLOOR and not floor_ids:
        error = "A floor posting needs at least one floor."
    # Validate date/time FORMAT and floor-id numericness BEFORE the ORM write —
    # DateField/TimeField.to_python() and a non-numeric pk__in both raise an
    # unhandled ValidationError (500) at INSERT/.set() time otherwise (CR-04).
    elif date_raw and parse_date(date_raw) is None:
        error = "Enter a valid date."
    elif start_raw and parse_time(start_raw) is None:
        error = "Enter a valid start time."
    elif end_raw and parse_time(end_raw) is None:
        error = "Enter a valid end time."
    elif floor_ids and not all(f.isdigit() for f in floor_ids):
        error = "Invalid floor selection."

    if error:
        ctx = {"assignments": _active_assignments(), "error": error,
               **_assignment_form_ctx()}
        return render(request, "ifo/_assignment_form.html", ctx, status=400)

    term = AcademicTerm.objects.filter(is_active=True).first()
    a = Assignment.objects.create(
        user=user, role=role, type=type_, scope=scope,
        date=date_raw or None,
        start_time=start_raw or None,
        end_time=end_raw or None,
        term=term, status="active")
    if scope == AssignmentScope.FLOOR:
        # Only real floor pks land on the M2M; ONLINE ignores floors entirely.
        a.floors.set(Floor.objects.filter(pk__in=floor_ids))

    AuditLog.objects.create(
        actor=request.user, event_type="assignment.created",
        target_type="assignment", target_id=str(a.pk),
        payload={"user": user.pk, "role": role, "scope": scope, "type": type_,
                 "floors": list(a.floors.values_list("pk", flat=True))})

    # Granting online duty immediately pre-assigns unowned online sessions so the
    # new online-duty Checker picks them up (a dated posting -> that date only; a
    # standing posting -> today..+horizon).
    if scope == AssignmentScope.ONLINE:
        start = a.date or timezone.localdate()
        horizon = 0 if a.date else get_policy("materialization_horizon_days")
        d = start
        for _ in range(horizon + 1):
            assign_online_sessions(d)
            d += timedelta(days=1)

    ctx = {"assignments": _active_assignments(), "created": a,
           **_assignment_form_ctx()}
    return render(request, "ifo/_assignment_form.html", ctx)


# --- IFO-09 reporting dashboard + scorecard drill-down (RPT-04/RPT-05) -------
# The (start, end, as_of, note) window parser is the single shared implementation
# in web.reporting_common (imported as _reporting_range above), mirrored by the Dean
# surface -- no per-role copy is kept in sync by hand (code-review LO-03).


@ifo_required
def dashboard(request):
    """IFO-09: an unscoped reporting dashboard of summary cards over a selectable
    range. Each section is wrapped in ``safe_card`` so one raising aggregate shows
    its own inline error card while the rest of the page renders (RPT-05). The
    dashboard is read-only and point-in-time -- it refreshes on filter Apply, it
    is NOT continuously polled (assumption A-POLL).
    """
    start, end, as_of, note = _reporting_range(request)
    summary = safe_card(
        dept_summary, start=start, end=end, department=None, as_of=as_of)
    rows = safe_card(
        faculty_attendance, start=start, end=end, department=None, as_of=as_of)
    # Unscoped means every faculty member in the institution lands in one table --
    # the largest list in the product. Paged; the exports still cover the full set.
    pager = paginate(request, rows[0])
    return render(request, "ifo/dashboard.html", {
        "summary": summary, "rows": rows,
        "date_from": start, "date_to": end, "range_note": note, **pager,
    })


@ifo_required
def scorecard(request, faculty_id):
    """RPT-04 drill-down: one faculty's full-page attendance scorecard (early-ends
    + effective-modality breakdown + itemized absences) over the same selectable
    range, reusing the shared ``faculty_scorecard`` aggregate. IFO is unscoped, so
    any faculty is reachable (A-DRILL: a full page, not a modal). Wrapped in
    ``safe_card`` so an aggregate failure renders the shared error card, not a 500.
    """
    faculty = get_object_or_404(get_user_model(), pk=faculty_id)
    start, end, as_of, note = _reporting_range(request)
    card = safe_card(
        faculty_scorecard, faculty=faculty, start=start, end=end, as_of=as_of)
    modality_items = None
    if card[0] is not None:
        labels = dict(Modality.choices)
        modality_items = [(labels.get(k, k), n)
                          for k, n in card[0].modality_breakdown.items()]
    return render(request, "reports/scorecard.html", {
        "faculty": faculty, "card": card, "modality_items": modality_items,
        "date_from": start, "date_to": end, "range_note": note,
        "export_csv_url": f"/ifo/scorecard/{faculty.id}/export.csv",
    })


@ifo_required
@require_http_methods(["GET"])
def scorecard_csv(request, faculty_id):
    """RPT-04: export ONE faculty's attendance row for the current range as CSV.

    The scorecard's declared primary CTA (UI-SPEC). Reuses the shared aggregate +
    ``build_csv`` (csv_safe-neutralized name cells, T-06-02) rather than
    re-implementing either: runs the unscoped ``faculty_attendance`` and keeps only
    this faculty's row (IFO is unscoped, so any faculty is reachable). An
    out-of-range faculty simply yields a header-only CSV. Read-only (GET-only).
    """
    faculty = get_object_or_404(get_user_model(), pk=faculty_id)
    start, end, as_of, _note = _reporting_range(request)
    rows = [r for r in faculty_attendance(start=start, end=end, as_of=as_of)
            if r.faculty_id == faculty.id]
    resp = HttpResponse(build_csv(rows), content_type="text/csv")
    resp["Content-Disposition"] = (
        f'attachment; filename="scorecard-{faculty.id}-{start}.csv"')
    return resp


# --- Weekly Consolidated Report surface (RPT-01/03) -------------------------
# The IFO-facing deliverable: an index of the STORED weekly reports (every
# department PLUS the org-wide department=None roll-up) for a selected/most-recent
# week, each downloadable as the stored PDF/CSV bytes. IFO is the institution-wide
# role, so this surface is intentionally UNSCOPED -- unlike the department-scoped
# Dean surface (web.dean.weekly_download), there is NO department filter and the
# None roll-up is reachable. Every view is GET-only (read-only, T-06-07).


@ifo_required
@require_http_methods(["GET"])
def weekly_reports(request):
    """RPT-01/03: IFO-wide index of the stored weekly consolidated reports.

    Lists every ``WeeklyReport`` stored for the most-recent week (or a ``?week=``
    ISO date if supplied) -- one row per department PLUS the org-wide
    ``department=None`` roll-up -- each offering a primary ``Download PDF`` and a
    secondary ``Export CSV`` of the stored bytes. UNSCOPED by design: IFO sees all
    departments and the consolidated roll-up. Read-only (GET-only). An institution
    with no generated reports yet gets a calm Pattern-F empty state, never a crash.
    """
    week_raw = (request.GET.get("week") or "").strip()
    week = parse_date(week_raw) if week_raw else None
    if week is None:
        latest = WeeklyReport.objects.order_by("-week_start").first()
        week = latest.week_start if latest else None

    weeks = list(
        WeeklyReport.objects.order_by("-week_start")
        .values_list("week_start", flat=True).distinct())

    if week is not None:
        # NULLs sort first in ASC on both SQLite and MSSQL, so the department=None
        # roll-up leads the list; the template labels it "All departments".
        reports = list(
            WeeklyReport.objects.filter(week_start=week)
            .select_related("department")
            .order_by("department__code"))
    else:
        reports = []

    return render(request, "ifo/weekly_reports.html", {
        "reports": reports, "week": week, "weeks": weeks,
    })


@ifo_required
@require_http_methods(["GET"])
def weekly_download(request, pk, fmt):
    """RPT-03: stream a STORED WeeklyReport's csv/pdf for IFO -- UNSCOPED.

    Mirrors ``web.dean.weekly_download``'s storage-safety guard (server-built stored
    path, a missing file/path 404s -- never a 500) but WITHOUT the department
    scoping: IFO is institution-wide, so any report pk -- INCLUDING the org-wide
    ``department=None`` roll-up -- resolves. Read-only (GET-only).
    """
    report = get_object_or_404(WeeklyReport, pk=pk)
    if fmt == "csv":
        path, content_type = report.csv_path, "text/csv"
    elif fmt == "pdf":
        path, content_type = report.pdf_path, "application/pdf"
    else:
        raise Http404("Unknown export format.")
    if not path or not default_storage.exists(path):
        raise Http404("Report file not found.")
    with default_storage.open(path, "rb") as fh:
        data = fh.read()
    filename = path.rsplit("/", 1)[-1]
    resp = HttpResponse(data, content_type=content_type)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

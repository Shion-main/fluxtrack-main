"""IFO Admin surfaces: rooms list, per-room schedule (IFO-11), QR poster (IFO-01),
and a live 'today' view (IFO-07, htmx-polled)."""
import io
from datetime import datetime, timedelta
from functools import wraps

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.management import call_command
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
from ops.availability import room_is_free
from ops.import_staging import (ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES,
                                ImportStagingError, consume_staged,
                                discard_staged, resolve_staged, staged_path,
                                stage_upload, sweep_abandoned)
from ops.models import AuditLog, Booking, RoomConflictFlag, WeeklyReport
from ops.occupancy import release_room
from ops.policy import get_policy
from scheduling.models import (AcademicTerm, DayOfWeek, Modality, Schedule,
                                ScheduleStatus, Session, SessionStatus)
from scheduling.importing import reconcile
from scheduling.report_render import build_csv
from scheduling.reporting import (dept_summary, faculty_attendance,
                                  faculty_scorecard, safe_card)
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 DutyRole)
from verification.services import assign_online_sessions
from web.pagination import paginate
from web.room_state import (ROOM_PROBLEM_STATES, ROOM_STATE_ORDER, occupies,
                            room_tile, room_timetable)
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


# `_room_timetable` moved to `web/room_state.py` as public `room_timetable`
# (07-11): the Guard per-room page (GRD-02) builds the same grid, and a role
# module must not import a private name from another role module.


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
        "timetable": room_timetable(room, term),
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
    room = get_object_or_404(
        Room.objects.select_related("floor__building", "code_rotated_by"),
        code=code)
    return render(request, "ifo/poster.html", {"room": room})


# --- Credential rotation (IFO-02) -------------------------------------------
# `Room.code_rotated_at` / `code_rotated_by` shipped in Phase 1 with no writer.
# These two views are that writer.
#
# Rotation is the one room action that BREAKS something in the physical world:
# the poster taped to the door stops working the instant it lands, and nothing
# on the door announces that. D-14 answers this by binding the destructive act
# to its remedy -- a confirm page that names the consequence for that specific
# room, and a success path that lands on the reprint page so the operator is
# already holding the new poster.


@ifo_required
@require_http_methods(["GET"])
def room_rotate_confirm(request, code):
    """IFO-02 / D-14: the confirmation page for a credential rotation.

    A real GET page rather than a JavaScript confirm() dialog, for the same
    reasons `room_delete` gives: a dialog cannot carry the last-rotated stamp
    or the "what to do next" instruction, and it is hostile to keyboard-only
    and screen-reader users.

    Read-only by contract -- nothing here changes the room.
    """
    room = get_object_or_404(
        Room.objects.select_related("floor__building", "code_rotated_by"),
        code=code)
    return render(request, "ifo/room_rotate.html", {"room": room})


@ifo_required
@require_http_methods(["POST"])
def room_rotate(request, code):
    """IFO-02: mint a fresh QR token + six-digit code for one room.

    POST-ONLY, and that is a control rather than a convention (T-07-16). A
    GET-reachable rotation would fire on a link prefetch, a crawler, or an
    accidental reload -- silently killing a poster nobody was asked about.

    THE CREDENTIALS COME FROM `campus.codes.new_room_credentials()` AND
    NOWHERE ELSE. Minting inline here would reintroduce the UNIQUE-column
    collision that module exists to prevent (~2.3% per full room load,
    observed). Rotation is the worst possible place for that intermittent 500:
    it fires immediately before D-14 sends the operator away to reprint, so a
    failure leaves them unable to tell whether the poster on the door is dead
    or alive.

    Nothing is cached. `room_qr` regenerates the image on demand from
    `room.qr_token`, so changing the stored values IS the rotation.

    THE AUDIT PAYLOAD CARRIES NO CREDENTIAL VALUE, old or new (T-07-15). These
    are resolver-only secrets that are never rendered client-side (SCAN-07,
    6.2), and the AuditLog table is read far more widely than the two columns
    it would be describing. The room, the actor and the instant are enough to
    answer every question the audit trail is for.
    """
    room = get_object_or_404(
        Room.objects.select_related("floor__building"), code=code)

    with transaction.atomic():
        qr_token, manual_code = new_room_credentials()
        room.qr_token = qr_token
        room.manual_code = manual_code
        room.code_rotated_at = timezone.now()
        room.code_rotated_by = request.user
        room.save(update_fields=["qr_token", "manual_code",
                                 "code_rotated_at", "code_rotated_by"])
        AuditLog.objects.create(
            actor=request.user, event_type="room.code_rotated",
            target_type="room", target_id=str(room.pk),
            payload={"code": room.code,
                     "floor": str(room.floor),
                     "rotated_at": room.code_rotated_at.isoformat()})

    # D-14: land on the reprint surface, not back on the room. The remedy for
    # the dead poster is the next thing the operator has to do.
    return redirect("ifo_room_poster", code=room.code)


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


# Plain-language names for the five relations `room_delete_blockers` can report.
# The probe returns machine keys; an operator needs to know WHAT they are looking
# at and WHY it stops the delete, so the label, the icon and the explanation all
# live here rather than being branched on in the template.
#
# Each row carries an icon AND a text label alongside any colour treatment --
# colour is never the only signal (WCAG 1.4.1, the rule stated at
# web/checker.py:636).
_BLOCKER_LABELS = [
    ("schedules", "Recurring class schedules", "calendar-days",
     "Classes that meet in this room every week this term."),
    ("sessions", "Class sessions", "history",
     "Dated meetings of a class in this room, and the attendance recorded "
     "against them."),
    ("bookings", "Ad-hoc bookings", "book-marked",
     "One-off reservations of this room, including cancelled ones -- they are "
     "still the record of who booked what."),
    ("validations", "Checker validations", "shield-check",
     "Confirmations a Checker recorded while standing in this room."),
    ("reservations", "Approved modality-shift reservations", "arrow-left-right",
     "This room is held for an approved modality shift. Nothing in the "
     "database would refuse this delete -- the reservation would simply be "
     "emptied without a trace."),
]


def _blocker_rows(blockers):
    """Render the probe's {relation: count} into ordered, human rows."""
    return [{"key": key, "label": label, "icon": icon, "detail": detail,
             "count": blockers[key]}
            for key, label, icon, detail in _BLOCKER_LABELS if key in blockers]


@ifo_required
@require_http_methods(["GET", "POST"])
def room_delete(request, code):
    """IFO-01b / D-17: confirm page (GET) and delete action (POST), or a NAMED refusal.

    D-17 rules out both easy answers. Cascade destroys attendance history,
    which is the one thing an attendance-integrity system may never do. A
    soft-deactivate `is_active` flag would have to be taught to every room
    query in the codebase, including the scan resolver this phase deliberately
    leaves untouched. What is left is a refusal -- and a refusal that does not
    say what is blocking it is just a broken button, so NAMING each blocking
    relation and its count IS the feature.

    A real GET page, not a JavaScript confirm() dialog: a dialog cannot show
    the blocker detail and cannot be reached by keyboard-only or screen-reader
    users.

    TWO CONTROLS, BOTH KEPT, NEITHER SUFFICIENT ALONE:

      * The PROBE (`campus.services.room_delete_blockers`) is the primary
        control. It is the only thing that catches `ModalityShiftItem.
        assigned_room`, which is SET_NULL -- an approved reservation would be
        silently emptied, and nothing else in the stack would notice.
      * `ProtectedError` is the BACKSTOP. The four PROTECT relations raise it
        from Django's Collector if a reference appears between the probe and
        the delete. Note it is an ORM-level guarantee, not a database
        constraint: Django never encodes `on_delete` in DDL, so every FK to
        campus_room is NO_ACTION in the schema. Whichever control fires, the
        operator gets the same friendly refusal and never a 500.

    The POST re-runs the probe inside `transaction.atomic()`. The GET-time
    probe is DISPLAY ONLY and is never the authorization (T-07-10) -- a room
    can gain a session between the operator reading the page and clicking the
    button, so the re-check is the actual control.

    Both outcomes are audited: `room.deleted` on success, `room.delete_refused`
    with the blocker counts on a refusal. The refusal trail is the one D-17's
    discretion note asks for -- it shows IFO which destructive attempts landed
    on rooms that turned out to be live.
    """
    room = get_object_or_404(
        Room.objects.select_related("floor__building"), code=code)

    if request.method == "GET":
        blockers = room_delete_blockers(room)
        return render(request, "ifo/room_delete.html", {
            "room": room, "blockers": _blocker_rows(blockers),
            "can_delete": not blockers})

    refused, protected = None, False
    deleted_pk, floor_label = room.pk, str(room.floor)
    with transaction.atomic():
        blockers = room_delete_blockers(room)
        if blockers:
            refused = blockers
        else:
            try:
                room.delete()
            except ProtectedError:
                # Nothing was written before the Collector raised, so the
                # transaction is clean and simply commits as a no-op. Audit
                # writes happen after the block so they can never ride a
                # transaction this branch has already given up on.
                protected = True

    if protected:
        # Re-probe outside the transaction to name whatever appeared. If it
        # still reads clean, the template falls back to a generic refusal --
        # a 500 is never an acceptable answer here.
        refused = room_delete_blockers(room)

    if refused is not None or protected:
        AuditLog.objects.create(
            actor=request.user, event_type="room.delete_refused",
            target_type="room", target_id=str(room.pk),
            payload={"code": room.code, "blockers": refused,
                     "protected_error": protected})
        return render(request, "ifo/room_delete.html", {
            "room": room, "blockers": _blocker_rows(refused),
            "can_delete": False, "refused": True, "protected": protected,
        }, status=400)

    AuditLog.objects.create(
        actor=request.user, event_type="room.deleted",
        target_type="room", target_id=str(deleted_pk),
        payload={"code": room.code, "floor": floor_label})
    return redirect("ifo_rooms")


# --- Manual room release + open conflicts (IFO-08) --------------------------
# `ops.occupancy.release_room` shipped in Phase 2 with zero callers, and MOD-03
# became its first. `session_release` below is its SECOND and, by the source
# guard in ops/tests.py ReleaseRoomCallerGuardTests, its last.
#
# D-11 is the whole design of this section and it is smaller than it looks: IFO
# does ONE thing -- release the session that should not be holding the room --
# and the RoomConflictFlag closes on the next sweep because the cause is gone.
# There is deliberately NO manual flag-close anywhere in this module. A second
# resolution path could mark a flag resolved while the conflict was still live,
# which is strictly worse than no surface at all.


# The statuses in which a session is actually occupying its room. SCHEDULED is
# included on purpose: a class that has not been checked into yet still holds
# the room -- that is exactly the ghost booking IFO needs to be able to clear.
# COMPLETED and ABSENT have already finished with it, so releasing them would
# stamp a release instant for an occupancy that ended on its own.
_ROOM_HOLDING_STATUSES = {SessionStatus.SCHEDULED, SessionStatus.ACTIVE}


def _contending_sessions(room_ids):
    """ACTIVE sessions still holding each of `room_ids`, grouped by room.

    One query for every flag, not one per flag. The room-holding definition is
    the same one `detect_room_conflicts` uses to RAISE the flag -- ACTIVE with
    `room_released_at` NULL -- so the page can never disagree with the job about
    what is contending.
    """
    out = {}
    for s in (Session.objects
              .filter(room_id__in=room_ids, status=SessionStatus.ACTIVE,
                      room_released_at__isnull=True)
              .select_related("schedule", "faculty", "room")
              .order_by("scheduled_start")):
        out.setdefault(s.room_id, []).append(s)
    return out


@ifo_required
@require_http_methods(["GET"])
def conflicts(request):
    """IFO-08: every open RoomConflictFlag with the sessions contending for it.

    Read-only. The only action offered is Release, which posts to
    `session_release`; this view never writes.
    """
    flags_qs = (RoomConflictFlag.objects.filter(resolved_at__isnull=True)
                .select_related("room__floor__building")
                .order_by("-detected_at"))
    pager = paginate(request, flags_qs)
    # MATERIALIZE BEFORE THE FOLLOW-UP QUERY. pyodbc runs with MARS off, so
    # issuing the session query while the flag SELECT cursor is still streaming
    # raises HY010 ("function sequence error"). Same guard both sweeps in
    # scheduling/jobs.py carry, and web/ifo.py:131.
    flags = list(pager["page"].object_list)
    by_room = _contending_sessions([f.room_id for f in flags])

    rows = [{"flag": f, "room": f.room, "sessions": by_room.get(f.room_id, [])}
            for f in flags]
    return render(request, "ifo/conflicts.html", {"rows": rows, **pager})


@ifo_required
@require_http_methods(["POST"])
def session_release(request, pk):
    """IFO-08 / D-11: manually release the room a session is still holding.

    NO AUDITLOG IS WRITTEN HERE, AND THAT IS DELIBERATE. This is the documented
    exception to "every state change writes an AuditLog" (Conventions rule 2):
    `release_room` already writes `session.room_released` with this actor and
    the release instant. A second row here would double-count every release and
    make "how many rooms did IFO release last week" unanswerable. Do not "fix"
    the missing audit -- ManualReleaseTests asserts the count is exactly one.

    NO FLAG IS TOUCHED HERE EITHER (D-11). Releasing the contended session makes
    the conflict genuinely gone, so the next `detect_room_conflicts` run finds
    the key absent and stamps `resolved_at` through the existing JOB-02c
    auto-resolve path. Closing the flag from this view would be a second,
    competing resolution path that could mark a flag resolved while the conflict
    persisted.

    THE RE-GATE IS THE CONTROL, not the button. The operator clicked a snapshot
    that may be minutes stale -- on a polled board, quite likely stale -- so the
    session's actual state is re-read here and a session that is not currently
    holding the room is refused with a plain message at 400, never a 500.
    """
    session = get_object_or_404(
        Session.objects.select_related("schedule", "faculty",
                                       "room__floor__building"), pk=pk)

    error = None
    if session.room_id is None:
        error = "That session has no room to release."
    elif session.room_released_at is not None:
        # No `%-d`/`%-I` padding-strippers here: those are glibc extensions and
        # raise ValueError on Windows, where this project is developed.
        error = (f"{session.room} was already released "
                 f"{timezone.localtime(session.room_released_at):%b %d, %I:%M %p}.")
    elif session.status not in _ROOM_HOLDING_STATUSES:
        error = (f"That session is {session.get_status_display().lower()}, so it "
                 f"is not holding {session.room}.")

    if error is None:
        release_room(session, actor=request.user)

    return render(request, "ifo/_release_result.html",
                  {"session": session, "error": error},
                  status=400 if error else 200)


# --- Ad-hoc bookings (IFO-05) -----------------------------------------------
# `ops.Booking` has existed since Phase 1 with only a Django-admin surface.
# These three views are its non-admin UI.
#
# ONE RULE HOLDS THIS SECTION TOGETHER: the conflict answer comes from
# `ops.availability.room_is_free` and from nowhere else (D-08). That function is
# already the occupancy oracle for the faculty room picker and Dean approval,
# and it already counts active Bookings, room-holding non-Online Sessions and
# approved modality-shift reservations on half-open overlap. A second overlap
# query written here would be a second DEFINITION of "free" -- one that starts
# out agreeing and silently drifts. `ops/availability.py` is not modified by
# this plan and must not be.

BOOKING_PAGE_SIZE = 25


def _booking_form_ctx(*, error=None, created=None, cancelled=None, form=None):
    """Choice data + sticky values for the booking panel."""
    rooms = (Room.objects.select_related("floor__building")
             .order_by("floor__building__code", "code"))
    bookings = (Booking.objects
                .select_related("room__floor__building", "created_by")
                .order_by("-start_datetime"))
    return {"rooms": rooms, "bookings": bookings, "error": error,
            "created": created, "cancelled": cancelled, "form": form or {}}


def _booking_panel(request, *, error=None, created=None, cancelled=None,
                   form=None):
    """Render the bookings panel partial, paginated."""
    ctx = _booking_form_ctx(error=error, created=created, cancelled=cancelled,
                            form=form)
    pager = paginate(request, ctx.pop("bookings"), per_page=BOOKING_PAGE_SIZE)
    ctx["bookings"] = pager["page"].object_list
    return {**ctx, **pager}


@ifo_required
@require_http_methods(["GET"])
def bookings_list(request):
    """IFO-05: the booking create form plus a paginated table of bookings.

    CANCELLED BOOKINGS ARE SHOWN, not filtered out. A cancelled booking is
    still historical data, and since plan 07-02 migrated `Booking.room` to
    PROTECT it is still a room-delete blocker -- so an operator who cannot find
    it in this list cannot understand why a room refuses to delete.
    """
    return render(request, "ifo/bookings.html", _booking_panel(request))


def _safe_parse_date(raw):
    """`parse_date` that returns None for BOTH kinds of bad input.

    Django's `parse_date`/`parse_time` return None only when the string does
    not MATCH the expected shape. A string that matches the shape but carries
    an impossible value -- "25:99", "2026-13-45" -- gets as far as constructing
    the date/time object and raises ValueError instead. A validation ladder
    that only tests `is None` therefore lets exactly the inputs an operator is
    most likely to fat-finger through as a 500 (T-07-25).
    """
    try:
        return parse_date(raw)
    except ValueError:
        return None


def _safe_parse_time(raw):
    """See `_safe_parse_date` -- same trap, same reason."""
    try:
        return parse_time(raw)
    except ValueError:
        return None


def _booking_fields(request):
    return {
        "occupant_name": (request.POST.get("occupant_name") or "").strip(),
        "purpose": (request.POST.get("purpose") or "").strip(),
        "room": (request.POST.get("room") or "").strip(),
        "date": (request.POST.get("date") or "").strip(),
        "start_time": (request.POST.get("start_time") or "").strip(),
        "end_time": (request.POST.get("end_time") or "").strip(),
    }


@ifo_required
@require_http_methods(["POST"])
def booking_create(request):
    """IFO-05: create an ad-hoc booking, conflict-checked by the single oracle.

    THE VALIDATION LADDER IS ORDERED ON PURPOSE (CR-04, the same trap
    `assignment_create` documents): FORMAT and pk-numericness are settled
    BEFORE anything reaches the ORM. `parse_date` / `parse_time` returning None
    and a non-numeric room pk both surface as an unhandled ValidationError --
    a 500 -- at INSERT time otherwise. Each must be a friendly 400.

    NO OVERRIDE CONTROL EXISTS, AND THIS IS A DELIBERATE READING OF D-09.
    D-09's parenthetical ("absent an explicit override") describes the default
    refusal; nothing in IFO-05 asks for a way to double-book over a scheduled
    class. Building one would let this console manufacture exactly the
    contradictory occupancy that JOB-02c exists to detect and that IFO-08 now
    exists to clean up -- three surfaces working against each other. Recorded
    in the 07-06 summary so the operator can overrule this reading if they
    disagree.
    """
    fields = _booking_fields(request)
    error, room, start, end = None, None, None, None

    if not fields["occupant_name"]:
        error = "Enter who the room is for."
    elif len(fields["occupant_name"]) > 120:
        error = "The occupant name is at most 120 characters."
    elif len(fields["purpose"]) > 255:
        error = "The purpose is at most 255 characters."
    elif not fields["room"].isdigit():
        error = "Select a room."
    elif _safe_parse_date(fields["date"]) is None:
        error = "Enter a valid date."
    elif _safe_parse_time(fields["start_time"]) is None:
        error = "Enter a valid start time."
    elif _safe_parse_time(fields["end_time"]) is None:
        error = "Enter a valid end time."

    if error is None:
        room = (Room.objects.select_related("floor__building")
                .filter(pk=fields["room"]).first())
        if room is None:
            error = "Select a room."

    if error is None:
        day = _safe_parse_date(fields["date"])
        # Combined the same way ops/availability.py:106 builds a reservation
        # window, so a booking and a reservation are compared on one clock.
        start = timezone.make_aware(
            datetime.combine(day, _safe_parse_time(fields["start_time"])))
        end = timezone.make_aware(
            datetime.combine(day, _safe_parse_time(fields["end_time"])))
        if end <= start:
            # Half-open overlap means a zero-length booking occupies nothing at
            # all, so it would silently "succeed" while reserving no time.
            error = "The end time must be after the start time."

    if error is None and not room_is_free(room, start, end):
        error = (f"{room.code} is not free for that window. Open the room's "
                 f"schedule to see what already occupies it.")

    if error:
        return render(request, "ifo/_booking_form.html",
                      _booking_panel(request, error=error, form=fields),
                      status=400)

    booking = Booking.objects.create(
        room=room, created_by=request.user,
        occupant_name=fields["occupant_name"], purpose=fields["purpose"],
        start_datetime=start, end_datetime=end, status="active")
    AuditLog.objects.create(
        actor=request.user, event_type="booking.created",
        target_type="booking", target_id=str(booking.pk),
        payload={"room": room.code, "occupant": booking.occupant_name,
                 "start": start.isoformat(), "end": end.isoformat()})

    return render(request, "ifo/_booking_form.html",
                  _booking_panel(request, created=booking))


@ifo_required
@require_http_methods(["POST"])
def booking_cancel(request, pk):
    """IFO-05 / D-10: cancel a booking by flipping its status away from active.

    THE STATUS FLIP IS THE ENTIRE CANCELLATION MECHANISM. `room_is_free` counts
    only `status="active"` bookings, so the room frees itself the moment the
    flip lands and `ops/availability.py` needs no change whatsoever.

    DO NOT REPLACE THIS WITH A DELETE. Deleting the row would destroy the record
    that a booking ever existed, and since plan 07-02 migrated `Booking.room` to
    PROTECT it would also silently change what blocks a room delete -- an
    operator would see a room become deletable for reasons nothing on screen
    explains.
    """
    booking = get_object_or_404(
        Booking.objects.select_related("room__floor__building"), pk=pk)

    if booking.status != "active":
        # Re-gated server-side: the row the operator saw may be minutes stale.
        return render(request, "ifo/_booking_form.html",
                      _booking_panel(request, error=(
                          f"That booking for {booking.room.code} is already "
                          f"{booking.status}.")),
                      status=400)

    booking.status = "cancelled"
    booking.save(update_fields=["status"])
    AuditLog.objects.create(
        actor=request.user, event_type="booking.cancelled",
        target_type="booking", target_id=str(booking.pk),
        payload={"room": booking.room.code,
                 "occupant": booking.occupant_name,
                 "start": booking.start_datetime.isoformat(),
                 "end": booking.end_datetime.isoformat()})

    return render(request, "ifo/_booking_form.html",
                  _booking_panel(request, cancelled=booking))


# --- Schedule import by upload (IFO-03b) ------------------------------------
# THIS SECTION ESTABLISHES THIS PROJECT'S FILE-UPLOAD HOUSE PATTERN. Before it
# there was no `request.FILES` handling, no multipart form and no upload
# validation anywhere in the codebase. Plan 07-08's profile-photo upload copies
# what is here, which is why the harder case (a file that must survive BETWEEN
# two requests) was built first.
#
# Flow is preview-then-commit (D-12): stage the bytes, dry-run and show the
# reconciliation report, and only apply when the operator says so.
#
# THREE STORES, THREE JOBS, and mixing them up is the whole class of bug this
# design avoids:
#   the BYTES     live on disk under MEDIA_ROOT at a server-composed path;
#   the SESSION   carries only the opaque token;
#   the ROW       (ops.ImportStaging) owns ownership and lifecycle.
# The client's filename is display text and is NEVER joined into a path
# (T-07-31), and the token is read from the session and NEVER from the form
# (T-07-32) -- a form-supplied token would be an IDOR handle letting any IFO
# user commit any staged file.

IMPORT_SESSION_KEY = "ifo_import_token"

# An .xlsx is a zip archive, so a 10 MB upload can expand into an enormous
# amount of XML: the byte cap in ops/import_staging.py does not bound the
# PARSED size (T-07-33). This does. Sized well above a real term load (~2,000
# offering rows) so it can only ever fire on something pathological.
MAX_PARSED_ROWS = 20000


def _delete_staged_file(staging):
    """Best-effort removal of a consumed staged file.

    `consume_staged` marks the ROW spent; the BYTES are ours to remove. Guarded
    because an already-missing or externally-cleaned file must never turn a
    successful import into a 500 at the last step.
    """
    path = staging.stored_path
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except OSError:
        pass


def _import_read_rows(path, sheet=None):
    """Read an offerings file through the COMMAND'S OWN extension dispatch.

    Deliberately `Command()._read_rows` rather than a parser written here:
    04.1-01 locked a stdlib zipfile/xml reader with no openpyxl and no pandas,
    and a second parser in the web layer would be a second answer to "what does
    this file say" that starts out agreeing and drifts.
    """
    from scheduling.management.commands.import_offerings import (
        DEFAULT_SHEET, Command)
    return Command()._read_rows(path, sheet or DEFAULT_SHEET)


def _import_report(path):
    """Parse + reconcile a staged file. Returns (report_ctx, error_message).

    `reconcile()` is called DIRECTLY for the structured numbers. The management
    command PRINTS its reconciliation rather than returning it, so
    screen-scraping its stdout for the primary display would be brittle; the
    command's narrative is captured separately as a secondary detail pane.
    """
    try:
        rows = _import_read_rows(path)
    except Exception:
        # Deliberately broad. Extension proves nothing about content -- the real
        # validation is that the parser accepts the bytes -- and the failure
        # modes of a hostile or merely corrupt file are open-ended
        # (BadZipFile for a renamed non-zip, KeyError for a missing sheet,
        # UnicodeDecodeError, IndexError on a truncated grid, and so on).
        # Enumerating them would leave the next unlisted one as a 500, which is
        # exactly what T-07-34 forbids on an operator-facing upload.
        return None, ("That file could not be read as an offerings export. "
                      "Check it is the unmodified .xlsx or .csv from the "
                      "registrar and try again.")

    if not rows:
        return None, "That file has no rows in it."
    if len(rows) > MAX_PARSED_ROWS:
        return None, (f"That file has {len(rows):,} rows, which is beyond the "
                      f"{MAX_PARSED_ROWS:,}-row limit for a single import.")

    header, data = rows[0], rows[1:]
    col = {(c or "").strip(): i for i, c in enumerate(header)}
    try:
        report = reconcile(data, col)
    except Exception:
        return None, ("That file could not be reconciled. It may be missing "
                      "the expected Code / Sec / Schedule columns.")

    # The command's own narrative, as a secondary detail pane.
    buf = io.StringIO()
    try:
        call_command("import_offerings", file=path, dry_run=True, stdout=buf)
        detail = buf.getvalue()
    except Exception as exc:                       # narrative only, never fatal
        detail = f"(dry-run detail unavailable: {exc})"

    return {"report": report, "detail": detail, "row_count": len(data)}, None


def _staged_for(request):
    """The live staged row for this request's session token, or None."""
    token = request.session.get(IMPORT_SESSION_KEY)
    return resolve_staged(token, request.user) if token else None


def _import_ctx(request, *, staging=None, report=None, error=None,
                committed=None, discarded=False):
    return {"staging": staging, "report": report, "error": error,
            "committed": committed, "discarded": discarded,
            "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "allowed": ", ".join(sorted(ALLOWED_EXTENSIONS))}


@ifo_required
@require_http_methods(["GET"])
def import_page(request):
    """IFO-03b: the import console page.

    Sweeps abandoned staged uploads opportunistically. Plan 07-02 deliberately
    did NOT add a fifth scheduler job for this, because the 4-job count is an
    asserted invariant (`NoImplicitSchedulerTests` / `SchedulerWiringTests`);
    for a surface used a handful of times per term, sweeping on page load is
    the cheaper answer and costs a single indexed query.

    A staged-but-uncommitted file for this user is re-previewed, so reloading
    the page does not lose a review in progress.
    """
    sweep_abandoned()

    staging = _staged_for(request)
    report, error = None, None
    if staging is not None:
        report, error = _import_report(staged_path(staging))
    return render(request, "ifo/import.html",
                  _import_ctx(request, staging=staging, report=report,
                              error=error))


@ifo_required
@require_http_methods(["POST"])
def import_preview(request):
    """IFO-03b: stage the upload and show the dry-run reconciliation.

    NOTHING IS WRITTEN TO THE DATABASE HERE beyond the staging row itself. That
    is the entire point of D-12's preview step: a bad file is caught while it
    is still just bytes on disk.
    """
    uploaded = request.FILES.get("file")
    if uploaded is None:
        # Almost always the missing `hx-encoding="multipart/form-data"`: htmx
        # serializes as urlencoded by default, which cannot carry file content,
        # so the file silently never arrives and request.FILES is empty.
        return render(request, "ifo/_import_panel.html",
                      _import_ctx(request, error="Choose a file to upload."),
                      status=400)

    # An operator who uploads twice without committing would otherwise orphan
    # the first file until the TTL sweep.
    previous = _staged_for(request)
    if previous is not None:
        discard_staged(previous)
        request.session.pop(IMPORT_SESSION_KEY, None)

    try:
        staging = stage_upload(uploaded, request.user)
    except ImportStagingError as exc:
        return render(request, "ifo/_import_panel.html",
                      _import_ctx(request, error=str(exc)), status=400)

    report, error = _import_report(staged_path(staging))
    if error:
        # The bytes are unusable, so do not leave a row the operator cannot act
        # on and the sweeper has to collect later.
        discard_staged(staging)
        return render(request, "ifo/_import_panel.html",
                      _import_ctx(request, error=error), status=400)

    # ONLY the token. Never the path, never the bytes.
    request.session[IMPORT_SESSION_KEY] = staging.token
    return render(request, "ifo/_import_panel.html",
                  _import_ctx(request, staging=staging, report=report))


@ifo_required
@require_http_methods(["POST"])
def import_commit(request):
    """IFO-03b: apply the previewed file. Additive only (D-13).

    The token comes from `request.session` and from nowhere else (T-07-32).
    `resolve_staged` filters on `uploaded_by` AND on `consumed_at IS NULL`, so
    a cross-user commit and a double-submitted commit both resolve to None --
    which is a friendly message, not an exception.

    `import_offerings` uses `get_or_create` throughout and deletes nothing, so
    re-running the same file is idempotent. `reset_term` -- the destructive
    path that clears 2000+ Schedule/Session rows -- is NOT imported anywhere in
    `web/` and must not be (D-13, T-07-36).
    """
    staging = _staged_for(request)
    if staging is None:
        return render(request, "ifo/_import_panel.html", _import_ctx(
            request, error=("That upload is no longer available. Please upload "
                            "the file again.")), status=400)

    path = staged_path(staging)
    before = Schedule.objects.count()
    buf = io.StringIO()
    try:
        # Same options the preview used, so preview and commit can never
        # describe different work.
        call_command("import_offerings", file=path, dry_run=False, stdout=buf)
    except Exception as exc:
        # The staging row is deliberately NOT consumed: the operator should be
        # able to retry or discard rather than being stranded.
        return render(request, "ifo/_import_panel.html", _import_ctx(
            request, staging=staging,
            error=f"The import stopped partway through: {exc}"), status=400)

    created = Schedule.objects.count() - before
    consume_staged(staging)
    _delete_staged_file(staging)
    request.session.pop(IMPORT_SESSION_KEY, None)

    AuditLog.objects.create(
        actor=request.user, event_type="schedule.imported",
        target_type="import", target_id=str(staging.pk),
        # `original_name` is display text only -- never a path (T-07-31).
        payload={"original_name": staging.original_name,
                 "size_bytes": staging.size_bytes,
                 "schedules_created": created})

    return render(request, "ifo/_import_panel.html", _import_ctx(
        request, committed={"created": created, "detail": buf.getvalue(),
                            "original_name": staging.original_name}))


@ifo_required
@require_http_methods(["POST"])
def import_discard(request):
    """IFO-03b: drop a staged upload the operator reviewed and walked away from.

    Without this, a rejected preview sits on disk until the TTL sweeper
    collects it, and the operator has no way to say "no, not that file".
    """
    staging = _staged_for(request)
    if staging is not None:
        discard_staged(staging)
    request.session.pop(IMPORT_SESSION_KEY, None)
    return render(request, "ifo/_import_panel.html",
                  _import_ctx(request, discarded=True))


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
    # `_safe_parse_*` rather than the raw parsers: a shape-matching but
    # impossible value ("25:99", "2026-13-45") raises ValueError out of
    # `parse_time`/`parse_date` instead of returning None, so an `is None` test
    # alone still lets a fat-fingered time through as a 500.
    elif date_raw and _safe_parse_date(date_raw) is None:
        error = "Enter a valid date."
    elif start_raw and _safe_parse_time(start_raw) is None:
        error = "Enter a valid start time."
    elif end_raw and _safe_parse_time(end_raw) is None:
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

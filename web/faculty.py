"""Faculty surfaces (mobile-first, §2.5): today/week schedule (FAC-01), check-in,
and the modality-shift request surface (MOD-01/MOD-05/MOD-06, D-12).

MOD-06 / D-13: the modality-shift REQUEST workflow below (modality_new /
modality_mine / modality_withdraw) is the SOLE faculty entry point for changing a
session's modality. It replaces the retired FAC-07 faculty self-declare path --
there is no self-declare form or route here, by design. Same-day changes have no
formal path and fall back to existing scan-time behavior (D-13).
"""
from datetime import timedelta
from functools import wraps
from urllib.parse import urlparse

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from accounts.photos import (MAX_UPLOAD_BYTES, TARGET, PhotoError,
                             normalize_profile_photo)
from campus.models import Room
from ops.availability import available_rooms_for, available_times_for
from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.merge import (_effective_is_online, merged_sibling_ids,
                              propagate_merged_present)
from scheduling.models import (
    AcademicTerm,
    CheckinMethod,
    Modality,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Schedule,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from scheduling.resolver import is_no_show_past_grace
from verification.models import CheckerValidation, ValidationAction
from web.pagination import paginate
from web.reporting_common import status_label
from scheduling.services import (
    ModalityShiftError,
    submit_modality_shift,
    weeks_window,
    withdraw_modality_shift,
)

_OCCUPYING_STATUSES = (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)
_MAX_WEEKS = 16  # a term is ~14-16 weeks; cap the recurring-request span


def faculty_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.FACULTY and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def _greeting(now):
    """Time-of-day greeting for the Home dashboard header."""
    h = now.hour
    if h < 12:
        return "Good morning"
    if h < 18:
        return "Good afternoon"
    return "Good evening"


def _group_merged(sessions):
    """Collapse co-scheduled "merged" sections into single cards (D-01).

    A faculty teaching two sections at the same exact instant (same room/course,
    or any two online) is ONE presence event -- one check-in covers the group
    (scheduling.merge.propagate_merged_present). So the schedule should show them
    as one card, not duplicate rows. Uses the same pure D-01 detector as the
    check-in/verify/sweep seams so the display can never disagree with the fill.

    Returns a list of "card" dicts in schedule order, each aggregating its group:
    the representative session plus distinct rooms, total headcount, and count.
    """
    for s in sessions:  # annotate the fields the pure detector reads
        s.course_code = s.schedule.course_code
        s.is_online = _effective_is_online(s)

    cards, used = [], set()
    for anchor in sessions:
        if anchor.id in used:
            continue
        sibs = merged_sibling_ids(anchor, sessions)
        group = [anchor] + [s for s in sessions if s.id in sibs]
        for s in group:
            used.add(s.id)
        rooms = list(dict.fromkeys(s.room.code for s in group))  # distinct, ordered
        cards.append({
            "rep": anchor,
            "sessions": group,
            "merged": len(group) > 1,
            "count": len(group),
            "rooms": rooms,
            "rooms_label": ", ".join(rooms),
            "students": sum(s.schedule.enrolled_count for s in group),
            "modality": anchor.declared_modality or anchor.schedule.modality,
        })
    return cards


def _faculty_cards(user, now):
    """This faculty's sessions for today + the next 7 days, merged-grouped.
    Returns (today_cards, week_cards, today)."""
    today = now.date()
    week_end = today + timedelta(days=7)
    sessions = (Session.objects.filter(faculty=user,
                                       date__gte=today, date__lt=week_end)
                .select_related("schedule", "room__floor__building")
                .order_by("date", "scheduled_start"))
    todays, upcoming = [], []
    for s in sessions:
        (todays if s.date == today else upcoming).append(s)
    return _group_merged(todays), _group_merged(upcoming), today


@faculty_required
def home(request):
    """Check-in landing (the faculty app's Home tab): the one merged group the
    faculty most likely acts on now -- in-progress first, else next still ahead
    today, else the next upcoming session this week -- with its modality and the
    check-in actions. The full day/week list lives on Schedule."""
    now = timezone.localtime()
    today_cards, week_cards, today = _faculty_cards(request.user, now)

    def _is_active(card):
        return any(s.status == SessionStatus.ACTIVE for s in card["sessions"])

    def _is_next(card):
        return any(s.status == SessionStatus.SCHEDULED and s.scheduled_end >= now
                   for s in card["sessions"])

    hero = next((c for c in today_cards if _is_active(c)), None)
    hero_live = hero is not None
    if hero is None:
        hero = next((c for c in today_cards if _is_next(c)), None)
    if hero is None:  # nothing left today -> surface the next upcoming session
        hero = week_cards[0] if week_cards else None

    hero_is_today = bool(hero) and hero["rep"].date == today
    return render(request, "faculty/home.html", {
        "greeting": _greeting(now), "today": today,
        "hero": hero, "hero_live": hero_live, "hero_is_today": hero_is_today,
        "hero_modality": hero["modality"] if hero else "", "modalities": Modality,
        "today_count": len(today_cards),
    })


@faculty_required
def schedule(request):
    """Pure schedule: today + this week as scannable rows. No hero/CTAs/modality
    control -- the check-in action and modality live on Home."""
    now = timezone.localtime()
    today_cards, week_cards, today = _faculty_cards(request.user, now)
    return render(request, "faculty/schedule.html", {
        "today_cards": today_cards, "week_cards": week_cards,
        "today": today, "greeting": _greeting(now),
    })


@faculty_required
def scan_page(request):
    # Home's "Input Room Code" deep-links with ?manual=1 to open the OTP keypad.
    return render(request, "faculty/scan.html", {
        "auto_payload": "",
        "manual": request.GET.get("manual") == "1",
    })


# --- Modality-shift request surface (MOD-01/MOD-05, D-12) -------------------
# The service raises terse domain strings ("no in-window sessions to shift").
# Those are the right words for an exception and the wrong words for a faculty
# member on a phone, so they are translated HERE, at the presentation edge --
# scheduling.services keeps its vocabulary and its tests. Anything unmapped
# falls through unchanged rather than being swallowed.
_ERROR_COPY = {
    "no in-window sessions to shift":
        "None of those classes meet again inside that window. Try more weeks, "
        "or pick a date when the class actually meets.",
    "request is past the lead-time cutoff":
        "That is too soon. Shift requests need a couple of days' notice, so pick "
        "a later date or a longer window.",
    "no schedules selected":
        "Select at least one class.",
    "invalid target modality":
        "Choose what to shift the class to.",
    "window start is after window end":
        "That date range runs backwards. Check the dates.",
    "no Dean assigned - contact IFO":
        "Your department has no Dean assigned right now, so there is nobody to "
        "approve this. Contact the IFO and they can fix it.",
    "a time-move must be bundled with a F2F or Blended shift":
        "A new time only applies to a Face-to-face or Blended class. Clear the "
        "times, or shift to Face-to-face or Blended instead.",
    "the new time double-books the requesting faculty":
        "You already teach another class at that time. Pick a different slot.",
}

# Which step a given failure belongs to, so the form can reopen where the
# problem is instead of dumping the user back at step 1.
_STEP1_ERRORS = (
    "Select at least one class.", "Invalid class selection.",
    "One or more selected classes are not yours.",
)


def _friendly_error(message):
    return _ERROR_COPY.get(message, message)


def _error_step(message):
    return 1 if message in _STEP1_ERRORS else 2


def _modality_new_ctx(user, *, error=None, posted=None):
    """GET context for the submit form: the faculty's active schedules with an
    availability-first preview (D-05/D-15).

    For each active schedule the next upcoming SCHEDULED/ACTIVE session drives the
    picker data -- ``available_rooms_for`` (rooms free at that slot, original room
    first) and ``available_times_for`` (alternative same-day time-move slots).
    These are only meaningful for a ->F2F/Blended target; a ->Online shift needs no
    room. The concrete choice is finalized at Dean approval (D-06), so this is a
    preview, never a reservation.
    """
    today = timezone.localdate()
    term = AcademicTerm.objects.filter(is_active=True).first()
    schedules = []
    if term:
        schedules = list(
            Schedule.objects.filter(
                faculty=user, status=ScheduleStatus.ACTIVE, term=term)
            .select_related("room__floor__building")
            .order_by("day_of_week", "start_time"))
    # NO availability here. It used to be computed for every schedule on every
    # render, which cost 6.5s and 5488 queries on the real dataset -- almost all
    # of it inside available_times_for, which probes every room in the building
    # at every slot in the day. Step 1 only asks which classes to shift, so none
    # of that is needed to draw the page; it is fetched by modality_rooms() when
    # the user reaches step 2 with a room-based target, and only for the classes
    # they actually picked. Same context, 0.02s and 11 queries.
    picked = set(posted.getlist("schedules")) if posted else set()
    rows = []
    for sch in schedules:
        rows.append({
            "schedule": sch,
            "picked": str(sch.pk) in picked,
            "preferred": (posted.get(f"preferred_room_{sch.pk}") or "") if posted else "",
        })

    def _p(key, default=""):
        return (posted.get(key) or default) if posted else default

    return {
        "schedule_rows": rows,
        "modalities": Modality.choices,
        "error": _friendly_error(error) if error else None,
        "error_step": _error_step(error) if error else None,
        "form": {
            "target": _p("target_modality"),
            "window_mode": _p("window_mode", "weeks"),
            "weeks": _p("weeks", "1"),
            "on_date": _p("on_date"),
            "new_start_time": _p("new_start_time"),
            "new_end_time": _p("new_end_time"),
        },
    }


@faculty_required
@require_http_methods(["GET"])
def modality_rooms(request):
    """Step 2's room picker, fetched on demand (MOD-01/D-05/D-15).

    Availability is the expensive half of this surface: available_times_for
    probes every room in the building at every slot of the day, so rendering it
    for all nine of a faculty member's classes cost 6.5s. It is only ever needed
    once the user has (a) chosen classes and (b) chosen a room-based target, so
    it is computed here for THOSE schedules only -- typically one or two.

    Read-only and scoped: schedules are re-resolved to the requester's own active
    schedules, so a forged pk yields nothing rather than another faculty's rooms.
    """
    raw = (request.GET.get("schedules") or "").split(",")
    ids = [s for s in (r.strip() for r in raw) if s.isdigit()]
    rows = []
    if ids:
        schedules = (Schedule.objects
                     .filter(pk__in=ids, faculty=request.user,
                             status=ScheduleStatus.ACTIVE)
                     .select_related("room__floor__building")
                     .order_by("day_of_week", "start_time"))
        today = timezone.localdate()
        for sch in schedules:
            nxt = (Session.objects.filter(
                        schedule=sch, date__gte=today,
                        status__in=_OCCUPYING_STATUSES)
                   .select_related("schedule__room__floor__building")
                   .order_by("date", "scheduled_start").first())
            rows.append({
                "schedule": sch,
                "next_session": nxt,
                "rooms": available_rooms_for(nxt) if nxt else [],
                "times": available_times_for(nxt) if nxt else [],
                "preferred": (request.GET.get(f"pref_{sch.pk}") or ""),
            })
    return render(request, "faculty/_modality_rooms.html", {"schedule_rows": rows})


@faculty_required
def modality_new(request):
    """Submit an availability-first modality-shift request (MOD-01/D-05/D-15).

    GET renders the picker; POST validates FORMAT before any write (parse_date on
    the window, target modality in ``Modality.values``, numeric schedule/room pks)
    exactly like ``ifo.assignment_create`` and, on any bad input, re-renders the
    form partial at status=400 (never a 500). Selected schedules are re-resolved to
    the requester's OWN active schedules server-side; a forged room pk is never
    trusted -- it is passed as a mere preference and the service re-resolves rooms.
    A valid submit calls ``submit_modality_shift`` (lead-time gate + Dean routing);
    any service refusal (too-late, no Dean, double-book) surfaces as a friendly 400.
    """
    if request.method != "POST":
        return render(request, "faculty/modality_new.html",
                      _modality_new_ctx(request.user))

    target = request.POST.get("target_modality")
    mode = (request.POST.get("window_mode") or "weeks").strip()
    weeks_raw = (request.POST.get("weeks") or "").strip()
    on_date_raw = (request.POST.get("on_date") or "").strip()
    schedule_ids = request.POST.getlist("schedules")
    nst_raw = (request.POST.get("new_start_time") or "").strip()
    net_raw = (request.POST.get("new_end_time") or "").strip()

    # Validate FORMAT before any ORM write -- a bad enum/count/date/pk must be a
    # friendly 400, never an unhandled ValidationError (500). The window is derived
    # server-side from either a weeks count (recurring) or a single date (one-off);
    # the client never posts raw start/end dates (D-01/D-15, UAT 2026-07-05).
    error = None
    window_start = window_end = None
    if target not in Modality.values:
        error = "Select a valid target modality."
    elif not schedule_ids:
        error = "Select at least one class."
    elif not all(s.isdigit() for s in schedule_ids):
        error = "Invalid class selection."
    elif mode == "single":
        on_date = parse_date(on_date_raw)
        if on_date is None:
            error = "Pick a valid date for the single session."
        else:
            window_start = window_end = on_date
    elif not weeks_raw.isdigit() or not (1 <= int(weeks_raw) <= _MAX_WEEKS):
        error = f"Choose how many weeks (1 to {_MAX_WEEKS})."
    else:
        window_start, window_end = weeks_window(int(weeks_raw))
    if error is None and (nst_raw or net_raw) and (
            parse_time(nst_raw) is None or parse_time(net_raw) is None):
        error = "Enter a valid alternative start and end time."

    # Re-resolve schedules to the requester's OWN active schedules (never trust the
    # posted pk set for ownership). A mismatch means a forged/foreign schedule.
    schedules = []
    if error is None:
        schedules = list(Schedule.objects.filter(
            pk__in=schedule_ids, faculty=request.user,
            status=ScheduleStatus.ACTIVE))
        if len(schedules) != len(set(schedule_ids)):
            error = "One or more selected classes are not yours."

    # Preferred rooms are a PREFERENCE only (D-05/D-06): the client room pk is never
    # trusted -- the service re-resolves free rooms at approval. Validate numericness
    # here so a bad pk is a 400, not a 500.
    preferred_rooms = {}
    if error is None:
        for sch in schedules:
            rk = (request.POST.get(f"preferred_room_{sch.pk}") or "").strip()
            if not rk:
                continue
            if not rk.isdigit():
                error = "Invalid room selection."
                break
            room = Room.objects.filter(pk=rk).first()
            if room is not None:
                preferred_rooms[sch] = room

    time_move = None
    if error is None and nst_raw and net_raw:
        time_move = (parse_time(nst_raw), parse_time(net_raw))

    if error is None:
        try:
            submit_modality_shift(
                request.user, schedules, target,
                window_start, window_end,
                preferred_rooms=preferred_rooms or None,
                time_move=time_move,
            )
        except ModalityShiftError as exc:
            error = str(exc)

    if error is not None:
        ctx = _modality_new_ctx(request.user, error=error, posted=request.POST)
        return render(request, "faculty/_modality_form.html", ctx, status=400)

    # Success: PRG to the "my requests" list. htmx uses HX-Redirect so the whole
    # page navigates rather than swapping the list into the form panel.
    if request.headers.get("HX-Request"):
        resp = HttpResponse(status=204)
        resp["HX-Redirect"] = reverse("faculty_modality_mine")
        return resp
    return redirect("faculty_modality_mine")


def _modality_mine_ctx(user, *, error=None):
    """Context for the 'my requests' list: only the requester's tickets (D-12)."""
    requests = (ModalityShiftRequest.objects.filter(requester=user)
                .select_related("dean", "department")
                .prefetch_related("items__schedule")
                .order_by("-created_at"))
    return {"requests": requests, "error": error,
            "PENDING": ModalityShiftStatus.PENDING}


@faculty_required
def modality_mine(request):
    """The faculty's own modality-shift requests with per-status display (MOD-05).

    Scoped strictly to ``requester=request.user`` -- a faculty never sees another's
    tickets. Each row shows target modality, window, affected classes, status
    (pending/approved/rejected/withdrawn/denied) with the decision reason for
    rejected/denied, and a Withdraw control only while PENDING (D-10).
    """
    return render(request, "faculty/modality_mine.html",
                  _modality_mine_ctx(request.user))


@faculty_required
@require_http_methods(["POST"])
def modality_withdraw(request, pk):
    """Withdraw a still-PENDING ticket (MOD-05/D-10). POST-only; guard delegated.

    Re-fetches the request by pk and calls ``withdraw_modality_shift`` which itself
    re-checks requester==user AND status==PENDING inside the transaction (never the
    earlier snapshot / client -- the IDOR re-gate, T-04-01). A foreign or
    non-pending withdraw is refused and the list re-renders with the error at 400;
    on success the updated list renders.
    """
    req = get_object_or_404(ModalityShiftRequest, pk=pk)
    error = None
    try:
        withdraw_modality_shift(req, request.user)
    except ModalityShiftError as exc:
        error = str(exc)
    ctx = _modality_mine_ctx(request.user, error=error)
    return render(request, "faculty/modality_mine.html", ctx,
                  status=400 if error else 200)


# --- Online "Verify & Start" (FAC-08, D-01/D-02/D-03) -----------------------
# Starting and verifying are two distinct acts by two people, not two competing
# claims about one fact (D-01). This surface owns the START half only: the
# faculty member pastes the meeting link and the session becomes ACTIVE. The
# Checker's independent VERIFY half lives in web/checker.py and is untouched
# here -- `verified_by_checker` is never written by this module, so a self-start
# that nobody ever verifies stays ACTIVE (it was genuinely held) while reporting
# as unverified on the Dean/IFO/HR scorecards (D-02).

# Hosts that serve a real MS Teams meeting join page. Matched on the host ONLY,
# with an exact-or-dot-boundary test -- never a substring search over the whole
# URL, which `https://example.com/teams.microsoft.com/meet` satisfies while
# pointing at an attacker's site (T-07-48). A Checker clicks whatever lands
# here, so this list is a trust decision, not a formatting nicety.
_TEAMS_HOSTS = (
    "teams.microsoft.com",      # commercial cloud
    "teams.live.com",           # Teams for personal/consumer meetings
    "teams.cloud.microsoft",    # the newer Microsoft 365 domain
    "teams.microsoft.us",       # GCC / GCC-High
    "gov.teams.microsoft.us",
    "dod.teams.microsoft.us",
)

# Server-computed display state per online session card. Colour is NEVER the only
# signal (WCAG 1.4.1): every state also carries a Lucide icon and a text label.
# Mirrors web/checker.py `_CARD_STYLES` -- the template never branches on colour.
_ONLINE_STYLES = {
    "upcoming": {"card": "ft-card--neutral", "pill": "ft-pill ft-pill--upcoming",
                 "icon": "clock", "label": "Not started"},
    "startable": {"card": "ft-card--info", "pill": "ft-pill ft-pill--online",
                  "icon": "monitor", "label": "Ready to start"},
    "active": {"card": "ft-card--ok", "pill": "ft-pill ft-pill--active",
               "icon": "play", "label": "In session"},
    # SCHEDULED but already past grace: the sweep has not run yet, but a start is
    # refused, so the card must not offer one. Same predicate, same answer.
    "past-grace": {"card": "ft-card--warn", "pill": "ft-pill ft-pill--late",
                   "icon": "alert-triangle", "label": "Past grace window"},
    "absent": {"card": "ft-card--bad", "pill": "ft-pill ft-pill--absent",
               "icon": "x", "label": "Absent"},
    "completed": {"card": "ft-card--neutral", "pill": "ft-pill ft-pill--done",
                  "icon": "check", "label": "Done"},
}

# The two states from which `online_start` will accept a write. Display and the
# write ladder read the SAME tokens, so the page can never offer a Start that the
# POST would then refuse.
_STARTABLE_STATES = ("upcoming", "startable")


def _is_effective_online(session):
    """Effective modality is Online: a declared override beats the schedule.

    The same override rule used at ops/availability.py:54 and web/guard.py:98.
    """
    return (session.declared_modality or session.schedule.modality) == Modality.ONLINE


def _online_state(session, now, grace_min):
    """Map an online session to a display-state token (see `_ONLINE_STYLES`).

    The past-grace branch calls the SHARED `is_no_show_past_grace` predicate
    rather than re-deriving a cutoff, so this surface, the scan resolver and the
    JOB-02 sweep can never disagree about whether a class is still startable.
    """
    if session.status == SessionStatus.ACTIVE:
        return "active"
    if session.status == SessionStatus.COMPLETED:
        return "completed"
    if session.status == SessionStatus.ABSENT:
        return "absent"
    if is_no_show_past_grace(session.scheduled_start, now, grace_min):
        return "past-grace"
    if now < session.scheduled_start:
        return "upcoming"
    return "startable"


def _online_row(session, now, grace_min, *, error=None):
    """One rendered card: the session, its state token, its style, its actions."""
    state = _online_state(session, now, grace_min)
    return {
        "session": session,
        "state": state,
        "style": _ONLINE_STYLES[state],
        "can_start": state in _STARTABLE_STATES,
        "error": error,
    }


def _online_rows(user, now):
    """The requesting faculty's EFFECTIVE-online sessions for today.

    Scoped server-side to `faculty=user` and today's date before anything else --
    the rendered list is a snapshot, never the authorization (see `online_start`).
    `select_related` covers everything the card reads, so the list is one query.
    """
    grace_min = get_policy("grace_minutes")
    sessions = (Session.objects
                .filter(faculty=user, date=now.date())
                .select_related("schedule", "room")
                .order_by("scheduled_start"))
    return [_online_row(s, now, grace_min)
            for s in sessions if _is_effective_online(s)]


def _teams_link_error(raw):
    """Validate a pasted MS Teams meeting URL. Returns an error string or None.

    Requires https (a Checker is asked to click this, so a downgradeable link is
    not acceptable) and requires the HOST to be a Teams host by an exact or
    dot-boundary match. `evilteams.microsoft.com` and
    `https://example.com/teams.microsoft.com/meet` both fail, which a substring
    check over the URL would not (T-07-48).
    """
    if not raw:
        return ("Paste the Microsoft Teams meeting link for this class.")
    try:
        parsed = urlparse(raw)
    except ValueError:
        return "That does not look like a link. Paste the full meeting URL."
    if parsed.scheme != "https":
        return ("The meeting link must start with https:// -- "
                "copy it from Teams with 'Copy link'.")
    host = (parsed.hostname or "").lower()
    if not any(host == d or host.endswith("." + d) for d in _TEAMS_HOSTS):
        return ("That is not a Microsoft Teams meeting link. It should look "
                "like https://teams.microsoft.com/l/meetup-join/...")
    return None


@faculty_required
@require_http_methods(["GET"])
def online_list(request):
    """FAC-08: the requesting faculty's Online classes for today, with Start.

    Read-only. Scoped to `faculty=request.user` and today; only sessions whose
    EFFECTIVE modality is Online appear -- Blended still checks in by QR, and a
    Blended class showing a Start box here would be a lie about how it is held.
    """
    now = timezone.localtime()
    rows = _online_rows(request.user, now)
    return render(request, "faculty/online.html", {
        "rows": rows, "today": now.date(), "greeting": _greeting(now),
    })


@faculty_required
@require_http_methods(["POST"])
def online_start(request, pk):
    """FAC-08/D-01: start an own Online session from a pasted Teams link.

    The full validation ladder runs BEFORE any write, and every rung is re-derived
    server-side from the re-fetched row -- the list the faculty member saw is a
    snapshot, never the authorization (the IDOR re-gate rule, see
    `modality_withdraw` above). A forged pk must not start someone else's class.

    On success this writes exactly four columns: `teams_link` (D-03 -- the SAME
    field web/checker.py `online_open` reads, which is what stops its `no_link`
    branch from firing, so the two roles can never verify against different
    meetings), `status`, `actual_start` and `checkin_method`. It does NOT touch
    `verified_by_checker` (a derived property over CheckerValidation rows) and
    writes no CheckerValidation: starting is not verifying (D-02). It does not
    touch `online_checker` either -- online duty is IFO's to assign.

    The JOB-02 sweep needs no change: it only moves SCHEDULED sessions to ABSENT,
    so a self-started ACTIVE session is naturally skipped (D-02). Co-scheduled
    siblings are filled via `propagate_merged_present` in the same transaction
    (04.2 D-04) -- the same one-action-covers-the-group rule as a room scan or a
    checker online Verify, so the sweep cannot falsely absent a sibling of a
    started merged group.
    """
    now = timezone.localtime()
    grace_min = get_policy("grace_minutes")
    raw_link = (request.POST.get("teams_link") or "").strip()

    # 1. Ownership, re-gated on the re-fetched row. A foreign pk is a 404, not a
    #    403: this surface must not confirm that another faculty's session exists.
    session = get_object_or_404(
        Session.objects.select_related("schedule", "room"),
        pk=pk, faculty=request.user)

    error = None
    # 2. Effective modality, re-derived server-side.
    if not _is_effective_online(session):
        error = ("This class is not Online, so it checks in by scanning the "
                 "room QR or entering the room code.")
    # 3. Status. ABSENT is final -- CHK-06 was removed and Absent is the sweep's
    #    decision, not something a late start may quietly undo. ACTIVE is already
    #    started; COMPLETED is over.
    elif session.status != SessionStatus.SCHEDULED:
        if session.status == SessionStatus.ACTIVE:
            error = "This class is already started."
        elif session.status == SessionStatus.ABSENT:
            error = ("This class is recorded as Absent and cannot be started. "
                     "A Checker can correct it if you did hold it.")
        else:
            error = "This class is already finished."
    # 4. Grace. The SHARED predicate is called, never copied -- it is the single
    #    atom the scan resolver and the sweep agree on, and this surface must
    #    agree with both. Discretion call: reusing the F2F/Blended grace rule for
    #    an online start is a consistency choice, revisitable as a policy.
    elif is_no_show_past_grace(session.scheduled_start, now, grace_min):
        error = (f"Start is past the {grace_min}-minute grace window for this "
                 f"class, so it can no longer be started here.")
    # 5. The pasted link.
    else:
        error = _teams_link_error(raw_link)

    if error is not None:
        # Render the row straight from the re-fetched session rather than from
        # `_online_rows`: a refused NON-online session is not in that list at all,
        # and the refusal must still be shown rather than swapping in an empty box.
        row = _online_row(session, now, grace_min, error=error)
        return render(request, "faculty/_online_start.html",
                      {"rows": [row]}, status=400)

    with transaction.atomic():
        previous = session.teams_link
        session.teams_link = raw_link
        session.status = SessionStatus.ACTIVE
        session.actual_start = timezone.now()
        session.checkin_method = CheckinMethod.ONLINE_SELF
        session.save(update_fields=["teams_link", "status", "actual_start",
                                    "checkin_method"])
        # Overwrites are the interesting case: a link changed mid-class is
        # exactly what a Checker who could not join would need explained, so the
        # PREVIOUS value is carried in the payload (T-07-51).
        AuditLog.objects.create(
            actor=request.user, event_type="session.teams_link_set",
            target_type="session", target_id=str(session.pk),
            payload={"session": session.pk, "previous_teams_link": previous,
                     "teams_link": raw_link,
                     "checkin_method": CheckinMethod.ONLINE_SELF.value})
        # One start covers the co-scheduled group (04.2 D-04): the same
        # propagation the room-scan and checker-Verify seams already run, inside
        # the same transaction as the anchor write so the group never half-flips.
        # Without this, the sweep marks the un-started sibling Absent even though
        # the instructor is holding the one merged meeting that covers both.
        propagate_merged_present(session, session.actual_start,
                                 actor=request.user)

    row = _online_row(session, now, grace_min)
    return render(request, "faculty/_online_start.html", {"rows": [row]})


# --- Attendance history (FAC-11, D-15) --------------------------------------
# READ-ONLY, Checker flags visible, and NO contest/dispute control anywhere. The
# flag is already the system of record feeding the Dean/HR/IFO scorecards; a
# dispute state machine plus a reviewer surface is real scope of its own and is a
# recorded deferred idea, not a Phase 7 clarification. Disputes go through HR out
# of band (D-15).

FACULTY_HISTORY_PAGE_SIZE = 25

# The two actions that are a flag AGAINST the faculty member. VERIFIED_EMPTY is
# deliberately excluded: "the Checker found the room empty" is not the same claim
# as "this faculty member was not present", and counting it here would put a mark
# on a record that nobody actually made.
_FACULTY_FLAG_ACTIONS = (ValidationAction.FLAG_IDENTITY_MISMATCH,
                         ValidationAction.FLAG_NOT_PRESENT)


def _history_filters(request):
    """Parse the history filter bar, mirroring `web/hr.py:_filtered_sessions`.

    FK-id filters apply only when the raw value is a clean integer; dates go
    through `parse_date` and an invalid one drops just that bound behind a
    friendly note -- a 200 with a notice, never a 500. Filters key on the FK id
    and `date__range` ONLY: never a `pk__in` list, which is how this project has
    previously hit the MSSQL 2100-parameter limit (the 04.1-04 `reset_term`
    incident, and 06-07 avoided it the same way).

    NOTE what is absent: there is no `faculty` parameter. Not a defaulted one,
    not an ignored one -- this surface does not accept the concept, which is the
    whole reason it is a separate view rather than HR's with another template.
    """
    term_raw = (request.GET.get("term") or "").strip()
    from_raw = (request.GET.get("from") or "").strip()
    to_raw = (request.GET.get("to") or "").strip()

    note = None
    d_from = parse_date(from_raw) if from_raw else None
    d_to = parse_date(to_raw) if to_raw else None
    if (from_raw and d_from is None) or (to_raw and d_to is None):
        note = ("That date wasn't valid, so the date filter was ignored. "
                "Enter dates as YYYY-MM-DD.")
    return {
        "term": term_raw, "date_from": from_raw, "date_to": to_raw,
        "note": note, "_term_id": int(term_raw) if term_raw.isdigit() else None,
        "_d_from": d_from, "_d_to": d_to,
        "any_applied": bool(term_raw or from_raw or to_raw),
    }


@faculty_required
@require_http_methods(["GET"])
def history(request):
    """FAC-11: the requesting faculty member's own attendance history.

    HARD-SCOPED to `faculty=request.user` server-side (T-07-53). `web/hr.py`
    `attendance` is the model for everything else here, but HR is cross-
    department and takes a faculty filter from the querystring; this surface must
    not accept one at all. That is the IDOR re-gate rule stated at
    `modality_withdraw` above.

    Verification and flags are resolved by `Exists()` ANNOTATIONS in the main
    query, never by the per-object `Session.verified_by_checker` property: that
    property issues a subquery per object, which 06-07 found fatal inside a
    streaming iterator on MSSQL and which is an N+1 even here.
    """
    filters = _history_filters(request)

    verified_sq = CheckerValidation.objects.filter(
        session=OuterRef("pk"), action=ValidationAction.VERIFIED)
    flagged_sq = CheckerValidation.objects.filter(
        session=OuterRef("pk"), action__in=_FACULTY_FLAG_ACTIONS)

    qs = (Session.objects
          .filter(faculty=request.user)
          .select_related("schedule", "schedule__term", "room")
          .annotate(is_verified=Exists(verified_sq),
                    is_flagged=Exists(flagged_sq))
          # Newest-first, matching HR, so the page shows the most recent sessions
          # rather than the oldest historical rows.
          .order_by("-date", "-scheduled_start"))

    if filters["_term_id"] is not None:
        qs = qs.filter(schedule__term_id=filters["_term_id"])
    if filters["_d_from"] is not None:
        qs = qs.filter(date__gte=filters["_d_from"])
    if filters["_d_to"] is not None:
        qs = qs.filter(date__lte=filters["_d_to"])

    pager = paginate(request, qs, per_page=FACULTY_HISTORY_PAGE_SIZE)
    # Materialize BEFORE the flag-detail lookup below. MSSQL runs with MARS off,
    # so a follow-up query issued while an outer cursor is still open raises
    # HY010 (the guards in scheduling/jobs.py and web/ifo.py:131 are the
    # precedent).
    sessions = list(pager["page"].object_list)

    # ONE additional query for the flag reasons on this page, not one per row.
    # The id list is bounded by the page size, so it cannot approach the 2100
    # parameter ceiling.
    flagged_ids = [s.pk for s in sessions if s.is_flagged]
    reasons = {}
    if flagged_ids:
        for v in (CheckerValidation.objects
                  .filter(session_id__in=flagged_ids,
                          action__in=_FACULTY_FLAG_ACTIONS)
                  .order_by("session_id", "-validated_at")):
            reasons.setdefault(v.session_id, v.get_action_display())

    for s in sessions:
        s.present_label = status_label(s.status)
        s.flag_reason = reasons.get(s.pk, "")

    ctx = {"sessions": sessions, "filters": filters,
           "term_choices": AcademicTerm.objects.order_by("-is_active",
                                                         "-start_date"),
           "greeting": _greeting(timezone.localtime()),
           "today": timezone.localdate(), **pager}
    return render(request, "faculty/history.html", ctx)


# --- Profile: identity photo (FAC-12, D-16) ---------------------------------
# FAC-12 has two halves and only ONE of them is new here. The notification
# preferences half already ships for every role at web/notifications.py
# settings_page / mute_toggle (routed notif_settings / notif_mute), so this page
# LINKS to it rather than growing a second copy of the mute logic. Two mute
# surfaces would drift, and the one a faculty member happened to find would be
# the one that lied to them.
#
# The photo is identity evidence: a Checker looks at it to confirm the person in
# the room is the scheduled faculty member. All validation, re-encoding and
# EXIF-stripping lives in accounts/photos.py, which is pure bytes-in/bytes-out --
# see that module's docstring for why the re-encode IS the security control.


def _photo_version(field):
    """A cache-buster for the <img> src.

    Re-uploading can land on the SAME stored name: the old file is deleted after
    the new one is written, so the sequence is 7.jpg -> 7_a8Kd2.jpg -> 7.jpg. On
    that third upload the URL is unchanged and the browser would happily show the
    previous photo, which reads as "the upload silently did nothing". One stat
    call fixes it. A missing file is not an error here -- the template renders the
    placeholder in that case anyway.
    """
    try:
        return int(default_storage.get_modified_time(field.name).timestamp())
    except (OSError, NotImplementedError, ValueError):
        return 0


def _profile_ctx(user, *, error=None, saved=False):
    """Context for the profile page and for its small status region."""
    return {
        "photo": user.profile_photo if user.profile_photo else None,
        "photo_v": _photo_version(user.profile_photo) if user.profile_photo else 0,
        "error": error,
        "saved": saved,
        "max_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "target_px": TARGET[0],
        "today": timezone.localdate(),
        "greeting": _greeting(timezone.localtime()),
    }


def _photo_status(request, user, *, error=None, saved=False):
    """Render ONLY the small status region (never the form -- see the template).

    400 on a refusal is the project's friendly-400 seam (web/faculty.py
    modality_withdraw is the precedent): a readable message, never a 500.
    """
    return render(request, "faculty/_photo_status.html",
                  _profile_ctx(user, error=error, saved=saved),
                  status=400 if error else 200)


@faculty_required
@require_http_methods(["GET"])
def profile(request):
    """The faculty member's own profile: identity photo + a link to notification
    preferences (FAC-12). Read-only; the photo write is a separate POST view."""
    return render(request, "faculty/profile.html", _profile_ctx(request.user))


@faculty_required
@require_http_methods(["POST"])
def profile_photo_upload(request):
    """Replace the requesting faculty member's identity photo (FAC-12, D-16).

    The target is ALWAYS request.user. No user id is read from the POST body --
    the IDOR re-gate this module states at modality_withdraw. A posted id is not
    rejected with an error, it is simply never consulted, which is the shape that
    cannot be got wrong later by someone adding a "convenience" lookup.
    """
    upload = request.FILES.get("photo")
    if upload is None:
        # Also the symptom of a missing hx-encoding on the form: htmx serializes
        # as urlencoded by default and the file silently never arrives.
        return _photo_status(request, request.user,
                             error="Choose a JPEG or PNG photo to upload.")

    try:
        data = normalize_profile_photo(upload)
    except PhotoError as exc:
        return _photo_status(request, request.user, error=str(exc))

    user = request.user
    # Captured BEFORE the save. FileSystemStorage.get_available_name appends a
    # random suffix on collision, so without this the same user accumulates
    # profile_photos/7.jpg, 7_a8Kd2.jpg, 7_pQ91x.jpg... forever.
    old_name = user.profile_photo.name or ""

    # This one call writes the file AND the field. Do NOT follow it with a
    # user.save(update_fields=[...]) that omits profile_photo -- that stores the
    # bytes and then drops the pointer to them.
    user.profile_photo.save(f"{user.pk}.jpg", ContentFile(data), save=True)

    if old_name and old_name != user.profile_photo.name:
        try:
            default_storage.delete(old_name)
        except (OSError, NotImplementedError):
            # A missing old file is the goal state, not an error worth failing a
            # successful upload over.
            pass

    AuditLog.objects.create(
        actor=user, event_type="user.photo_updated", target_type="user",
        target_id=str(user.pk),
        # Byte size only. An identity photo does not belong in an audit payload.
        payload={"user": user.pk, "bytes": len(data)})

    return _photo_status(request, user, saved=True)

"""Checker room-scan verification surface (CHK-01..05).

Mirrors web/scan.py's seam: the outcome DECISION is the pure core
(verification/resolver.resolve_checker_scan, 03-01); this module only fetches
context, re-gates against CURRENT on-duty state, writes CheckerValidation +
AuditLog, and fires notify() to IFO + HR for flags. On-duty gating lives in the
pure core — never re-derived inline in a view (project rule #1).

The `action` endpoint NEVER trusts the client's gating: it re-identifies the
room from POST `room_id`, recomputes the room's session state server-side, and
UNCONDITIONALLY re-runs resolve_checker_scan against the checker's current
active floors before any write. A forged or stale POST for a floor the checker
is no longer on duty for is refused and writes nothing (T-03-03/05).
"""
import re
from functools import wraps
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog
from ops.notify import notify
from ops.policy import get_policy
from scheduling.models import CheckinMethod, Modality, Session, SessionStatus
from verification import resolver as R
from verification.models import (Assignment, AssignmentScope, CheckerValidation,
                                 DutyRole, ValidationAction)

_FLAG_ACTIONS = {ValidationAction.FLAG_IDENTITY_MISMATCH,
                 ValidationAction.FLAG_NOT_PRESENT}
_VALID_ACTIONS = set(ValidationAction.values)


# --- authorization ---------------------------------------------------------
def checker_required(view):
    """Per-view role guard (Convention rule #5), mirroring ifo_required."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.CHECKER and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


# --- on-duty state ---------------------------------------------------------
def _active_floor_ids(user, now):
    """Floor pks the checker is on duty for RIGHT NOW (CHK-01).

    An active FLOOR-scoped CHECKER assignment grants powers when it is either a
    standing posting (`date` NULL) or a shift covering `now` (`date` == today
    and start_time <= now <= end_time; either bound may be NULL/open). This is
    the server's sole source of the checker's floors — the client never supplies
    its own gating floor.
    """
    local = timezone.localtime(now)
    today, now_t = local.date(), local.time()
    floor_ids = set()
    assignments = (Assignment.objects
                   .filter(user=user, role=DutyRole.CHECKER,
                           scope=AssignmentScope.FLOOR, status="active")
                   .prefetch_related("floors"))
    for a in assignments:
        if a.date is None:
            on_duty = True                       # standing posting
        elif a.date == today:
            start_ok = a.start_time is None or a.start_time <= now_t
            end_ok = a.end_time is None or now_t <= a.end_time
            on_duty = start_ok and end_ok        # shift covering now
        else:
            on_duty = False
        if on_duty:
            floor_ids.update(a.floors.values_list("pk", flat=True))
    return floor_ids


# --- room + session state --------------------------------------------------
def _room_from_payload(request, payload):
    """QR deep link (…?t=TOKEN) or a six-digit manual code -> (room, method).

    Returns (None, error) for a bad/rate-limited payload. The manual-code path is
    rate-limited per user-per-minute (T-03-07), mirroring web/scan.py; the QR
    path is not (an opaque token is not brute-forceable).
    """
    payload = (payload or "").strip()
    token = None
    if "t=" in payload:
        qs = parse_qs(urlparse(payload).query)
        token = (qs.get("t") or [None])[0]
    if token:
        return Room.objects.filter(qr_token=token).first(), CheckinMethod.QR_SCAN

    if re.fullmatch(r"\d{6}", payload):
        user = request.user
        minute = timezone.now().strftime("%Y%m%d%H%M")
        key = f"checker-rl:{user.pk}:{minute}"
        limit = get_policy("manual_code_rate_limit_per_min")
        count = cache.get_or_set(key, 0, timeout=90)
        if count >= limit:
            AuditLog.objects.create(actor=user, event_type="checker.rate_limited",
                                    payload={"attempts": count + 1})
            return None, "rate-limited"
        cache.incr(key)
        room = Room.objects.filter(manual_code=payload).first()
        if room is None:
            AuditLog.objects.create(actor=user, event_type="checker.bad_manual_code",
                                    payload={})
        return room, CheckinMethod.MANUAL_CODE

    return None, "bad-payload"


class _SessionState:
    """Minimal value object the pure core reads: .id / .status / .verified."""

    def __init__(self, id, status, verified):
        self.id = id
        self.status = status
        self.verified = verified


def _room_session_state(room, now):
    """Today's non-online session in `room` -> (session, _SessionState) or
    (None, None) when the room is empty.

    F2F/Blended only: an online session (declared or scheduled) has no room-scan
    target in this plan (online verify is 03-05), so it reads as an empty room.
    Completed sessions are ignored (the room is free again).
    """
    session = (Session.objects
               .filter(room=room, date=timezone.localdate())
               .exclude(status=SessionStatus.COMPLETED)
               .select_related("schedule", "faculty")
               .order_by("scheduled_start")
               .first())
    if session is None:
        return None, None
    effective = session.declared_modality or session.schedule.modality
    if effective == Modality.ONLINE:
        return None, None
    return session, _SessionState(session.pk, session.status,
                                  session.verified_by_checker)


# --- apply layer -----------------------------------------------------------
def _apply_action(request, session, room, action, *, note="", identity_match=None,
                  scanned_at=None, offline=False):
    """Write the CheckerValidation + AuditLog and, for flags, notify IFO + HR.

    Thin apply (mirror web/scan.py._apply): no gating decision here — the caller
    has already re-gated through the pure core. Online status semantics
    (Verify-activation, Flag-not-present -> Absent) are 03-05; this plan is
    F2F/Blended only.
    """
    cv = CheckerValidation.objects.create(
        session=session, room=room, checker=request.user, action=action,
        identity_match=identity_match, note=note, scanned_at=scanned_at,
        offline_queued=offline)
    AuditLog.objects.create(
        actor=request.user, event_type=f"checker.{action}",
        target_type="session", target_id=str(session.pk if session else ""),
        payload={"room": room.code, "offline": offline})
    if action in _FLAG_ACTIONS:
        # Consequential: reaches IFO + HR permanently, no dispute. The note is
        # mandatory (validated in the view). notify() is the single write path.
        who = request.user.get_full_name() or request.user.username
        notify(role=Role.IFO_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action} by {who}. {note}")
        notify(role=Role.HR_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action}. {note}")
    return cv


# --- views -----------------------------------------------------------------
@checker_required
def scan_page(request):
    return render(request, "checker/scan.html")


@checker_required
@require_http_methods(["POST"])
def resolve(request):
    now = timezone.now()
    room, method = _room_from_payload(request, request.POST.get("payload", ""))
    if room is None:
        return render(request, "checker/_outcome.html", {"error": method})

    session, state = _room_session_state(room, now)
    resolution = R.resolve_checker_scan(
        _active_floor_ids(request.user, now), room.floor_id, state, now)
    return render(request, "checker/_outcome.html", {
        "resolution": resolution, "room": room, "session": session})


@checker_required
@require_http_methods(["POST"])
def action(request):
    now = timezone.now()
    action_val = request.POST.get("action", "")
    note = request.POST.get("note", "")

    if action_val not in _VALID_ACTIONS:
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})

    # Re-identify the room from POST (ids identify WHICH room only; they are NOT
    # trusted for gating). A missing/forged room_id degrades to an error partial.
    room = (Room.objects.filter(pk=request.POST.get("room_id"))
            .select_related("floor").first())
    if room is None:
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})

    # UNCONDITIONAL server-side re-gate: recompute the room's session state and
    # re-run the pure core against CURRENT on-duty floors before any write. A
    # stale/off-duty action is refused here and writes nothing (T-03-03/05).
    session, state = _room_session_state(room, now)
    resolution = R.resolve_checker_scan(
        _active_floor_ids(request.user, now), room.floor_id, state, now)

    if not resolution.actionable:
        AuditLog.objects.create(
            actor=request.user, event_type="checker.action_refused",
            target_type="room", target_id=str(room.pk),
            payload={"outcome": resolution.outcome, "action": action_val})
        return render(request, "checker/_outcome.html", {
            "resolution": resolution, "room": room, "session": session})

    # Flags require a note (Pitfall 4). Reject empty server-side with a 200 error
    # partial (never a 500) and write nothing.
    if action_val in _FLAG_ACTIONS and not note.strip():
        return render(request, "checker/_outcome.html", {
            "error": "note-required", "resolution": resolution,
            "room": room, "session": session})

    identity_match = None
    if action_val == ValidationAction.FLAG_IDENTITY_MISMATCH:
        identity_match = False
    elif action_val == ValidationAction.VERIFIED:
        identity_match = True

    # Idempotency: same checker + room/session + minute does not re-apply.
    scope_pk = session.pk if session else room.pk
    idem = f"checker-idem:{request.user.pk}:{scope_pk}:{now:%Y%m%d%H%M}"
    if cache.get(idem) != action_val:
        _apply_action(request, session, room, action_val, note=note,
                      identity_match=identity_match, scanned_at=now)
        cache.set(idem, action_val, timeout=120)

    return render(request, "checker/_outcome.html", {
        "resolution": resolution, "room": room, "session": session,
        "applied": True, "applied_action": action_val})

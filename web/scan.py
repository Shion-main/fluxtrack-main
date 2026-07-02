"""
Scan endpoints (SCAN-01..07): payload lookup, rate limiting, idempotency,
two-step signed confirmations, and outcome side effects.

The outcome *decision* is the pure resolver (scheduling/resolver.py);
this module fetches context, applies state changes, and renders outcomes.
"""
import re
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog
from ops.notify import notify
from ops.policy import get_policy
from scheduling import resolver as R
from scheduling.models import CheckinMethod, Session, SessionStatus

CONFIRM_SALT = "fluxtrack.scan.confirm"
CONFIRM_MAX_AGE = 180  # seconds a two-step token stays valid (SCAN-04)


# --- payload -> room -------------------------------------------------------
def _room_from_payload(request, payload):
    """Accept a QR deep link (…/scan?t=TOKEN or fluxtrack://…) or a six-digit
    manual code. Returns (room, method) or (None, error_response)."""
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
        key = f"scan-rl:{user.pk}:{minute}"
        limit = get_policy("manual_code_rate_limit_per_min")
        count = cache.get_or_set(key, 0, timeout=90)
        if count >= limit:
            AuditLog.objects.create(actor=user, event_type="scan.rate_limited",
                                    payload={"attempts": count + 1})
            return None, "rate-limited"
        cache.incr(key)
        room = Room.objects.filter(manual_code=payload).first()
        if room is None:
            AuditLog.objects.create(actor=user, event_type="scan.bad_manual_code",
                                    payload={})
        return room, CheckinMethod.MANUAL_CODE

    return None, "bad-payload"


# --- outcome side effects --------------------------------------------------
def _apply(request, resolution, room, method, reason=""):
    """Apply the resolved outcome's state changes. Returns context for rendering."""
    now = timezone.now()
    user = request.user
    session = (Session.objects.filter(pk=resolution.session_id).first()
               if resolution.session_id else None)

    def audit(event, **payload):
        AuditLog.objects.create(actor=user, event_type=event,
                                target_type="session",
                                target_id=str(session.pk if session else ""),
                                payload=payload)

    o = resolution.outcome
    if o == R.CHECKED_IN:
        session.status = SessionStatus.ACTIVE
        session.actual_start = now
        session.checkin_method = method
        session.save(update_fields=["status", "actual_start", "checkin_method"])
        audit("session.checked_in", room=room.code, method=method)
    elif o == R.ABSENT:
        if session.status == SessionStatus.SCHEDULED:
            session.status = SessionStatus.ABSENT
            session.save(update_fields=["status"])
            audit("session.marked_absent", room=room.code)
    elif o == R.CHECKED_OUT:
        session.status = SessionStatus.COMPLETED
        session.actual_end = now
        session.save(update_fields=["status", "actual_end"])
        audit("session.checked_out", room=room.code)
    elif o == R.EARLY_END:  # confirmed early end (reason supplied)
        session.status = SessionStatus.COMPLETED
        session.actual_end = now
        session.ended_early = True
        session.early_end_reason = reason
        session.save(update_fields=["status", "actual_end", "ended_early",
                                    "early_end_reason"])
        audit("session.ended_early", room=room.code, reason=reason)
    elif o == R.WRONG_ROOM:  # confirmed room change (FAC-10)
        old = session.room.code
        session.room = room
        session.save(update_fields=["room"])
        audit("session.room_changed", old_room=old, new_room=room.code)
        notify(role=Role.IFO_ADMIN, type="room_event", title="Room change",
               body=f"{user.get_full_name() or user.username} moved "
                    f"{session.schedule.course_code} from {old} to {room.code}.")
    elif o == R.ROOM_OCCUPIED:  # confirmed force handover (FAC-09)
        prior = Session.objects.filter(pk=resolution.prior_session_id).first()
        if prior and prior.status == SessionStatus.ACTIVE:
            prior.status = SessionStatus.COMPLETED
            prior.actual_end = now
            prior.save(update_fields=["status", "actual_end"])
        session.status = SessionStatus.ACTIVE
        session.actual_start = now
        session.checkin_method = CheckinMethod.FORCE_HANDOVER
        session.handover_from_session = prior
        session.save(update_fields=["status", "actual_start", "checkin_method",
                                    "handover_from_session"])
        audit("session.force_handover", room=room.code,
              prior_session=resolution.prior_session_id)
        notify(role=Role.IFO_ADMIN, type="room_event", title="Force handover",
               body=f"{room.code}: prior session auto-completed; "
                    f"{session.schedule.course_code} started via handover.")
    return {"resolution": resolution, "room": room, "session": session}


# --- views ------------------------------------------------------------------
@login_required
@require_http_methods(["POST"])
def resolve(request):
    payload = request.POST.get("payload", "")
    room, method = _room_from_payload(request, payload)
    if room is None:
        return render(request, "faculty/_outcome.html",
                      {"resolution": None, "error": method})

    now = timezone.now()
    sessions_today = list(
        Session.objects.filter(faculty=request.user, date=timezone.localdate())
        .select_related("schedule", "room").order_by("scheduled_start"))
    occupying = (Session.objects.filter(room=room, status=SessionStatus.ACTIVE)
                 .exclude(faculty=request.user).values_list("pk", flat=True).first())

    resolution = R.resolve_faculty_scan(
        sessions_today, room.pk, occupying, now,
        grace_min=get_policy("grace_minutes"),
        early_end_min=get_policy("early_end_threshold_minutes"))

    ctx = {"resolution": resolution, "room": room}
    if resolution.needs_confirm:
        # Two-step: sign the resolution; apply only on /scan/confirm (SCAN-04).
        ctx["confirm_token"] = signing.dumps(
            {"outcome": resolution.outcome, "session_id": resolution.session_id,
             "prior_session_id": resolution.prior_session_id, "room_id": room.pk,
             "method": method, "user_id": request.user.pk},
            salt=CONFIRM_SALT)
    elif resolution.session_id:
        # Idempotency: same user+session+minute returns without reapplying (SCAN-06).
        idem = f"scan-idem:{request.user.pk}:{resolution.session_id}:{now:%Y%m%d%H%M}"
        if cache.get(idem) != resolution.outcome:
            ctx = _apply(request, resolution, room, method)
            cache.set(idem, resolution.outcome, timeout=120)
        else:
            ctx["session"] = Session.objects.filter(pk=resolution.session_id).first()
    return render(request, "faculty/_outcome.html", ctx)


@login_required
@require_http_methods(["POST"])
def confirm(request):
    try:
        data = signing.loads(request.POST.get("token", ""), salt=CONFIRM_SALT,
                             max_age=CONFIRM_MAX_AGE)
    except signing.BadSignature:
        return HttpResponseBadRequest("Confirmation expired or invalid.")
    if data["user_id"] != request.user.pk:
        return HttpResponseBadRequest("Token does not belong to this user.")

    room = Room.objects.get(pk=data["room_id"])
    resolution = R.Resolution(data["outcome"], data["session_id"],
                              prior_session_id=data.get("prior_session_id"))
    ctx = _apply(request, resolution, room, data["method"],
                 reason=request.POST.get("reason", ""))
    ctx["confirmed"] = True
    return render(request, "faculty/_outcome.html", ctx)


@login_required
def deep_link(request):
    """QR deep-link landing (SCAN-07): /scan?t=TOKEN — auto-resolves on load.
    @login_required sends anonymous users through sign-in and back here."""
    token = request.GET.get("t", "")
    return render(request, "faculty/scan.html",
                  {"auto_payload": f"/scan?t={token}" if token else ""})

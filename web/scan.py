"""
Scan endpoints (SCAN-01..07): payload lookup, rate limiting, idempotency,
two-step signed confirmations, and outcome side effects.

The outcome *decision* is the pure resolver (scheduling/resolver.py);
this module fetches context, applies state changes, and renders outcomes.
"""
import re
import secrets
from urllib.parse import parse_qs, urlparse

from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog
from ops.notify import notify
from ops.policy import get_policy
from ops.locking import serialized_write
from scheduling import resolver as R
from scheduling.jobs import close_finished_sessions_for
from scheduling.merge import (
    propagate_merged_completed,
    propagate_merged_present,
    propagate_merged_room,
)
from scheduling.models import CheckinMethod, Session, SessionStatus
from scheduling.term_scope import get_active_term
from web.faculty import faculty_required

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


def _current_resolution(user, room, now):
    """Resolve one faculty scan against current authoritative state."""
    active_term = get_active_term()
    if active_term is None:
        return None
    sessions_today = list(
        Session.objects.filter(
            faculty=user,
            date=timezone.localdate(),
            schedule__term=active_term,
        )
        .select_related("schedule", "room")
        .order_by("scheduled_start")
    )
    occupying = (
        # A room released by IFO no longer counts as occupied, even if its
        # session remains ACTIVE for attendance/audit purposes.
        Session.objects.filter(
            room=room,
            status=SessionStatus.ACTIVE,
            room_released_at__isnull=True,
            schedule__term=active_term,
        )
        .exclude(faculty=user)
        .values_list("pk", flat=True)
        .first()
    )
    return R.resolve_faculty_scan(
        sessions_today,
        room.pk,
        occupying,
        now,
        grace_min=get_policy("grace_minutes"),
        early_end_min=get_policy("early_end_threshold_minutes"),
    )


def _stale_context(room):
    return {
        "resolution": None,
        "room": room,
        "error": "stale-confirmation",
    }


# --- outcome side effects --------------------------------------------------
@serialized_write
def _apply(request, resolution, room, method, reason=""):
    """Apply the resolved outcome's state changes. Returns context for rendering."""
    now = timezone.now()
    user = request.user
    room.refresh_from_db()
    if room.out_of_service:
        return {"resolution": None, "room": room, "error": "out-of-service"}
    active_term = get_active_term()
    session = (
        Session.objects.filter(
            pk=resolution.session_id,
            faculty=user,
            schedule__term=active_term,
        )
        .select_related("schedule", "room")
        .first()
        if resolution.session_id and active_term is not None else None
    )
    if resolution.session_id and session is None:
        return _stale_context(room)

    def audit(event, **payload):
        AuditLog.objects.create(actor=user, event_type=event,
                                target_type="session",
                                target_id=str(session.pk if session else ""),
                                payload=payload)

    o = resolution.outcome
    if o == R.CHECKED_IN:
        if session.status != SessionStatus.SCHEDULED:
            return _stale_context(room)
        # Anchor write + merged-group present fill share ONE transaction (D-04):
        # a rollback of the anchor rolls back every propagated sibling too.
        with transaction.atomic():
            close_finished_sessions_for(user, now)
            session.status = SessionStatus.ACTIVE
            session.actual_start = now
            session.checkin_method = method
            session.save(update_fields=["status", "actual_start", "checkin_method"])
            audit("session.checked_in", room=room.code, method=method)
            # Anchor keeps its REAL method (D-09); only SCHEDULED siblings become
            # MERGED via the helper's status-guarded, faculty-scoped fill.
            propagate_merged_present(session, now, user)
    elif o == R.ABSENT:
        if session.status == SessionStatus.SCHEDULED:
            session.status = SessionStatus.ABSENT
            session.save(update_fields=["status"])
            audit("session.marked_absent", room=room.code)
    elif o == R.CHECKED_OUT:
        if session.status != SessionStatus.ACTIVE:
            return _stale_context(room)
        with transaction.atomic():
            session.status = SessionStatus.COMPLETED
            session.actual_end = now
            session.save(update_fields=["status", "actual_end"])
            audit("session.checked_out", room=room.code)
            propagate_merged_completed(session, now, user)
    elif o == R.EARLY_END:  # confirmed early end (reason supplied)
        if session.status != SessionStatus.ACTIVE:
            return _stale_context(room)
        with transaction.atomic():
            session.status = SessionStatus.COMPLETED
            session.actual_end = now
            session.ended_early = True
            session.early_end_reason = reason
            session.save(update_fields=["status", "actual_end", "ended_early",
                                        "early_end_reason"])
            audit("session.ended_early", room=room.code, reason=reason)
            propagate_merged_completed(
                session,
                now,
                user,
                ended_early=True,
                reason=reason,
            )
    elif o == R.WRONG_ROOM:  # confirmed room change (FAC-10)
        if session.status not in (SessionStatus.SCHEDULED, SessionStatus.ACTIVE):
            return _stale_context(room)
        if Session.objects.filter(room=room, status=SessionStatus.ACTIVE,
                                  room_released_at__isnull=True,
                                  schedule__term=active_term).exclude(faculty=user).exists():
            return {"resolution": R.Resolution(R.MOVE_OCCUPIED, session.pk), "room": room}
        old = session.room.code
        with transaction.atomic():
            # Before the anchor moves: same-room siblings are found through the
            # room it is leaving. Left behind, they would lose the merge and be
            # swept Absent.
            siblings = propagate_merged_room(session, room, user)
            session.room = room
            session.save(update_fields=["room"])
            audit("session.room_changed", old_room=old, new_room=room.code)
        also = f" with {len(siblings)} merged section(s)" if siblings else ""
        notify(role=Role.IFO_ADMIN, type="room_event", title="Room change",
               body=f"{user.get_full_name() or user.username} moved "
                    f"{session.schedule.course_code}{also} from {old} to "
                    f"{room.code}.")
    elif o == R.ROOM_OCCUPIED:  # confirmed force handover (FAC-09)
        if session.status != SessionStatus.SCHEDULED:
            return _stale_context(room)
        # Prior auto-complete + anchor handover + merged-group present fill all
        # share ONE transaction (D-04), mirroring the CHECKED_IN path. The prior
        # occupant is a DIFFERENT faculty and is never merge-filled (faculty-
        # scoped helper, T-04.2-01).
        with transaction.atomic():
            prior = (
                Session.objects.select_for_update().filter(
                    pk=resolution.prior_session_id,
                    room=room,
                    status=SessionStatus.ACTIVE,
                    room_released_at__isnull=True,
                    schedule__term=active_term,
                ).exclude(faculty=user).first()
                if active_term is not None else None
            )
            if prior is None:
                return _stale_context(room)
            prior.status = SessionStatus.COMPLETED
            prior.actual_end = now
            prior.save(update_fields=["status", "actual_end"])
            propagate_merged_completed(prior, now, user)
            close_finished_sessions_for(user, now)
            session.status = SessionStatus.ACTIVE
            session.actual_start = now
            session.checkin_method = CheckinMethod.FORCE_HANDOVER
            session.handover_from_session = prior
            session.save(update_fields=["status", "actual_start", "checkin_method",
                                        "handover_from_session"])
            audit("session.force_handover", room=room.code,
                  prior_session=resolution.prior_session_id)
            # Anchor keeps FORCE_HANDOVER (D-09); siblings become MERGED.
            propagate_merged_present(session, now, user)
        notify(role=Role.IFO_ADMIN, type="room_event", title="Force handover",
               body=f"{room.code}: prior session auto-completed; "
                    f"{session.schedule.course_code} started via handover.")
    return {"resolution": resolution, "room": room, "session": session}


# --- views ------------------------------------------------------------------
@faculty_required
@require_http_methods(["POST"])
@serialized_write
def resolve(request):
    payload = request.POST.get("payload", "")
    room, method = _room_from_payload(request, payload)
    if room is None:
        return render(request, "faculty/_outcome.html",
                      {"resolution": None, "error": method})
    # Out-of-service (Phase 10, A7): a room closed for renovation refuses check-in
    # with a clear reason rather than resolving against stale schedule state.
    if room.out_of_service:
        detail = ("This room is out of service"
                  + (f" ({room.out_of_service_reason})."
                     if room.out_of_service_reason else ".")
                  + " Ask the IFO office where your class has moved.")
        return render(request, "faculty/_outcome.html",
                      {"resolution": None, "error": "out-of-service",
                       "error_detail": detail})

    now = timezone.now()
    resolution = _current_resolution(request.user, room, now)
    if resolution is None:
        return render(request, "faculty/_outcome.html",
                      {"resolution": None, "error": "bad-payload"})
    ctx = {"resolution": resolution, "room": room}
    if resolution.needs_confirm:
        # Two-step: sign the resolution; apply only on /scan/confirm (SCAN-04).
        ctx["confirm_token"] = signing.dumps(
            {"outcome": resolution.outcome, "session_id": resolution.session_id,
             "prior_session_id": resolution.prior_session_id, "room_id": room.pk,
             "method": method, "user_id": request.user.pk,
             "nonce": secrets.token_urlsafe(18)},
            salt=CONFIRM_SALT)
    elif resolution.session_id:
        # Idempotency: same user+session+minute returns without reapplying (SCAN-06).
        idem = f"scan-idem:{request.user.pk}:{resolution.session_id}:{resolution.outcome}:{now:%Y%m%d%H%M}"
        if cache.add(idem, True, timeout=120):
            try:
                ctx = _apply(request, resolution, room, method)
            except Exception:
                cache.delete(idem)
                raise
        else:
            ctx["session"] = Session.objects.filter(
                pk=resolution.session_id,
                faculty=request.user,
                schedule__term=get_active_term(),
            ).first()
    return render(request, "faculty/_outcome.html", ctx)


@faculty_required
@require_http_methods(["POST"])
@serialized_write
def confirm(request):
    try:
        data = signing.loads(request.POST.get("token", ""), salt=CONFIRM_SALT,
                             max_age=CONFIRM_MAX_AGE)
    except signing.BadSignature:
        return HttpResponseBadRequest("Confirmation expired or invalid.")
    if data["user_id"] != request.user.pk:
        return HttpResponseBadRequest("Token does not belong to this user.")

    room = Room.objects.filter(pk=data.get("room_id")).first()
    if room is None:
        return HttpResponseBadRequest("Confirmation room no longer exists.")
    if room.out_of_service:
        return HttpResponse("This room is out of service. Scan another room.", status=409)
    resolution = R.Resolution(data["outcome"], data["session_id"],
                              prior_session_id=data.get("prior_session_id"))
    current = _current_resolution(request.user, room, timezone.now())
    expected = (
        resolution.outcome,
        resolution.session_id,
        resolution.prior_session_id,
    )
    actual = (
        current.outcome,
        current.session_id,
        current.prior_session_id,
    ) if current is not None else None
    if actual != expected:
        return HttpResponse(
            "The session changed. Scan the room again.",
            status=409,
        )

    reason = (request.POST.get("reason") or "").strip()
    if resolution.outcome == R.EARLY_END and not reason:
        return HttpResponseBadRequest("A reason is required to end early.")

    nonce = data.get("nonce")
    if not nonce or not cache.add(
        f"scan-confirm-used:{request.user.pk}:{nonce}",
        True,
        timeout=CONFIRM_MAX_AGE,
    ):
        return HttpResponse("This confirmation was already used.", status=409)

    claim_key = f"scan-confirm-used:{request.user.pk}:{nonce}"
    try:
        ctx = _apply(request, resolution, room, data["method"], reason=reason)
    except Exception:
        cache.delete(claim_key)
        raise
    if ctx.get("error") == "stale-confirmation":
        return HttpResponse(
            "The session changed. Scan the room again.",
            status=409,
        )
    ctx["confirmed"] = True
    return render(request, "faculty/_outcome.html", ctx)


@faculty_required
def deep_link(request):
    """QR deep-link landing (SCAN-07): /scan?t=TOKEN — auto-resolves on load.
    @login_required sends anonymous users through sign-in and back here."""
    token = request.GET.get("t", "")
    return render(request, "faculty/scan.html",
                  {"auto_payload": f"/scan?t={token}" if token else ""})

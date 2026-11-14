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
import json
import re
from datetime import timedelta
from functools import wraps
from urllib.parse import parse_qs, urlparse
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from ops.locking import serialized_write
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from web.pagination import paginate
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog, Notification
from ops.notify import notify
from ops.policy import get_policy
from scheduling.merge import (merged_group_session_ids,
                              propagate_merged_absent,
                              propagate_merged_present)
from scheduling.models import CheckinMethod, Modality, Session, SessionStatus
from scheduling.resolver import is_no_show_past_grace
from scheduling.term_scope import get_active_term
from verification import resolver as R
from verification.models import (Assignment, AssignmentScope,
                                 CheckerReplayReceipt, CheckerValidation,
                                 DutyRole, ValidationAction)
from web.parsing import is_id

_FLAG_ACTIONS = {ValidationAction.FLAG_IDENTITY_MISMATCH,
                 ValidationAction.FLAG_NOT_PRESENT}
_VALID_ACTIONS = set(ValidationAction.values)

# Which action(s) each ACTIONABLE outcome permits (CR-02). resolution.actionable
# only tells us SOME action applies; this pins WHICH. A forged POST applying
# `verified_empty` to an occupied ACTIVE_UNVERIFIED session — or `verified` to an
# empty NO_SESSION room — is incongruent and refused (audited, writes nothing).
_OUTCOME_ACTIONS = {
    R.NO_SESSION: {ValidationAction.VERIFIED_EMPTY},
    R.ACTIVE_UNVERIFIED: {ValidationAction.VERIFIED,
                          ValidationAction.FLAG_IDENTITY_MISMATCH,
                          ValidationAction.FLAG_NOT_PRESENT},
}


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
    active_term = get_active_term()
    if active_term is None:
        return set()
    floor_ids = set()
    assignments = (Assignment.objects
                   .filter(user=user, role=DutyRole.CHECKER,
                           scope=AssignmentScope.FLOOR, status="active",
                           term=active_term)
                   .prefetch_related("floors"))
    for a in assignments:
        if R.assignment_covers_now(a, today, now_t):  # shared predicate (IN-03)
            floor_ids.update(a.floors.values_list("pk", flat=True))
    return floor_ids


def _is_online_on_duty(user, now):
    """True iff the checker holds an active ONLINE-scope CHECKER assignment RIGHT
    NOW (CHK-02/IFO-06) — the online analog of `_active_floor_ids`.

    Online duty is floor-agnostic: a standing posting (`date` NULL) is on duty
    whenever active; a shift is on duty only when `now` falls inside its window
    (either bound may be NULL/open). This is the server's sole source of the
    checker's online-duty state — the client never asserts it (CHK-01 rule).
    """
    local = timezone.localtime(now)
    today, now_t = local.date(), local.time()
    active_term = get_active_term()
    if active_term is None:
        return False
    for a in (Assignment.objects
              .filter(user=user, role=DutyRole.CHECKER,
                      scope=AssignmentScope.ONLINE, status="active",
                      term=active_term)):
        if R.assignment_covers_now(a, today, now_t):  # shared predicate (IN-03)
            return True
    return False


def _online_session(session_id, user):
    """The effective-online session identified by `session_id` AND owned by
    `user` (`Session.online_checker == user`), or None (CHK-02).

    Ownership and modality are ALWAYS re-derived server-side from the id — the
    id names WHICH session only, never that the caller may act on it (the same
    CHK-01 rule the F2F floor path enforces). A non-numeric id, a missing
    session, a non-online session, or a foreign owner all resolve to None.
    """
    if not is_id(session_id):
        return None
    active_term = get_active_term()
    if active_term is None:
        return None
    session = (Session.objects.filter(pk=session_id)
               .filter(schedule__term=active_term)
               .select_related("schedule", "faculty", "room").first())
    if session is None:
        return None
    effective = session.declared_modality or session.schedule.modality
    if effective != Modality.ONLINE:
        return None
    if session.online_checker_id != user.pk:
        return None
    return session


class _OnlineRefusal:
    """Minimal resolution shim so the online re-gate can reuse `_outcome.html`'s
    off-duty / absent-excluded refusal alerts (no F2F room state involved)."""

    actionable = False

    def __init__(self, outcome):
        self.outcome = outcome


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


def _room_from_replay_token(token):
    """QR token or six-digit manual code -> Room, or None (CHK-08 replay).

    Reuses `_room_from_payload`'s lookup STYLE (QR token first, manual code
    fallback) without its rate limiting: a replay POST is already
    `checker_required` + idempotency-guarded per item, so the manual-code
    brute-force concern (T-03-07) does not apply here.
    """
    token = (token or "").strip()
    if not token:
        return None
    room = Room.objects.filter(qr_token=token).select_related("floor").first()
    if room is None and re.fullmatch(r"\d{6}", token):
        room = Room.objects.filter(manual_code=token).select_related("floor").first()
    return room


def _replay_manual_code_allowed(user, now):
    """Per-checker-per-minute cap on manual-code (6-digit) lookups during replay
    (WR-02). Reuses the `_room_from_payload` rate-limit idiom so a single batch
    POST — each item a fresh client_uuid + a different six-digit guess, none of
    which trips the per-uuid idempotency guard — cannot enumerate manual codes
    for rooms across the whole campus, unthrottled. QR-token lookups are exempt
    (opaque, not brute-forceable).
    """
    minute = now.strftime("%Y%m%d%H%M")
    key = f"checker-replay-rl:{user.pk}:{minute}"
    limit = get_policy("manual_code_rate_limit_per_min")
    count = cache.get_or_set(key, 0, timeout=90)
    if count >= limit:
        return False
    cache.incr(key)
    return True


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
    target in this plan (online verify is 03-05), so it is skipped and can never
    hide a real class in the room. Completed sessions are ignored (the room is
    free again).

    Selection is `now`-aware (CR-01): prefer the room's ACTIVE session, else the
    session whose scheduled window contains `now`, else the room reads empty. A
    stale earlier-in-the-day ABSENT session (ABSENT is never COMPLETED) must NOT
    latch and block verifying a later session in the same room.
    """
    active_term = get_active_term()
    if active_term is None:
        return None, None
    sessions = [s for s in (Session.objects
                            .filter(room=room, date=timezone.localdate(),
                                    schedule__term=active_term)
                            .exclude(status=SessionStatus.COMPLETED)
                            .select_related("schedule", "faculty")
                            .order_by("scheduled_start"))
                if (s.declared_modality or s.schedule.modality) != Modality.ONLINE]
    session = next((s for s in sessions if s.status == SessionStatus.ACTIVE), None)
    if session is None:
        session = next((s for s in sessions
                        if s.scheduled_start <= now <= s.scheduled_end), None)
    if session is None:
        return None, None
    return session, _SessionState(session.pk, session.status,
                                  session.verified_by_checker)


def _room_session_at_scan(room, scanned_at):
    """Best historical identity for a legacy/offline-first queued room scan.

    New queue records carry ``session_id`` explicitly. Older records cannot, so
    infer the session whose room window contained the original scan time. An
    ambiguous timestamp fails closed instead of being attached to a later class.
    """
    if timezone.is_naive(scanned_at):
        scanned_at = timezone.make_aware(scanned_at)
    active_term = get_active_term()
    if active_term is None:
        return None
    candidates = list(
        Session.objects.filter(
            room=room,
            date=timezone.localdate(scanned_at),
            schedule__term=active_term,
            scheduled_start__lte=scanned_at,
            scheduled_end__gte=scanned_at,
        )
        .select_related("schedule")
        .order_by("scheduled_start")
    )
    return next((s for s in candidates
                 if (s.declared_modality or s.schedule.modality) != Modality.ONLINE),
                None)


# --- apply layer -----------------------------------------------------------
@serialized_write
def _apply_action(request, session, room, action, *, note="", identity_match=None,
                  scanned_at=None, offline=False, online=False):
    """Write the CheckerValidation + AuditLog and, for flags, notify IFO + HR.

    Thin apply (mirror web/scan.py._apply): no gating decision here — the caller
    has already re-gated (through the pure core for F2F, or the online re-gate in
    `_online_action`). For an online action (`online=True`) this ALSO carries the
    online status semantics (03-05): a Verify ACTIVATES the session (the online
    analog of a faculty room check-in), and a Flag-not-present drives it ABSENT
    authoritatively. F2F/Blended NEVER overrides status here (record-only) — an
    F2F Flag-not-present writes the flag and notifies, but leaves status to the
    sweep (no silent status override, research Open Q2).
    """
    cv = CheckerValidation.objects.create(
        session=session, room=room, checker=request.user, action=action,
        identity_match=identity_match, note=note, scanned_at=scanned_at,
        offline_queued=offline)
    AuditLog.objects.create(
        actor=request.user, event_type=f"checker.{action}",
        target_type="session", target_id=str(session.pk if session else ""),
        payload={"room": room.code, "offline": offline, "online": online})

    # Online branch: the only non-faculty write that moves a session out of
    # SCHEDULED. A genuine online attendee made ACTIVE is precisely what lets the
    # sweep safely include online (scheduling/jobs.py exclusion removed in lockstep).
    if online and session is not None:
        group_ids = merged_group_session_ids(session)
        before = _class_states(group_ids)
        if action == ValidationAction.VERIFIED:
            # One online Verify covers the whole online merged group present
            # (D-04/D-06 online). Anchor write + sibling fill share ONE
            # transaction so the group can never half-flip. Siblings are
            # server-derived via the D-01 course_code / V-room key -- teams_link
            # is NEVER consulted (Post-Research Clarification #1). Merge-filled
            # siblings get checkin_method=MERGED + a session.merged_present
            # AuditLog but NO CheckerValidation (D-09), so verified_by_checker
            # coverage stays honest (CHK-04 not inflated).
            with transaction.atomic():
                session.status = SessionStatus.ACTIVE
                if session.actual_start is None:
                    session.actual_start = scanned_at or timezone.now()
                    session.checkin_method = CheckinMethod.ONLINE_MANUAL
                session.save(update_fields=["status", "actual_start", "checkin_method"])
                propagate_merged_present(session, session.actual_start,
                                         actor=request.user)
        elif action == ValidationAction.FLAG_NOT_PRESENT:
            # Online not-present fails the online merged group ABSENT (D-07
            # online), in ONE transaction. A sibling a Checker activated or
            # verified has its own evidence and stays ACTIVE, and the helper's
            # grace gate (audit H2) defers within-grace SCHEDULED siblings to
            # the sweep.
            with transaction.atomic():
                session.status = SessionStatus.ABSENT  # authoritative (Open Q2)
                session.save(update_fields=["status"])
                propagate_merged_absent(session, actor=request.user)
        # Remember exactly which class rows this action changed, so an undo can
        # put back those rows and nothing else.
        after = _class_states(group_ids)
        cv.restore = {pk: {"before": before[pk], "after": after[pk]}
                      for pk in before if after.get(pk) != before[pk]}
        cv.save(update_fields=["restore"])

    if action in _FLAG_ACTIONS:
        # Consequential: reaches IFO + HR permanently, no dispute. The note is
        # mandatory (validated in the view). notify() is the single write path.
        who = request.user.get_full_name() or request.user.username
        notify(role=Role.IFO_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action} by {who}. {note}")
        notify(role=Role.HR_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action}. {note}")
    return cv


# --- undo (checklist 3.3, decided 2026-11-14) -------------------------------
# A Checker who taps the wrong result can take it back for UNDO_WINDOW, from the
# result screen. Only their own live taps: an offline replay arrives late and is
# not offered. Undo deletes the CheckerValidation (so every report and board that
# reads validations is right at once); the AuditLog keeps both the tap and the
# undo. A flag already reached IFO and HR, so they get a "Flag withdrawn" notice.
UNDO_WINDOW = timedelta(minutes=5)
_CLASS_STATE_FIELDS = ("status", "actual_start", "checkin_method")


def _class_states(session_ids, *, lock=False):
    """{str(pk): {status, actual_start (ISO or None), checkin_method}}."""
    qs = Session.objects.filter(pk__in=session_ids)
    if lock:
        qs = qs.select_for_update()
    out = {}
    for row in qs.values("pk", *_CLASS_STATE_FIELDS):
        start = row["actual_start"]
        out[str(row["pk"])] = {
            "status": row["status"],
            "actual_start": start.isoformat() if start else None,
            "checkin_method": row["checkin_method"]}
    return out


def _acted_at(cv):
    # scanned_at is the server clock at the tap for live actions.
    return cv.scanned_at or cv.validated_at


def _idem_key(user_pk, scope_pk, action, at):
    """The per-minute double-tap guard key `action` and `_online_action` set."""
    return f"checker-idem:{user_pk}:{scope_pk}:{action}:{at:%Y%m%d%H%M}"


def _undo_target(user, session, room, action, now):
    """This Checker's still-undoable live tap for this result, if any.

    Looked up rather than taken from the write, so a double tap (whose second
    request writes nothing) still gets the Undo button on the screen it shows.
    """
    qs = CheckerValidation.objects.filter(
        checker=user, room=room, action=action, offline_queued=False)
    qs = qs.filter(session=session) if session else qs.filter(session__isnull=True)
    cv = qs.order_by("-validated_at").first()
    if cv is None or now > _acted_at(cv) + UNDO_WINDOW:
        return None
    return cv


def _own_verify_to_undo(user, resolution, session, room, now):
    """On "Already verified", this Checker's own Verify if still undoable."""
    if getattr(resolution, "outcome", None) != R.ALREADY_VERIFIED:
        return None
    return _undo_target(user, session, room, ValidationAction.VERIFIED, now)


@checker_required
@require_http_methods(["POST"])
@serialized_write
def undo(request, pk):
    cv = (CheckerValidation.objects
          .select_related("room", "session__schedule")
          .filter(pk=pk, checker=request.user).first())
    if cv is None:
        raise Http404("No such check of yours.")
    now = timezone.now()
    ctx = {"room": cv.room, "session": cv.session, "undone_action": cv.action,
           "undo_online": bool(cv.session
                               and cv.session.online_checker_id == request.user.pk)}
    if cv.offline_queued or now > _acted_at(cv) + UNDO_WINDOW:
        return render(request, "checker/_outcome.html",
                      {**ctx, "undo_refused": "too-late"})

    restore = cv.restore or {}
    with transaction.atomic():
        current = _class_states(restore.keys(), lock=True)
        if any(current.get(k) != v["after"] for k, v in restore.items()):
            return render(request, "checker/_outcome.html",
                          {**ctx, "undo_refused": "changed"})
        for k, v in restore.items():
            b = v["before"]
            Session.objects.filter(pk=int(k)).update(
                status=b["status"], checkin_method=b["checkin_method"],
                actual_start=parse_datetime(b["actual_start"])
                if b["actual_start"] else None)
        AuditLog.objects.create(
            actor=request.user, event_type="checker.undone",
            target_type="session" if cv.session_id else "room",
            target_id=str(cv.session_id or cv.room_id),
            payload={"action": cv.action, "note": cv.note, "room": cv.room.code,
                     "acted_at": _acted_at(cv).isoformat(),
                     "restored": sorted(int(k) for k in restore)})
        if cv.action in _FLAG_ACTIONS:
            who = request.user.get_full_name() or request.user.username
            body = (f"{cv.room.code}: the {cv.get_action_display().lower()} "
                    f"sent by {who} was withdrawn by them. Please disregard it.")
            for role in (Role.IFO_ADMIN, Role.HR_ADMIN):
                notify(role=role, type="checker_flag_withdrawn",
                       title="Checker flag withdrawn", body=body)
        cache.delete(_idem_key(request.user.pk, cv.session_id or cv.room_id,
                               cv.action, _acted_at(cv)))
        cv.delete()
    return render(request, "checker/_outcome.html", {**ctx, "undone": True})


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
        "resolution": resolution, "room": room, "session": session,
        "undo_cv": _own_verify_to_undo(request.user, resolution, session, room, now)})


@checker_required
@require_http_methods(["POST"])
@serialized_write
def action(request):
    now = timezone.now()
    action_val = request.POST.get("action", "")
    note = request.POST.get("note", "")

    if action_val not in _VALID_ACTIONS:
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})

    # Online branch: a POST with a session_id and NO room_id targets an online
    # session (no room-scan). Re-gated server-side against ownership + on-duty +
    # actionable in `_online_action`, mirroring the floor re-gate below.
    room_id = request.POST.get("room_id")
    session_id = request.POST.get("session_id")
    if not room_id and session_id:
        return _online_action(request, session_id, action_val, note, now)

    # Re-identify the room from POST (ids identify WHICH room only; they are NOT
    # trusted for gating). A missing/forged room_id degrades to an error partial.
    # Guard non-numeric room_id BEFORE the ORM filter (CR-03) — an AutoField pk
    # filtered on "abc" raises ValidationError (500); mirror the online path's
    # `is_id` guard so it degrades to the bad-payload partial (200).
    if not is_id(room_id):
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})
    room = (Room.objects.filter(pk=room_id)
            .select_related("floor").first())
    if room is None:
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})

    if room.out_of_service:
        return render(request, "checker/_outcome.html", {"error": "out-of-service"})

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
            "resolution": resolution, "room": room, "session": session,
            "undo_cv": _own_verify_to_undo(request.user, resolution, session,
                                           room, now)})

    # Congruence gate (CR-02): the action must be the one this outcome permits —
    # an actionable room is not a blank cheque. An incongruent action (e.g.
    # verified_empty on an occupied session) is refused, audited, writes nothing.
    if action_val not in _OUTCOME_ACTIONS.get(resolution.outcome, set()):
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

    # Idempotency: same checker + room/session + action + minute applies once.
    # Atomic cache.add (WR-01) closes the TOCTOU double-apply/double-notify race a
    # non-atomic get-then-set left open (two overlapping requests both reading the
    # cache before either writes). Only the request that wins the add() applies.
    scope_pk = session.pk if session else room.pk
    idem = _idem_key(request.user.pk, scope_pk, action_val, now)
    if cache.add(idem, True, timeout=120):
        try:
            _apply_action(request, session, room, action_val, note=note,
                          identity_match=identity_match, scanned_at=now)
        except Exception:
            cache.delete(idem)
            raise

    return render(request, "checker/_outcome.html", {
        "resolution": resolution, "room": room, "session": session,
        "applied": True, "applied_action": action_val,
        "undo_cv": _undo_target(request.user, session, room, action_val, now)})


# --- offline replay (CHK-08) ------------------------------------------------
def _claim_replay_receipt(user, client_uuid, status, reason=""):
    """Durably claim one terminal replay result inside the caller's transaction."""
    try:
        # Nested atomic gives a savepoint: a concurrent unique-key loser can be
        # handled as a duplicate without breaking the caller's outer transaction.
        with transaction.atomic():
            CheckerReplayReceipt.objects.create(
                client_uuid=client_uuid,
                checker=user,
                status=status,
                reason=reason,
            )
    except IntegrityError:
        return False
    return True


@checker_required
@require_http_methods(["POST"])
@serialized_write
def replay(request):
    """Re-validate every offline-queued scan against CURRENT state through the
    SAME pure gating core `action` uses above — the offline snapshot's
    room/session/on-duty decision is NEVER trusted (T-03-19/20). A batch POST
    `{"items": [{client_uuid, token, session_id, action, note, scanned_at}, ...]}` from the
    client's IndexedDB queue. Per item: re-derive the checker's CURRENT
    on-duty floors and the room's CURRENT session state server-side and
    re-run `R.resolve_checker_scan`; a still-actionable item applies
    (offline_queued=True, the ORIGINAL scanned_at preserved); anything else
    (off-duty/wrong-floor/absent/already-verified/bad-payload/empty-note flag)
    is recorded via AuditLog(checker.replay_conflict) and flags IFO via
    notify(), never applied. A unique durable CheckerReplayReceipt is committed
    in the same transaction as each terminal result, so a cache flush, process
    restart, or second worker can never reapply the same ``client_uuid``.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"results": []}, status=400)

    if not isinstance(payload, dict) or not isinstance(payload.get("items", []), list):
        return JsonResponse({"results": []}, status=400)
    items = payload.get("items", [])
    if len(items) > 500 or any(not isinstance(item, dict) for item in items):
        return JsonResponse({"results": []}, status=400)
    now = timezone.now()
    results = []

    for item in items:
        # Ownership precedes UUID/receipt lookup, rate limits and all writes.
        # Legacy unowned records remain quarantined in the browser.
        if str(item.get("owner_id", "")) != str(request.user.pk):
            results.append({"uuid": str(item.get("client_uuid") or ""),
                            "status": "rejected", "reason": "owner-mismatch"})
            continue
        client_uuid_raw = str(item.get("client_uuid") or "")
        # Reject items with a missing/empty client_uuid outright (WR-03): without
        # it the per-uuid idempotency guard cannot key the item, so a re-post
        # would re-apply the same queued scan with the double-apply protection
        # bypassed. Flagged, never applied (the shipped client always sends one).
        try:
            client_uuid = UUID(client_uuid_raw)
        except (ValueError, AttributeError):
            results.append({"uuid": "", "status": "flagged", "reason": "bad-payload"})
            continue
        client_uuid_text = str(client_uuid)
        if CheckerReplayReceipt.objects.filter(client_uuid=client_uuid).exists():
            results.append({"uuid": client_uuid_text, "status": "duplicate"})
            continue

        # Rate-limit manual-code (6-digit) lookups per checker per minute (WR-02)
        # BEFORE the room lookup — a QR token is exempt (opaque). Over the cap the
        # item is flagged (not applied), never used to probe another floor's code.
        token_raw = str(item.get("token") or "").strip()
        if re.fullmatch(r"\d{6}", token_raw) and \
                not _replay_manual_code_allowed(request.user, now):
            with transaction.atomic():
                claimed = _claim_replay_receipt(
                    request.user, client_uuid, "flagged", "rate-limited")
                if claimed:
                    AuditLog.objects.create(
                        actor=request.user, event_type="checker.rate_limited",
                        target_type="session", target_id="",
                        payload={"uuid": client_uuid_text, "context": "replay"})
            results.append({
                "uuid": client_uuid_text,
                "status": "flagged" if claimed else "duplicate",
                **({"reason": "rate-limited"} if claimed else {}),
            })
            continue

        room = _room_from_replay_token(token_raw)
        action_val = item.get("action", "")
        note = item.get("note", "") or ""
        scanned_at = parse_datetime(item.get("scanned_at") or "") or now
        claimed_session_id = item.get("session_id")
        claimed_session_valid = (claimed_session_id in (None, "")
                                 or is_id(claimed_session_id))

        if room is None:
            reason = "bad-room"
            session = None
        elif room.out_of_service:
            reason = "out-of-service"
            session = None
        else:
            # ALWAYS re-derive CURRENT state server-side — never the offline
            # snapshot (the CHK-08 "never blindly trusted" rule).
            session, state = _room_session_state(room, now)
            resolution = R.resolve_checker_scan(
                _active_floor_ids(request.user, now), room.floor_id, state, now)
            if not claimed_session_valid:
                reason = "bad-payload"
            else:
                historical = None
                if claimed_session_id in (None, ""):
                    historical = _room_session_at_scan(room, scanned_at)
                expected_session_id = (
                    int(claimed_session_id)
                    if claimed_session_id not in (None, "")
                    else (historical.pk if historical is not None else None)
                )
                current_session_id = session.pk if session is not None else None
                reason = ("session-changed"
                          if expected_session_id != current_session_id else None)

            if reason is not None:
                pass
            elif not resolution.actionable:
                reason = resolution.outcome
            elif action_val not in _VALID_ACTIONS:
                reason = "bad-payload"
            elif action_val not in _OUTCOME_ACTIONS.get(resolution.outcome, set()):
                # CR-02: an item whose action does not match the current outcome
                # is flagged for IFO review, never applied.
                reason = "action-incongruent"
            elif action_val in _FLAG_ACTIONS and not note.strip():
                # Reuse the FLAG note-required rule (Pitfall 4): a flag item
                # with an empty note is rejected/flagged, never silently applied.
                reason = "note-required"
            else:
                reason = None

        if reason is None:
            identity_match = None
            if action_val == ValidationAction.FLAG_IDENTITY_MISMATCH:
                identity_match = False
            elif action_val == ValidationAction.VERIFIED:
                identity_match = True
            with transaction.atomic():
                claimed = _claim_replay_receipt(
                    request.user, client_uuid, "applied")
                if claimed:
                    _apply_action(
                        request, session, room, action_val, note=note,
                        identity_match=identity_match, scanned_at=scanned_at,
                        offline=True)
            results.append({"uuid": client_uuid_text,
                            "status": "applied" if claimed else "duplicate"})
        else:
            with transaction.atomic():
                claimed = _claim_replay_receipt(
                    request.user, client_uuid, "flagged", reason)
                if claimed:
                    AuditLog.objects.create(
                        actor=request.user, event_type="checker.replay_conflict",
                        target_type="session",
                        target_id=str(session.pk if session else ""),
                        payload={"outcome": reason, "uuid": client_uuid_text,
                                 "action": action_val})
                    room_label = room.code if room else "an unknown room"
                    notify(role=Role.IFO_ADMIN, type="checker_replay_conflict",
                           title="Offline scan needs review",
                           body=(f"A queued checker scan for {room_label} no longer "
                                 f"applies ({reason}); please resolve."))
            results.append({
                "uuid": client_uuid_text,
                "status": "flagged" if claimed else "duplicate",
                **({"reason": reason} if claimed else {}),
            })

    return JsonResponse({"results": results})


# --- online verification (CHK-02/03) ---------------------------------------
_ONLINE_ACTIONS = {ValidationAction.VERIFIED, ValidationAction.FLAG_NOT_PRESENT}


@serialized_write
def _online_action(request, session_id, action_val, note, now):
    """Apply an online Verify / Flag-not-present after a server-side re-gate.

    The online analog of the floor re-gate (T-03-16): ownership, active
    online-duty, and session-actionability are ALL re-derived server-side from
    the POST `session_id` — never trusted from the client. A forged, stale, or
    foreign online action is refused here and writes NOTHING. Only Verify and
    Flag-not-present are meaningful online actions.
    """
    session = _online_session(session_id, request.user)
    on_duty = _is_online_on_duty(request.user, now)
    actionable = (session is not None
                  and session.status in (SessionStatus.SCHEDULED, SessionStatus.ACTIVE)
                  and session.date == timezone.localdate(now)
                  and session.scheduled_start <= now <= session.scheduled_end
                  and not session.verified_by_checker)

    if session is None or not on_duty or not actionable:
        # Refuse: not owned / not on duty / already resolved. Audit + no write.
        outcome = "absent-excluded" if (session is not None and not actionable) \
            else "off-duty"
        if session is not None:
            AuditLog.objects.create(
                actor=request.user, event_type="checker.action_refused",
                target_type="session", target_id=str(session.pk),
                payload={"outcome": outcome, "action": action_val, "online": True})
        return render(request, "checker/_outcome.html", {
            "resolution": _OnlineRefusal(outcome), "session": session})

    if action_val not in _ONLINE_ACTIONS:
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})

    # Flags require a note (server is the gate) — reject empty with a 200 error
    # partial, never a 500 (mirrors the F2F path).
    if action_val == ValidationAction.FLAG_NOT_PRESENT and not note.strip():
        return render(request, "checker/_outcome.html", {
            "error": "note-required", "session": session})

    identity_match = True if action_val == ValidationAction.VERIFIED else None
    # Idempotency: same checker + session + action + minute applies once. Atomic
    # cache.add (WR-01) closes the double-apply/double-notify TOCTOU race.
    idem = _idem_key(request.user.pk, session.pk, action_val, now)
    if cache.add(idem, True, timeout=120):
        # room=session.room: online sessions still carry their scheduled room, so
        # the NOT-NULL CheckerValidation.room is satisfied without a schema change.
        try:
            _apply_action(request, session, session.room, action_val, note=note,
                          identity_match=identity_match, scanned_at=now, online=True)
        except Exception:
            cache.delete(idem)
            raise

    return render(request, "checker/_outcome.html", {
        "session": session, "room": session.room,
        "applied": True, "applied_action": action_val,
        "undo_cv": _undo_target(request.user, session, session.room, action_val, now)})


@checker_required
def online_list(request):
    """CHK-02 online-to-verify list: today's owned online sessions not yet
    verified. A verified online session becomes ACTIVE and drops off the list;
    Absent/Completed are excluded too (only SCHEDULED effective-online remain)."""
    active_term = get_active_term()
    if active_term is None:
        sessions = []
        return render(request, "checker/online_list.html", {"sessions": sessions})
    sessions = [
        s for s in (Session.objects
                    .filter(online_checker=request.user, date=timezone.localdate(),
                            status__in=[SessionStatus.SCHEDULED, SessionStatus.ACTIVE],
                            schedule__term=active_term)
                    .select_related("schedule", "faculty", "room")
                    .order_by("scheduled_start"))
        if (s.declared_modality or s.schedule.modality) == Modality.ONLINE
        and not s.verified_by_checker]
    pg = paginate(request, sessions)            # 15 rows per page (D10)
    return render(request, "checker/online_list.html",
                  {**pg, "sessions": pg["page"].object_list})


@checker_required
@require_http_methods(["GET"])
def online_open(request, session_id):
    """CHK-02 open one owned online session -> its public Teams link + the
    Verify / Flag-not-present controls (no room-state card). A non-owner gets a
    404. An empty teams_link renders the "No Teams link" state and flags IFO so
    they can add one (rather than a dead redirect)."""
    session = _online_session(session_id, request.user)
    if session is None:
        raise Http404("No online session for this checker.")
    if not session.teams_link:
        # A blank link is normal until the instructor starts the class, and only
        # the instructor can set it, so IFO hears about it only past grace. This
        # is a page view, so it can repeat freely: tell IFO once per class meeting,
        # however often the page is opened and by whichever Checker.
        late = is_no_show_past_grace(session.scheduled_start, timezone.now(),
                                     get_policy("grace_minutes"))
        if late and session.status != SessionStatus.CANCELLED:
            body = (f"{session.schedule.course_code}-{session.schedule.section} on "
                    f"{session.date} is past its grace period with no Teams meeting "
                    f"link. Only the instructor can set it, so please contact them.")
            if not Notification.objects.filter(type="online_no_link",
                                               body=body).exists():
                notify(role=Role.IFO_ADMIN, type="online_no_link",
                       title="Online session missing its Teams link", body=body)
        return render(request, "checker/online_open.html",
                      {"session": session, "no_link": True})
    return render(request, "checker/online_open.html", {"session": session})


# --- floor board (CHK-07) --------------------------------------------------
# Server-computed status token per room card. Color is NEVER the only signal
# (WCAG 1.4.1): each state also carries a Lucide icon + a text label. The exact
# palette is the approved 03-UI-SPEC functional-state table, expressed in the
# navy floor-family vocabulary: `card` = the .ft-card--* accent modifier, `pill`
# = the .ft-pill--* status chip (see static/faculty/faculty.css).
_CARD_STYLES = {
    "idle": {"card": "ft-card--neutral", "pill": "ft-pill ft-pill--upcoming",
             "icon": "circle", "label": "Not started"},
    # "Class ended", not "Done": this class was never checked, and a Checker
    # must not read the card as already covered.
    "finished": {"card": "ft-card--neutral", "pill": "ft-pill ft-pill--done",
                 "icon": "log-out", "label": "Class ended"},
    "active-unverified": {"card": "ft-card--warn", "pill": "ft-pill ft-pill--late",
                          "icon": "clock", "label": "Needs check"},
    "verified": {"card": "ft-card--ok", "pill": "ft-pill ft-pill--active",
                 "icon": "check-check", "label": "Verified"},
    "flagged": {"card": "ft-card--bad", "pill": "ft-pill ft-pill--absent",
                "icon": "flag", "label": "Flagged"},
    "verified-empty": {"card": "ft-card--info", "pill": "ft-pill ft-pill--online",
                       "icon": "door-closed", "label": "Empty (checked)"},
}


def _card_state(actions, status):
    """Map a session's validation actions + status to a display state token.

    Flagged wins over verified for the card's face (a flagged room needs the
    eye even if a prior verify exists); coverage counting is independent (any
    'verified' validation counts, matching Session.verified_by_checker).
    """
    if any(a.startswith("flag") for a in actions):
        return "flagged"
    if ValidationAction.VERIFIED in actions:
        return "verified"
    if ValidationAction.VERIFIED_EMPTY in actions:
        return "verified-empty"
    if status == SessionStatus.ACTIVE:
        return "active-unverified"
    if status == SessionStatus.COMPLETED:
        return "finished"
    return "idle"                                    # scheduled / not yet started


@checker_required
def floor_board(request):
    """CHK-07 board shell — mirrors ifo.live. The poll interval is policy-driven
    (settings.FLUXTRACK_POLICY[poll_interval_seconds]); NEVER hardcoded."""
    state = request.GET.get("state") or ""
    return render(request, "checker/floor.html", {
        "poll_ms": settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000,
        "state_choices": [(k, v["label"]) for k, v in _CARD_STYLES.items()],
        "state": state if state in _CARD_STYLES else ""})


@checker_required
def floor_rows(request):
    """CHK-07 polled partial. ONE shared queryset (exclude ABSENT, scoped to the
    checker's active floors) feeds the cards, the oldest-first priority queue,
    AND the coverage denominator (Pitfall 5) so the numbers can never disagree.
    """
    now = timezone.now()
    active_term = get_active_term()
    floor_ids = _active_floor_ids(request.user, now)
    active = []
    if active_term is not None:
        active = list(Session.objects
                      .filter(room__floor_id__in=floor_ids, date=timezone.localdate(),
                              schedule__term=active_term)
                      .exclude(status__in=[SessionStatus.ABSENT,
                                           SessionStatus.CANCELLED])
                      .select_related("room", "room__floor", "schedule", "faculty")
                      .prefetch_related("validations")
                      .order_by("scheduled_start"))
    # F2F/Blended board only: drop effective-online sessions (declared overrides
    # schedule), matching _room_session_state's online short-circuit.
    board = [s for s in active
             if (s.declared_modality or s.schedule.modality) != Modality.ONLINE]

    cards, queue = [], []
    verified = 0
    for s in board:
        actions = {v.action for v in s.validations.all()}
        is_verified = ValidationAction.VERIFIED in actions
        verified += 1 if is_verified else 0
        state = _card_state(actions, s.status)
        cards.append({"session": s, "state": state, "style": _CARD_STYLES[state]})
        if s.status == SessionStatus.ACTIVE and not is_verified:
            queue.append(s)                          # already oldest-first ordered

    total = len(board)
    coverage = round(100 * verified / total) if total else 100
    # The room table can be narrowed by state (the filter lives in the board
    # shell and rides along in the poll URL). Coverage and the priority queue
    # still count the whole floor, so a filter never changes the numbers.
    state = request.GET.get("state") or ""
    if state in _CARD_STYLES:
        cards = [c for c in cards if c["state"] == state]
    # Shared 50-row pager (D10) on the room table.
    pg = paginate(request, cards)
    return render(request, "checker/_floor_rows.html", {
        **pg, "cards": pg["page"].object_list, "queue": queue, "coverage": coverage,
        "verified": verified, "total": total, "now": timezone.localtime(now)})

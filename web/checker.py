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
from functools import wraps
from urllib.parse import parse_qs, urlparse

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from campus.models import Room
from ops.models import AuditLog
from ops.notify import notify
from ops.policy import get_policy
from scheduling.merge import (propagate_merged_absent,
                              propagate_merged_present)
from scheduling.models import CheckinMethod, Modality, Session, SessionStatus
from scheduling.term_scope import get_active_term
from verification import resolver as R
from verification.models import (Assignment, AssignmentScope, CheckerValidation,
                                 DutyRole, ValidationAction)

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
    if not str(session_id or "").isdigit():
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
    target in this plan (online verify is 03-05), so it reads as an empty room.
    Completed sessions are ignored (the room is free again).

    Selection is `now`-aware (CR-01): prefer the room's ACTIVE session, else the
    session whose scheduled window contains `now`, else the room reads empty. A
    stale earlier-in-the-day ABSENT session (ABSENT is never COMPLETED) must NOT
    latch and block verifying a later session in the same room.
    """
    active_term = get_active_term()
    if active_term is None:
        return None, None
    sessions = list(Session.objects
                    .filter(room=room, date=timezone.localdate(),
                            schedule__term=active_term)
                    .exclude(status=SessionStatus.COMPLETED)
                    .select_related("schedule", "faculty")
                    .order_by("scheduled_start"))
    session = next((s for s in sessions if s.status == SessionStatus.ACTIVE), None)
    if session is None:
        session = next((s for s in sessions
                        if s.scheduled_start <= now <= s.scheduled_end), None)
    if session is None:
        return None, None
    effective = session.declared_modality or session.schedule.modality
    if effective == Modality.ONLINE:
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
                session.actual_start = scanned_at or timezone.now()
                session.checkin_method = CheckinMethod.ONLINE_MANUAL
                session.save(update_fields=["status", "actual_start", "checkin_method"])
                propagate_merged_present(session, session.actual_start,
                                         actor=request.user)
        elif action == ValidationAction.FLAG_NOT_PRESENT:
            # Online not-present fails the online merged group ABSENT (D-07
            # online), in ONE transaction. The helper's SCHEDULED status-guard
            # leaves an already-ACTIVE sibling untouched, and its grace gate
            # (audit H2) defers within-grace siblings to the sweep -- only the
            # anchor is the checker's immediate, authoritative call.
            with transaction.atomic():
                session.status = SessionStatus.ABSENT  # authoritative (Open Q2)
                session.save(update_fields=["status"])
                propagate_merged_absent(session, actor=request.user)

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
    # `.isdigit()` guard so it degrades to the bad-payload partial (200).
    if not str(room_id or "").isdigit():
        return render(request, "checker/_outcome.html", {"error": "bad-payload"})
    room = (Room.objects.filter(pk=room_id)
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
    idem = f"checker-idem:{request.user.pk}:{scope_pk}:{action_val}:{now:%Y%m%d%H%M}"
    if cache.add(idem, True, timeout=120):
        _apply_action(request, session, room, action_val, note=note,
                      identity_match=identity_match, scanned_at=now)

    return render(request, "checker/_outcome.html", {
        "resolution": resolution, "room": room, "session": session,
        "applied": True, "applied_action": action_val})


# --- offline replay (CHK-08) ------------------------------------------------
@checker_required
@require_http_methods(["POST"])
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
    notify(), never applied. Idempotent per `client_uuid` via the Django cache
    (mirrors web/scan.py's scan-idem idiom, T-03-21) so a double-replay never
    double-applies.
    """
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"results": []}, status=400)

    items = list(payload.get("items") or [])   # materialize up front (Pitfall 3, MSSQL HY010)
    now = timezone.now()
    results = []

    for item in items:
        client_uuid = str(item.get("client_uuid") or "")
        # Reject items with a missing/empty client_uuid outright (WR-03): without
        # it the per-uuid idempotency guard cannot key the item, so a re-post
        # would re-apply the same queued scan with the double-apply protection
        # bypassed. Flagged, never applied (the shipped client always sends one).
        if not client_uuid:
            results.append({"uuid": "", "status": "flagged", "reason": "bad-payload"})
            continue
        idem_key = f"checker-replay:{client_uuid}"
        if cache.get(idem_key):
            results.append({"uuid": client_uuid, "status": "duplicate"})
            continue

        # Rate-limit manual-code (6-digit) lookups per checker per minute (WR-02)
        # BEFORE the room lookup — a QR token is exempt (opaque). Over the cap the
        # item is flagged (not applied), never used to probe another floor's code.
        token_raw = str(item.get("token") or "").strip()
        if re.fullmatch(r"\d{6}", token_raw) and \
                not _replay_manual_code_allowed(request.user, now):
            AuditLog.objects.create(
                actor=request.user, event_type="checker.rate_limited",
                target_type="session", target_id="",
                payload={"uuid": client_uuid, "context": "replay"})
            results.append({"uuid": client_uuid, "status": "flagged",
                            "reason": "rate-limited"})
            continue

        room = _room_from_replay_token(token_raw)
        action_val = item.get("action", "")
        note = item.get("note", "") or ""
        scanned_at = parse_datetime(item.get("scanned_at") or "") or now
        claimed_session_id = item.get("session_id")
        claimed_session_valid = claimed_session_id in (None, "") or str(
            claimed_session_id).isdigit()

        if room is None:
            reason = "bad-room"
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
            # Atomically claim this uuid BEFORE applying (WR-01): a concurrent
            # replay of the same item loses the add() race and is reported a
            # duplicate, closing the TOCTOU double-apply/double-notify window the
            # separate get/set left open.
            if not cache.add(idem_key, True, timeout=None):
                results.append({"uuid": client_uuid, "status": "duplicate"})
                continue
            _apply_action(request, session, room, action_val, note=note,
                          identity_match=identity_match, scanned_at=scanned_at,
                          offline=True)
            results.append({"uuid": client_uuid, "status": "applied"})
        else:
            AuditLog.objects.create(
                actor=request.user, event_type="checker.replay_conflict",
                target_type="session", target_id=str(session.pk if session else ""),
                payload={"outcome": reason, "uuid": client_uuid, "action": action_val})
            room_label = room.code if room else "an unknown room"
            notify(role=Role.IFO_ADMIN, type="checker_replay_conflict",
                   title="Offline scan needs review",
                   body=f"A queued checker scan for {room_label} no longer applies "
                        f"({reason}); please resolve.")
            results.append({"uuid": client_uuid, "status": "flagged", "reason": reason})

    return JsonResponse({"results": results})


# --- online verification (CHK-02/03) ---------------------------------------
_ONLINE_ACTIONS = {ValidationAction.VERIFIED, ValidationAction.FLAG_NOT_PRESENT}


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
    actionable = session is not None and session.status not in (
        SessionStatus.ABSENT, SessionStatus.COMPLETED)

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
    idem = f"checker-idem:{request.user.pk}:{session.pk}:{action_val}:{now:%Y%m%d%H%M}"
    if cache.add(idem, True, timeout=120):
        # room=session.room: online sessions still carry their scheduled room, so
        # the NOT-NULL CheckerValidation.room is satisfied without a schema change.
        _apply_action(request, session, session.room, action_val, note=note,
                      identity_match=identity_match, scanned_at=now, online=True)

    return render(request, "checker/_outcome.html", {
        "session": session, "room": session.room,
        "applied": True, "applied_action": action_val})


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
                            status=SessionStatus.SCHEDULED,
                            schedule__term=active_term)
                    .select_related("schedule", "faculty", "room")
                    .order_by("scheduled_start"))
        if (s.declared_modality or s.schedule.modality) == Modality.ONLINE]
    return render(request, "checker/online_list.html", {"sessions": sessions})


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
        notify(role=Role.IFO_ADMIN, type="online_no_link",
               title="Online session missing its Teams link",
               body=f"{session.schedule.course_code}-{session.schedule.section} "
                    f"has no Teams meeting link. Please add one so the assigned "
                    f"checker can verify attendance.")
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
             "icon": "circle", "label": "No session"},
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
    return "idle"                                    # scheduled / not yet started


@checker_required
def floor_board(request):
    """CHK-07 board shell — mirrors ifo.live. The poll interval is policy-driven
    (settings.FLUXTRACK_POLICY[poll_interval_seconds]); NEVER hardcoded."""
    return render(request, "checker/floor.html",
                  {"poll_ms": settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000})


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
                      .exclude(status=SessionStatus.ABSENT)
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
    return render(request, "checker/_floor_rows.html", {
        "cards": cards, "queue": queue, "coverage": coverage,
        "verified": verified, "total": total, "now": timezone.localtime(now)})

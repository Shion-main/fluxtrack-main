---
phase: 03-duty-assignments-checker-verification
reviewed: 2026-07-03T02:53:42Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - scheduling/jobs.py
  - scheduling/management/commands/assign_online.py
  - scheduling/models.py
  - static/checker/offline_queue.js
  - templates/checker/_floor_rows.html
  - templates/checker/_online_list.html
  - templates/checker/_outcome.html
  - templates/checker/floor.html
  - templates/checker/online_list.html
  - templates/checker/online_open.html
  - templates/checker/scan.html
  - templates/ifo/_assignment_form.html
  - templates/ifo/assignments.html
  - verification/models.py
  - verification/resolver.py
  - verification/services.py
  - web/checker.py
  - web/ifo.py
  - web/urls.py
  - web/views.py
findings:
  critical: 5
  warning: 3
  info: 3
  total: 11
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-07-03T02:53:42Z
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Reviewed the checker gating core (`verification/resolver.py`), its web-layer callers (`web/checker.py`), the JOB-02 sweep change (`scheduling/jobs.py`), the offline replay endpoint, the online verify path, and the IFO assignment views/templates.

The pure `resolve_checker_scan` core itself is clean and correctly used for room/floor-level re-gating (unconditional server-side re-derivation of `active_floor_ids` and `session_state` on every `action`/`replay` call — no bypass at that layer). `sweep_no_shows` correctly reuses the single shared `is_no_show_past_grace` predicate and sweeps only `SCHEDULED` sessions, matching the JOB-02 coupling guarantee.

However, five BLOCKER-level correctness/robustness gaps were found below that layer:
1. The room-scan session lookup (`_room_session_state`) can permanently latch onto a stale earlier-in-the-day `ABSENT` session and block verification of a later session in the same room.
2. Neither `action()` nor `replay()` validates that the submitted `action_val` is congruent with the resolved `outcome` — a forged POST can apply `verified_empty` to an occupied session, or `verified` to an empty room, bypassing the intent (though not the floor/room identity) of the re-gate.
3. `action()`'s F2F room lookup is not guarded against non-numeric `room_id`, unlike the online path's equivalent (`_online_session`), causing an unhandled 500 on a trivial malformed POST.
4. `ifo.assignment_create` writes unvalidated `date`/`start_time`/`end_time`/`floors` POST values directly into the ORM, which can raise an unhandled `ValidationError`/`ValueError` (500) instead of the documented "never a 500" friendly 400 response.
5. The online round-robin pre-assignment (`verification/services._online_duty_checker_ids`) ignores the shift `start_time`/`end_time` window that the real-time on-duty gate (`web/checker._is_online_on_duty`) enforces, so a shift-scoped online-duty Checker can be pre-assigned sessions outside their shift window that they can never actually verify — those sessions then fall through to the sweep and get marked `ABSENT` despite genuine attendance.

No SQL injection, XSS (no `|safe`/`mark_safe` usage found), hardcoded secrets, or IDOR was found in the reviewed files — ownership checks (`_online_session`, `online_open`) and role gating (`checker_required`, `ifo_required`) are correctly applied.

## Critical Issues

### CR-01: Room-scan session lookup can latch onto a stale ABSENT session and block a later session in the same room

**File:** `web/checker.py:207-227` (`_room_session_state`), consumed by `resolve()` (285-296), `action()` (326-328), and `replay()` (409-411)

**Issue:** `_room_session_state` selects a single session per room per day via:
```python
session = (Session.objects
           .filter(room=room, date=timezone.localdate())
           .exclude(status=SessionStatus.COMPLETED)
           .select_related("schedule", "faculty")
           .order_by("scheduled_start")
           .first())
```
This ignores `now` entirely and always returns the earliest non-`COMPLETED` session for the room that day. `ABSENT` is not `COMPLETED` (per `scheduling/jobs.py::sweep_no_shows`, an absent session stays `ABSENT` — it is never transitioned to `COMPLETED`). Rooms routinely host multiple different `Schedule`s across different time slots in the same day (normal timetabling). If an earlier same-day session in that room was marked `ABSENT` (by the sweep or otherwise), that stale session — not the room's current occupant — will be returned forever for the rest of the day, because it sorts first by `scheduled_start`.

Concretely: Room 101 has an 8–9am class (now `ABSENT`, unattended) and a 9–10am class (currently `ACTIVE`, genuinely occupied). A checker scanning Room 101 at 9:15am gets `session = <8-9am ABSENT session>` → `resolve_checker_scan` returns `ABSENT_EXCLUDED` → the checker sees "Session is Absent — can't be verified" and can never verify the class that is actually in progress. This directly undermines CHK-01/07 coverage for any room with back-to-back sessions.

No test in `verification/tests.py` exercises a room with more than one session per day, so this is untested and unnoticed.

**Fix:** Prefer an `ACTIVE` session, else the session whose scheduled window contains `now`, else fall back to `None` (empty) rather than an arbitrary earliest non-completed row:
```python
def _room_session_state(room, now):
    sessions = list(Session.objects
                     .filter(room=room, date=timezone.localdate())
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
    return session, _SessionState(session.pk, session.status, session.verified_by_checker)
```

---

### CR-02: `action_val` is never validated against the resolved `outcome` — action-type gating can be bypassed

**File:** `web/checker.py:330-361` (`action`), `web/checker.py:409-421` (`replay`)

**Issue:** Both `action()` and `replay()` re-derive `resolution` via the pure core and check only `resolution.actionable` (True for both `NO_SESSION` and `ACTIVE_UNVERIFIED`). Neither checks that the submitted `action_val` is the one that actually applies to the resolved outcome:
```python
if not resolution.actionable:
    ... refuse
if action_val in _FLAG_ACTIONS and not note.strip():
    ... error
...
_apply_action(request, session, room, action_val, ...)
```
`_VALID_ACTIONS` contains `verified`, `flag_identity_mismatch`, `flag_not_present`, and `verified_empty` — any of these is accepted as long as the room/floor state is *some* actionable outcome, regardless of which one. The UI only ever renders the form matching the actual outcome, but the server does not enforce it. A forged/hand-crafted POST from an authenticated (but malicious) Checker can:
- Send `action=verified_empty&room_id=<room with an actually-occupied ACTIVE_UNVERIFIED session>` → `_apply_action` writes `CheckerValidation(session=<real occupied session>, action="verified_empty")`, falsely recording an occupied class as verified-empty — the exact kind of attendance-record falsification CHK-01 is meant to prevent.
- Send `action=verified&room_id=<truly empty room>` (`NO_SESSION`, `session=None`) → creates a `CheckerValidation(session=None, action="verified", identity_match=True)`, a nonsensical/garbage record with an empty `target_id` in its `AuditLog`.

This is untested (no test in `verification/tests.py` submits a mismatched action/outcome pair).

**Fix:** Map each actionable outcome to its permitted action set and refuse anything else, mirroring the note-required refusal pattern already in place:
```python
_OUTCOME_ACTIONS = {
    R.NO_SESSION: {ValidationAction.VERIFIED_EMPTY},
    R.ACTIVE_UNVERIFIED: {ValidationAction.VERIFIED,
                           ValidationAction.FLAG_IDENTITY_MISMATCH,
                           ValidationAction.FLAG_NOT_PRESENT},
}
if action_val not in _OUTCOME_ACTIONS.get(resolution.outcome, set()):
    AuditLog.objects.create(actor=request.user, event_type="checker.action_refused",
                             target_type="room", target_id=str(room.pk),
                             payload={"outcome": resolution.outcome, "action": action_val})
    return render(request, "checker/_outcome.html", {
        "resolution": resolution, "room": room, "session": session})
```
Apply the same congruence check inside `replay()`'s `reason` computation.

---

### CR-03: `action()`'s room lookup crashes (500) on a non-numeric `room_id` instead of degrading gracefully

**File:** `web/checker.py:316-321`

**Issue:**
```python
room = (Room.objects.filter(pk=room_id)
        .select_related("floor").first())
if room is None:
    return render(request, "checker/_outcome.html", {"error": "bad-payload"})
```
`room_id = request.POST.get("room_id")` is used directly as a `pk` filter value with no numeric validation. `Room`'s primary key is Django's default `AutoField` (integer). Filtering `pk="abc"` (or any non-numeric string) raises an unhandled `django.core.exceptions.ValidationError` when the queryset is evaluated (`.first()`), producing a 500 — not the "bad-payload" error partial the surrounding comment promises ("A missing/forged room_id degrades to an error partial"). This is trivially triggered by any authenticated Checker sending `POST /checker/action` with `room_id=abc`.

Notably, the online counterpart (`_online_session`, line 121) already guards against exactly this: `if not str(session_id or "").isdigit(): return None`. The F2F path was not given the same treatment.

**Fix:**
```python
room_id = request.POST.get("room_id")
if not str(room_id or "").isdigit():
    return render(request, "checker/_outcome.html", {"error": "bad-payload"})
room = Room.objects.filter(pk=room_id).select_related("floor").first()
```

---

### CR-04: `ifo.assignment_create` writes unvalidated `date`/`start_time`/`end_time`/`floors` POST fields — malformed input crashes with a 500

**File:** `web/ifo.py:141-196`, specifically lines 166-175

**Issue:** The function's docstring states: "Invalid input renders a friendly error partial (status 400), never a 500." Validation is only performed for `user`, `role`, `type_`, and `scope`:
```python
a = Assignment.objects.create(
    user=user, role=role, type=type_, scope=scope,
    date=request.POST.get("date") or None,
    start_time=request.POST.get("start_time") or None,
    end_time=request.POST.get("end_time") or None,
    term=term, status="active")
if scope == AssignmentScope.FLOOR:
    a.floors.set(Floor.objects.filter(pk__in=floor_ids))
```
`date`, `start_time`, `end_time` are passed straight from `request.POST.get(...)` with no format check. `DateField`/`TimeField.to_python()` raises an unhandled `django.core.exceptions.ValidationError` for a malformed value (e.g. `date=not-a-date`) during `.create()`'s `INSERT`, which is not caught anywhere in this view — the request 500s. Similarly, `floor_ids = request.POST.getlist("floors")` is passed unvalidated into `pk__in=floor_ids`; a non-numeric floor id (e.g. `floors=abc`) raises an unhandled `ValidationError`/`ValueError` when the M2M `.set()` query is evaluated. Both are trivially reachable by any authenticated IFO admin (or a stolen/forged session) sending a malformed POST, and both violate the stated "never a 500" contract.

**Fix:** Validate format before constructing the object, alongside the existing field-presence checks:
```python
from django.utils.dateparse import parse_date, parse_time
...
date_raw = request.POST.get("date") or ""
start_raw = request.POST.get("start_time") or ""
end_raw = request.POST.get("end_time") or ""
if date_raw and parse_date(date_raw) is None:
    error = "Enter a valid date."
elif start_raw and parse_time(start_raw) is None:
    error = "Enter a valid start time."
elif end_raw and parse_time(end_raw) is None:
    error = "Enter a valid end time."
elif floor_ids and not all(f.isdigit() for f in floor_ids):
    error = "Invalid floor selection."
```
and only proceed to `Assignment.objects.create(...)` / `a.floors.set(...)` once `error` is still `None`.

---

### CR-05: Online round-robin pre-assignment ignores shift time window — sessions can be assigned to a Checker who can never verify them, causing false "Absent" markings

**File:** `verification/services.py:50-63` (`_online_duty_checker_ids`) vs. `web/checker.py:88-109` (`_is_online_on_duty`)

**Issue:** `_online_duty_checker_ids` (used by `assign_online_sessions` to pick the round-robin pool) considers an `ONLINE`-scope `Assignment` eligible purely by date:
```python
return list(
    Assignment.objects
    .filter(role=DutyRole.CHECKER, scope=AssignmentScope.ONLINE, status="active")
    .filter(Q(date__isnull=True) | Q(date=target_date))
    .order_by("user_id")
    .values_list("user_id", flat=True)
    .distinct())
```
It never checks `start_time`/`end_time`. But the real-time gate that actually lets a Checker act on an owned online session, `_is_online_on_duty`, DOES enforce the shift window:
```python
if a.date == today:
    start_ok = a.start_time is None or a.start_time <= now_t
    end_ok = a.end_time is None or now_t <= a.end_time
    if start_ok and end_ok:
        return True
```
Consequence: an IFO admin can create a `SHIFT`-type `ONLINE` assignment for a Checker covering only e.g. 08:00–10:00. When online sessions for that date are round-robin distributed, this Checker is treated as an eligible owner for ALL of that date's unowned online sessions — including a 15:00 session outside their shift. `Session.online_checker` gets set to that Checker, but `_online_action`/`_is_online_on_duty` will refuse them at verify time for that session (`off-duty`) for the rest of the day. Since the session already has a non-null owner, `assign_online_sessions`'s "no online-duty Checker" IFO-notify path never fires for it (it only fires when the whole mapping is empty), so nobody is flagged. If the class is genuinely attended but nobody with a covering shift ever verifies it, `scheduling.jobs.sweep_no_shows` — which now includes online sessions per 03-05 — will mark it `ABSENT` past grace despite real attendance. This is a data-integrity bug in the attendance record, not just a UX gap.

**Fix:** Pass `now` (or the target date's representative time) into the eligibility filter and mirror `_is_online_on_duty`'s window check, e.g. compute eligible checker ids in Python after fetching candidate assignments (mirroring `_is_online_on_duty`'s loop), or add the same `Q(start_time__isnull=True) | Q(start_time__lte=...)`-style time filter when a `date` is set. At minimum, exclude `SHIFT`-type assignments with a narrower window than the sessions being distributed, or defer assignment of a given session until a checker whose window actually covers `scheduled_start` is available.

## Warnings

### WR-01: TOCTOU race in the idempotency check-then-set pattern

**File:** `web/checker.py:352-357` (`action`), `web/checker.py:490-496` (`_online_action`), `web/checker.py:391-394` / `432-433` (`replay`, keyed on `client_uuid`)

**Issue:** All three idempotency guards follow the same non-atomic pattern:
```python
if cache.get(idem) != action_val:
    _apply_action(...)
    cache.set(idem, action_val, timeout=120)
```
Two near-simultaneous requests (e.g. a double-tap that fires two overlapping fetches, or a retried request racing the original) can both read the cache before either writes it, so both proceed to `_apply_action`. For `verified` this mostly creates a harmless duplicate row; for the two flag actions it creates a duplicate `CheckerValidation` AND sends duplicate `notify()` calls to IFO and HR for the same event.

**Fix:** Use an atomic add, e.g. `cache.add(idem, action_val, timeout=120)` returning `False` if the key already existed, instead of separate `get`/`set` calls; only proceed to `_apply_action` when `add()` returns `True` (or the existing value differs, requiring a `cache.get_or_set`-style compare-and-swap capable backend).

### WR-02: `/checker/replay`'s manual-code path has no rate limiting, enabling code enumeration across floors

**File:** `web/checker.py:181-195` (`_room_from_replay_token`)

**Issue:** The comment justifies skipping the `/checker/scan`-style rate limit because the replay endpoint is "idempotency-guarded per item" — but that guard is keyed on `client_uuid`, not on the guessed `token`. A single batch POST to `/checker/replay` can include many items, each with a fresh, distinct `client_uuid` and a different six-digit `token` guess, none of which trip the duplicate-detection path. This lets any authenticated Checker (regardless of assigned floor) enumerate valid `manual_code` values for rooms across the entire campus in bulk, with no throttling, unlike the equivalent live-scan path which is explicitly rate-limited per T-03-07.

**Fix:** Rate-limit distinct manual-code lookups per checker per minute inside the `replay()` loop (e.g. reuse the same `cache.get_or_set`/`incr` pattern as `_room_from_payload`, keyed per-checker rather than per-payload) or cap the number of distinct 6-digit-token items processed per replay batch.

### WR-03: Offline replay items missing `client_uuid` get no duplicate-apply protection

**File:** `web/checker.py:392-397`, `429-434`

**Issue:**
```python
client_uuid = str(item.get("client_uuid") or "")
idem_key = f"checker-replay:{client_uuid}"
if client_uuid and cache.get(idem_key):
    results.append({"uuid": client_uuid, "status": "duplicate"})
    continue
...
if client_uuid:
    cache.set(idem_key, True, timeout=None)
```
When `client_uuid` is empty/missing, both the duplicate check and the "mark seen" write are skipped (guarded by `if client_uuid`). The shipped client (`static/checker/offline_queue.js`) always generates a UUID, so this is not reachable through the normal UI — but the server has no independent enforcement that `client_uuid` is present, so any other client (or a replay of the same payload with the uuid stripped) can re-apply the same queued scan repeatedly with full protection bypassed.

**Fix:** Reject items with a missing/empty `client_uuid` outright (`reason = "bad-payload"`) rather than silently letting them skip the idempotency guard.

## Info

### IN-01: Dead `now` parameter in `assign_online_sessions`

**File:** `verification/services.py:74`

**Issue:** `now = now or timezone.now()` is computed but never referenced again in the function body — the parameter is accepted and normalized but has no effect on behavior.

**Fix:** Either use `now` where the current time is actually needed (e.g. for the CR-05 fix above, to filter eligible checkers by shift window) or drop the unused parameter.

### IN-02: `Assignment.status` has no `choices=` constraint

**File:** `verification/models.py:41`

**Issue:** `status = models.CharField(max_length=20, default="active")` accepts any string; every other status-like field in this codebase (`SessionStatus`, `ScheduleStatus`, `ValidationAction`, etc.) uses a `TextChoices` enum for validation and discoverability. This field currently only ever gets the literal `"active"` written to it, but nothing stops a future writer from introducing a typo'd status string that silently fails to match `.filter(status="active")` lookups elsewhere.

**Fix:** Introduce an `AssignmentStatus(models.TextChoices)` (e.g. `ACTIVE`, `REVOKED`) and use it for the field's `choices=`.

### IN-03: Duplicated on-duty date/time-window logic

**File:** `web/checker.py:58-85` (`_active_floor_ids`) and `web/checker.py:88-109` (`_is_online_on_duty`)

**Issue:** Both functions implement the same "standing posting (date NULL) is always on; a dated shift is on only when `start_time <= now <= end_time`" logic independently, with near-identical code. This duplication is exactly the kind of thing that produced the CR-05 gap (a third copy of similar logic, `_online_duty_checker_ids` in `verification/services.py`, diverged by omitting the time-window check).

**Fix:** Extract a shared helper, e.g. `_assignment_covers_now(assignment, today, now_t) -> bool`, and reuse it in `_active_floor_ids`, `_is_online_on_duty`, and (per CR-05) `_online_duty_checker_ids`.

---

_Reviewed: 2026-07-03T02:53:42Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

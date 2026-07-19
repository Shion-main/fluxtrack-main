# Phase 07: Remaining Operational Surfaces - Pattern Map

**Mapped:** 2026-07-18
**Scope:** REMAINING work only. SYS-04, GRD-01, GRD-03 (locator) and FAC-12 notification-prefs are ALREADY SHIPPED and are mapped here only as *analogs*, never as new work.
**Surfaces mapped:** 11
**Analogs found:** 10 / 11 (1 net-new pattern: file upload)

---

## 0. Headline finding — file upload is NET-NEW

**There is NO `request.FILES` handling anywhere in `web/`, and no `enctype="multipart/form-data"` in any template.** Repo-wide grep for `request.FILES|FileField|ImageField|enctype` returns exactly two hits, both model declarations:

- `accounts/models.py:36` — `profile_photo = models.ImageField(upload_to="profile_photos/", null=True, blank=True)`
- `accounts/migrations/0001_initial.py:43` — same field

The field exists; nothing ever writes it. The closest *related* code is read-side file streaming, not upload: `web/ifo.py:544-568` `weekly_download` uses `default_storage.exists()` / `default_storage.open(path,"rb")` — that is the storage API to mirror on the write side (`default_storage.save`), but it is not an upload handler.

**Consequence for the planner:** IFO-03b (schedule upload) and FAC-12 (photo upload) must both establish the multipart pattern from scratch — POST view reading `request.FILES`, a template `<form enctype="multipart/form-data">`, size/type validation, and `default_storage` write. These two should NOT be planned independently; **plan the first one to establish the house pattern and have the second copy it.** Recommend IFO-03b first (it is the harder case: the file must survive between preview and commit).

Also missing repo-wide: no Django `Form`/`ModelForm` usage in `web/` at all. Every existing write view hand-validates `request.POST` fields and re-renders a partial with `error` at status 400 (`web/ifo.py:342-422`). New upload views should follow that same hand-validation idiom rather than introducing forms.py — consistency beats convention here.

---

## 1. File Classification

| New/Modified file or surface | Req | Role | Data flow | Closest analog | Match |
|---|---|---|---|---|---|
| `web/guard.py` per-room schedule view + `templates/guard/room.html` | GRD-02 | role-view | request-response (read) | `web/ifo.py:190` `room_panel` + `web/ifo.py:219` `_room_timetable` | exact |
| `scheduling/jobs.py` guard fan-out (modify) | GRD-04 | job/notify | event-driven, batch | `scheduling/jobs.py:77` `detect_room_conflicts` → `notify()` at `:113` | exact |
| `web/guard.py` decorators (modify, 3 views) | GRD-05 | role-view | n/a | `web/hr.py:178`, `web/ifo.py:477` `@require_http_methods(["GET"])` | exact |
| `web/ifo.py` room create/edit/delete + templates | IFO-01b | role-view | CRUD | `web/ifo.py:342` `assignment_create` | role-match |
| `web/ifo.py` code/QR rotation + confirm template | IFO-02 | role-view | request-response (write) | `web/ifo.py:342` `assignment_create` (audit) + `web/ifo.py:310` `room_poster` (landing) | role-match |
| `web/ifo.py` import upload preview+commit + templates | IFO-03b | role-view | file-I/O | **none** — see §0 | none |
| `web/ifo.py` ad-hoc booking + template | IFO-05 | role-view | CRUD + conflict check | `web/faculty.py:314` `modality_new` (validate→service→outcome) | role-match |
| `web/ifo.py` manual release action | IFO-08 | role-view | request-response (write) | `web/faculty.py:441` `modality_withdraw` | exact |
| `web/faculty.py` online Verify & Start + template | FAC-08 | role-view | request-response (write) | `web/faculty.py:441` `modality_withdraw` + read-side `web/checker.py:611` `online_open` | exact |
| `web/faculty.py` attendance history + template | FAC-11 | role-view | read, paginated | `web/hr.py:178` `attendance` | exact |
| `web/faculty.py` profile photo upload + template | FAC-12 | role-view | file-I/O | **none** — copy whatever IFO-03b establishes | none |

---

## 2. Shared Patterns (apply to every new surface)

### 2.1 Role-gated view module + decorator
Every role module opens with a `*_required` decorator built the same way. Guard's, at `web/guard.py:23-31`:

```python
def guard_required(view):
    """Per-view role guard (Convention rule #5), mirroring checker_required."""
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.GUARD and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```

Identical shape at `web/ifo.py:33-40` (`ifo_required`), `web/faculty.py:47`, `web/hr.py:56`, `web/sys.py:19`. **All new views go in the existing module and reuse its existing decorator — do not create new modules or new decorators.**

### 2.2 Read-only enforcement (GRD-05 and every read surface)
`web/hr.py:178` and `web/ifo.py:477-479`:

```python
@ifo_required
@require_http_methods(["GET"])
def scorecard_csv(request, faculty_id):
```

Decorator order is always role-gate outermost, `require_http_methods` inner. `web/guard.py` currently has **zero** of these (`web/guard.py:57`, `:64`, `:79` are bare `@guard_required`) — GRD-05 is exactly adding `@require_http_methods(["GET"])` to those three plus every new Guard view. Import already needed: `from django.views.decorators.http import require_http_methods` (not currently imported in `web/guard.py`).

### 2.3 Hand-validated write + error partial at 400
The canonical write view, `web/ifo.py:342-422` `assignment_create`. Structure to copy verbatim:

```python
@ifo_required
@require_http_methods(["POST"])
def assignment_create(request):
    ...
    error = None
    if user is None:
        error = "Select a Checker or Guard."
    elif role not in DutyRole.values:
        error = "Select a valid duty role."
    ...
    if error:
        ctx = {"assignments": _active_assignments(), "error": error,
               **_assignment_form_ctx()}
        return render(request, "ifo/_assignment_form.html", ctx, status=400)
```

Note the deliberate ordering comment at `web/ifo.py:375-377`: **validate date/time FORMAT and pk numericness BEFORE the ORM write**, because `parse_date` returning None or a non-numeric `pk__in` raises an unhandled `ValidationError` (500) at INSERT time (CR-04). Every new form (booking dates/times, room create) hits the same trap.

The service-error variant, `web/faculty.py:452-460`:
```python
    try:
        withdraw_modality_shift(req, request.user)
    except ModalityShiftError as exc:
        error = str(exc)
    ctx = _modality_mine_ctx(request.user, error=error)
    return render(request, "faculty/modality_mine.html", ctx,
                  status=400 if error else 200)
```
Use this shape for IFO-05 (`room_is_free` refusal), IFO-08, FAC-08 (bad Teams link).

### 2.4 AuditLog on every domain state change
`web/ifo.py:403-407`:

```python
    AuditLog.objects.create(
        actor=request.user, event_type="assignment.created",
        target_type="assignment", target_id=str(a.pk),
        payload={"user": user.pk, "role": role, "scope": scope, "type": type_,
                 "floors": list(a.floors.values_list("pk", flat=True))})
```

Naming convention is `noun.verb_past` (`assignment.created`, `session.room_released`). New events: `room.created`/`room.updated`/`room.delete_refused`, `room.code_rotated`, `booking.created`/`booking.cancelled`, `session.teams_link_set`, `schedule.imported`. IFO-08 does **not** write its own AuditLog — `release_room` already writes `session.room_released` (see §4.2).

### 2.5 Pagination for any table
`web/hr.py:190` + `web/ifo.py:446`:
```python
    pager = paginate(request, qs, per_page=HR_PAGE_SIZE)
    ...
    return render(request, "...", {..., **pager})
```
`web/pagination.py:24` `paginate(request, object_list, per_page, param="page")` — it preserves active querystring filters across pages. Template side is `{% include "_pager.html" %}` (`templates/_pager.html`). Applies to FAC-11, IFO-01b room list, IFO-03b preview report.

### 2.6 URLs — flat list, no namespace
`web/urls.py` is one flat `urlpatterns` with globally-unique `name=` strings and role-prefixed paths (`web/urls.py:52-74`). New patterns go in the existing role comment block. **No `app_name`, no namespace — templates use `{% url 'ifo_rooms' %}` not `'ifo:rooms'`.**

Also fix while here: `web/urls.py:71` comments the Guard block as "GRD-01/02" and `web/guard.py:80` docstrings `locate` as "GRD-02" — that view is GRD-03. Relabel before adding the real GRD-02.

---

## 3. UI system — every new surface must be born styled

### 3.1 IFO surfaces → the shared console
`templates/ifo/_console.html` wraps `templates/_console.html`, which exposes blocks `console_title`, `page_actions`, `console`. Every new IFO template (`ifo/room_form.html`, `ifo/import.html`, `ifo/booking_new.html`) extends `ifo/_console.html` — see `templates/ifo/assignments.html` and `templates/ifo/weekly_reports.html` as the two closest skeletons (form-page and index-page respectively).

### 3.2 Guard + Faculty surfaces → the navy `.ft-*` shell
`static/faculty/faculty.css`. Vocabulary in active use:
- shell/layout: `.ft-*`
- forms: `.ft-form*`, `.ft-control`, `.ft-fieldset`, `.ft-choice`
- results: `.ft-outcome*` result cards (`templates/faculty/_outcome.html`)
- primary action: `.ft-btn-navy`
- cards/status: `.ft-card--neutral|ok|warn|bad|info`, `.ft-pill--upcoming|active|late|absent|online`

The card/pill mapping is server-computed, never client-derived — `web/checker.py:636-647` `_CARD_STYLES` is the reference table, and its comment states the rule: **colour is never the only signal; each state also carries a Lucide icon + a text label (WCAG 1.4.1).** GRD-02's per-room schedule and FAC-08's start outcome both need state tokens; derive them server-side into a dict like this, do not branch on colour in the template.

Closest template analogs: `templates/guard/monitor.html` + `templates/guard/_monitor_rows.html` (Guard shell + polled body), `templates/faculty/modality_new.html` + `templates/faculty/_modality_form.html` (Faculty form + partial + outcome).

### 3.3 Tables and skeletons
`static/css/app.css` provides `.tbl`, `.data-grid`, `.table-wrap`, `.skel*`. Any polled region gets a `.skel*` placeholder. `static/css/tokens.css` is the single source of truth for colour/spacing — no hard-coded hex in new CSS, and **no border-left accent stripes** (explicit UI contract).

---

## 4. Pattern Assignments

### 4.1 GRD-02 — per-room schedule for Guard (`web/guard.py`, new view + template)

**Analog: `web/ifo.py:190-216` `room_panel` and `web/ifo.py:219-263` `_room_timetable`.** Reuse both shapes; the Guard version differs only by (a) floor authorization and (b) the navy shell instead of the console.

Tile/state derivation to reuse rather than reinvent — `web/ifo.py:86-123` `_room_tile` gives the five states (`absent`/`starting`/`in_session`/`free`/`idle`) with the grace-window rule at `web/ifo.py:117-120`:
```python
    elif now > current.scheduled_start + grace:
        # Past grace with nobody checked in. The sweep job will mark this ABSENT;
        # the board must not wait for the job to tell the truth.
        tile["state"] = "absent"
```
And the online-occupancy rule at `web/ifo.py:67-83` `_occupies` — an ONLINE class does not occupy a physical room. Both `_room_tile` and `_occupies` are module-private in `web/ifo.py`; **the planner must decide: import them cross-module, or lift them to a shared helper.** Recommend lifting to `web/room_state.py` and having `web/ifo.py` import from there — a `from web.ifo import _room_tile` in `web/guard.py` inverts the dependency and imports a private.

Authorization is the piece that has no IFO analog: the room must belong to a floor the guard is on duty for **right now**, re-derived server-side. Reuse `web/guard.py:34-50` `_guard_floor_ids` verbatim:
```python
    for a in (Assignment.objects
              .filter(user=user, role=DutyRole.GUARD,
                      scope=AssignmentScope.FLOOR, status="active")
              .prefetch_related("floors")):
        if R.assignment_covers_now(a, today, now_t):
            floor_ids.update(a.floors.values_list("pk", flat=True))
```
An off-floor room must 404 (not 403) — mirrors `web/checker.py:616-618`'s non-owner 404 for online sessions.

Polling: `web/guard.py:53-54` `_poll_ms()` reads `settings.FLUXTRACK_POLICY["poll_interval_seconds"]`; the IFO side reads it via `get_policy(...)` at `web/ifo.py:179`. Note the **inconsistency** — Guard reads settings directly, IFO reads policy. New Guard code should stay consistent with `_poll_ms()` locally, but flag it.

---

### 4.2 GRD-04 — debounced push alerts (`scheduling/jobs.py` modify)

**Analog: `scheduling/jobs.py:113` inside `detect_room_conflicts` (`scheduling/jobs.py:77`).** The existing single-recipient fan-out:
```python
            notify(role=Role.IFO_ADMIN, type="room_conflict",
                   title="Room double-booking detected", ...)
```
`ops/notify.py:18` signature is `notify(*, type, title, body="", link="", role=None, users=None)` — it already accepts an explicit `users=` list, so the floor-scoped Guard fan-out needs **no change to `notify()` itself**. Build the recipient list from the same on-duty derivation as §4.1 (`_guard_floor_ids` logic, but inverted: given a floor, find guards) and pass `users=[...]`.

Per D-06 the debounce is the job cadence: collect all events during the run, then emit **one** `notify()` per on-duty guard at the end summarizing the batch ("3 rooms now free on Floor 3"). That means the `notify()` call moves out of the per-conflict loop into a post-loop aggregation — structurally different from the IFO call it sits beside. Both `sweep_no_shows` (`scheduling/jobs.py:35`) and `detect_room_conflicts` (`:77`) feed it, so the aggregation buffer likely belongs in whatever runs them together.

Guard: `ops/tests.py:115` asserts `ops.notify.notify` is the NOTIF-00 **single write path** — the new fan-out must go through `notify()`, never `Notification.objects.create`.

---

### 4.3 GRD-05 — enforce read-only

Mechanical. Add `@require_http_methods(["GET"])` under `@guard_required` on `web/guard.py:57` `monitor`, `:64` `monitor_rows`, `:79` `locate`, plus every new GRD-02 view. Add the import. Test analog: `web/tests.py:590` `GuardSurfaceTests` — extend it with POST-returns-405 assertions per view.

---

### 4.4 IFO-01b — Room CRUD

**Analog: `web/ifo.py:342-422` `assignment_create`** for the create/edit write shape (§2.3 + §2.4), and `web/ifo.py:317-326` `_assignment_form_ctx` for the choice-data helper:
```python
def _assignment_form_ctx():
    """Choice data for the assignment create form (Checkers/Guards + floors)."""
    ...
    floors = (Floor.objects.select_related("building")
              .order_by("building__code", "number"))
```
A room form needs the identical `Floor.objects.select_related("building")` list.

Delete-refusal (D-17) has no direct analog. Nearest precedent in spirit is `web/ifo.py:561-562`'s "report, never 500" guard. Implementation is a pre-flight count across `Schedule`, `Session`, `Booking` filtered on the room, and the error string must **name** what references it — so count each relation separately, not one boolean.

Room lookup convention everywhere is by `code`, not pk: `get_object_or_404(Room.objects.select_related("floor__building"), code=code)` (`web/ifo.py:195`, `:268`, `:312`). Keep it for the CRUD URLs.

---

### 4.5 IFO-02 — QR / six-digit-code rotation

The fields (`campus.models.Room.code_rotated_at` / `code_rotated_by`) have **zero writers** today. The reprint landing already exists: `web/ifo.py:310-313` `room_poster` → `templates/ifo/poster.html`, routed at `web/urls.py:56` `name="ifo_room_poster"`.

Write view copies §2.3/§2.4 exactly; on success `redirect("ifo_room_poster", code=room.code)` (D-14). Redirect precedent: `web/ifo.py:287-290` `live` uses `redirect("ifo_rooms", permanent=True)` — same flat-name style, minus `permanent`.

The QR image is regenerated on demand from `room.qr_token` (`web/ifo.py:294-307`), so rotation only needs to change the token + stamp the two fields; nothing cached to invalidate.

Confirmation step: no destructive-confirm dialog exists anywhere in the codebase yet. Build it as a GET confirm page (not a JS `confirm()`), stating "this invalidates the current poster for room X", POST to rotate. Style with `.ft-outcome*`-equivalent console card.

---

### 4.6 IFO-03b — schedule import upload (preview → commit)

**No analog for the upload half (§0).** For the wrapping half, `scheduling/management/commands/import_offerings.py` already dispatches by extension and supports `--dry-run`; `scheduling/importing.py` `reconcile()` produces the four-bucket report. Call the module functions directly — do **not** shell out to `call_command`, and do not re-implement the parser.

Read-side storage analog for holding the file between preview and commit, `web/ifo.py:561-567`:
```python
    if not path or not default_storage.exists(path):
        raise Http404("Report file not found.")
    with default_storage.open(path, "rb") as fh:
        data = fh.read()
```
`default_storage` is already imported in `web/ifo.py:10`. Write side is `default_storage.save(name, file)` — net-new. The server-built-path safety property (never trust a client-supplied path) at `web/ifo.py:546-553` must carry over: the commit step takes a token/pk, resolves the stored path server-side, and never accepts a path from the form.

Preview report table: `.tbl` / `.data-grid` + `paginate` (§2.5). Commit is a separate `@require_http_methods(["POST"])` view.

`scheduling/management/commands/reset_term.py` stays unreachable from the web (D-13) — do not import it into `web/`.

---

### 4.7 IFO-05 — ad-hoc booking with conflict check

**Analog: `web/faculty.py:314` `modality_new`** — the existing validate-then-call-a-domain-service-then-render-outcome surface, with its room-picker sibling `web/faculty.py:274-275` `modality_rooms` (`@require_http_methods(["GET"])`, htmx-loaded partial `templates/faculty/_modality_rooms.html`). That picker is already backed by availability, so it is the closest thing to a booking room-chooser.

Conflict check is `ops/availability.py:113` `room_is_free(room, start, end, *, exclude_session_id=None)` — the single oracle (D-08). Its overlap semantics live in `_session_occupants` (`ops/availability.py:64`) and `_reservation_occupies` (`:81`). Do not write a second overlap query.

Cancellation is a status flip only (D-10): `room_is_free` counts `status="active"` bookings, so cancel = flip status. No availability code changes.

MSSQL note that applies to any follow-up query after an availability call: materialize with `list()` before follow-ups (HY010) — precedent visible in `web/ifo.py:131`, `:198`, `:244`.

---

### 4.8 IFO-08 — manual room release

**Analog: `web/faculty.py:441-460` `modality_withdraw`** — POST-only, re-fetch by pk, delegate to a domain service, service-error → 400 re-render.

Call `ops/occupancy.py:17` `release_room(session, *, actor=None, now=None)` with `actor=request.user`. It writes the `session.room_released` AuditLog itself — **do not add a second AuditLog** (§2.4 exception).

**Invariant to update (expected, not a regression):**
- `ops/occupancy.py:5` — `"ONLY caller is MOD-03 (Phase 4) on an approved ->Online modality shift."`
- `ops/occupancy.py:21` — `"INVOKED ONLY by MOD-03 (Phase 4)..."`
- `ops/tests.py:118-130` `ReleaseRoomTests` docstring — `"release_room has zero Phase-2 callers (T-02-11)"`, and the paired grep-guard it points at in Plan 02-03 `SweepTests`.

All three must be amended to name IFO-08 as the second legitimate caller. The actor-recording test at `ops/tests.py:158-166` already proves `actor=` works and needs no change — it is the exact behaviour IFO-08 depends on.

---

### 4.9 FAC-08 — online Verify & Start with pasted Teams link

**Write-side analog: `web/faculty.py:441` `modality_withdraw`** (POST-only + service-error → 400).
**Read-side counterpart to stay compatible with: `web/checker.py:611-627` `online_open`** — it renders `session.teams_link` and explicitly handles the empty case:
```python
    if not session.teams_link:
        notify(role=Role.IFO_ADMIN, type="online_no_link", ...)
        return render(request, "checker/online_open.html",
                      {"session": session, "no_link": True})
```
Faculty self-start writes the **same** `Session.teams_link` field the Checker reads (D-03), which is what makes that `no_link` branch stop firing. Set `status=ACTIVE`, `actual_start`, and an ONLINE self-start `checkin_method`; leave `verified_by_checker` alone (D-02).

URL-plausibility validation goes in the §2.3 hand-validation ladder, before the write.

Audit: `session.teams_link_set` with the previous value in `payload` (overwrites are the interesting case).

Outcome rendering: `templates/faculty/_outcome.html` + `.ft-outcome*`.

Do **not** touch `web/scan.py` or `scheduling/resolver.py` (D-09).

---

### 4.10 FAC-11 — faculty attendance history (read-only, flags visible)

**Analog: `web/hr.py:178-190` `attendance`** — the closest existing surface by every axis (read-only session-level attendance table, filters, pagination, status labels).

Copy from it:
- `@require_http_methods(["GET"])` (`web/hr.py:178`)
- `_filtered_sessions(request)` (`web/hr.py:86`) — filter-parsing shape; scope it to `faculty=request.user` instead of cross-dept
- `_status_label(status)` (`web/hr.py:73`) — reuse; do not invent a second label map
- `_filter_choices()` (`web/hr.py:160`)
- `paginate(request, qs, per_page=...)` (`web/hr.py:190`)

Difference: HR's version is unscoped/cross-dept; faculty's is hard-scoped to the requesting user server-side (never a `?faculty=` param — that is the IDOR re-gate rule stated at `web/faculty.py:447-449`).

Checker flags are visible but non-actionable (D-15) — render as `.ft-pill--absent`-family chips with icon + text, no buttons.

Shell is navy `.ft-*`, not the HR console — closest template is `templates/faculty/schedule.html`.

No CSV export requested; `web/hr.py:220` `attendance_csv` is the analog if one is added.

---

### 4.11 FAC-12 — profile photo upload

**No analog (§0).** Copy the multipart pattern established by IFO-03b (§4.6).

Target field already exists: `accounts/models.py:36`. Validation per D-16 — jpg/png, max size, Pillow decode, server-side re-encode/resize. Pillow is already a dependency. Everything else (POST-only, hand-validation ladder, 400 re-render, `.ft-form*` controls, `.ft-outcome*` result) follows §2.3 and §3.2.

Do **not** rebuild the notification-prefs half — `web/notifications.py` `settings_page`/`mute_toggle` already ship it (`web/urls.py:80-81`). If the profile page should host both, embed/link the existing surface.

---

## 5. Test Conventions

`web/tests.py` is class-per-surface: `SysJobMonitorTests` (`web/tests.py:551`), `GuardSurfaceTests` (`:590`), `FacultyModalityAuthzTests` (`:246`), `DeanModalityAuthzTests` (`:412`). Larger surfaces get their own module — `web/tests_ifo_board.py`, `web/tests_hr.py`, `web/tests_pagination.py`.

Recommended split: extend `GuardSurfaceTests` for GRD-02/05; new `web/tests_ifo_rooms.py` for IFO-01b/02, `web/tests_ifo_import.py` for IFO-03b, `web/tests_ifo_booking.py` for IFO-05/08, `web/tests_faculty_history.py` for FAC-08/11/12.

Every role surface needs the three-way authz test (right role 200 / wrong role 403 / anon redirect) plus, for read-only surfaces, POST → 405.

Domain-test idiom: method-local imports so a new class goes RED before the module exists (`ops/tests.py:128-129` explains this explicitly), and `from scheduling.tests import make_session` as the FK-chain factory (`ops/tests.py:134`).

**Known pre-existing failures:** 3 dev-login / home-redirect tests fail today, unrelated to this phase. Do not chase them; do not count them as regressions.

---

## 6. No Analog Found

| Surface | Role | Data flow | Reason |
|---|---|---|---|
| IFO-03b upload handler | role-view | file-I/O | No `request.FILES` / multipart anywhere in the repo (§0). Establishes the house pattern. |
| FAC-12 photo upload | role-view | file-I/O | Same. Should copy IFO-03b once it lands. |
| Destructive-confirm step (IFO-02, IFO-01b delete) | UI | request-response | No confirm-before-destroy interaction exists yet. Build as a GET confirm page, not a JS dialog. |
| Batch-coalesced notification (GRD-04) | job | batch | `notify()` is called once per event today; the per-run aggregation buffer is new structure around an existing call. |

---

## 7. Metadata

**Search scope:** `web/`, `ops/`, `scheduling/`, `campus/`, `accounts/`, `verification/`, `templates/`, `static/`
**Key reads:** `web/guard.py` (full), `web/ifo.py` (full), `web/urls.py` (full), `ops/tests.py:115-184`, `web/faculty.py:440-460`, plus targeted greps across `web/hr.py`, `web/checker.py`, `scheduling/jobs.py`, `ops/availability.py`, `ops/occupancy.py`, `ops/notify.py`
**Date:** 2026-07-18

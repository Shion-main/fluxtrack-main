# Phase 4: Modality Shift Approval & SRS v1.2 - Pattern Map

**Mapped:** 2026-07-03
**Files analyzed:** 8 new/modified artifacts
**Analogs found:** 8 / 8

> Scope note: RESEARCH.md already mapped the **reused primitives** (`release_room`, `notify`,
> `get_policy`, `declared_modality`, Dean routing). This file does NOT duplicate that. It names,
> per NEW artifact, the single closest existing file + the exact `file:line` to copy the shape from.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `ops/availability.py` (new) | service | transform / query | `scheduling/jobs.py:87-92` (occupancy annotate) + `web/scan.py:144-145` (room-held query) | role-match |
| `scheduling/models.py` — `ModalityShiftRequest` (+migration) | model | CRUD | `scheduling/models.py:70-131` (Session/status enums/FKs) | exact |
| `scheduling/services.py` (new) — submit / apply-approval / withdraw | service | event-driven / transform | `verification/services.py:66-139` (pure-core + apply + notify-once + list() guard) | exact |
| `web/faculty.py` — submit form + "my requests" | view | request-response | `web/ifo.py:131-211` (`assignment_create`) + `web/faculty.py:24-35` | exact |
| `web/dean.py` (new) — approval queue + approve/reject POST | view | request-response | `web/ifo.py:27-34,131-211` (role gate + validated POST) | role-match |
| `scheduling/management/commands/materialize_sessions.py` — born-released/assigned hook | command | batch | `materialize_sessions.py:54-61` (self) + `verification/services.py:42-47` (effective-modality) | exact |
| `scheduling/management/commands/regenerate_srs_docx.py` (new) — DOC-01 | command | file-I/O | `scheduling/management/commands/assign_online.py` (BaseCommand shape) | role-match |
| Authz gates (in `web/dean.py` / `web/faculty.py` / `scheduling/services.py`) | middleware | request-response | `web/faculty.py:14-21` + `web/ifo.py:27-34` (role decorators) | exact |

---

## Pattern Assignments

### `ops/availability.py` (new — service, room-free query)

**Analog:** `scheduling/jobs.py` (occupancy annotate) + `web/scan.py` (room-held-by-ACTIVE query). The
"is room R free for [start,end)?" primitive does NOT exist — build it from these two shapes.

**Occupant / `room_released_at IS NULL` query shape** (`scheduling/jobs.py:87-92`):
```python
conflicting_room_ids = [
    row["room_id"] for row in
    (Session.objects.filter(status=SessionStatus.ACTIVE,
                            room_released_at__isnull=True)
     .values("room_id").annotate(n=Count("id")).filter(n__gt=1))
]
```

**Room-held-by-a-session query** (`web/scan.py:144-145`):
```python
occupying = (Session.objects.filter(room=room, status=SessionStatus.ACTIVE)
             .exclude(faculty=request.user).values_list("pk", flat=True).first())
```

**Effective-modality exclusion (online sessions hold no physical room)** — copy from
`verification/services.py:46-47`:
```python
return [s for s in sessions
        if (s.declared_modality or s.schedule.modality) == Modality.ONLINE]
```
Availability inverts this: an occupant is a Session whose effective modality **≠ Online**.

**Building scope** — `campus/models.py`: `Room.floor → Floor.building`. Candidate set:
`Room.objects.filter(floor__building=session.schedule.room.floor.building)`; prefer original
`schedule.room` first, then deterministic order.

**MSSQL guard** (`scheduling/jobs.py:52-58`): `list(...)` the candidate rooms/sessions before any
write loop — pyodbc single active result set (HY010). Overlap predicate is half-open:
`O.start < end AND start < O.end`.

---

### `scheduling/models.py` — `ModalityShiftRequest` (model, CRUD)

**Analog:** the existing `Session` / `Schedule` / `SessionStatus` definitions in the same file.

**Status enum pattern** (`scheduling/models.py:70-75`):
```python
class SessionStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    ACTIVE = "active", "Active"
    ...
```
→ Mirror as `ModalityShiftStatus(PENDING/APPROVED/REJECTED/WITHDRAWN)` (D-10).

**FK + audit-field pattern** (`scheduling/models.py:86-105`) — copy the `PROTECT` requester FK, the
`Modality` choices field for `target_modality`, and the `SET_NULL` actor + timestamp shape already
used for `modality_changed_by` / `modality_changed_at`:
```python
faculty = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sessions")
declared_modality = models.CharField(max_length=10, choices=Modality.choices, blank=True)
modality_changed_at = models.DateTimeField(null=True, blank=True)
modality_changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
    on_delete=models.SET_NULL, related_name="modality_changes")
```
Model fields to add: `schedule` FK, `requester` FK, `dean` FK, `target_modality`, window
(`window_start`/`window_end` dates), `preferred_room` (nullable FK — D-05/D-06 preference),
`status`, `reason` (blank), timestamps. Add a migration.

**Anti-pattern (RESEARCH):** do NOT add a `Session.modality` column — `declared_modality` IS the override.

---

### `scheduling/services.py` (new — service: submit / apply-approval / withdraw)

**Analog:** `verification/services.py:66-139` (`assign_online_sessions`) — the canonical "gather context
→ pure decision → transactional apply → notify-once, materialize-before-write" shape.

**Transactional apply + list() guard + audited write** (`verification/services.py:114-125`):
```python
for s in sessions:                              # sessions = list(...) materialized first
    ...
    with transaction.atomic():
        s.online_checker_id = checker_id
        s.save(update_fields=["online_checker"])
        AuditLog.objects.create(actor=None, event_type="session.online_checker_assigned",
            target_type="session", target_id=str(s.pk), payload={"checker_id": checker_id})
```

**Apply-→Online consequence** — compose with `ops.occupancy.release_room` (`ops/occupancy.py:17-36`)
per in-window session; see RESEARCH.md §"Applying a →Online approval" for the exact loop.

**Lead-time gate** (D-02) — Manila math, see RESEARCH.md Pattern 4. Uses `timezone` + `get_policy`.

**Dean routing** (D-09) — RESEARCH.md Pattern 5, `Role.DEAN` + `User.department` (`accounts/models.py:14-35`).

**TOCTOU re-check** (D-06) — re-resolve room via `ops/availability.py` INSIDE `transaction.atomic()`
before the write; block-and-stay-pending on no-free-room (D-07 — no partial apply).

---

### `web/faculty.py` — submit form + "my requests" list (view, request-response)

**Analog:** `web/ifo.py:131-211` (`assignment_create`) for the validated-POST + friendly-400 pattern;
existing `web/faculty.py:24-35` for the faculty list view + `faculty_required` gate.

**Validate-before-write, 400-not-500, server-side object resolution** (`web/ifo.py:143-179`):
```python
user = User.objects.filter(pk=request.POST.get("user"), role__in=[...]).first()
...
elif date_raw and parse_date(date_raw) is None:
    error = "Enter a valid date."
...
if error:
    return render(request, "ifo/_assignment_form.html", ctx, status=400)
```
Apply to the submit form: never trust the client `room` pk — re-resolve against
`available_rooms_for(session)`; validate window dates with `parse_date` (V5).

**Audited create + post-create side effect** (`web/ifo.py:182-207`) — mirror: create the
`ModalityShiftRequest`, write an `AuditLog`, then `notify(users=[dept_dean], ...)`.

**"My requests" list** — copy the `faculty.schedule` shape (`web/faculty.py:24-35`): filter by
`requester=request.user`, `select_related`, render a template.

---

### `web/dean.py` (new — view: approval queue + approve/reject)

**Analog:** `web/ifo.py:27-34` (role-gate decorator) + `web/ifo.py:131-207` (validated approve POST).

**Role decorator to clone for `dean_required`** (`web/ifo.py:27-34`):
```python
def ifo_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.IFO_ADMIN and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```
→ `dean_required`: `request.user.role != Role.DEAN`.

**Approve/reject POST** — `@require_http_methods(["POST"])` (see `web/scan.py:132`); re-gate on the
server: `request.status == PENDING AND request.requester.department == request.user.department`
(Pitfall 6 / 03-02 re-gate). Call `scheduling.services.apply_approval(...)`; on the D-07 no-room
block, render the queue partial with a 400/error message and leave status PENDING.

**URL wiring** — add to `web/urls.py:5-38` alongside the existing grouped `path(...)` entries:
```python
path("dean/requests", dean.queue, name="dean_queue"),
path("dean/requests/<int:pk>/approve", dean.approve, name="dean_approve"),
path("dean/requests/<int:pk>/reject", dean.reject, name="dean_reject"),
path("faculty/modality/new", faculty.modality_new, name="faculty_modality_new"),
path("faculty/modality/mine", faculty.modality_mine, name="faculty_modality_mine"),
```
Import `dean` in the `from . import ...` line (`web/urls.py:3`).

---

### `materialize_sessions.py` — born-released / born-assigned hook (command, batch)

**Analog:** the command itself (`materialize_sessions.py:54-61`) + `verification/services.py:42-47`.

**Insertion point — right after `get_or_create` when `was_created`** (`materialize_sessions.py:54-60`):
```python
_, was_created = Session.objects.get_or_create(
    schedule=sch, date=d,
    defaults={"faculty": sch.faculty, "room": sch.room,
              "scheduled_start": ss, "scheduled_end": se,
              "status": SessionStatus.SCHEDULED})
created += was_created
```
After a create, look up an APPROVED `ModalityShiftRequest` covering `(schedule=sch, window contains d)`
and set the new session's `declared_modality` (+`room_released_at` for →Online via `release_room`,
+resolved room for →F2F) — Pitfall 1 (out-of-horizon recurring window). Pitfall 2 / A1: →F2F with no
free room at materialize time → fall back to `schedule.room` + `notify(role=IFO_ADMIN, ...)`, never crash.
Materialize candidate lookups with `list(...)` (HY010).

---

### `regenerate_srs_docx.py` (new — command, file-I/O, DOC-01)

**Analog:** `scheduling/management/commands/assign_online.py` (clean `BaseCommand` + `add_arguments` +
`handle` + ASCII-only `self.stdout.write(self.style.SUCCESS(...))`).

**Command skeleton to copy** (`assign_online.py:22-31,49-51`):
```python
class Command(BaseCommand):
    help = "..."
    def add_arguments(self, p): ...
    def handle(self, *args, **o):
        ...
        self.stdout.write(self.style.SUCCESS("..."))
```
Body: `import pypandoc; pypandoc.convert_file("FluxTrack_SRS.md", "docx", outputfile="FluxTrack_SRS.docx")`
(RESEARCH.md §DOC-01). ⚠ `pypandoc_binary==1.17` install is gated behind one `checkpoint:human-verify`
(package-legitimacy protocol). pandoc is NOT on PATH — the bundled wheel is the reproducible route.

---

## Shared Patterns

### Authentication / role gates
**Source:** `web/faculty.py:14-21` (`faculty_required`), `web/ifo.py:27-34` (`ifo_required`)
**Apply to:** every new view — `faculty_required` on submit/my-requests, new `dean_required` on the queue.
```python
def faculty_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.FACULTY and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```

### Object-level re-gate on every POST (IDOR — Pitfall 6 / 03-02)
**Source:** `web/scan.py:172-181` (two-step confirm re-checks `user_id`) + the `@require_http_methods(["POST"])` guard
**Apply to:** approve/reject (Dean + same-department + PENDING) and withdraw (requester + PENDING).
Never trust the earlier snapshot; re-resolve the request from its pk and re-check status server-side.

### AuditLog on every state change (Convention §2)
**Source:** `verification/services.py:121-124`, `web/scan.py:71-75`, `ops/occupancy.py:30-35`
**Apply to:** submit, approve, reject, withdraw, room-assign, room-release (release_room self-audits).
```python
AuditLog.objects.create(actor=user, event_type="...", target_type="session",
                        target_id=str(s.pk), payload={...})
```

### Notification single write path (NOTIF-00)
**Source:** `ops.notify.notify` — usage at `web/scan.py:107-109`, `verification/services.py:133-136`,
`scheduling/jobs.py:113-116`
**Apply to:** submit → dept Dean (`notify(users=[dean], ...)`); decision → requester; →Online applied /
→F2F assigned → `notify(role=Role.IFO_ADMIN, ...)`. Never construct `Notification` rows inline
(guarded by `ops/tests.py` SingleWritePathTests).

### MSSQL HY010 guard
**Source:** `scheduling/jobs.py:52-58`, `verification/services.py:19-20,42-45`
**Apply to:** every service/hook — `list(...)` candidate sessions/rooms before the `save()` loop.

### Validated-input, 400-not-500
**Source:** `web/ifo.py:164-179` (`parse_date`/`parse_time` before ORM write; render partial `status=400`)
**Apply to:** submit form (window dates, target modality enum, room pk) and approve/reject (reason).

---

## No Analog Found

None. Every Phase-4 artifact has at least a role-match analog in-repo (this is an in-repo composition
phase). The single genuinely-new primitive (`ops/availability.py`) is assembled from three existing
query shapes cited above rather than copied wholesale — expected, since D-08's "booking conflict-check"
does not yet exist (Phase 7 / IFO-05).

## Metadata

**Analog search scope:** `web/`, `scheduling/`, `ops/`, `verification/`, `accounts/`, `campus/`,
`scheduling/management/commands/`
**Files scanned (read this session):** `web/scan.py`, `web/faculty.py`, `web/ifo.py`, `web/urls.py`,
`scheduling/jobs.py`, `scheduling/models.py`, `scheduling/management/commands/materialize_sessions.py`,
`scheduling/management/commands/assign_online.py`, `verification/services.py`, `ops/occupancy.py`,
`ops/tests.py`, `accounts/models.py`, `campus/models.py`
**Pattern extraction date:** 2026-07-03
</content>
</invoke>

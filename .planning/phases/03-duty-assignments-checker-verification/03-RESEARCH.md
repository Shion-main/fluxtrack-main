# Phase 3: Duty Assignments & Checker Verification - Research

**Researched:** 2026-07-03
**Domain:** Django 6 role-surface build — model extension, pure-decision-core scan mirroring, htmx-polled floor board, IndexedDB offline replay
**Confidence:** HIGH (this phase is almost entirely internal — extend existing models + mirror the shipped Faculty scan stack; no new external dependencies)

## Summary

Phase 3 builds the on-duty Checker verification surface on top of two already-scaffolded, already-migrated models (`verification.Assignment`, `verification.CheckerValidation`) and the shipped Faculty scan architecture (`web/scan.py` + `scheduling/resolver.py`). Nothing here needs a new library: the whole phase is Django views, one pure decision core, a small model extension, a migration to retire one dead enum member, an htmx-polled board (a direct analog of the existing `ifo.live`/`live_rows` pair), and a vanilla-JS IndexedDB queue whose only server surface is a re-validation replay endpoint. `accounts.User.profile_photo` **already exists** (`accounts/models.py:35`), so CHK-02 identity matching has no blocking dependency.

The single highest-value architectural decision is to **mirror the Faculty scan seam exactly**: a pure `resolve_checker_scan(...)` in `verification/resolver.py` (no ORM, no `timezone.now()`, returns an outcome dataclass) plus a thin `web/checker.py` apply layer that fetches context, writes `CheckerValidation` + `AuditLog`, and fires `notify()` for flags. This is the same pure-core/thin-apply/signed-two-step/idempotent-cache pattern the codebase already proves in `web/scan.py`, and reusing it keeps scan-time and replay-time decisions provably identical (the same coupling guarantee Phase 2 enforced between scan and sweep).

The subtle, must-get-right integration is **online verification flipping session status so the JOB-02 sweep stays correct**. For F2F a Verify only sets the derived `verified_by_checker` flag (status is already ACTIVE from the faculty check-in). For **online** there is no faculty check-in, so a Checker Verify is the *only* thing that can move the session out of SCHEDULED — it must set `status=ACTIVE` + `actual_start` + `checkin_method=ONLINE_MANUAL` (that choice already exists). Only then can the sweep's online exclusion be safely removed, because a genuinely-attended online session is now ACTIVE and the sweep skips it, while an un-verified online no-show correctly falls to Absent under the same grace predicate.

**Primary recommendation:** Add an `AssignmentScope` field (`FLOOR` default / `ONLINE`) to `Assignment` and an `online_checker` FK on `Session`; build `verification/resolver.py` (pure) + `web/checker.py` (apply) as a faithful mirror of the Faculty scan stack; assign online sessions to online-duty Checkers by a **pure round-robin core** run as a small step (default automatic, IFO-reassignable); retire `CONFIRMED_ABSENT` via a state-only `AlterField`; and remove the sweep's online `continue` guard in the same wave that ships the online Verify path (updating the two existing online-exclusion tests in lockstep).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| On-duty gating decision (off-duty / wrong-floor / room-state) | Pure core (`verification/resolver.py`) | — | Project rule #1: decision logic is a pure, ORM-free, `now`-injected function (mirrors `scheduling/resolver.py`) |
| Fetch context + write `CheckerValidation`/`AuditLog` + `notify()` | API/Backend view (`web/checker.py`) | DB | Project rule #2: every write emits AuditLog; thin apply layer owns all I/O (mirrors `web/scan.py._apply`) |
| Assignment CRUD (IFO grants floor/online duty) | API/Backend view (`web/ifo.py` extension) | DB | IFO-06 is an IFO surface; follows one-module-per-surface convention |
| Per-session online-Checker pre-assignment (round-robin) | Pure core (distribute) + thin apply | DB | Deterministic distribution is unit-testable in isolation; apply writes `Session.online_checker` + AuditLog |
| Floor board (coverage %, priority queue, color cards) | Frontend server (htmx-polled view) | Browser | Direct analog of `ifo.live`/`ifo.live_rows`; server computes state, browser polls + renders |
| Camera QR capture / manual code entry | Browser / Client | — | Reuses the existing PWA scan page shell; payload posts to the checker resolve endpoint |
| Offline scan queue | Browser / Client (IndexedDB, vanilla JS) | — | CHK-08 + project constraint: no client framework; queue lives client-side |
| Offline replay re-validation | API/Backend view (`web/checker.py` replay endpoint) | Pure core + DB | "Never blindly trusted": server re-runs the same pure core against current state |
| Online no-show → Absent | Scheduler job (`scheduling/jobs.py` sweep) | DB | Removing the online exclusion lets the existing sweep own online Absent under the shared grace predicate |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django | 6.0.6 | Views, ORM, migrations, `django.core.signing` | Pinned project baseline `[VERIFIED: requirements.txt]` |
| mssql-django | 1.7.3 | MSSQL backend (pyodbc, ODBC Driver 18) | Pinned; migration/collation behavior already proven in Phase 1 `[VERIFIED: requirements.txt]` |
| htmx | 2.0.6 | Polled floor board, partial swaps, action posts | Already loaded in `base.html:16`; the project's live-surface mechanism `[VERIFIED: templates/base.html]` |
| Franken UI | 2.1.2 | `uk-*` component classes + Tailwind utilities for cards/labels | Already loaded via CDN in `base.html:12-15` `[VERIFIED: templates/base.html]` |
| IndexedDB | Browser-native | Offline scan queue (CHK-08) | Vanilla JS per project constraint; no wrapper library permitted `[CITED: 03-CONTEXT.md decisions]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `django.core.signing` | (stdlib of Django) | Sign the scan→action binding token (two-step / replay integrity) | Mirror `CONFIRM_SALT` pattern from `web/scan.py:27` for any deferred/confirmed action |
| Django cache (locmem) | (built-in) | Idempotency keys for apply + replay dedupe | Mirror `scan-idem:` key pattern `web/scan.py:162-165`; also backs rate limiting |
| `qrcode` / `Pillow` | (already installed) | Not needed for Checker scan input (camera reads QR); Pillow already backs `profile_photo` ImageField | Only relevant to render `profile_photo`; no new install |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `AssignmentScope` field on `Assignment` | New `AssignmentType.ONLINE` member | Rejected — `type` already means shift-vs-standing (temporal); overloading it loses that axis for online duty. Scope is orthogonal to type. |
| `AssignmentScope` field | New `OnlineDutyAssignment` model | Rejected — duplicates user/term/status/date fields; a scoped additive field on the existing model is far less disruptive (CONTEXT: "small extension"). |
| `Session.online_checker` FK | Separate `OnlineSessionAssignment` model | Rejected — one owner per session, no history requirement; AuditLog already provides provenance. FK is the minimal viable surface and Phase 4 can set it in one line. |
| Round-robin at materialize time | Assign only via IFO manual UI | Round-robin is the automatic default (no per-session IFO toil); manual reassign stays as override. See Pattern 3. |
| IndexedDB raw API | `idb`/`localForage` wrapper | Rejected — project constraint forbids client libraries; the queue is small enough for the raw API. |

**Installation:**
```bash
# No new packages. Phase 3 uses only the pinned, already-installed stack.
```

## Package Legitimacy Audit

> This phase installs **no external packages**. All dependencies (Django 6.0.6, mssql-django 1.7.3, htmx 2.0.6, Franken UI 2.1.2, Pillow) are already pinned and in use. IndexedDB is a browser-native API. No registry lookup or legitimacy gate is required.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none — no new dependencies) | — | — | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
                          CHECKER (mobile, on the move)
                                    |
        +---------------------------+-----------------------------+
        |                           |                             |
   [Floor board]              [Room scan]                  [Offline queue]
   htmx poll GET              camera QR / manual code       IndexedDB (vanilla JS)
        |                           |                             |
        v                           v                             | reconnect
  /checker/floor/rows        POST /checker/resolve                v
  (coverage %, priority       (payload -> room)            POST /checker/replay
   queue, color cards,             |                       (batch of queued scans)
   Absent excluded)                v                             |
        |                  +-------------------+                 |
        |                  | verification/     |  <----re-run----+  (same pure core,
        |                  | resolver.py       |                     CURRENT state)
        |                  | resolve_checker_  |
        |                  | scan(...) PURE    |
        |                  +-------------------+
        |                          | outcome
        |                          v
        |                  +-------------------+
        |                  | web/checker.py    |
        |                  | _apply()  THIN    |
        |                  +-------------------+
        |                    |      |       |
        |         writes     |      |       | flags -> notify(IFO + HR)
        |    CheckerValidation|     |       |         replay conflict -> notify(IFO)
        |         + AuditLog  |     |       v
        |                     |     |   ops/notify.py --> Notification rows
        |                     v     v
        |            +----------------------------+
        |            | scheduling.Session         |
        |            |  F2F Verify: verified flag  |
        |            |  ONLINE Verify: status=     |
        |            |   ACTIVE + actual_start +   |
        |            |   checkin_method=online     |
        |            +----------------------------+
        |                          |
        v                          v
  [Online-to-verify list]   scheduling/jobs.py sweep_no_shows
  per online-duty Checker    (online EXCLUSION removed this phase:
  Session.online_checker     un-verified online no-show -> ABSENT
  opens Session.teams_link    under the shared grace predicate)
```

### Recommended Project Structure
```
verification/
├── models.py            # EXTEND: AssignmentScope field; retire CONFIRMED_ABSENT
├── resolver.py          # NEW  : pure resolve_checker_scan(...) + distribute_online_sessions(...)
├── services.py          # NEW? : thin apply helpers if web/checker.py grows (optional)
├── tests.py             # EXTEND: pure-core tests (SimpleTestCase) + DB-backed tests
└── migrations/
    ├── 0002_assignment_scope.py            # add scope field (default FLOOR)
    ├── 0003_session_online_checker.py      # FK on scheduling.Session (lives in scheduling app)
    └── 0004_retire_confirmed_absent.py     # AlterField choices (state-only on MSSQL)
web/
├── checker.py           # NEW  : checker_required, floor board views, resolve/action/replay endpoints
└── urls.py              # EXTEND: /checker/* routes
templates/checker/
├── floor.html           # full-page board shell (mirrors ifo/live.html)
├── _floor_rows.html     # polled partial (mirrors ifo/_live_rows.html)
├── scan.html            # camera/manual entry (reuse faculty/scan.html shape)
├── _outcome.html        # scan outcome + action buttons (mirrors faculty/_outcome.html)
└── _online_list.html    # per-Checker "online to verify" list
static/checker/
└── offline_queue.js     # vanilla-JS IndexedDB queue + reconnect replay
```

### Pattern 1: Pure Checker decision core (mirror `scheduling/resolver.py`)
**What:** A pure function that takes the Checker's active assignments, the scanned room's floor, the room's current session state, and `now`, and returns a `CheckerResolution` outcome. No ORM, no `timezone.now()`, no writes.
**When to use:** Every checker scan and every offline replay call it — guaranteeing scan-time and replay-time never disagree (the Phase-2 coupling guarantee, applied here).
**Example:**
```python
# verification/resolver.py  (NEW — pattern mirrored from scheduling/resolver.py)
from dataclasses import dataclass, field

OFF_DUTY = "off-duty"            # no active assignment at all
WRONG_FLOOR = "wrong-floor"      # active floor assignment, but not this floor
NO_SESSION = "no-session"        # on duty, room has no active/scheduled session -> confirm/verified empty
ACTIVE_UNVERIFIED = "active-unverified"   # returns session + faculty photo for Verify/Flag
ALREADY_VERIFIED = "already-verified"
ABSENT_EXCLUDED = "absent-excluded"       # session is Absent -> not actionable

ACTIONABLE = {ACTIVE_UNVERIFIED, NO_SESSION}

@dataclass
class CheckerResolution:
    outcome: str
    session_id: int | None = None
    actionable: bool = field(init=False)
    def __post_init__(self):
        self.actionable = self.outcome in ACTIONABLE

def resolve_checker_scan(active_floor_ids, scanned_floor_id, session_state, now, *, grace_min):
    """active_floor_ids: floor pks the checker is on duty for (empty => off duty).
    session_state: a small value object (status, scheduled_start, verified) or None.
    Pure: no ORM, no timezone.now(), returns a CheckerResolution."""
    if not active_floor_ids:
        return CheckerResolution(OFF_DUTY)
    if scanned_floor_id not in active_floor_ids:
        return CheckerResolution(WRONG_FLOOR)
    if session_state is None or session_state.status == "scheduled":
        return CheckerResolution(NO_SESSION)          # room empty -> Confirm/Verified empty
    if session_state.status == "absent":
        return CheckerResolution(ABSENT_EXCLUDED, session_state.id)
    if session_state.verified:
        return CheckerResolution(ALREADY_VERIFIED, session_state.id)
    return CheckerResolution(ACTIVE_UNVERIFIED, session_state.id)
```
*Provenance: structure `[VERIFIED: scheduling/resolver.py]`; outcome set `[ASSUMED]` — exact outcome taxonomy is a planning decision.*

### Pattern 2: Thin apply layer + flags via `notify()` (mirror `web/scan.py._apply`)
**What:** The view fetches context, calls the pure core, then writes `CheckerValidation` + `AuditLog`, and for the two flag actions fires `notify()` to IFO **and** HR immediately (no second confirm).
**When to use:** Every state-changing checker action.
**Example:**
```python
# web/checker.py  (NEW — mirrors web/scan.py._apply + web/scan.py flags)
from accounts.models import Role
from ops.notify import notify
from verification.models import CheckerValidation, ValidationAction

def _apply_action(request, session, room, action, *, note="", identity_match=None,
                  scanned_at=None, offline=False):
    cv = CheckerValidation.objects.create(
        session=session, room=room, checker=request.user, action=action,
        identity_match=identity_match, note=note, scanned_at=scanned_at,
        offline_queued=offline)
    AuditLog.objects.create(actor=request.user, event_type=f"checker.{action}",
                            target_type="session", target_id=str(session.pk if session else ""),
                            payload={"room": room.code, "offline": offline})
    if action == ValidationAction.VERIFIED and session and session.declared_modality_is_online:
        # ONLINE ONLY: Verify is the analog of a faculty check-in -> move out of SCHEDULED
        session.status = SessionStatus.ACTIVE
        session.actual_start = scanned_at or timezone.now()
        session.checkin_method = CheckinMethod.ONLINE_MANUAL
        session.save(update_fields=["status", "actual_start", "checkin_method"])
    if action in (ValidationAction.FLAG_IDENTITY_MISMATCH, ValidationAction.FLAG_NOT_PRESENT):
        # Consequential: reaches IFO + HR permanently, no dispute. Note is mandatory (validated in the view).
        notify(role=Role.IFO_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action} by {request.user.get_full_name() or request.user.username}. {note}")
        notify(role=Role.HR_ADMIN, type="checker_flag", title="Checker flag",
               body=f"{room.code}: {action}. {note}")
    return cv
```
*Provenance: `notify()` signature `[VERIFIED: ops/notify.py]`; AuditLog fields `[VERIFIED: ops/models.py]`; `CheckinMethod.ONLINE_MANUAL` `[VERIFIED: scheduling/models.py:80]`.*

### Pattern 3: Round-robin online pre-assignment (pure distribute + thin apply)
**What:** A deterministic pure function maps a list of online sessions to a rotating list of online-duty Checker ids; a thin apply writes `Session.online_checker` + AuditLog. IFO can override per session.
**When to use:** Default automatic assignment; also reused by Phase 4 when a →Online shift is approved.
**Where to run (recommendation):** A small step invoked (a) when IFO sets/edits the online-duty roster for a date, and (b) as a lightweight daily pass — **not** inside `materialize_sessions`, because online-duty assignments frequently don't exist yet at materialize time (7-day horizon). Assigning lazily when the roster is known avoids re-shuffling. If no online-duty Checker exists for a session's date, leave `online_checker` NULL and surface it to IFO (an unassigned-online flag) rather than guessing.
**Example:**
```python
# verification/resolver.py (pure)
def distribute_online_sessions(session_ids, checker_ids):
    """Deterministic round-robin. Returns {session_id: checker_id}. Pure, no ORM.
    Empty checker_ids -> {} (caller flags these to IFO as unassigned)."""
    if not checker_ids:
        return {}
    return {sid: checker_ids[i % len(checker_ids)] for i, sid in enumerate(session_ids)}
```
*Provenance: `[ASSUMED]` — round-robin vs manual is explicitly Claude's-discretion in CONTEXT; this is the recommended mechanism, to be confirmed at plan/discuss time.*

### Pattern 4: htmx-polled floor board (mirror `ifo.live` / `ifo.live_rows`)
**What:** A full-page shell whose inner div polls a rows partial `hx-trigger="load, every {{ poll_ms }}ms"`; the partial computes coverage %, the oldest-active-first queue, and per-room card state server-side.
**When to use:** CHK-07 board. Poll interval comes from `settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000` (never hardcode — Convention rule #3).
**Example:**
```python
# web/checker.py
@checker_required
def floor_board(request):
    return render(request, "checker/floor.html",
                  {"poll_ms": settings.FLUXTRACK_POLICY["poll_interval_seconds"] * 1000})

@checker_required
def floor_rows(request):
    floor_ids = _active_floor_ids(request.user, timezone.now())   # from active Assignments
    active = (Session.objects.filter(room__floor_id__in=floor_ids, date=timezone.localdate())
              .exclude(status=SessionStatus.ABSENT)               # CHK-07: Absent excluded
              .select_related("room", "schedule", "faculty")
              .order_by("scheduled_start"))                        # oldest-first priority queue
    total = active.count()
    verified = sum(1 for s in active if s.verified_by_checker)
    coverage = round(100 * verified / total) if total else 100
    return render(request, "checker/_floor_rows.html",
                  {"sessions": active, "coverage": coverage, "verified": verified, "total": total})
```
*Provenance: poll pattern `[VERIFIED: web/ifo.py:62-70 + templates/ifo/live.html]`; `verified_by_checker` `[VERIFIED: scheduling/models.py:118-121]`.*

### Pattern 5: IndexedDB offline queue + re-validated replay (CHK-08)
**What:** Client stores each offline scan (`{client_uuid, payload, action, note, identity_match, scanned_at}`) in IndexedDB and shows an "offline / N queued" banner. On reconnect, a batch POST to `/checker/replay` re-runs the **same pure core** against **current** session state per item. Valid → apply with `offline_queued=True` and the original `scanned_at`; stale/contradictory → do **not** apply, record it, and `notify(IFO)`. Idempotent via `client_uuid` (cache/DB dedupe) so a double-replay never double-applies.
**Why re-validate:** "never blindly trusted" — the room may have been handed over, the session already ended or already marked Absent between the offline scan and the replay.
**Example (server):**
```python
@checker_required
@require_http_methods(["POST"])
def replay(request):
    items = json.loads(request.body).get("items", [])
    results = []
    for it in items:
        if _already_applied(it["client_uuid"]):          # idempotency guard (cache/DB)
            results.append({"uuid": it["client_uuid"], "status": "duplicate"}); continue
        room = Room.objects.filter(qr_token=it.get("token")).first()
        session, state = _current_session_state(room, it)  # CURRENT state, not the offline snapshot
        res = R.resolve_checker_scan(_active_floor_ids(request.user, timezone.now()),
                                     room.floor_id if room else None, state,
                                     timezone.now(), grace_min=get_policy("grace_minutes"))
        if res.actionable:
            _apply_action(request, session, room, it["action"], note=it.get("note", ""),
                          identity_match=it.get("identity_match"),
                          scanned_at=parse_dt(it["scanned_at"]), offline=True)
            results.append({"uuid": it["client_uuid"], "status": "applied"})
        else:
            AuditLog.objects.create(actor=request.user, event_type="checker.replay_conflict",
                                    payload={"outcome": res.outcome, **it})
            notify(role=Role.IFO_ADMIN, type="checker_replay_conflict",
                   title="Offline scan needs review",
                   body=f"A queued checker scan no longer applies ({res.outcome}); please resolve.")
            results.append({"uuid": it["client_uuid"], "status": "flagged", "reason": res.outcome})
    return JsonResponse({"results": results})
```
*Provenance: idempotency-key pattern `[VERIFIED: web/scan.py:162-165]`; IndexedDB usage `[CITED: 03-CONTEXT.md]`; MDN IndexedDB API `[CITED: developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API]`.*

### Anti-Patterns to Avoid
- **Putting decision logic in the view.** Off-duty/wrong-floor/room-state logic must live in the pure resolver, not `web/checker.py`. Violates project rule #1 and breaks the scan/replay coupling guarantee.
- **Trusting the offline snapshot on replay.** Applying a queued scan against its *captured* state instead of *current* state is exactly the "blindly trusted" failure CHK-08 forbids.
- **Marking online Absent directly on Flag-not-present without deciding status semantics.** Decide explicitly (see Open Questions) whether Flag-not-present sets `status=ABSENT` or leaves it to the sweep — do not leave it implicit.
- **Hardcoding the poll interval or grace minutes.** Always `get_policy(...)` / `settings.FLUXTRACK_POLICY[...]` (rule #3).
- **A DB `AddConstraint`/`CHECK` for the enum retirement.** TextChoices are app-level only in this codebase; retiring `CONFIRMED_ABSENT` is a state-only `AlterField`, not a DDL constraint.
- **Streaming a queryset with `.iterator()` while mutating rows.** MSSQL single-active-result-set (MARS off) raises HY010; materialize candidate lists first (`list(...)`) before writing — the exact guard already documented in `scheduling/jobs.py:47-52`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Notification fan-out to IFO/HR | Inline `Notification.objects.create` loops | `ops.notify.notify(role=..., users=...)` | Single write path (NOTIF-00); provenance stays centralized `[VERIFIED: ops/notify.py]` |
| No-show / grace decision | A new grace comparison for online | `scheduling.resolver.is_no_show_past_grace` | One shared predicate; scan/sweep/checker must never disagree `[VERIFIED: scheduling/resolver.py:39]` |
| Deferred/confirmed action integrity | Session state or hidden form fields | `django.core.signing` salted token | Proven two-step pattern `[VERIFIED: web/scan.py:27,155-159]` |
| Idempotency / double-tap / double-replay | Custom dedupe tables | Django cache key `user:session:minute` (or `client_uuid`) | Already the codebase idiom `[VERIFIED: web/scan.py:162-165]` |
| Policy values (grace, poll interval) | Constants in code | `get_policy(...)` / `settings.FLUXTRACK_POLICY` | Rule #3 `[VERIFIED: ops/policy.py, CONVENTIONS.md]` |
| Role authorization | Middleware / per-view `if` checks | `checker_required` decorator (mirror `ifo_required`) | Convention rule #5 `[VERIFIED: web/ifo.py:18-25]` |
| Profile photo storage | New field / upload plumbing | `accounts.User.profile_photo` (exists) | Already an ImageField; CHK-02 has no blocking dependency `[VERIFIED: accounts/models.py:35]` |

**Key insight:** This phase's correctness comes almost entirely from *reusing* the four proven seams (pure core, thin apply+audit, `notify()`, signed-token/idempotency). The only genuinely new surface area is the online-duty model extension, the per-session assignment mechanism, and the IndexedDB client — everything else is a faithful copy of shipped, tested code.

## Runtime State Inventory

> Phase 3 is primarily additive (new views, new field, one enum retirement). It touches one migration-sensitive enum and one scheduler behavior. Inventory below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `CheckerValidation.action` rows with value `confirmed_absent`: **none exist** (surface not built; only in enum def + `verification/migrations/0001_initial.py` + docs — verified by grep). `CONFIRMED_EMPTY` vs `VERIFIED_EMPTY` both defined but unused. | State-only `AlterField` migration to drop `CONFIRMED_ABSENT` from choices. Optional defensive data-migration assert that no row uses it. Resolve the empty-action redundancy (see Open Questions). |
| Live service config | None — no external service holds Checker/Assignment state. | None. |
| OS-registered state | The dedicated `runscheduler` process runs `sweep_no_shows`. Removing the online exclusion changes sweep *behavior*, not its registration. | No re-registration; behavior change ships in code + tests. |
| Secrets/env vars | None new. `teams_link` is a plain `URLField` on `Session` (already exists), not a secret. | None. |
| Build artifacts | None — no compiled artifacts; `profile_photo` uploads go to `MEDIA` (`profile_photos/`). | Confirm `MEDIA_ROOT`/`MEDIA_URL` serve in dev so CHK-02 photos render (verify in settings). |

**Migration sensitivity (explicit):** `Assignment` and `CheckerValidation` are already migrated (`verification/migrations/0001_initial.py`). New work = `0002` (add `scope`), a Session FK migration in the `scheduling` app (`online_checker`), and `0003/0004` retiring `CONFIRMED_ABSENT`. All additive/state-only; filtered-unique and FK-on-MSSQL are already proven (Phase 1 `azure_oid`, JOB-02c `RoomConflictFlag`).

## Common Pitfalls

### Pitfall 1: Removing the sweep's online exclusion before the online Verify path exists
**What goes wrong:** If the `if effective_modality == Modality.ONLINE: continue` guard in `sweep_no_shows` (`scheduling/jobs.py:59-61`) is removed before a Checker Verify can flip an online session to ACTIVE, every online session gets marked Absent the moment grace passes — even genuinely-attended ones.
**Why it happens:** Online sessions have no faculty check-in, so nothing else moves them out of SCHEDULED.
**How to avoid:** Ship the online Verify apply (sets `status=ACTIVE` + `actual_start` + `checkin_method=ONLINE_MANUAL`) in the **same wave** that removes the exclusion. Sequence the two as a single atomic behavior change.
**Warning signs:** `test_online_no_show_stays_scheduled_declared` / `test_online_no_show_stays_scheduled_via_schedule` (`scheduling/tests.py:379-391`) start failing — these two tests **must be rewritten** this phase (un-verified online no-show → ABSENT; verified online → ACTIVE and skipped). Flag this to the planner: it is a deliberate, coordinated test change, not a regression.

### Pitfall 2: F2F Verify and online Verify are not symmetric
**What goes wrong:** Treating a Verify uniformly (only flipping the derived flag) leaves online sessions stuck SCHEDULED and the sweep marks them Absent despite verification.
**Why it happens:** For F2F the faculty check-in already set `status=ACTIVE`; the Verify only needs to record the validation (the `verified_by_checker` property derives from it). For online there was no check-in.
**How to avoid:** Branch in `_apply_action` on effective modality: online Verify additionally mutates session status; F2F Verify does not.
**Warning signs:** An online session shows `verified_by_checker=True` but `status=absent` after a sweep tick.

### Pitfall 3: MSSQL mutate-while-iterate (HY010)
**What goes wrong:** Any new loop that reads a queryset with `.iterator()` and writes inside the loop raises "Function sequence error (SQLFetch)" on SQL Server (MARS off).
**Why it happens:** Single active result set per pyodbc connection.
**How to avoid:** Materialize with `list(...)` before mutating — the exact pattern documented in `scheduling/jobs.py:47-52` and regression-tested by `test_batch_of_no_shows_all_marked_absent`. Applies to the replay endpoint's per-item apply loop and any batch assignment write.
**Warning signs:** Passes on SQLite, fails only on MSSQL under batches > 1.

### Pitfall 4: Flag actions submitted without a mandatory note
**What goes wrong:** A flag reaches IFO+HR permanently with no reason (CONTEXT: flags have no dispute/appeal, so a note is mandatory for accountability).
**Why it happens:** One-tap Verify and note-required Flag share the same surface; easy to let a flag through empty.
**How to avoid:** Server-side validation rejects `FLAG_*` actions with an empty note (render an error partial, don't 500 — Convention error-handling pattern). Client-side required-field is UX only, never the gate.
**Warning signs:** `CheckerValidation` flag rows with `note=""`.

### Pitfall 5: Coverage %, priority queue, and cards must all exclude Absent consistently
**What goes wrong:** If Absent sessions are excluded from the card grid but counted in coverage denominator (or vice-versa), coverage % is wrong and the queue shows dead rooms.
**How to avoid:** Apply `.exclude(status=SessionStatus.ABSENT)` once, in the shared queryset that feeds cards, queue, and the coverage denominator.
**Warning signs:** Coverage never reaches 100% on a fully-verified floor.

## Code Examples

Verified patterns from this codebase (authoritative internal sources):

### Effective modality (declared overrides schedule) — reuse verbatim
```python
# Source: scheduling/resolver.py:97 and scheduling/jobs.py:59
effective_modality = session.declared_modality or session.schedule.modality
is_online = effective_modality == Modality.ONLINE
```

### Role decorator (mirror for checker_required)
```python
# Source: web/ifo.py:18-25
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from accounts.models import Role

def checker_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if request.user.role != Role.CHECKER and not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped
```

### Enum retirement migration (state-only on MSSQL)
```python
# verification/migrations/0004_retire_confirmed_absent.py
# AlterField changing choices only — no DDL on MSSQL (choices are app-level).
# Optional forward func asserts no stray rows use the retired value.
def _assert_no_confirmed_absent(apps, schema_editor):
    CV = apps.get_model("verification", "CheckerValidation")
    assert not CV.objects.filter(action="confirmed_absent").exists(), \
        "confirmed_absent rows exist; migrate them before retiring the choice"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Sweep excludes online from Absent (Phase-2 hook) | Sweep includes online once Checker Verify path exists | This phase | Online sessions join JOB-02; two exclusion tests rewritten |
| `CONFIRMED_ABSENT` checker action | Absent is final via the sweep; action retired | This phase (CHK-06 removed) | Enum shrinks; state-only migration |
| Online = faculty self-declared (FAC-07/FAC-08) | Online = Checker-verified via public Teams link | Captured 2026-07-03 | Reconcile with FAC-08 in Phase 7; this phase owns the verify path |
| Faculty scan only surface using the pure-core seam | Checker scan is a second consumer of the same seam shape | This phase | Validates the seam generalizes; no framework change |

**Deprecated/outdated:**
- `ValidationAction.CONFIRMED_ABSENT` — retire this phase; no code emits it, no rows exist (grep-verified).
- The online `continue` guard in `sweep_no_shows` (`scheduling/jobs.py:59-61`) — remove this phase, paired with the online Verify path.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `AssignmentScope` (FLOOR/ONLINE) field is the least-disruptive online-duty extension | Standard Stack / Alternatives | Low — if IFO needs online duty to also be shift/standing-scoped, `type` still applies orthogonally; field stays valid |
| A2 | `Session.online_checker` FK (not a separate model) is sufficient (one owner, no history) | Alternatives | Low-Med — if reassignment history is later required, add an audit-backed model; AuditLog already captures each change |
| A3 | Round-robin at roster-set time (not materialize time), IFO-reassignable, is the assignment mechanism | Pattern 3 | Med — explicitly Claude's-discretion; confirm at discuss/plan. Wrong choice = re-shuffling churn or unassigned sessions |
| A4 | Online Verify sets `status=ACTIVE` + `checkin_method=ONLINE_MANUAL` as the check-in analog | Pattern 2 / Pitfall 2 | High if wrong — this is the linchpin that makes sweep-inclusion safe; must be confirmed |
| A5 | Flag-not-present on an online session drives it to Absent (directly or via sweep) | Open Questions | Med — affects reporting counts; needs an explicit decision |
| A6 | The checker outcome taxonomy (OFF_DUTY/WRONG_FLOOR/NO_SESSION/ACTIVE_UNVERIFIED/...) | Pattern 1 | Low — naming/shape is a planning decision; structure is sound |
| A7 | `CONFIRMED_EMPTY` and `VERIFIED_EMPTY` redundancy resolves to a single canonical empty action | Open Questions | Low-Med — picking the wrong one is a cheap rename, but decide before building the button |
| A8 | Removing the online sweep exclusion requires rewriting the two existing online-exclusion tests | Pitfall 1 | Low — verified those tests exist; the rewrite is expected, not a regression |

## Open Questions

1. **Which empty-confirmation action is canonical — `CONFIRMED_EMPTY` or `VERIFIED_EMPTY`?**
   - What we know: both exist in `ValidationAction` (`verification/models.py:42-43`); CONTEXT calls the action "Confirm/Verified empty" as a single one-tap action; neither is currently emitted by any code.
   - What's unclear: whether the two encode distinct meanings (e.g. "no session scheduled, room empty" vs "session scheduled but legitimately empty") or are accidental duplicates.
   - Recommendation: use `VERIFIED_EMPTY` as the single canonical action (aligns with the `verified_by_checker` naming family) and consider retiring `CONFIRMED_EMPTY` alongside `CONFIRMED_ABSENT`. Confirm at discuss/plan.

2. **Does Flag-not-present set session status, and to what?**
   - What we know: for online, an un-verified session already falls to Absent via the sweep once the exclusion is removed. For F2F, the faculty may already be ACTIVE (checked in) yet the Checker reports nobody present.
   - What's unclear: whether Flag-not-present should force `status=ABSENT` immediately (Checker is authoritative) or only record the flag and let downstream reporting reflect it.
   - Recommendation: online Flag-not-present → set `status=ABSENT` directly (authoritative, avoids waiting a sweep tick); F2F Flag-not-present → record the flag + notify, but do **not** silently override a faculty check-in without an IFO decision. Confirm.

3. **Where exactly does round-robin online assignment run, and what happens when no online-duty Checker exists for a date?**
   - What we know: assignments may not exist at materialize time; Phase 4 also needs to assign a Checker to newly-online sessions.
   - Recommendation: assign when the IFO online-duty roster is set/edited for a date and via a light daily pass; if no online-duty Checker exists, leave `online_checker` NULL and raise an "unassigned online session" flag to IFO rather than guessing. Confirm the trigger points.

4. **Media serving for `profile_photo` in dev.**
   - What we know: the field exists and uploads to `profile_photos/`.
   - What's unclear: whether `MEDIA_URL`/`MEDIA_ROOT` are wired to serve in DEBUG so CHK-02 photos render; seeded demo users likely have no photo.
   - Recommendation: verify media serving; provide a placeholder-avatar fallback in the scan outcome template for users without a photo.

## Environment Availability

> Phase 3 introduces no new external tools or services. It runs on the same stack Phases 1-2 already proved.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQL Server (Express/LocalDB) + ODBC Driver 18 | All DB writes/migrations | ✓ (proven Phase 1) | mssql-django 1.7.3 | — |
| Django | All views/models | ✓ | 6.0.6 | — |
| htmx (CDN) | Floor board polling, action posts | ✓ | 2.0.6 | — |
| Franken UI (CDN) | Card/label styling | ✓ | 2.1.2 | — |
| Pillow | `profile_photo` ImageField | ✓ (already installed) | — | — |
| IndexedDB | Offline queue (CHK-08) | ✓ browser-native | — | Feature-detect; if absent, disable offline queue and require online (degrade, don't crash) |
| Public MS Teams link | Online verification (CHK-02/03) | External (per-session `teams_link`) | — | If `teams_link` empty, surface "no link" to Checker + IFO flag |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** IndexedDB (feature-detect + degrade); missing `teams_link` (flag to IFO).

## Validation Architecture

> `nyquist_validation` is enabled (`.planning/config.json` → `workflow.nyquist_validation: true`). This section drives VALIDATION.md.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django test runner (`unittest`-based); `SimpleTestCase` for pure cores, `TestCase`/`TransactionTestCase` for DB |
| Config file | none — standard `manage.py test`; per-app `tests.py` |
| Quick run command | `py -3.12 manage.py test verification` |
| Full suite command | `py -3.12 manage.py test` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CHK-01 | Off-duty scan refused | unit (pure) | `py -3.12 manage.py test verification.tests.CheckerResolverTests.test_off_duty_refused` | ❌ Wave 0 |
| CHK-01 | Wrong-floor scan refused with reason | unit (pure) | `...test_wrong_floor_refused` | ❌ Wave 0 |
| CHK-01/IFO-06 | Active FLOOR assignment grants powers on that floor | integration (DB) | `...CheckerScanDBTests.test_active_assignment_grants_scan` | ❌ Wave 0 |
| CHK-02 | On-duty scan returns session state + faculty photo | integration (DB) | `...test_scan_returns_session_and_photo` | ❌ Wave 0 |
| CHK-02 | Online session redirects to `teams_link` (no room state) | integration (DB) | `...test_online_scan_redirects_to_teams` | ❌ Wave 0 |
| CHK-03/04 | Verify records validation; `verified_by_checker` true | integration (DB) | `...test_verify_marks_verified` | ❌ Wave 0 |
| CHK-03 | Online Verify sets status ACTIVE + ONLINE_MANUAL | integration (DB) | `...test_online_verify_activates_session` | ❌ Wave 0 |
| CHK-03 | Flag requires a note (empty note rejected) | integration (DB) | `...test_flag_requires_note` | ❌ Wave 0 |
| CHK-05 | Flag fires notify() to IFO **and** HR | integration (DB) | `...test_flag_notifies_ifo_and_hr` | ❌ Wave 0 |
| CHK-03 | `CONFIRMED_ABSENT` retired; no code path emits it | unit + migration | `...test_confirmed_absent_not_in_choices` | ❌ Wave 0 |
| CHK-07 | Coverage % = verified/total active, Absent excluded | integration (DB) | `...FloorBoardTests.test_coverage_excludes_absent` | ❌ Wave 0 |
| CHK-07 | Priority queue ordered oldest-active-first | integration (DB) | `...test_priority_queue_oldest_first` | ❌ Wave 0 |
| CHK-08 | Valid queued scan applies on replay (offline_queued=True, original scanned_at) | integration (DB) | `...ReplayTests.test_valid_replay_applies` | ❌ Wave 0 |
| CHK-08 | Stale queued scan not applied → IFO flag | integration (DB) | `...test_stale_replay_flags_ifo` | ❌ Wave 0 |
| CHK-08 | Replay is idempotent (same client_uuid twice → one apply) | integration (DB) | `...test_replay_idempotent` | ❌ Wave 0 |
| IFO-06 | Round-robin distributes online sessions deterministically | unit (pure) | `...DistributeTests.test_round_robin_even_split` | ❌ Wave 0 |
| IFO-06 | No online-duty Checker → sessions left unassigned + flag | integration (DB) | `...test_no_checker_leaves_unassigned` | ❌ Wave 0 |
| ROADMAP #6 | Un-verified online no-show → ABSENT (sweep exclusion removed) | integration (DB) | `py -3.12 manage.py test scheduling.tests.SweepTests` (REWRITE existing) | ⚠️ exists, must change |
| ROADMAP #6 | Verified online (ACTIVE) skipped by sweep | integration (DB) | `...test_verified_online_not_marked_absent` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `py -3.12 manage.py test verification` (pure cores run fast; no DB for `SimpleTestCase`)
- **Per wave merge:** `py -3.12 manage.py test verification scheduling web`
- **Phase gate:** `py -3.12 manage.py test` green before `/gsd-verify-work` (whole suite, MSSQL).

### Wave 0 Gaps
- [ ] `verification/tests.py` — add `CheckerResolverTests` (SimpleTestCase, no DB) for the pure gating core + `DistributeTests` for round-robin
- [ ] `verification/tests.py` — add `CheckerScanDBTests`, `FloorBoardTests`, `ReplayTests` (DB-backed); reuse the `_JobFixtureMixin`-style unique-key helper pattern from `scheduling/tests.py:292`
- [ ] `scheduling/tests.py` — **rewrite** `test_online_no_show_stays_scheduled_declared` / `..._via_schedule` to assert the new inclusion semantics; add `test_verified_online_not_marked_absent`
- [ ] Fixture helper for a Checker + Assignment (active floor / active online duty) + IFO + HR users
- [ ] Framework install: none (Django test runner already in use)

### Manual-only behaviors (documented, not automated)
- Live offline → reconnect flow in a real browser (Service Worker + IndexedDB timing).
- Camera QR capture on a phone (hardware/camera permission).
- Visual floor board: card colors, coverage bar, mobile-first layout (defer visual detail to `/gsd-ui-phase 3`).
- Opening the public MS Teams link and human identity match against the faculty photo.

## Sources

### Primary (HIGH confidence — internal, authoritative)
- `verification/models.py` — `Assignment`, `CheckerValidation`, `ValidationAction`, `DutyRole`, `AssignmentType` (extend targets)
- `scheduling/models.py` — `Session` (`teams_link`, `verified_by_checker`, `declared_modality`, `room_released_at`), `Modality`, `SessionStatus`, `CheckinMethod.ONLINE_MANUAL`
- `web/scan.py` + `scheduling/resolver.py` — pure-core / thin-apply / signed-two-step / idempotency template
- `scheduling/jobs.py` — `sweep_no_shows` online exclusion (`:59-61`) + MSSQL HY010 guard (`:47-52`)
- `web/ifo.py` + `templates/ifo/live.html` + `_live_rows.html` — htmx-polled live-surface pattern
- `ops/notify.py` — `notify(role=, users=)` single write path
- `accounts/models.py:35` — `profile_photo` ImageField (CHK-02 dependency satisfied)
- `.planning/codebase/CONVENTIONS.md` — the six project rules (pure resolver, AuditLog, get_policy, ASCII commands, role decorators, signed two-step)
- `scheduling/tests.py` — existing sweep/resolver test patterns + the online-exclusion tests to rewrite

### Secondary (MEDIUM confidence)
- `.planning/phases/03-duty-assignments-checker-verification/03-CONTEXT.md` — locked decisions and discretion areas
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` — IFO-06, CHK-01..08, ROADMAP criterion #6
- MDN IndexedDB API — offline queue reference `[CITED: developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API]`

### Tertiary (LOW confidence)
- None — this phase required no external/community research; all findings trace to the codebase or locked context.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all versions verified from `requirements.txt` and `base.html`.
- Architecture: HIGH — every pattern mirrors shipped, tested code; the one novel decision (online status flip) is clearly specified and flagged as the linchpin (A4).
- Pitfalls: HIGH — derived directly from existing code guards (HY010) and the explicit sweep/online coupling.
- Assignment mechanism (round-robin placement): MEDIUM — Claude's-discretion per CONTEXT; recommended, to be confirmed at discuss/plan (A3).

**Research date:** 2026-07-03
**Valid until:** 2026-08-03 (stable — internal codebase patterns; revisit only if the Faculty scan seam or `notify()` signature changes)

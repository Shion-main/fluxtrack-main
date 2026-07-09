# Phase 5: Notifications — Read Surface & Web Push - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the events `notify()` already writes to the `Notification` table **visible to
every role**: a polled in-app list (bell + unread badge + dropdown, plus a
full-page history), VAPID web push for a fixed set of key events, and per-user
mute preferences — with push delivery fully **fault-isolated** so a failed or
dead push endpoint never breaks the scan, approval, or job that triggered it.

Scope is the READ/DELIVERY surface only. The write path (`notify()`) already
exists from Phase 2 (NOTIF-00). No new event sources are added here.
</domain>

<decisions>
## Implementation Decisions

### Notification surface (NOTIF-01)
- **D-01:** **Both** a bell and a page. A bell icon with an unread-count badge in
  each role's top bar opens a polled dropdown of the latest few notifications; a
  "See all" link opens a dedicated full-page `/notifications` list with the full
  history. The bell must render in **both shells** — the faculty navy `ft-top`
  bar and the Franken header used by all other roles.
- **D-02:** The in-app list + badge poll via the **existing htmx pattern** already
  used by the checker floor board and IFO live view
  (`hx-get=... hx-trigger="load, every {{ poll_ms }}ms" hx-swap="innerHTML"`).
  Badge = unread count (rows with `read_at IS NULL`).

### Read / retention
- **D-03:** **Auto-mark-read on view** — opening the dropdown/page sets `read_at`
  on the shown rows and clears the badge. **Keep all** notifications indefinitely;
  no auto-expiry this phase (deferred).

### Mute preferences (NOTIF-03)
- **D-04:** Mute **by category group**, not per individual type. Three groups,
  mapped from the real `notify()` `type` values in use:
  - **Room events** — wrong-room / room change, force handover, room conflict
  - **Reports** — weekly report ready
  - **System** — job failures, admin/system notices
- **D-05:** A muted category is suppressed from **BOTH** the in-app list and web
  push (NOTIF-03 wording). Needs a **new per-user preference model** keyed by
  category group; default = everything unmuted.
- **D-06:** The category→type mapping is a **single source of truth** (one helper/
  table) consumed by both the list filter and the push filter, so the two can
  never disagree — mirroring the `notify()` single-write-path discipline.

### Web push (NOTIF-02)
- **D-07:** **Soft pre-prompt on first visit.** Show a dismissible in-app banner
  ("Turn on notifications?" → Enable / Not now). The real browser permission
  prompt fires **only** when the user taps Enable, so a "Not now" or an ignored
  banner never permanently blocks the origin, and it stays re-askable from the
  notifications surface. (Chosen over a raw auto-prompt specifically to avoid a
  stray "Block" permanently killing push — a real capstone-demo hazard.)
- **D-08:** Push fires for the roadmap's **key events only**: wrong-room, force
  handover, room conflict, weekly-report-ready. Recipients are the **same set**
  `notify()` targets for that event (role/user-scoped) — respecting mute (D-05).
- **D-09:** Push delivery is **fault-isolated** (NOTIF-02 criterion #4): the send
  runs **after commit / outside the triggering DB transaction**; a dead endpoint
  (410/404) is caught and its `PushSubscription` pruned; no push failure ever
  breaks or rolls back the scan/approval/job that emitted the `notify()`.

### Claude's Discretion
- Exact poll interval — reuse the value/policy the checker/IFO surfaces already use.
- Bell/badge visual styling within each shell.
- Whether push send + subscription-pruning runs inline post-commit vs handed to
  the dedicated APScheduler process (leaning async so it can't block the request)
  — planner/researcher to decide.
- VAPID signing library choice (`pywebpush` vs `py-vapid` + `cryptography`) —
  research item; `cryptography>=42.0` is already a dependency.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 5: Notifications — Read Surface & Web Push" — goal + the 4 success criteria (polled list, VAPID push for key events, mute suppresses both, push fault-isolation).
- `.planning/REQUIREMENTS.md` — NOTIF-01, NOTIF-02, NOTIF-03 (and NOTIF-00 for the write-path context this consumes).

### Existing code the phase builds on
- `ops/notify.py` — the single `notify()` write path (recipients = explicit `users` + all active users of `role`). The read surface consumes its rows; the push filter reuses its recipient set.
- `ops/models.py` — `Notification` (`type`, `title`, `body`, `link`, `read_at`, `created_at`) and `PushSubscription` (`endpoint`, `keys` JSON, `user`). Both already migrated.
- `web/views.py` — `service_worker` view (`SW_JS`) served at `/sw.js`: add `push` + `notificationclick` handlers here, and bump the `CACHE` version when the SW changes.
- `templates/checker/floor.html`, `templates/ifo/live.html` — the reference htmx polling pattern (`poll_ms`).
- `templates/base.html` — the two shells (faculty navy `ft-top` vs Franken header) where the bell must appear.

No external ADR/spec beyond the above — requirements are fully captured in the decisions here.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`notify()` (`ops/notify.py`)** — single write path; the list reads its rows and the push filter reuses its role/user recipient resolution. Do not add a second create path.
- **`Notification` model** — `read_at` already supports read/unread (auto-read sets it); `link` deep-links a notification to its target surface.
- **`PushSubscription` model** — `endpoint` + `keys` JSON already scaffolded for VAPID storage; **no new subscription model needed**, only subscribe/unsubscribe endpoints and pruning.
- **htmx polling pattern** — `hx-get + hx-trigger="load, every {{ poll_ms }}ms" hx-swap="innerHTML"` (checker floor, IFO live) drives the polled list + badge.
- **`cryptography>=42.0`** already in `requirements` — the VAPID signing base is present; only a signing helper/lib is missing.

### Established Patterns
- **Single-write-path discipline** (`notify()`) — mirror it for the category→type map (D-06).
- **Two shells** — faculty navy `ft-top` (from the just-shipped redesign) vs Franken header; the bell renders in both.
- **`notify()` deliberately does NOT `AuditLog`** — the read/push surface must not add audit noise either.
- **One scheduler process (APScheduler)** — if push send or subscription pruning runs as a job, it lives there, never in web workers. Management/job output stays ASCII-only (Windows cp1252).

### Integration Points
- **New per-user mute-preference model** (category-group keyed) — likely in `ops` alongside `Notification`.
- **New routes:** polled list partial (rows), full-page `/notifications`, mark-read, push subscribe/unsubscribe, and a VAPID public-key endpoint for the client.
- **Service worker:** `push` + `notificationclick` handlers added to `SW_JS` in `web/views.py`.
- **Push triggers:** the existing `notify()` call sites (`web/scan.py` wrong-room/force-handover, the sweep's room-conflict flag, the weekly-report job) gain a **post-commit** push hook — not inline — to preserve D-09 fault isolation.
</code_context>

<specifics>
## Specific Ideas

- The **soft pre-prompt** ("Enable / Not now") was chosen explicitly over a raw
  browser prompt to avoid a permanent origin-block — flagged as a demo-reliability
  requirement, not just a nicety.
</specifics>

<deferred>
## Deferred Ideas

- **Per-event-type granular mute** (finer than the three category groups) — future
  enhancement if the coarse groups prove too blunt.
- **Notification auto-expiry / pruning window** — keep-all this phase; revisit if
  the table grows unwieldy (would ride the existing scheduler).
- **Real-time delivery (SSE / WebSocket)** — out of scope; polling per the roadmap.

None of these block Phase 5.
</deferred>

---

*Phase: 5-notifications-read-surface-web-push*
*Context gathered: 2026-07-09*

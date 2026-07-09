# Phase 5: Notifications — Read Surface & Web Push - Research

**Researched:** 2026-07-09
**Domain:** Django server-rendered read surface (htmx polling) + W3C Web Push (VAPID) in a PWA
**Confidence:** HIGH (stack, patterns, code all verified against this repo and current PyPI)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Both a bell (unread-count badge + polled dropdown of latest few) in each role's top bar AND a dedicated full-page `/notifications` history. The bell renders in **both shells** — the faculty navy `ft-top` bar and the Franken header used by all other roles.
- **D-02:** In-app list + badge poll via the **existing htmx pattern** (`hx-get=... hx-trigger="load, every {{ poll_ms }}ms" hx-swap="innerHTML"`, as used by checker floor + IFO live). Badge = unread count (`read_at IS NULL`).
- **D-03:** **Auto-mark-read on view** — opening the dropdown/page sets `read_at` on shown rows and clears the badge. **Keep all** notifications indefinitely; no auto-expiry this phase.
- **D-04:** Mute **by category group**, not per type. Three groups mapped from real `notify()` type values: **Room events** (wrong-room/room change, force handover, room conflict), **Reports** (weekly report ready), **System** (job failures, admin/system notices).
- **D-05:** A muted category is suppressed from **BOTH** the in-app list and web push. New per-user preference model keyed by category group; **default = everything unmuted**.
- **D-06:** The category→type mapping is a **single source of truth** (one helper/table) consumed by both the list filter and the push filter — mirroring the `notify()` single-write-path discipline.
- **D-07:** **Soft pre-prompt on first visit** — a dismissible in-app banner ("Turn on notifications?" → Enable / Not now). The real browser permission prompt fires **only** on Enable, so "Not now"/ignore never permanently blocks the origin; stays re-askable from the notifications surface.
- **D-08:** Push fires for **key events only**: wrong-room, force handover, room conflict, weekly-report-ready. Recipients = the **same set** `notify()` targets for that event, respecting mute (D-05).
- **D-09:** Push delivery is **fault-isolated** — send runs **after commit / outside the triggering DB transaction**; a dead endpoint (410/404) is caught and its `PushSubscription` pruned; no push failure ever breaks/rolls back the scan/approval/job that emitted the `notify()`.

### Claude's Discretion
- Exact poll interval — reuse the checker/IFO value/policy (`poll_interval_seconds`).
- Bell/badge visual styling within each shell.
- Whether push send + subscription-pruning runs **inline post-commit** vs handed to the **dedicated APScheduler process** (leaning async so it can't block the request) — decided in this research (see Q4).
- VAPID signing library choice (`pywebpush` vs `py-vapid` + `cryptography`) — decided in this research (see Q1).

### Deferred Ideas (OUT OF SCOPE)
- Per-event-type granular mute (finer than the three groups).
- Notification auto-expiry / pruning window (keep-all this phase).
- Real-time delivery (SSE / WebSocket) — polling per the roadmap.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NOTIF-01 | Polled in-app notification list (bell + badge + dropdown, full-page history) visible to every role | Q5 — reuses the exact `hx-trigger="load, every {{ poll_ms }}ms"` pattern; bell partial mounted in both shells; unread-count query; auto-mark-read-on-open (D-03) |
| NOTIF-02 | VAPID web push for key events, with soft pre-prompt | Q1 (library `pywebpush`), Q2 (SW `push`/`notificationclick` handlers), Q3 (subscribe flow + soft pre-prompt) |
| NOTIF-03 | Per-user mute suppresses BOTH list and push | Q6 — single category→type map consumed by both filters; `NotificationMute` model; default-unmuted |
| Success criterion #4 | A failed push to a dead endpoint never breaks the scan/approval/job that triggered it | Q4 — outbox polled by the existing scheduler (web request does zero push network I/O); 410/404 pruning; broad `except` |
</phase_requirements>

## Summary

This phase is a **read/delivery surface only** — the write path (`notify()`) already fans out `Notification` rows and is untouched. Two independent capabilities: (1) a **polled in-app list** built entirely from the established htmx polling idiom already shipped on the checker floor and IFO live views, and (2) **VAPID web push**, which is the only genuinely new technical surface.

For web push, the standard, current, minimal-risk choice is **`pywebpush` 2.3.0** [VERIFIED: PyPI], which layers on top of `py-vapid` + `http-ece` + `cryptography` — and `cryptography` (48.0 installed, `>=42` pinned) is already a dependency, so there is **no native-build gotcha on Windows** (all three added packages are pure-Python; `cryptography` ships wheels). The service worker (`SW_JS` string in `web/views.py`) gains a `push` and a `notificationclick` handler and a `CACHE` version bump. The browser subscribes via `PushManager.subscribe({userVisibleOnly:true, applicationServerKey})`, gated behind the soft in-app pre-prompt so a stray "Block" never permanently kills the origin.

**Fault isolation (criterion #4)** is best served by a **DB-backed outbox polled by the existing single `BlockingScheduler` process** rather than sending inline in the web worker: the scan/approval request then does *zero* network I/O, so a hung or dead push endpoint is structurally incapable of touching it. This also unifies web-originated events (scan) and scheduler-originated events (weekly report) through one sender, and keeps all 410/404 pruning in the scheduler process — exactly matching the project's "all scheduled work in one process, never in web workers" rule.

**Primary recommendation:** Add `pywebpush>=2.3,<3`; add `push`/`notificationclick` to `SW_JS` and bump `CACHE` to `v5`; store VAPID keys as a gitignored `private_key.pem` file + `.env` public key + `mailto:` sub; build the polled bell/list on the existing htmx pattern with a context processor supplying `poll_ms`; add a `NotificationMute` model + a single `CATEGORY_TYPES` map helper consumed by both list and push filters; and send push from a `push_outbox` job on the existing scheduler, pruning dead subscriptions there.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Polled unread list + badge | API / Backend (Django views) | Browser (htmx poll) | Server owns the query + auth; htmx just re-fetches a partial on an interval |
| Auto-mark-read on open | API / Backend | — | A DB write (`read_at`); must be server-side, gated to the *open* action not the poll |
| Mute preferences + category→type map | API / Backend | — | Single source of truth in Python/DB; both filters must import the same helper |
| Push subscription persistence | API / Backend (`PushSubscription`) | Browser (`PushManager`) | Browser produces the endpoint+keys; server stores/prunes them |
| Service-worker push display | Browser / Client (service worker) | — | `showNotification` + click routing can only run in the SW |
| Push send + dead-endpoint pruning | **Scheduler process** (APScheduler) | — | Fault isolation (criterion #4) + "all scheduled/background work in one process" rule |
| Soft permission pre-prompt | Browser / Client | API (subscribe endpoint) | Permission is a browser-only capability; the banner just gates when it fires |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pywebpush` | 2.3.0 | Sign + POST an encrypted Web Push message to a subscription endpoint | Maintained by **web-push-libs** (the canonical org for reference web-push tooling); wraps VAPID signing + RFC 8291 payload encryption so you never hand-roll ECDH/HKDF [VERIFIED: PyPI + github.com/web-push-libs/pywebpush] |
| `py-vapid` | 1.9.4 (transitive of pywebpush) | Generate VAPID keypair + the browser `applicationServerKey`; sign the JWT `Authorization` header | Mozilla-services reference VAPID implementation; provides the `vapid` CLI for key generation [VERIFIED: PyPI + github.com/mozilla-services/vapid] |
| `http-ece` | 1.2.1 (transitive of pywebpush) | RFC 8188/8291 encrypted-content-encoding of the push payload | Pulled automatically by pywebpush; never called directly [VERIFIED: PyPI] |
| `cryptography` | 48.0 installed (`>=42.0` pinned) | ECDH P-256 + HKDF primitives under py-vapid/http-ece | **Already a dependency** — the VAPID base is present; only the wrapper is missing [VERIFIED: repo requirements.txt + `import cryptography` → 48.0.0] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `APScheduler` | 3.10–3.x (`>=3.10,<4` pinned) | Runs the `push_outbox` sender job in the existing dedicated process | Already installed + wired in `scheduling/management/commands/runscheduler.py`; add one job |
| `django.db.transaction.on_commit` | Django 6.0.6 | (Alternative sender) fire the outbox only after the triggering txn commits | Only if the planner chooses the inline-post-commit alternative over the scheduler |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pywebpush` (send + encrypt in one call) | `py-vapid` + `http-ece` + manual `requests.post` | More control, but you re-implement pywebpush's exact call for no benefit; pywebpush already depends on both. Not worth hand-rolling. |
| Outbox polled by scheduler (Q4 primary) | Inline `transaction.on_commit(send)` in the web worker | Simpler (no new job/field) but the web process then does a synchronous HTTPS round-trip per endpoint — blocks the response and reintroduces the exact hang risk criterion #4 forbids. Acceptable only with a hard `requests` timeout + broad `except`. |
| DB-backed outbox | Redis/Celery queue | Overkill — no Redis in this stack (locmem cache only, per Conventions §7); adds infra for a capstone. |

**Installation:**
```bash
pip install "pywebpush>=2.3,<3"     # pulls py-vapid, http-ece; cryptography already present
```
Add to `requirements.txt` under a new `# Web push (NOTIF-02)` heading:
```
pywebpush>=2.3,<3    # VAPID web push; pulls py-vapid + http-ece, uses existing cryptography
```

**Version verification (done this session):**
- `pip index versions pywebpush` → **2.3.0** latest (published 2026-02-09) [VERIFIED: PyPI]
- `pip index versions py-vapid` → **1.9.4** latest [VERIFIED: PyPI]
- `pip index versions http-ece` → **1.2.1** latest [VERIFIED: PyPI]
- installed `cryptography.__version__` → **48.0.0** (satisfies both `requirements.txt >=42` and pywebpush) [VERIFIED: local import]
- `py -3.12 --version` → **Python 3.12.10**; `Django==6.0.6` pinned [VERIFIED: repo]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `pywebpush` | PyPI | mature (2.3.0 pub. 2026-02-09) | unknown to tool | github.com/web-push-libs/pywebpush | SUS (unknown-downloads only) | Approved — see note |
| `py-vapid` | PyPI | mature (1.9.4) | unknown to tool | github.com/mozilla-services/vapid | SUS (unknown-downloads only) | Approved — transitive of pywebpush |
| `http-ece` | PyPI | mature (1.2.1, pub. 2024-08-08) | unknown to tool | github.com/web-push-libs/encrypted-content-encoding | SUS (unknown-downloads only) | Approved — transitive of pywebpush |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** all three, but **only** for `unknown-downloads` — a PyPI-API blind spot in the legitimacy tool (PyPI does not expose weekly download counts), **not** a risk signal. All three resolve to authoritative, long-lived repos under **web-push-libs** and **mozilla-services** (the reference orgs for the Web Push ecosystem), have no postinstall scripts, and are not deprecated. These are the canonical implementations. **Recommendation to planner:** treat as `OK`; a `checkpoint:human-verify` before the single `pip install "pywebpush>=2.3,<3"` is optional and low-value given the authoritative repos, but harmless if the workflow mandates one for any SUS verdict.

## Architecture Patterns

### System Architecture Diagram

```
WRITE PATH (already exists — untouched)
  scan / approval / scheduler job ──> notify(type=..., role/users=...) ──> Notification rows (fan-out, 1/recipient)

READ SURFACE (this phase)
  every page  ──(context processor injects poll_ms + initial unread)──> base.html / ft-top : <bell partial>
                                                                             │
        htmx poll (load, every poll_ms) ──GET /notifications/bell──────────> badge count + preview rows
                                                                             │  (READ-ONLY: never marks read)
        user opens dropdown ──GET /notifications/dropdown──> mark shown rows read_at=now ──> rendered rows
        "See all" ──GET /notifications──> full-page list ──> mark shown rows read_at=now
                                                                             │
                       both queries filter out muted categories ──> muted_types(user)  ◄── CATEGORY_TYPES (single map)

PUSH PATH (this phase)
  first visit ──> soft banner (Notification.permission==='default')
      Enable ──> Notification.requestPermission() ──granted──> PushManager.subscribe({userVisibleOnly, applicationServerKey})
                                                                    │
                          POST /notifications/push/subscribe ──> PushSubscription(endpoint, keys)  [dedup on endpoint]

  DELIVERY (fault-isolated):
      Notification rows (type ∈ PUSH_TYPES, pushed_at NULL, recent)
                    │
      scheduler process: push_outbox job (every N s) ──filter muted──> pywebpush.webpush(sub, payload, vapid_*)
                    │                                                        │
              stamp pushed_at=now                              200/201 ok │ 404/410 ──> delete PushSubscription
                    │                                                        │ other  ──> log, leave for retry/skip
      push endpoint (FCM/Mozilla/Apple) ──> device SW 'push' event ──> showNotification(title, body, data.link)
                                                            └─ notificationclick ──> focus/open data.link
```
*The web request that emits `notify()` never appears in the push path — it only writes rows. That structural separation is what makes criterion #4 hold.*

### Recommended Project Structure
```
web/
├── notifications.py          # NEW — one module per surface (Conventions): all /notifications/* views
templates/notifications/
├── list.html                 # NEW — full-page /notifications history
├── _bell.html                # NEW — badge + dropdown shell, hx-trigger poll (included in BOTH shells)
├── _rows.html                # NEW — dropdown/list row partial (shared render)
├── settings.html             # NEW — mute-category toggles
ops/
├── models.py                 # EDIT — add NotificationMute; add pushed_at to Notification
├── notifications.py          # NEW — CATEGORY_TYPES map + muted_types()/push_types() helpers (single source of truth, D-06)
├── push.py                   # NEW — send_push_outbox() called by the scheduler; VAPID config load; pruning
web/views.py                  # EDIT — SW_JS: add push + notificationclick; bump CACHE v4 -> v5
web/urls.py                   # EDIT — wire /notifications/* routes
config/settings.py            # EDIT — VAPID_* config; add 'notifications' context processor
scheduling/management/commands/runscheduler.py  # EDIT — register push_outbox job
static/js/push.js             # NEW — subscribe flow + soft pre-prompt + urlBase64ToUint8Array
```

### Pattern 1: Polled bell partial (reuse the shipped idiom)
**What:** The exact pattern already in `templates/ifo/live.html:13`.
**When to use:** The bell badge + dropdown preview, on every page.
**Example:**
```html
<!-- templates/notifications/_bell.html — included in the Franken header AND the faculty ft-top -->
<div class="ft-bell" hx-get="/notifications/bell" hx-trigger="load, every {{ poll_ms }}ms" hx-swap="innerHTML">
  {% include "notifications/_bell_inner.html" %}   {# initial render from context processor #}
</div>
```
`poll_ms` must be present in context on **every** page (the bell is global), so supply it via a context processor rather than per-view (see Pitfall 4).

### Pattern 2: Service-worker push + click handlers (append to `SW_JS`)
**What:** Add to the `SW_JS` raw string in `web/views.py`; bump `CACHE`.
```javascript
// Source: MDN Push API / Notifications API (developer.mozilla.org) — appended to SW_JS
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: 'FluxTrack', body: e.data ? e.data.text() : '' }; }
  const title = d.title || 'FluxTrack';
  const opts = {
    body: d.body || '',
    icon: '/icon-192.png',
    badge: '/icon-192.png',
    data: { link: d.link || '/notifications' },
    tag: d.tag || undefined,     // collapse duplicate alerts if provided
  };
  // iOS requires a notification to be shown for EVERY push, or it revokes the subscription.
  e.waitUntil(self.registration.showNotification(title, opts));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const link = (e.notification.data && e.notification.data.link) || '/notifications';
  e.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
      for (const w of wins) { if (w.url.includes(link) && 'focus' in w) return w.focus(); }
      if (clients.openWindow) return clients.openWindow(link);   // deep-link via the notification's link
    })
  );
});
```
Then change line 125 `const CACHE = 'fluxtrack-shell-v4';` → `'fluxtrack-shell-v5';`. The existing `activate` handler already purges non-current caches and calls `self.clients.claim()`, and `install` calls `self.skipWaiting()` — so the new handlers activate on next load with no extra wiring. **The push subscription survives SW version changes** (it lives on `pushManager`, independent of `CACHE`), so bumping the cache does not force re-subscription.

### Pattern 3: Subscribe flow + soft pre-prompt (client JS)
```javascript
// static/js/push.js
function urlBase64ToUint8Array(b64) {
  const pad = '='.repeat((4 - b64.length % 4) % 4);
  const s = (b64 + pad).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(s); const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function currentState() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return 'unsupported';
  const perm = Notification.permission;            // 'default' | 'granted' | 'denied'
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (perm === 'granted' && sub) return 'subscribed';
  return perm;                                      // drives banner visibility (see below)
}

async function enablePush(vapidPublicKey, csrftoken) {
  const perm = await Notification.requestPermission();   // fires ONLY from the Enable click (D-07)
  if (perm !== 'granted') return perm;                   // 'denied' -> show re-enable instructions
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,                               // REQUIRED (Chrome throws otherwise; iOS requires it)
    applicationServerKey: urlBase64ToUint8Array(vapidPublicKey),
  });
  await fetch('/notifications/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrftoken },
    body: JSON.stringify(sub),                           // sub.toJSON() -> {endpoint, keys:{p256dh, auth}}
  });
  return 'subscribed';
}
```
**Banner logic (D-07):** show the "Turn on notifications?" banner only when `currentState()` returns `'default'` (never asked) AND the user hasn't dismissed it this session (store a `localStorage` "not-now" flag). If `'granted'` but no subscription (e.g. subscription expired), silently re-subscribe. If `'denied'`, hide the banner and instead show a passive "notifications are blocked — re-enable in browser settings" note on the `/notifications/settings` surface (you cannot re-prompt a denied origin). The banner stays re-askable from `/notifications/settings` regardless.

### Pattern 4: pywebpush send call (the exact shape)
```python
# ops/push.py — Source: github.com/web-push-libs/pywebpush README
import json
from pywebpush import webpush, WebPushException
from django.conf import settings

def _send_one(sub, payload: dict):
    """Send to ONE PushSubscription. Returns True if delivered, False if the
    endpoint is dead (404/410) and the row should be pruned. Never raises for
    a failed send (criterion #4)."""
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
            data=json.dumps(payload),                       # {title, body, link}
            vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,   # path to private_key.pem
            vapid_claims={"sub": settings.VAPID_SUB},            # e.g. "mailto:ifo@mmcm.edu.ph"
            ttl=600,
            timeout=10,                                     # hard cap — never hang the job
        )
        return True
    except WebPushException as exc:
        code = exc.response.status_code if exc.response is not None else None
        if code in (404, 410):                             # Gone / Not Found -> prune (D-09)
            return False
        return True   # transient (429/5xx/network): don't prune; treat as handled this pass
```
`pywebpush` auto-derives the `aud` claim from the endpoint origin; you only supply `sub`. `vapid_private_key` accepts **either** a path to `private_key.pem` **or** the raw base64-url DER string — the file path avoids `.env` newline pain (see Q1 storage).

### Anti-Patterns to Avoid
- **Sending push inside the request/transaction that emitted `notify()`.** A dead or slow endpoint would block the scan response or (if it raised pre-commit) roll back the action — the exact failure criterion #4 forbids.
- **Marking rows read on the *poll*.** The badge would clear instantly and unread state would never be visible. Mark read only on the explicit *open* action (D-03).
- **Adding an `AuditLog` row for mark-read or push-send.** CONTEXT + `notify()`'s own comment establish the notification surface stays audit-silent. This is a *deliberate* exception to project rule #2 — do not "fix" it.
- **Precaching `/notifications` or `/` in the SW.** The existing SW comment already forbids caching redirect-prone navigations; keep it that way.
- **Muting an unmapped type by accident.** Types absent from `CATEGORY_TYPES` must be treated as *never muted* (always shown) — see Q6 + Open Questions.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Push payload encryption (RFC 8291) | ECDH P-256 + HKDF + AES-GCM by hand | `pywebpush` (wraps `http-ece`) | Getting the salt/keyid/record-size framing wrong yields silent non-delivery; this is a cryptographic footgun |
| VAPID JWT signing + `applicationServerKey` derivation | ES256 JWT + EC point encoding by hand | `py-vapid` (`vapid` CLI + `Vapid` class) | Point-encoding / base64url mistakes break every browser subscribe |
| Real-time delivery | SSE/WebSocket channel layer | The existing htmx poll (`poll_ms`) | Roadmap chose polling; the pattern already ships and needs no new infra |
| Background job runner | New thread pool / Celery / Redis | The existing single `BlockingScheduler` (`runscheduler`) | One-process rule already established; adding a queue is unjustified infra |
| Base64url ↔ bytes for the client key | Custom decoder variants | The canonical `urlBase64ToUint8Array` (Pattern 3) | Everyone uses this exact 8-line function; MDN reference |

**Key insight:** the only novel, error-prone work here is Web Push cryptography — and it is *entirely* absorbed by `pywebpush`. Everything else (list, badge, mute, poll) is a re-application of patterns already proven in this codebase.

## Runtime State Inventory

> This phase adds two DB columns/models and one new external subscription store. It is additive, not a rename, but the push-key material is genuine new runtime state worth inventorying.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `PushSubscription` rows (endpoint + keys JSON) accumulate per device; dead ones must be pruned on 404/410. New `Notification.pushed_at` column; new `NotificationMute` rows. | Migration for `pushed_at` + `NotificationMute`; pruning logic in `ops/push.py` (D-09) |
| Live service config | Push endpoints live at the browser vendors (FCM/Mozilla/Apple) — you cannot enumerate them; the only server-side record is `PushSubscription`. | None beyond pruning; nothing in a UI to export |
| OS-registered state | None — no Task Scheduler/pm2/systemd changes. The scheduler already runs as one unit; you add a *job*, not a process. | None — verified: `runscheduler.py` owns all jobs in one process |
| Secrets/env vars | **NEW:** `VAPID_PRIVATE_KEY_PATH` (points to gitignored `private_key.pem`), `VAPID_PUBLIC_KEY` (application server key, base64url), `VAPID_SUB` (`mailto:`). | Generate once via `vapid --gen`; add to `.env` (public key + sub) + a gitignored PEM file; document in `.env.example` |
| Build artifacts / installed packages | `pywebpush` (+ `py-vapid`, `http-ece`) newly installed; no compiled artifacts (all pure-Python; `cryptography` wheel already present). | `pip install`; add pin to `requirements.txt` |

## Common Pitfalls

### Pitfall 1: Push send blocking or breaking the triggering request
**What goes wrong:** Sending inline means a slow/dead endpoint stalls the scan response or a raised exception 500s the user after their action.
**Why it happens:** Web Push is a synchronous HTTPS POST per endpoint; endpoints can hang or return 410.
**How to avoid:** Send from the `push_outbox` scheduler job (primary, Q4) so the web request never touches the network; if inline is chosen instead, use `transaction.on_commit` + `timeout=10` + a broad `except` that never re-raises. Prune on 404/410 only.
**Warning signs:** Scan/approval latency rising with recipient count; 500s correlated with push.

### Pitfall 2: iOS silently revokes the subscription
**What goes wrong:** A push arrives but no notification is shown → iOS Safari drops the subscription.
**Why it happens:** iOS enforces `userVisibleOnly` strictly — every push **must** call `showNotification`.
**How to avoid:** The `push` handler always calls `showNotification` (never a "silent" push). Also: iOS Web Push works **only** for a PWA added to the Home Screen on iOS/iPadOS **16.4+**, not in the Safari tab [VERIFIED: MDN/Apple, WebSearch 2026]. Demo push on desktop Chrome/Edge; treat iOS as install-gated.
**Warning signs:** iOS subscriptions vanishing after the first push.

### Pitfall 3: SW change shipped without a CACHE bump
**What goes wrong:** Browsers keep the old `SW_JS` (no push handler) because byte-identical caches persist.
**Why it happens:** SW update is byte-diff based; the `activate` purge only runs when `CACHE` changes.
**How to avoid:** Bump `CACHE` `v4 → v5` in the same commit that adds the handlers. `skipWaiting` + `clients.claim` already present will then activate it on next load.
**Warning signs:** Push logs show delivery but no notification appears on already-open clients.

### Pitfall 4: `poll_ms` / VAPID key missing on some pages
**What goes wrong:** The bell is global (both shells) but `poll_ms` (and the public VAPID key for the banner) are only passed by some views → `hx-trigger="every ms"` renders broken, or the banner has no key.
**Why it happens:** Per-view context can't cover a globally-rendered component.
**How to avoid:** Add a **context processor** `web.context.notifications(request)` returning `poll_ms` (`FLUXTRACK_POLICY["poll_interval_seconds"] * 1000`, via `get_policy`), the initial unread count, and `VAPID_PUBLIC_KEY`. Register it in `TEMPLATES['OPTIONS']['context_processors']`.
**Warning signs:** Bell works on IFO pages but not faculty pages.

### Pitfall 5: CSRF on the JSON subscribe POST
**What goes wrong:** `/notifications/push/subscribe` 403s because the raw `fetch()` (not htmx) omits the CSRF token.
**Why it happens:** `base.html` sets `X-CSRFToken` via htmx `hx-headers`, but the subscribe call is plain `fetch`.
**How to avoid:** Pass the token explicitly in the `fetch` headers (Pattern 3 shows `X-CSRFToken`), sourced from `{{ csrf_token }}` rendered into `push.js`'s caller or read from the cookie.
**Warning signs:** 403 on subscribe only.

### Pitfall 6: Duplicate `PushSubscription` rows per device
**What goes wrong:** Re-subscribing (or subscribing on multiple visits) creates duplicate endpoint rows → duplicate pushes.
**Why it happens:** No uniqueness on `endpoint`.
**How to avoid:** `update_or_create` keyed on `endpoint` (and store `user`); optionally add `unique=True` on `endpoint` or a `unique_together=(user, endpoint)`. Prune stale rows on 404/410.
**Warning signs:** Users get 2+ copies of every push.

## Code Examples

### Category→type map (single source of truth, D-06)
```python
# ops/notifications.py — the ONE map both the list filter and the push filter import
from django.db import models

class NotificationCategory(models.TextChoices):
    ROOM    = "room",    "Room events"
    REPORTS = "reports", "Reports"
    SYSTEM  = "system",  "System"

# Maps EXISTING notify() type strings (verified in-repo) to the three groups.
CATEGORY_TYPES = {
    NotificationCategory.ROOM:    {"room_event", "room_conflict"},          # scan.py, jobs.py
    NotificationCategory.REPORTS: {"weekly_report_ready"},                   # Phase 6 will emit this type
    NotificationCategory.SYSTEM:  {"job_failed", "modality_materialize_no_room"},  # jobrun.py, materialize
}
TYPE_CATEGORY = {t: c for c, ts in CATEGORY_TYPES.items() for t in ts}

# Push fires for key events only (D-08). wrong-room + force-handover share type="room_event".
PUSH_TYPES = {"room_event", "room_conflict", "weekly_report_ready"}

def muted_types(user):
    """Set of type strings the user has muted (empty by default -> nothing muted)."""
    muted_cats = set(
        user.notification_mutes.values_list("category", flat=True))
    return {t for c in muted_cats for t in CATEGORY_TYPES.get(c, set())}
```
Types **not** in `CATEGORY_TYPES` (e.g. `checker_flag`, `online_assigned`, `modality_shift_*`) are never returned by `muted_types` → always shown, never mutable this phase (see Open Questions).

### Mute model + unread/list query
```python
# ops/models.py (additions)
class NotificationMute(models.Model):
    """Presence of a row = that category is muted for the user (default-unmuted, D-05)."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="notification_mutes")
    category = models.CharField(max_length=20)   # NotificationCategory value
    class Meta:
        unique_together = [("user", "category")]

# add to Notification:
#   pushed_at = models.DateTimeField(null=True, blank=True)   # outbox stamp (Q4)
#   Meta.indexes = [models.Index(fields=["user", "read_at"])]  # unread badge query
```
```python
# ops/notifications.py helper — visible (non-muted) notifications for a user
def visible_qs(user):
    return (user.notifications
            .exclude(type__in=muted_types(user))
            .order_by("-created_at"))

def unread_count(user):
    return visible_qs(user).filter(read_at__isnull=True).count()
```

### Auto-mark-read on open (D-03) — no AuditLog
```python
from django.utils import timezone
def _mark_read(qs):
    # bulk update, NO AuditLog (read surface stays audit-silent, per notify() discipline)
    qs.filter(read_at__isnull=True).update(read_at=timezone.now())
```

### Outbox sender registered on the existing scheduler (Q4 primary)
```python
# runscheduler.py — add alongside materialize/sweep/weekly_report
from ops.push import send_push_outbox
sched.add_job(
    lambda: run_job("push_outbox", send_push_outbox),
    IntervalTrigger(seconds=get_policy("push_outbox_interval_seconds")),  # e.g. 15; policy-driven, not magic
    id="push_outbox", max_instances=1, coalesce=True,
    misfire_grace_time=60, replace_existing=True)
```
```python
# ops/push.py — send_push_outbox()
from datetime import timedelta
from django.utils import timezone
from ops.models import Notification, PushSubscription
from ops.notifications import PUSH_TYPES, muted_types

def send_push_outbox():
    """Send push for unpushed key-event notifications; prune dead endpoints. Returns count sent."""
    window = timezone.now() - timedelta(minutes=15)   # bound the scan; keep-all means never re-scan old rows
    pending = (Notification.objects
               .filter(type__in=PUSH_TYPES, pushed_at__isnull=True, created_at__gte=window)
               .select_related("user"))
    sent = 0
    for n in pending:
        if n.type in muted_types(n.user):             # D-05: mute suppresses push too
            n.pushed_at = timezone.now(); n.save(update_fields=["pushed_at"]); continue
        payload = {"title": n.title, "body": n.body, "link": n.link or "/notifications"}
        for sub in n.user.push_subscriptions.all():
            if not _send_one(sub, payload):
                sub.delete()                          # 404/410 prune (D-09)
        n.pushed_at = timezone.now(); n.save(update_fields=["pushed_at"])
        sent += 1
    return sent
```
`run_job` already wraps this in JobRun + broad `except` (never re-raises), so a bad pass records `failed` and alerts SysAdmins without killing the scheduler — reinforcing criterion #4.

### VAPID key generation (one-time, dev + prod)
```bash
# py-vapid CLI ships with pywebpush; run once, commit NEITHER pem to git
vapid --gen                    # -> private_key.pem, public_key.pem
vapid --applicationServerKey   # prints "Application Server Key = <base64url>"  (the browser key)
```
Store: `private_key.pem` at a gitignored path referenced by `VAPID_PRIVATE_KEY_PATH`; put the printed application server key in `.env` as `VAPID_PUBLIC_KEY`; set `VAPID_SUB=mailto:<admin>@mmcm.edu.ph`. In `settings.py` read all three from env (`python-dotenv` already loads `.env`).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GCM/FCM server keys + browser-specific push | Standard **VAPID** (self-signed app-server key, no vendor cert) | ~2017, universal since ~2018 | One keypair works across Chrome/Firefox/Edge/Safari; `pywebpush` handles it |
| No web push on iOS | **iOS/iPadOS 16.4+** web push for **home-screen PWAs** using the same VAPID/`applicationServerKey` — no APNs cert | 2023-03 (16.4), stable through 2026 | iOS reachable but install-gated; not in Safari tab [VERIFIED: WebSearch 2026] |
| `pywebpush` 1.x (`cryptography` older pins) | `pywebpush` **2.x** (works with `cryptography` 40+) | 2024–2026 | Compatible with the repo's `cryptography>=42`/installed 48; no conflict |

**Deprecated/outdated:**
- APScheduler 4.0 pre-release — repo explicitly pins `<4`; do not adopt (unrelated to push but relevant since the sender rides the scheduler).
- Legacy GCM push endpoints — irrelevant; VAPID-only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `weekly_report_ready` is the type string Phase 6's weekly-report `notify()` will use (it does not exist yet in code) | Q6 map / PUSH_TYPES | If Phase 6 picks a different string, Reports mute + report push silently miss. **Mitigation:** define the constant in `ops/notifications.py` now and have Phase 6 import it. Coordinate. |
| A2 | Types outside the three groups (`checker_flag`, `online_*`, `modality_shift_*`, `modality_materialize_no_room` placement) should stay **always-shown/never-mutable** this phase | Q6 / Open Q | If the owner expected these mutable, some users see "un-muteable" noise. Low risk — matches D-04's explicit three-group scope + default-unmuted. |
| A3 | `modality_materialize_no_room` belongs in **System** | CATEGORY_TYPES | Mild mis-grouping only; it is an admin/system materialize notice, so System is the natural fit. Confirm with owner. |
| A4 | Reusing `poll_interval_seconds` (8s) for the bell is acceptable; a separate `push_outbox_interval_seconds` (~15s) is fine for push latency | Q4/Q5 | Too-frequent bell polling on every page for all roles adds load; 8s matches existing live surfaces so acceptable. |
| A5 | Desktop Chrome/Edge is the demo target for push; iOS is install-gated | Pitfall 2 | If the capstone demo is on an iPhone in Safari (not installed PWA), push won't work — flagged as a demo-planning item. |

## Open Questions

1. **Unmapped notification types (the ~10 live types beyond the three groups).**
   - What we know: `notify()` currently emits `room_event`, `room_conflict`, `job_failed`, `modality_materialize_no_room`, **plus** `checker_flag`, `checker_replay_conflict`, `online_no_link`, `online_unassigned`, `online_assigned`, `modality_shift_submitted/approved/rejected/denied/applied` [VERIFIED: repo grep]. D-04 only names three groups covering a subset.
   - What's unclear: should modality-shift and checker/online notices be mutable (join a group) or always-on?
   - Recommendation: **always-shown / never-mutable this phase** (unmapped ⇒ not in `muted_types`). Preserves default-unmuted + D-04's explicit scope; granular mute is deferred. Have the planner confirm with the owner and note it in the plan.

2. **`weekly_report_ready` type string (Phase 6 dependency).**
   - What we know: the Reports group + weekly-report push both need a type string that does not exist yet.
   - Recommendation: Phase 5 defines `WEEKLY_REPORT_READY = "weekly_report_ready"` in `ops/notifications.py` and adds it to `CATEGORY_TYPES`/`PUSH_TYPES` now; Phase 6's report job imports and emits it. Flag as a cross-phase contract.

3. **Sender choice — scheduler outbox (recommended) vs inline `on_commit`.**
   - What we know: both satisfy criterion #4; the outbox is structurally safer (web request does no network I/O) and unifies web- + scheduler-originated events; inline is simpler but blocking-prone.
   - Recommendation: **outbox on the existing scheduler** (primary). Planner may downgrade to inline `on_commit`+`timeout` if it wants zero new job/column, but must then add the hard timeout + broad `except`. Requires the `runscheduler` process to be running for push (already the established dev/prod pattern).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12.10 | — |
| Django | everything | ✓ | 6.0.6 | — |
| `cryptography` | VAPID/http-ece base | ✓ | 48.0.0 (`>=42` pinned) | — |
| `pywebpush` | push send (NEW) | ✗ (not yet installed) | 2.3.0 available on PyPI | none needed — pure-Python install, no blocker |
| `APScheduler` | outbox sender job | ✓ | 3.10–3.x (`<4` pinned) | — |
| `python-dotenv` | VAPID env config | ✓ | `>=1.0` | — |
| HTTPS / secure context | Push API (prod) | prod ✓ (EC2 + domain); dev = `http://localhost` (treated secure) | — | localhost is a secure context for desktop dev |
| iOS 16.4+ installed PWA | iOS push only | device-dependent | — | Demo push on desktop Chrome/Edge |

**Missing dependencies with no fallback:** none — `pywebpush` installs cleanly on Windows (no compiler; `cryptography` wheel already present).
**Missing dependencies with fallback:** iOS push requires an installed PWA on 16.4+; desktop Chrome/Edge is the reliable demo path.

## Validation Architecture

> `.planning/config.json` was not read as disabling `nyquist_validation`; included per default-on rule. FluxTrack uses the **Django test runner** (not pytest) — per MEMORY: run via the full `py -3.12 manage.py test`.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Django `unittest`-based test runner (`manage.py test`) — NOT pytest |
| Config file | none (Django default; tests live in each app's `tests*.py`) |
| Quick run command | `py -3.12 manage.py test ops.tests web.tests -v1` |
| Full suite command | `py -3.12 manage.py test -v1` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NOTIF-01 | Poll endpoint returns unread count + preview; badge = `read_at IS NULL` | unit (view) | `py -3.12 manage.py test web.tests_notifications` | ❌ Wave 0 |
| NOTIF-01 | Opening dropdown/page sets `read_at`, clears badge (D-03) | unit | same | ❌ Wave 0 |
| NOTIF-03 | Muting a category removes its types from list AND from push outbox | unit | `py -3.12 manage.py test ops.tests_notifications` | ❌ Wave 0 |
| NOTIF-03 | Single map: same `muted_types` drives both filters (no divergence, D-06) | unit | same | ❌ Wave 0 |
| NOTIF-02 | Subscribe endpoint persists/updates `PushSubscription` (dedup on endpoint) | unit | `py -3.12 manage.py test web.tests_notifications` | ❌ Wave 0 |
| NOTIF-02 | `send_push_outbox` stamps `pushed_at`, respects mute, prunes on 404/410 (mock `webpush`) | unit | `py -3.12 manage.py test ops.tests_push` | ❌ Wave 0 |
| Criterion #4 | A `WebPushException(410)` prunes the sub and does NOT raise (`run_job` records ok/failed) | unit | same | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `py -3.12 manage.py test ops.tests_notifications ops.tests_push web.tests_notifications -v1`
- **Per wave merge:** `py -3.12 manage.py test ops web -v1`
- **Phase gate:** `py -3.12 manage.py test -v1` green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `ops/tests_notifications.py` — covers the category map + `muted_types` + `visible_qs`/`unread_count` (NOTIF-03/01)
- [ ] `ops/tests_push.py` — covers `send_push_outbox` with a **mocked** `pywebpush.webpush` (200, 410-prune, timeout-no-raise) (NOTIF-02, criterion #4)
- [ ] `web/tests_notifications.py` — covers bell/dropdown/page views, mark-read, subscribe/unsubscribe (NOTIF-01/02)
- [ ] Framework install: none — Django test runner already present

## Security Domain

> `security_enforcement` not disabled in config → included.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | All `/notifications/*` views `@login_required`; a user sees only `user.notifications` (own rows) |
| V4 Access Control | yes | No role decorator (all roles have notifications) but **strict per-user scoping** — never expose another user's notifications or subscriptions; subscribe/unsubscribe act only on `request.user` |
| V5 Input Validation | yes | Subscribe payload: validate `endpoint` is an https URL + `keys` has `p256dh`+`auth`; reject otherwise. `link` in payload is server-controlled (from the Notification row), not user input |
| V6 Cryptography | yes | **Never hand-roll** — `pywebpush`/`py-vapid` own all crypto; VAPID private key stays out of git (gitignored PEM) |
| V13 API / SSRF | yes | The outbox POSTs to browser-vendor push endpoints stored from real subscriptions only; `timeout=10` caps each; do not follow arbitrary user-supplied endpoints beyond validated subscribe input |

### Known Threat Patterns for Django + Web Push
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| IDOR on another user's notifications/subscriptions | Information Disclosure | Scope every query to `request.user`; no PK-addressed cross-user access |
| CSRF on subscribe/mark-read/mute POSTs | Tampering | Django CSRF; pass `X-CSRFToken` in the raw `fetch` (Pitfall 5); htmx POSTs already carry it |
| VAPID private key leak | Spoofing | Gitignored PEM + env path; never commit; rotate = regenerate keypair (invalidates existing subs) |
| Dead-endpoint DoS / hang on the sender | Denial of Service | `timeout=10` + broad `except` in the outbox; runs in the scheduler, never the web worker (criterion #4) |
| XSS via notification title/body in the dropdown | Tampering | Django template auto-escaping (default); do not `|safe` notification text |

## Sources

### Primary (HIGH confidence)
- Repo code (read this session): `ops/notify.py`, `ops/models.py`, `ops/jobrun.py`, `ops/policy.py`, `web/views.py` (`SW_JS`), `web/scan.py`, `web/ifo.py`, `web/urls.py`, `scheduling/management/commands/runscheduler.py`, `scheduling/jobs.py`, `templates/base.html`, `templates/ifo/live.html`, `templates/faculty/home.html`, `config/settings.py`, `requirements.txt` — established patterns, `notify()` type inventory, poll pattern, scheduler wiring.
- `.planning/codebase/CONVENTIONS.md` — project rules (pure resolver, AuditLog-on-write + its notification exception, `get_policy`, ASCII-only, one-module-per-surface, htmx CSRF).
- PyPI (`pip index versions`, local `import`): `pywebpush` 2.3.0, `py-vapid` 1.9.4, `http-ece` 1.2.1, `cryptography` 48.0.0, Python 3.12.10 [VERIFIED].
- `github.com/web-push-libs/pywebpush`, `github.com/mozilla-services/vapid` — canonical library repos (via legitimacy check `repoUrl`).

### Secondary (MEDIUM confidence)
- WebSearch (2026): iOS 16.4+ web push for home-screen PWAs, same VAPID/`applicationServerKey`, no APNs cert; not supported in the Safari tab — MDN/Apple-corroborated. [CITED: magicbell.com, apple developer forums, MDN]

### Tertiary (LOW confidence)
- Service-worker `push`/`notificationclick` handler shape and `urlBase64ToUint8Array` — standard MDN idiom from training knowledge, matched to this repo's existing SW structure. [ASSUMED — verify handlers fire on a real subscribe during execution]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions verified on PyPI this session; `cryptography` already installed and compatible.
- Architecture / patterns: HIGH — reuses shipped in-repo patterns (htmx poll, single-write-path, one-scheduler); grounded in actual code.
- Fault isolation design: HIGH — outbox-on-scheduler maps directly onto existing `run_job`/`runscheduler` guarantees.
- Pitfalls / iOS constraints: MEDIUM-HIGH — iOS behavior corroborated by current web sources; exact SW handler firing to be confirmed at execution.
- Category map completeness: MEDIUM — full type inventory grepped, but grouping of non-core types is an owner decision (Open Q1).

**Research date:** 2026-07-09
**Valid until:** 2026-08-09 (stable stack; re-check `pywebpush` + iOS push status if execution slips past ~30 days)

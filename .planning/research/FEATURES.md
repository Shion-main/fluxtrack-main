# Feature Research

**Domain:** Faculty attendance + facility utilization (mobile-first PWA, Django + htmx + vanilla JS, polling-only, MSSQL)
**Researched:** 2026-07-02
**Confidence:** HIGH (design specs + USE_CASES pin exact contracts; standard patterns verified against current sources)

> **Scope note:** This is a *subsequent-milestone* feature study. The scan
> resolver, Faculty check-in, and IFO room/schedule surface are already
> built and are NOT re-researched here. This document maps the *expected
> behavior and edge cases* of the six UNBUILT feature areas so planning can
> phase and implement them well. The template's "MVP / v1 / v2" framing is
> reinterpreted as "build-order tiers within this milestone," since the
> product is already past MVP.

---

## Already Built (context only — do not dwell)

| Area | State | Why it matters to the unbuilt work |
|------|-------|-----------------------------------|
| Scan resolver (pure function, 16 tests) | ✅ Built | The **re-validation contract** for the offline queue must reuse this exact pattern — replayed scans go back through resolver logic, not a shortcut path. |
| Faculty check-in (scan + outcomes) | ✅ Built | Checker "scan a room, see state" reads the same `Session` state the resolver produces. Modality workflow *amends* FAC-07 (self-declare removed). |
| IFO room + schedule surface (read) | ✅ Built | Guard per-room schedule (GRD-02) literally reuses this view under a `guard_required` decorator. Faculty locator reuses the same `Session`/`Room` join. |
| `_notify_ifo()` write path in `web/scan.py` | ✅ Built (write only) | Every notification feature below reuses this fan-out pattern. There is **no read surface yet** — that gap is the whole of NOTIF-01. |

---

## Feature Landscape

### Table Stakes (Users Expect These) — all six areas are table-stakes-still-to-build

These are not differentiators; each closes a role's core story that is currently
broken or absent. Missing them means that role's use of FluxTrack is incomplete.

| Feature | Why Expected (expected/standard behavior) | Complexity | Notes |
|---------|-------------------------------------------|------------|-------|
| **1. Checker verification UX** | A physical checker on a floor must, per-room: be gated to their assignment, scan → see live session state + faculty photo, and take one action (Verify / Flag mismatch / Flag not-present / Confirm-empty). This is *the* trust primitive of the whole system. | **HIGH** | Mobile, one-handed, intermittent connectivity. On-duty gating is server-enforced per scan. Action set already trimmed by the modality spec (no "Confirm absent"). |
| **2. Offline scan queue (IndexedDB)** | Scans made offline queue locally, replay in batch on reconnect, and are **re-validated server-side before applying** — never blindly trusted, because room state may have changed while offline. Unappliable scans are flagged for IFO, not silently dropped. | **HIGH** | The re-validation requirement is the hard part, not the queue. Standard "replay = truth" PWA advice is *wrong* here. See edge cases. |
| **3. Modality shift approval** | Instructor submits F2F/Blended↔Online change → routed to Dean → approve/reject → on approval, room auto-releases (or auto-assigns) + IFO notified. Lead-time gated (default 2 days, hard reject). | **MEDIUM** | Fully specified in `2026-07-02-modality-shift-approval-design.md`. Lightweight single-hop approval + audit. Online→F2F direction needs a narrow conflict-check routine that does not exist yet. |
| **4. In-app + web-push notifications** | In-app polled list (all roles) reading the `Notification` rows already being written; web push (VAPID) for floor activity + key events; per-user mute prefs. Fan-out to *relevant roles*, debounced. | **MEDIUM** (in-app) / **HIGH** (push) | In-app list is low-risk (read surface over existing rows). Web push carries real platform edge cases (iOS install-gating, no Background Sync). |
| **5. Weekly reporting + scorecards** | Weekly consolidated attendance per department (one row/faculty: scheduled, held, absent, %, verified count) + per-faculty scorecard, CSV **and** PDF export. Aggregates are pure + independently tested; one failed aggregate degrades its own section, never blanks the page. | **MEDIUM-HIGH** | Largest single dependency hub — IFO-10, HR-03, DEAN-03 all consume it. Build the aggregate **once** as a reusable pure function (resolver pattern), filter by department for scope. |
| **6. Faculty locator (Guard)** | Search faculty by name → their *currently active* session (room/building/floor, course, end time), or "Online — not on campus," or "Not in class + next class" + today's schedule. Read-only. | **LOW-MEDIUM** | A genuinely new query (find active session across all rooms), but small. No writes, no new infra. |

### Differentiators (Competitive Advantage)

Where these features go beyond a generic attendance app and reinforce FluxTrack's
core value ("presence is physically verified, not self-reported").

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Server-side re-validation of offline scans | Most offline-first apps replay-and-trust; FluxTrack treating the *current* server state as authoritative on replay is what keeps "checker-verified" meaningful even after a connectivity gap. | HIGH | This is the correctness differentiator. Get it right and the whole trust model holds under real field conditions. |
| Priority-queue floor view (oldest-unverified first) | Directs the checker to the class that has waited longest for a physical check, not the nearest room — turns coverage from ad-hoc into measurable. | MEDIUM | Primary Checker landing screen. Excludes Absent sessions per modality spec (nothing to check). |
| Auto room-release on modality approval | Removes the Checker entirely from the room-release loop; rooms follow schedule/policy mechanically. Eliminates "pending release until someone confirms empty." | MEDIUM | The `Session.room_released_at` field's first writer. |
| Graceful-degradation reporting | A single broken aggregate shows an error in its card, not a 500 for the whole report — deans/HR still get the rest of the page under a data glitch. | MEDIUM | A constraint on *how* aggregates are built, not a separate feature. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Background Sync API for offline replay | It's the "official" PWA offline-queue mechanism and demos cleanly. | **Not supported in Safari/iOS or Firefox as of 2026.** Faculty/Checkers on iPhones would silently never replay. | Explicit flush on `online` event **and** `visibilitychange` (tab visible), plus a manual "sync now" affordance. Do not depend on Background Sync. |
| WebSockets for live floor/notification updates | "Real-time" feels modern; simplest mental model for live coverage. | Ruled out by SRS §2.5 (polling only); adds a stateful server surface incompatible with the single-EC2 + Gunicorn deploy. | htmx polling at the configured interval (already the pattern in `/ifo/live`). Reuse it for Checker floor view + notification bell. |
| Blind replay of the offline queue ("trust the scan") | Simplest possible sync; every queued action just applies. | Room state may have changed while offline (handover, release, modality shift) → replay corrupts the authoritative record. | Re-run each queued scan through the resolver against *current* state; on mismatch, flag for IFO instead of applying. |
| Checker override of auto-Absent (old CHK-06) | Intuitive: "the checker sees them, fix the record." | **Explicitly removed** by the modality spec. Reopening an already-released room is the easy bug; Absent is now final. | None — Absent is final, room releases on `room_hold_minutes` timer with zero checker action. Do not build the override. |
| Same-day / emergency modality declaration | Instructor falls sick, wants to flip to Online today. | Out of scope by design (lead-time gate exists precisely because same-day can't deliver the room-release benefit). | Falls back to existing scan-time `online-reject` outcome. Accepted gap, not a bug. |
| Email notifications | Familiar channel; "just send an email." | Out of scope (SRS §7). Adds SMTP/deliverability surface for a capstone. | In-app polled list + web push only. |
| General booking/conflict engine to support Online→F2F room auto-assign | "We'll need bookings eventually anyway." | Scope explosion; IFO-05 bookings is a separate unbuilt feature. | Implement only a **narrow** "is this room free at this day/time in the active term" check, scoped to the modality feature. |
| Payroll periods / locks / finalization | HR wants "attendance for payroll." | Explicit product boundary (HR-04, SRS §7). | Stop at CSV export; external payroll consumes it. |

---

## Feature Dependencies

```
IFO-06 (Checker/Guard floor assignments)
    └──HARD BLOCKS──> 1. Checker verification UX (on-duty gating needs an active Assignment)
                          └──requires──> 2. Offline scan queue (same scan surface, offline path)

JOB-02 (status sweep marks no-show Absent, releases rooms)
    └──BLOCKS trustworthy──> 1. Checker floor view (must exclude Absent sessions correctly)
    └──BLOCKS trustworthy──> 5. Weekly reporting (absent counts are only correct once sweep runs)

NOTIF-01 (in-app read surface over existing Notification rows)
    └──unblocks visibility of──> 3. Modality approval (IFO/instructor/Dean notifications)
    └──unblocks visibility of──> already-built FAC-10 wrong-room notification (silently invisible today)

NOTIF-02 (web push / VAPID infrastructure)
    └──HARD BLOCKS──> 6-adjacent: Guard push alerts (GRD-04)
    └──enhances──> 1. Checker + 4. all notification fan-out

5. Weekly reporting aggregates (pure functions)
    └──shared by──> IFO-09 dashboard drill-down
    └──shared by──> DEAN-04 dashboard + DEAN-02/03
    └──shared by──> HR-01..03
    (build ONCE, filter by department for scope)

RPT-02 auto-generation ──requires──> JOB-03 (weekly report job) ──requires──> scheduler process wired

6. Faculty locator ──reuses──> built IFO-11 room/schedule join (read-only, low new surface)

3. Modality approval (Online→F2F) ──requires──> narrow room-conflict check (net-new, self-contained)
```

### Dependency Notes

- **Checker UX requires IFO-06 assignments (hard blocker):** on-duty gating
  literally reads an active `Assignment`; without it there is no way to grant
  or deny verification powers. IFO-06 must land *before or alongside* the
  Checker slice, never after.
- **Checker floor view + reporting both depend on JOB-02 being trustworthy:**
  Absent is currently only detected reactively at scan time. Until the sweep
  marks no-show sessions Absent independently, the floor view's coverage math
  and the weekly report's absent counts are both wrong for any session nobody
  scanned. The modality spec's "floor view never shows Absent" rule only works
  once Absent is reliably set.
- **Offline queue is a mode of the Checker scan surface, not a separate feature:**
  it shares the same scan entry point and the same server-side resolver
  re-validation. Sequence it immediately after the online Checker path.
- **Notifications split into two risk tiers:** NOTIF-01 (in-app list) is a
  low-risk read surface over rows already being written and should ship early
  to make existing flows (FAC-10 wrong-room, modality approvals) visible.
  NOTIF-02 (web push) is higher-risk platform work and hard-blocks Guard alerts
  (GRD-04) — sequence it deliberately, not bundled into NOTIF-01.
- **Reporting is the widest hub:** IFO-09, DEAN-04, HR, and DEAN-02/03 all
  consume the same aggregates. Build them once as pure, independently tested
  functions; department scoping is a filter argument, not a reimplementation.
- **Faculty locator is nearly free:** it reuses the built room/schedule surface
  and adds one "currently active session by faculty" query. No new infra, no
  dependency on notifications.

---

## MVP Definition (re-read as build-order tiers for this milestone)

### Tier 1 — Prerequisites (must precede the feature work)

- [ ] **JOB-02 status sweep** — makes Absent trustworthy without every session
  being scanned; the Checker floor view and reporting both silently mis-count
  without it.
- [ ] **IFO-06 floor assignments** — hard blocker for Checker on-duty gating.

### Tier 2 — Core attendance loop (the milestone's center of gravity)

- [ ] **1. Checker verification UX (online path)** — floor view + scan +
  Verify/Flag/Confirm-empty actions, on-duty gated.
- [ ] **2. Offline scan queue** — same surface, offline mode, server-side
  re-validation on replay. Ship right after the online path.
- [ ] **3. Modality shift approval** — instructor→Dean→auto-release + IFO notify;
  lead-time gate. Self-contained; can run parallel once notifications exist.

### Tier 3 — Visibility + reporting

- [ ] **4a. NOTIF-01 in-app list** — read surface over existing rows; ship early
  to unblock visibility of Tier-2 events.
- [ ] **4b. NOTIF-02 web push + mute prefs** — VAPID infra; hard-blocks Guard alerts.
- [ ] **5. Weekly reporting + scorecards** — pure aggregates, CSV+PDF, graceful
  degradation. Unblocks IFO-10 / HR-03 / DEAN-03 together.

### Tier 4 — Thin read-only role layers (mostly reuse)

- [ ] **6. Faculty locator (Guard)** — new active-session query; small.
- [ ] Guard floor monitor + per-room schedule reuse; Dean dashboard (DEAN-04)
  over Tier-3 aggregates; HR attendance list + CSV.

---

## Per-Area Expected Behavior + Edge Cases

### 1. Checker verification UX

**Expected behavior:** Floor view is the primary landing screen (most sessions
start here, not from a raw scan): color-coded room cards (green verified / yellow
awaiting / red anomaly), a coverage-progress indicator, and a priority queue
sorted by *oldest unverified active session*. Scanning a room shows current
session state + the scheduled faculty's profile photo, then one action:
Verify / Flag identity mismatch / Flag not-present / Confirm-empty (Verified empty).

**Edge cases (get these right):**
- **On-duty gating must give a *reason*, not a silent deny** — off-duty and
  wrong-floor scans return a clear message. Gating is checked server-side on
  every action, not just at screen load (an assignment can expire mid-shift).
- **Floor view must exclude Absent sessions** from coverage math and the priority
  queue (modality spec §6) — there is nothing for a checker to verify on an
  Absent session, and including them makes coverage un-completable.
- **"Confirm empty" is NOT "confirm absent"** — it is ghost-booking detection: a
  room found empty *during* its active window before any Absent determination.
  It stays in scope; "Confirm absent" was removed with CHK-06.
- **Photo availability** — faculty profile photo (FAC-12) may be unset; the UI
  must degrade to name-only rather than a broken identity check.
- **Priority-queue staleness under polling** — the queue is polled, so a session
  another checker just verified may still show briefly; the action must be
  idempotent (verifying an already-verified session is a no-op, not an error).

**Complexity: HIGH.** Depends on IFO-06 (hard) and JOB-02 (correctness).

### 2. Offline scan queue (IndexedDB)

**Expected behavior (standard PWA pattern, adapted):** Queue mutations locally in
IndexedDB while offline, each entry recording action + payload + client timestamp
+ a **schema/app version**; flush on reconnect. Optimistic UI shows the scan as
"pending sync."

**The FluxTrack-specific correctness rule — this overrides the generic pattern:**
- **Re-validate server-side before applying.** Each replayed scan is re-run
  through the resolver against *current* state, not blindly applied. Room state
  may have changed while offline (handover, release, modality shift). This is a
  server-authoritative model, deliberately **not** last-write-wins-by-client-
  timestamp. Do not import the common "replay = truth" advice.
- **Unappliable scans are flagged for IFO**, not dropped and not force-applied.

**Edge cases:**
- **No Background Sync on iOS/Safari or Firefox (2026).** Cannot rely on the
  Background Sync API. Flush on the `online` event AND on `visibilitychange`
  (tab becomes visible), plus a manual "sync now" control. This is the single
  biggest platform gotcha for the Checker slice.
- **Duplicate replay / at-least-once delivery** — a flush may fire twice
  (reconnect + visibility). Server actions must be idempotent, keyed by a
  client-generated scan id, so a re-sent scan is deduped, not double-applied.
- **Stale-app payloads** — a checker offline for a long stretch may sync an old
  payload shape; the schema version lets the server reject/adapt rather than
  mis-parse.
- **Ordering** — replay in capture order; a later scan may depend on an earlier
  one's effect (e.g. verify then flag on the same room).
- **Queue growth / storage limits** — bound the queue and surface a "N scans
  pending" indicator so a checker knows sync hasn't happened.

**Complexity: HIGH** (the re-validation + platform fallbacks, not the storage).

### 3. Modality shift approval

**Expected behavior:** Fully specified in the design doc — instructor submits a
`ModalityShiftRequest` (single-session or recurring), lead-time gated (default 2
days, hard reject on submission if it doesn't clear the window), routed to the
Dean of the instructor's department. Approve → room auto-releases (F2F→Online) or
auto-assigns a room (Online→F2F) + one `Notification` per active IFO Admin
(informational; IFO cannot block). Reject → closes with Dean's reason, instructor
notified. Faculty may withdraw while `pending_dean`. Standard lightweight
single-hop approval; every write audited (`AuditLog` per conventions).

**Edge cases:**
- **Online→F2F with no free room = approval fails outright** — no silent
  partial-apply, no invented IFO fallback. Needs a narrow room-conflict check
  (same building, prefer original room) that does not exist in the codebase yet.
- **Recurring approval must patch `materialize_sessions`** — sessions materialized
  *after* approval must be born already-Online with `room_released_at` stamped at
  creation, else they sit with an unset release field forever.
- **Lead-time is measured against the earliest affected date**, not submission
  date alone; recurring uses the start date.
- **Withdraw race** — instructor withdraws while the Dean is deciding; the
  decision must no-op cleanly on an already-withdrawn request.
- **No dispute path** — rejections are final (matches CHK-05/FAC-11 no-dispute
  pattern). `decision_reason` is informational only.

**Complexity: MEDIUM.** Self-contained; the conflict-check routine is the only
net-new primitive. Needs NOTIF-01 for its notifications to be *visible*.

### 4. In-app + web-push notifications

**Expected behavior:**
- **NOTIF-01 (in-app):** polled list/bell over the `Notification` rows already
  written by `_notify_ifo()` and (future) modality/report events. All roles.
- **NOTIF-02 (web push):** VAPID (ECDSA P-256 key pair, JWT-signed requests,
  `mailto:` or HTTPS `sub`), service worker `push` handler. For floor activity
  (Checker/Guard) + key events (wrong-room, force-handover, room conflict, weekly
  report ready).
- **NOTIF-03 (mute prefs):** per-user, feeds FAC-12; checked at fan-out time.

**Edge cases:**
- **iOS web push requires Home-Screen install** (Add to Home Screen via Safari);
  an open browser tab gets no push. Permission prompt must be triggered by a
  **user gesture** — `requestPermission()` in `DOMContentLoaded`/`setTimeout` is
  silently blocked on iOS. Provide an explicit "enable notifications" action.
- **Subscriptions expire / device restarts** can silently unsubscribe; store
  subscriptions (`PushSubscription` model exists) and prune on 404/410 from the
  push service; re-subscribe on next app open.
- **Fan-out to *relevant roles only*** — wrong-room → IFO; modality approval →
  IFO + instructor; weekly report → IFO + relevant Dean(s) (RPT-02 amended).
  Avoid broadcast-to-all.
- **Debouncing** — floor-activity pushes (repeated scan failures, flags) must be
  debounced/coalesced so a checker/guard isn't spammed; mute prefs honored.
- **In-app list uses polling** (no WebSockets) — consistent with SRS §2.5; reuse
  the `/ifo/live` polling pattern.

**Complexity: MEDIUM (in-app) / HIGH (push, due to platform edge cases).**

### 5. Weekly consolidated reporting + faculty scorecards

**Expected behavior:** Weekly consolidated report per department (one row per
faculty: scheduled, held/present, absent, attendance %, checker-verified count) +
itemized absence detail; faculty scorecard (scheduled vs held, %, absences,
early-ends, modality breakdown, selectable period). Available on-demand by
week/department and auto-generated weekly (JOB-03), stored as `WeeklyReport`, IFO
+ relevant Deans notified. CSV **and** PDF export, per-department or all.

**Edge cases:**
- **Graceful degradation is a build constraint** — each aggregate is a pure,
  independently tested function (resolver pattern); a single failed aggregate
  renders an error state *in its own section*, never a blank/500 page. Compose
  the report from independent sections, not one monolithic query.
- **Build the scorecard aggregate ONCE** — shared by IFO-09 drill-down, DEAN-04,
  and Dean per-faculty view. Department scope is a filter parameter.
- **Absent counts depend on JOB-02** having run — a report generated before the
  sweep under-counts absences. Order matters.
- **PDF generation** adds a dependency (e.g. a server-side HTML→PDF path);
  keep it isolated so a PDF failure degrades to CSV rather than failing the view.
- **Empty/partial weeks** (term start, breaks) — zero-scheduled faculty must
  render cleanly (0/0, not a divide-by-zero on attendance %).
- **MSSQL aggregate portability** — verify GROUP BY / date-truncation behaves
  under SQL Server (compat still unproven per CONCERNS); avoid SQLite-only SQL.

**Complexity: MEDIUM-HIGH.** Widest downstream dependency; the aggregate layer is
the reusable core.

### 6. Faculty locator (Guard)

**Expected behavior:** Search faculty by name → resolve their *currently active*
session across all rooms: room/building/floor, course/section, end time. If no
active F2F session: "Online — not on campus" (active Online session) or "Not in a
class" + next scheduled class, plus today's schedule. Read-only.

**Edge cases:**
- **"Currently active" is a point-in-time query across all rooms** — new join,
  not a reuse of a per-room view; index on session status + faculty.
- **Multiple/ambiguous name matches** — return a disambiguation list, don't guess.
- **Online vs on-campus distinction** — an active session with declared Online
  modality resolves to "not on campus," not a room location.
- **Force-handover edge** — a faculty force-closed out of a room should no longer
  show as active there (relies on the built handover logic being correct).
- **Guards are strictly read-only** — enforced by never adding write views to a
  `guard_required`-gated surface (GRD-05), not a special check.

**Complexity: LOW-MEDIUM.** Reuses built room/schedule data; one new query.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| JOB-02 status sweep (prereq) | HIGH | MEDIUM | P1 |
| IFO-06 floor assignments (prereq) | HIGH | LOW-MEDIUM | P1 |
| 1. Checker verification UX (online) | HIGH | HIGH | P1 |
| 2. Offline scan queue | HIGH | HIGH | P1 |
| 3. Modality shift approval | MEDIUM | MEDIUM | P2 |
| 4a. NOTIF-01 in-app list | HIGH | LOW-MEDIUM | P1 |
| 4b. NOTIF-02 web push + mute | MEDIUM | HIGH | P2 |
| 5. Weekly reporting + scorecards | HIGH | MEDIUM-HIGH | P2 |
| 6. Faculty locator (Guard) | MEDIUM | LOW-MEDIUM | P3 |

**Priority key:** P1 = core attendance loop + its prerequisites and visibility;
P2 = high-value but not blocking the loop; P3 = thin read-only reuse.

---

## Sources

- Project design specs (authoritative, in-repo): `docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md`, `docs/superpowers/specs/2026-07-02-dean-dashboard-design.md`; feature/status reference `docs/USE_CASES.md`; narrative `docs/SCENARIOS.md`; `.planning/PROJECT.md` — **HIGH confidence** (exact contracts, current).
- Offline-first PWA sync/queue patterns (Background Sync gaps, replay + conflict, schema-versioned payloads): [LogRocket — Offline-first frontend apps 2025](https://blog.logrocket.com/offline-first-frontend-apps-2025-indexeddb-sqlite/), [Let's Build — Offline-First Web Apps](https://letsbuildsolutions.com/blog/web-engineering/building-offline-first-web-applications-service-workers-indexeddb-and-sync-strategies-for-production/), [MS Learn — Background syncs](https://learn.microsoft.com/en-us/microsoft-edge/progressive-web-apps/how-to/background-syncs) — **MEDIUM-HIGH** (multiple sources agree; Background-Sync-not-in-Safari confirmed).
- Web push / VAPID + iOS constraints (Home-Screen install, user-gesture permission, VAPID subject format, subscription expiry): [MagicBell — PWA push complete guide](https://www.magicbell.com/blog/using-push-notifications-in-pwas), [MDN — Re-engageable Notifications & Push](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Tutorials/js13kGames/Re-engageable_Notifications_Push), [MagicBell — iOS PWA limitations 2026](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide) — **MEDIUM-HIGH**.

---
*Feature research for: faculty attendance + facility utilization (FluxTrack, subsequent milestone — unbuilt feature areas)*
*Researched: 2026-07-02*

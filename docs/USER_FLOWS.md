# FluxTrack — User Flows (by role)

> **What this is:** how each role actually moves through the app, screen to screen — not code
> layers (see [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md)) and not infrastructure (see
> [`docs/IT_ARCHITECTURE.md`](./IT_ARCHITECTURE.md)). Traced from `web/urls.py`, the view modules,
> and `templates/`.

Every session starts the same way for everyone:

```mermaid
flowchart LR
    A["Open app<br/>(PWA icon or URL)"] --> B{Logged in?}
    B -- no --> L["/login<br/>Sign in with Microsoft (Entra SSO)<br/>[DEBUG only: pick a demo user]"]
    L --> C
    B -- yes --> C{"role"}
    C -- Faculty --> F["/faculty/schedule<br/>(skips the launcher — opens straight in)"]
    C -- Checker --> H["/  home.html launcher<br/>(card grid)"]
    C -- IFO Admin --> H
    C -- Dean --> H
    C -- HR Admin --> H
    C -- Guard --> H
    C -- System Admin --> H
```

Faculty is the one role that never sees the card-grid launcher — `home()` redirects them straight
to Schedule so the bottom nav is present immediately. Every other role lands on `web/home.html`,
a grid of role-specific cards built from the `SURFACES` map in `web/views.py`. Cards pointing at
`#` are later-phase stubs (Reports, HR Attendance, Guard surfaces) — they render but do nothing yet.

Two persistent nav bars exist. **Faculty only** gets a bottom tab bar on mobile (`Schedule · Scan ·
Requests`) and its desktop mirror in the header — every other role navigates by returning to `/`
and picking a different card (no equivalent persistent nav yet). Every authenticated header shows
the role badge, full name, and **Sign out**; `is_staff` users also get an **Admin** shortcut to
Django admin.

---

## 1. Faculty

Persistent bottom nav (mobile) / header nav (desktop): **Schedule · Scan · Requests**.

```mermaid
flowchart TD
    Login(["Sign in"]) --> Sched["Schedule<br/>/faculty/schedule<br/>today + this week's sessions"]

    Sched -->|tab: Scan| Scan["Scan<br/>/faculty/scan"]
    Scan --> Cam["Open camera → aim at room QR<br/>(or type the room's manual code)"]
    Cam --> Resolve["POST /scan/resolve"]
    Resolve --> Out1{Outcome}
    Out1 -- "clean check-in" --> Done1["HTMX fragment:<br/>Checked in ✓"]
    Out1 -- "needs confirm<br/>(wrong room / room occupied / early-end)" --> Confirm["Confirm prompt<br/>(signed token)"]
    Confirm -->|Yes, proceed| ConfirmPost["POST /scan/confirm"]
    ConfirmPost --> Done2["HTMX fragment: outcome applied"]
    Confirm -->|Cancel| Scan
    Out1 -- "too early / no session here" --> Done3["HTMX fragment: rejection reason shown"]

    Sched -->|tab: Requests| Mine["My requests<br/>/faculty/modality/mine<br/>list of past/pending shift requests"]
    Mine -->|"New request"| New["Request modality shift<br/>/faculty/modality/new<br/>pick session(s) + target (Online/F2F/room)"]
    New -->|submit| Submitted["Request created, status = PENDING<br/>routed to Dean"]
    Submitted --> Mine
    Mine -->|"Withdraw (pending only)"| Withdraw["POST /faculty/modality/&lt;id&gt;/withdraw"]
    Withdraw --> Mine
```

**Screens:**
- **Schedule** (`faculty/schedule.html`) — today + week view; the faculty's landing screen.
- **Scan** (`faculty/scan.html`) — camera-based QR scan or manual code entry; deep-linked from a
  room's posted QR (`GET /scan?t=TOKEN`) as well as the nav tab. Outcome renders as an HTMX
  fragment (`faculty/_outcome.html`) in place — no full page reload.
- **Requests** — two screens: **My requests** (`modality_mine.html`, list + withdraw) and
  **New request** (`modality_new.html`, the submission form, `_modality_form.html` partial for
  validation re-renders). Approval itself happens on the Dean's side, not here — Faculty only sees
  the resulting status change when they revisit "My requests."

## 2. Checker

No persistent nav — always returns to `/` (home launcher) between surfaces.

```mermaid
flowchart TD
    Home(["/ home launcher"]) --> Floor["Floor view<br/>/checker/floor<br/>coverage + priority queue, auto-refreshing rows"]
    Home --> ScanC["Scan a room<br/>/checker/scan"]
    Home --> Online["Online to verify<br/>/checker/online"]

    ScanC --> CamC["Scan room QR / manual code"]
    CamC --> ResolveC["POST /checker/resolve<br/>→ shows faculty expected in this room now"]
    ResolveC --> ActionC["Choose action: confirm present / mark absent /<br/>force handover / note"]
    ActionC --> ApplyC["POST /checker/action"]
    ApplyC --> OutC["HTMX fragment: outcome"]
    OutC --> Floor

    Floor -->|row action| ActionC

    Online --> OnlineOpen["Open a session<br/>/checker/online/&lt;id&gt;<br/>join the Teams link, verify attendance"]
    OnlineOpen --> OnlineAction["Mark present/absent for that online session"]
    OnlineAction --> Online

    subgraph Offline["Offline (spotty floor wifi)"]
      direction LR
      Queue["Scans queued client-side<br/>(IndexedDB, offline_queue.js)"]
      Queue -->|connectivity restored| Replay["POST /checker/replay<br/>server re-validates every queued scan<br/>through the same resolver as live scans"]
    end
    CamC -.->|no connection| Queue
```

**Screens:**
- **Floor view** (`checker/floor.html` + `_floor_rows.html`) — the checker's main dashboard: which
  rooms on their assigned floor(s) still need a walk-by, polled/refreshed via HTMX rows.
- **Scan a room** (`checker/scan.html`) — same QR/manual-code mechanic as Faculty's scan, but
  resolves *who's expected in this room right now* rather than the checker's own schedule.
- **Online to verify** (`checker/online_list.html` → `online_open.html`) — for checkers on
  *online-duty* assignment: a list of online sessions to confirm via Teams instead of a room walk.
- **Offline replay** is invisible as a "screen" — it's the same Scan UI, but failed submits queue
  locally and flush to `/checker/replay` later; the user experience is "it just works" even with
  no signal.

## 3. Dean

No persistent nav; single surface today.

```mermaid
flowchart TD
    Home(["/ home launcher"]) --> Queue["Modality approvals<br/>/dean/requests<br/>pending shift requests from your department"]
    Queue -->|Approve| Approve["POST /dean/requests/&lt;id&gt;/approve"]
    Queue -->|Reject| Reject["POST /dean/requests/&lt;id&gt;/reject"]
    Approve --> QueueUpdated["HTMX-refreshed queue (_queue.html)<br/>+ Faculty notified"]
    Reject --> QueueUpdated
    QueueUpdated --> Queue
```

**Screens:**
- **Modality approvals** (`dean/queue.html` + `_queue.html`) — the only wired Dean surface. Approve
  triggers room re-assignment/release inside `scheduling/services.py` (not visible to the Dean —
  they just see the request disappear from the pending queue and the Faculty gets notified).
  "Department oversight" (`#`) is a Phase 6 stub card on the home launcher.

## 4. IFO Admin

No persistent nav; three live surfaces + one stub.

```mermaid
flowchart TD
    Home(["/ home launcher"]) --> Rooms["Rooms<br/>/ifo/rooms<br/>grouped by building/floor"]
    Home --> Live["Live today<br/>/ifo/live<br/>room-by-room status, polled"]
    Home --> Assign["Assignments<br/>/ifo/assignments<br/>post Checkers/Guards, grant online duty"]
    Home -.-> Reports["Reports (stub, Phase 6)"]

    Rooms -->|select room| Detail["Room detail<br/>/ifo/rooms/&lt;code&gt;<br/>that room's schedule today"]
    Detail --> Poster["Print QR poster<br/>/ifo/rooms/&lt;code&gt;/poster<br/>(also serves raw /qr.png)"]
    Detail --> Rooms

    Live -->|auto-refresh| LiveRows["_live_rows.html fragment<br/>updates without full reload"]

    Assign -->|new assignment| Form["_assignment_form.html<br/>pick Checker/Guard, floor(s)/room, window"]
    Form -->|submit| AssignPost["POST /ifo/assignments/create"]
    AssignPost --> Assign
```

**Screens:**
- **Rooms** (`ifo/rooms.html`) — building → floor → room browse; each room links to its **Room
  detail** (`room_detail.html`, that room's schedule for today) and from there to its **QR poster**
  (`poster.html`, printable, plus a raw `qr.png` endpoint used by the poster image itself).
- **Live today** (`ifo/live.html` + `_live_rows.html`) — campus-wide live occupancy, polled rows.
- **Assignments** (`ifo/assignments.html` + `_assignment_form.html`) — where Checker/Guard floor
  coverage and online-verification duty actually get posted; this is what makes the Checker's
  Floor view and Online list non-empty.
- **Reports** is a Phase 6 stub card — no screen behind it yet.

## 5. HR Admin

Fully stubbed today — one home-launcher card, no live screen.

```mermaid
flowchart LR
    Home(["/ home launcher"]) -.-> Att["Attendance (stub, Phase 6)<br/>verified records, CSV export — not built yet"]
```

## 6. Guard

Fully stubbed today — two home-launcher cards, no live screens.

```mermaid
flowchart LR
    Home(["/ home launcher"]) -.-> Mon["Floor monitor (stub, Phase 6)<br/>read-only live room status"]
    Home -.-> Loc["Faculty locator (stub, Phase 6)<br/>find a professor on campus"]
```

## 7. System Admin

Bypasses FluxTrack's own UI entirely — routed straight into Django admin.

```mermaid
flowchart LR
    Home(["/ home launcher"]) --> Users["Users & settings<br/>/admin/<br/>Django admin: provision users, policy values"]
    Home --> Audit["Audit log<br/>/admin/ops/auditlog/<br/>every write event, read-only"]
```

No custom FluxTrack templates for this role — both cards link into the stock Django admin site,
which is why `is_staff` users additionally get an **Admin** shortcut baked into every header (§ above).

---

## Cross-role notes

- **QR scanning is the one mechanic two roles share** (Faculty check-in, Checker verification) but
  it means different things: Faculty confirms *their own* attendance; Checker confirms *someone
  else's*. Same camera UI, same resolver shape server-side (see `ARCHITECTURE.md` §6), different
  question being answered.
- **Nothing routes a user into another role's screens.** Every view module has its own
  `*_required` decorator (`faculty_required`, `checker_required`, `dean_required`, `ifo_required`);
  a wrong-role request is refused, not redirected.
- **Stub cards (`href: "#"`) render but go nowhere** — Reports (IFO), Department oversight (Dean),
  Attendance (HR Admin), Floor monitor + Faculty locator (Guard). These are Phase 6 scope, not
  broken links.

*Companion documents: [`docs/ARCHITECTURE.md`](./ARCHITECTURE.md) (software/request-flow
architecture) · [`docs/IT_ARCHITECTURE.md`](./IT_ARCHITECTURE.md) (deployment topology).*

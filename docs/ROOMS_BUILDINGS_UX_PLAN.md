# Rooms & Buildings UX Plan

Status: Design-approved and engineering-reviewed; ready to implement
Owner: IFO Admin experience  
Date: 2026-07-25

## Decision Summary

Combine the current Rooms and Buildings navigation items into one
**Rooms & buildings** workspace. Keep the fast operational room board, but place
it beside a searchable directory that exposes the building → floor → room
hierarchy without making users switch screens.

**Live is the default mode.** This preserves the IFO team's daily operational
workflow and the behavior of the existing `/ifo/rooms` route. Directory is one
click away and keeps its search and filters in the URL.

The physical campus has exactly three current buildings:

1. **ACAD — Academic Building**
2. **ADMIN — Admin Building**
3. **GYM — Gym**

`IT` is not a building. `IT-301`, `IT-302`, and `IT-303` are IT lab rooms on
Academic Building Floor 3. `ONLINE` and `UNASSIGNED` are system record groups,
not physical campus buildings.

## Problem

The existing Rooms board is strong for live monitoring and already supports
search and building chips, but it presents every database group as though it
were a physical building. The separate Buildings screen is CRUD-first, pushes
the campus list below a large create form, and loses its Manage action off the
right edge on mobile.

This creates four UX problems:

- users must switch pages to understand a room's building and floor;
- `IT`, `ONLINE`, and `UNASSIGNED` appear beside real buildings;
- adding a building is visually more important than finding an existing space;
- the mobile building table is not reliably actionable.

## Goals

- Make live room status the fastest answer for daily IFO operations.
- Make every physical room findable by code, name, building, floor, or type.
- Let IFO manage a building, floor, or room from the same directory context.
- Represent the three-building campus accurately.
- Treat IT lab as a room type, not a location.
- Keep virtual and unresolved import records visible without calling them
  buildings.
- Preserve current room URLs, QR workflows, polling, and role permissions.

## Information Architecture

```text
IFO navigation
└── Rooms & buildings
    ├── Live
    │   ├── Search
    │   ├── Physical building filter
    │   ├── Attention/status filters
    │   └── Live room tiles → room detail drawer
    └── Directory
        ├── Search
        ├── Filters
        │   ├── Building: Academic | Admin | Gym
        │   ├── Floor: dependent on building
        │   ├── Room type: Classroom | IT lab | Gym | Other
        │   ├── Service: In service | Out of service
        │   └── Record type: Physical | Virtual | Unassigned
        ├── Physical campus
        │   └── Building → floor → room results
        └── System records
            ├── Virtual rooms
            └── Unassigned rooms
```

Constraint priority for the first viewport:

1. Search for a room.
2. See rooms needing attention now.
3. Narrow by physical building.

Creating or renaming structure is important but infrequent, so it stays
available as a secondary action rather than occupying the first viewport.

## Primary Screen

### Header

- Title: **Rooms & buildings**
- Supporting count: physical room count by default; result count when filtered.
- Primary action: **Add room**
- Secondary **Add** menu: Add floor, Add building.
- Existing notification and console controls remain unchanged.

### Mode switch

Use a two-option segmented control:

- **Live** — default; room state, current session, faculty, next session,
  attention.
- **Directory** — inventory, location, capacity, room type, service state.

Both modes share the same search field and preserve the query in the URL.

### Search

Visible label: **Search rooms**  
Placeholder: `Room code, name, building, or faculty`

Behavior:

- case-insensitive partial matching;
- matches room code, room name, building code/name, and floor in both modes;
- additionally matches current faculty/course in Live mode;
- 250 ms debounce;
- `/` focuses search when focus is not already in a field;
- Escape clears the query;
- query is reflected in `?q=` so filtered views can be bookmarked.

### Filters

Desktop shows one compact filter row. Mobile shows Search first and a
44-pixel **Filters (n)** button that opens a bottom sheet.

Physical building choices are:

- All physical buildings
- Academic
- Admin
- Gym

Do not render IT, Online, or Unassigned as building chips.

Directory adds:

- Floor, dependent on the selected building;
- Room type;
- Service state;
- Record type.

Live adds:

- Needs attention;
- In session;
- Starting;
- Free;
- Idle.

Active filters appear as removable chips below Search. **Clear all** appears
only when at least one filter or query is active.

## Directory Layout

### Desktop (≥ 1024 px)

Use a two-column workspace, not a grid of decorative cards:

- 240 px left rail: the three physical buildings with room/floor counts and an
  expandable floor tree.
- flexible main area: result toolbar and a dense room table.

Selecting a building or floor updates the results and URL. A trailing overflow
menu on the selected building/floor exposes Rename, Add floor, and Remove when
allowed.

Room columns:

- Room
- Name / type
- Building & floor
- Capacity
- Service
- Current status
- Row action

Selecting a row opens the existing room detail drawer. Edit, QR poster, service
state, and delete remain in that drawer/full room page.

### Tablet (641–1023 px)

Replace the fixed building rail with a horizontal building switcher. Keep the
room table, allowing low-priority columns to collapse into the room subtitle.

### Mobile (≤ 640 px)

- Search remains first.
- Filters open in a bottom sheet.
- Building selection uses a single-select list inside the filter sheet.
- Results become compact room rows, not two-column status tiles in Directory.
- Each row shows room code, name/type, location, and service/current state.
- Structure actions live in an overflow menu with 44 px targets.
- Live mode keeps the existing two-column operational tiles.

## Building and Floor Management

Building management is contextual:

- select Academic, Admin, or Gym in Directory;
- open **Manage building** from the building rail/switcher menu;
- edit code/name, add floors, and review deletion blockers in a side drawer on
  desktop or full-screen sheet on mobile;
- floor rows show room counts and can be selected to filter the directory;
- destructive actions keep the existing dependency-aware refusal and audit log.

Because adding buildings is rare, **Add building** belongs in the header Add
menu. It must not be a full-width form above the campus inventory.

## Campus Data Correction

Implement a guarded, reversible data migration. The migration is atomic and
fails loudly instead of guessing when production data differs from the expected
campus shape:

1. Ensure Academic Building Floor 3 exists.
2. Move `IT-301`, `IT-302`, and `IT-303` to Academic Building Floor 3 by
   updating their floor foreign key. Preserve room IDs, schedules, sessions,
   QR tokens, manual codes, and audit history.
3. Classify those rooms as `IT lab`.
4. Before deleting anything, require the `IT` building to contain no rooms
   other than those three exact codes and no unexpected floors. If it does,
   raise a diagnostic `RuntimeError` and roll back the entire migration.
5. Delete the now-empty `IT` floor and building records.
6. On reverse, recreate `IT` Floor 3 only when at least one exact room is still
   on ACAD Floor 3 in the migrated state. Move only those still-matching rooms;
   preserve any room that an operator moved elsewhere after deployment.
7. Treat an already-corrected database as a valid no-op, but never move a
   similarly named or unexpected room.
8. Update `seed_demo` so it creates those rooms under ACAD Floor 3 and remains
   idempotent without recreating the `IT` building.
9. Keep importer prefix behavior unchanged: `R` → ACAD, `A` → ADMIN,
   `GYM` → GYM, `V` → ONLINE.

After the move, the physical inventory remains **119 rooms**: Academic 74,
Admin 39, and Gym 6. The migration changes classification and location, not the
number of physical rooms.

Add a stable `Room.room_type` choice field:

- `CLASSROOM` (default)
- `IT_LAB`
- `GYM`
- `OTHER`

This makes “IT lab” searchable/filterable without encoding it as a building.
The data migration backfills exact IT room codes as `IT_LAB`, physical rooms in
GYM as `GYM`, other physical rooms as `CLASSROOM`, and virtual/unassigned
records as `OTHER`. Room create/edit exposes this field, validates it against
the model choices, preserves rejected values, and includes it in audit payloads.

## System Records

`ONLINE` and `UNASSIGNED` remain in the database because they serve distinct
operational purposes, but the UI presents them under **System records**:

- **Virtual rooms** — online-only schedule placeholders; never physical
  capacity.
- **Unassigned rooms** — import records requiring data cleanup.

They are excluded from the physical building count and physical building
filter. An Unassigned count badge should link directly to
`record_type=unassigned`.

Classification has one reusable source of truth:

- reserved system building codes are `ONLINE` and `UNASSIGNED`;
- every non-reserved building is physical, so a future real building works
  without adding another view/template allowlist;
- a room is Virtual when its existing `is_virtual` convention is true,
  Unassigned when it belongs to `UNASSIGNED`, and Physical otherwise;
- reserved system groups are read-only through physical building/floor CRUD.

Do not add a second `Building.kind` column. The importer and `Room.is_virtual`
already own the source conventions, so duplicating them would create a
synchronization problem.

## Roles and Actions

| Action | IFO Admin | Other app roles |
|---|---:|---:|
| View live room status | Yes | Existing role-specific surfaces only |
| Search physical room directory | Yes | No new access in this change |
| Create/edit room | Yes | No |
| Manage building/floor | Yes | No |
| Change room service state | Yes | No |
| Rotate QR credentials | Yes | No |
| Delete structure | Yes, with existing blockers and audit | No |

This merge changes navigation and presentation, not authorization.

## Interaction States

| Feature | Loading | Empty | Error | Success | Partial |
|---|---|---|---|---|---|
| Live board | Existing tiles stay visible with “Updating…” stamp | Explain nothing is scheduled; link to Directory | Keep last good board and show reconnecting | Update timestamp and results | Show available groups while one poll is stale |
| Directory results | Six compact row skeletons | “No rooms match” with Clear filters | Inline retry region; keep filters | Result count + rows | Show rows and identify unavailable metadata |
| Search | Small progress indicator only for server requests | Explain which query had no matches | Preserve query and offer Retry | Highlight matching text accessibly | Return available matches |
| Filter sheet | Controls available immediately | Dependent Floor control says “Choose a building first” | Preserve selections | Apply and announce result count | Disabled unavailable choices show why |
| Structure drawer | Section skeletons | No floors: Add first floor | Inline error beside failed section | Toast plus updated counts | Other sections remain usable |
| Migration cleanup | Not user-facing | IT group disappears when empty | Admin diagnostic; no destructive fallback | IT labs appear under ACAD F3 | Flag unmoved rooms for manual review |

## User Journey

| Step | User does | Intended feeling | Design support |
|---|---|---|---|
| 1 | Opens Rooms & buildings | Oriented in under five seconds | Search, Live/Directory switch, three building choices |
| 2 | Searches or filters | In control | Instant feedback, visible active filters, result count |
| 3 | Opens a room | Confident it is the right space | Code, location, type, and current state stay visible |
| 4 | Acts on the room | Safe | Role-correct actions, confirmations, dependency blockers |
| 5 | Returns to results | Not disoriented | Drawer closes to the same scroll/filter state |

Time horizon:

- **5 seconds:** the operator can find search and see whether rooms need attention.
- **5 minutes:** the operator can locate, inspect, and manage any room without
  changing navigation context.
- **5 years:** the hierarchy can accept a future real building without turning
  room types or system buckets into fake campus locations.

## Accessibility

- Search has a persistent visible label or accessible name.
- All controls and rows are keyboard reachable.
- Segmented controls expose current selection with `aria-current`.
- Filter chips use `aria-pressed`; the filter sheet traps focus and returns it
  to the opener.
- Result count updates use a polite live region.
- Status never depends on color alone.
- Touch targets are at least 44 × 44 px.
- Focus remains on the triggering room after the detail drawer closes.
- Reduced-motion behavior keeps drawer transitions nonessential.

## URL and Compatibility

- Canonical workspace: `/ifo/rooms`
- Live default: `/ifo/rooms` (accept `?view=live` as an explicit equivalent)
- Directory: `/ifo/rooms?view=directory`
- Filters: `q`, `building`, `floor`, `room_type`, `service`, `record_type`,
  and live `status`.
- Redirect only the GET `/ifo/buildings` list to
  `/ifo/rooms?view=directory`.
- Keep building detail and all structure mutation URLs stable. Building detail
  renders a drawer partial for `HX-Request` and the existing complete page for
  direct navigation, bookmarks, and non-JavaScript recovery.
- Keep all existing room detail, edit, poster, rotation, and delete URLs.

## Engineering Architecture

Live and Directory share a shell and URL-state contract, not a data-loading
pipeline:

```text
GET /ifo/rooms
│
├── view missing | live | invalid
│   ├── normalize to Live
│   ├── render persistent toolbar + drawer host
│   └── two-query live board
│       ├── rooms + floor + building
│       └── today's sessions + schedule + faculty
│
└── view=directory
    ├── parse allowlisted query state
    ├── filter Room queryset
    ├── paginate 50 rooms
    ├── select_related floor + building
    ├── fetch today's sessions for visible room IDs
    └── render hierarchy counts + directory results (no polling)
```

The shared query-state parser owns defaults, allowlists, URL serialization, and
active-filter counting. Unknown filter values are ignored safely; an invalid
`view` falls back to Live; out-of-range pages use the existing pagination
clamping behavior. A valid floor/building mismatch produces zero results rather
than silently changing the requested filter.

Directory work is bounded to the visible page:

- filter and paginate before deriving current room status;
- use `select_related("floor__building")`;
- load today's sessions for only the visible room IDs in one query and group
  them in memory;
- load annotated physical building/floor counts in a separate bounded query;
- do not call `_room_board()` from Directory and do not perform template-time
  relation queries;
- enforce the query budget with `assertNumQueries`.

At the current inventory size, additional caching and new substring-search
indexes are not justified. The 50-row page, batched relations, and 250 ms
debounce provide sufficient headroom without cache invalidation complexity.

## Component Boundaries

Keep the existing room-state oracle and CRUD services. Add narrow orchestration
helpers instead of parallel business logic:

- model/query helpers own physical/system classification;
- one directory-state parser and queryset builder own GET filtering;
- one building-detail context builder feeds both full and partial templates;
- structure mutation functions continue to own validation, audit, and blocker
  logic;
- an HTMX response helper returns refreshed drawer markup for partial requests
  and preserves redirect/flash behavior for ordinary requests;
- database uniqueness remains the final concurrency guard. Building, floor,
  and room mutations catch `IntegrityError` from check-then-insert/edit races
  and return the same friendly validation state instead of a 500.

Structure mutation response contract:

```text
POST structure action
├── validate / re-check blockers / attempt write atomically
│   ├── validation or uniqueness race
│   │   ├── HX request → drawer partial, status 400, sticky values
│   │   └── normal request → full-page feedback, no data changed
│   └── success
│       ├── HX request → refreshed partial or 204 close event
│       │                + roomsStructureChanged event
│       └── normal request → existing redirect + flash
└── Directory listens for roomsStructureChanged and refreshes rail/results
```

System groups reject physical structure mutations through the same response
contract. Deletion continues to re-check blockers at POST time and preserves
all existing audit events.

JavaScript is split by responsibility:

- `rooms-workspace.js` owns mode-independent URL state, keyboard shortcuts,
  mobile filter sheet behavior, drawer focus/close/restore, and structure-change
  refresh events;
- `live-board.js` owns local tile filtering, poll-swap reapplication, attention
  counts, and stale/reconnecting behavior;
- Directory search/results use server-rendered HTMX updates and the shared
  workspace controller; they do not inherit Live polling branches.

Update template references and source comments when `board.js` is split so the
polling and drawer ownership documentation remains accurate.

## Test Coverage Plan

Framework: Django `TestCase`/`TransactionTestCase` for model, migration, query,
and response contracts; Python Playwright as a development-only browser harness
for cross-component interaction flows.

```text
CODE PATHS                                      USER FLOWS
[+] campus migration                           [+] Rooms workspace
  ├── [GAP] forward move + identity              ├── [GAP →E2E] Live filter survives poll
  ├── [GAP] deterministic type backfill          ├── [GAP →E2E] Live ↔ Directory + back
  ├── [GAP] conflict abort + atomic rollback      ├── [GAP →E2E] Filter/page/open/close
  ├── [GAP] state-aware reverse                   └── [GAP →E2E] 375 px filter sheet
  └── [GAP] seed idempotency
[+] room type                                  [+] Structure management
  ├── [GAP] create/edit valid choices            ├── [GAP →E2E] invalid → recover → save
  ├── [GAP] invalid + sticky 400                  └── [GAP →E2E] blocker stays recoverable
  └── [GAP] audit + credentials unchanged
[+] rooms workspace                            [+] Failure feedback
  ├── [★★★ TESTED] existing Live states          ├── [GAP →E2E] poll failure keeps board
  ├── [GAP] mode/default/authorization            └── [GAP] mutation race is friendly
  ├── [GAP] search + every filter branch
  ├── [GAP] malformed/contradictory state
  ├── [GAP] record separation + counts
  └── [GAP] empty + pagination + query budget
[+] structure responses
  ├── [★★ TESTED] ordinary CRUD/blockers
  ├── [CRITICAL] full-page regression paths
  ├── [GAP] HX full/partial distinction
  ├── [GAP] HX success/error/blocker branches
  └── [GAP] reserved-group refusal

Coverage before implementation: existing Live/CRUD foundations are covered;
all 37 new or changed branches above are required before completion.
Browser coverage: 6 Playwright journeys, each exercised at desktop and mobile
where layout or interaction differs.
```

Required test files and assertions:

- add a campus migration test module using the existing `MigrationExecutor`
  pattern for forward, reverse, fail-loud, atomicity, identity/history, and
  seed-idempotency contracts;
- extend `web/tests_ifo_rooms.py` for every room-type choice, invalid/sticky
  input, audit payloads, and unchanged scan credentials;
- extend `web/tests_ifo_board.py` or add a focused directory test module for
  mode parsing, authorization, every search/filter branch, record separation,
  counts, empty states, pagination, and query budget;
- extend `web/tests_ifo_structure.py` for full-page regressions, HTMX
  success/error/blocker responses, reserved groups, and uniqueness races;
- add a development-only Playwright setup and six focused journeys for polling
  persistence, navigation history, Directory context restoration, structure
  recovery, reconnecting behavior, and mobile filters;
- run the complete Django suite plus Playwright, then visually verify 375, 768,
  and 1280 px with zero console errors.

## Production Failure Modes

| Path | Realistic failure | Test | Handling | User/operator feedback |
|---|---|---|---|---|
| Campus migration | IT contains unexpected rooms/floors | Migration conflict test | Atomic abort; no destructive fallback | Deployment diagnostic names mismatch |
| Migration reverse | Operator moved a migrated room later | Reverse-state test | Move only still-matching rooms | Rollback log; later location preserved |
| Directory query | Unknown or stale filter/page | View tests | Ignore unknown values; clamp page | Valid results/empty state, never 500 |
| Current status | No active term or no sessions | View tests | Batched empty mapping | Neutral available/idle state |
| Live poll | Network/500 response | Playwright | Keep last good DOM | “Reconnecting…” stale label |
| Drawer validation | Invalid input | HTMX/full response tests | No write; sticky partial/full form | Inline message beside failed section |
| Concurrent create/edit | Unique value claimed after pre-check | Race regression test | Catch `IntegrityError`; rollback | Same friendly duplicate message |
| Structure delete | Blocker appears after drawer opened | Existing + HTMX blocker tests | Re-check on POST | Named refusal; record preserved |
| System record action | Crafted mutation targets ONLINE/UNASSIGNED | Authorization/structure test | Reject as non-physical | Clear read-only explanation |
| Browser history | Back/close after filtered drill-down | Playwright | URL is source of truth; restore focus/scroll | Prior results return unchanged |

No path above may fail silently. A failure without both handling and a test
blocks implementation completion.

## Implementation Tasks

Synthesized from design and engineering review. Each task is independently
verifiable; check it off only after its named tests pass.

- [ ] **T1 (P1, human: ~2h / Codex: ~20m)** — Campus model — Add room types
  and centralized physical/system record classification.
  - Surfaced by: Architecture issues 3 and 5.
  - Files: `campus/models.py`, campus migration files.
  - Verify: model-choice and classification unit tests.
- [ ] **T2 (P1, human: ~4h / Codex: ~40m)** — Campus migration — Perform the
  guarded IT-to-ACAD move and deterministic room-type backfill.
  - Surfaced by: Architecture issue 1.
  - Files: campus migration files, `accounts/management/commands/seed_demo.py`.
  - Verify: forward/reverse/conflict/identity/idempotency migration tests.
- [ ] **T3 (P1, human: ~3h / Codex: ~25m)** — Room CRUD — Make room type
  editable, validated, sticky on errors, and audited.
  - Surfaced by: Code-quality issue 6.
  - Files: `web/ifo.py`, `templates/ifo/room_form.html`,
    `web/tests_ifo_rooms.py`.
  - Verify: room create/edit validation, audit, and credential regression tests.
- [ ] **T4 (P1, human: ~4h / Codex: ~35m)** — Workspace shell — Merge
  navigation and add Live/Directory URL-state parsing.
  - Surfaced by: Architecture issue 4.
  - Files: `web/ifo.py`, `templates/ifo/_console.html`,
    `templates/ifo/rooms.html`, `web/urls.py`.
  - Verify: mode/default/authorization and navigation tests.
- [ ] **T5 (P1, human: ~5h / Codex: ~45m)** — Directory query — Implement
  allowlisted search/filter/pagination with physical/system separation.
  - Surfaced by: Architecture issues 3–4 and Performance issue 14.
  - Files: `web/ifo.py`, focused query helpers.
  - Verify: every filter, malformed state, counts, pagination, and query budget.
- [ ] **T6 (P1, human: ~6h / Codex: ~55m)** — Directory UI — Build the
  responsive hierarchy, table/rows, filters, active chips, and all states.
  - Surfaced by: approved design specification.
  - Files: IFO room templates and `static/css/board.css`.
  - Verify: template tests and visual checks at 375, 768, and 1280 px.
- [ ] **T7 (P1, human: ~4h / Codex: ~35m)** — Frontend boundaries — Split
  workspace/drawer behavior from Live polling and add URL/history behavior.
  - Surfaced by: Code-quality issue 7.
  - Files: `static/js/rooms-workspace.js`, `static/js/live-board.js`, templates.
  - Verify: Playwright navigation, polling, focus, and mobile-filter journeys.
- [ ] **T8 (P1, human: ~5h / Codex: ~45m)** — Structure responses — Add
  drawer-aware rendering without duplicating CRUD logic.
  - Surfaced by: Architecture issue 2 and Code-quality issue 8.
  - Files: `web/ifo.py`, structure templates, `web/tests_ifo_structure.py`.
  - Verify: HTMX success/error/blocker plus full-page regression tests.
- [ ] **T9 (P1, human: ~2h / Codex: ~20m)** — Mutation safety — Convert
  uniqueness races into friendly atomic validation responses.
  - Surfaced by: production failure-mode audit.
  - Files: room/structure mutation helpers and their tests.
  - Verify: simulated `IntegrityError` never becomes a 500 or partial write.
- [ ] **T10 (P2, human: ~2h / Codex: ~15m)** — Compatibility — Redirect only
  the old building list and retain detail/mutation and room deep links.
  - Surfaced by: Architecture issue 2.
  - Files: `web/ifo.py`, `web/urls.py`, navigation templates.
  - Verify: legacy list redirect and full-page detail/action tests.
- [ ] **T11 (P1, human: ~7h / Codex: ~60m)** — Django coverage — Add the full
  server-side test matrix and mandatory full-page regressions.
  - Surfaced by: Test issues 9–12.
  - Files: campus migration tests and IFO room/directory/structure tests.
  - Verify: `python manage.py test`.
- [ ] **T12 (P1, human: ~9h / Codex: ~90m)** — Browser coverage — Add the
  Python Playwright development harness and six cross-component journeys.
  - Surfaced by: Test issue 13.
  - Files: development requirements/configuration and browser tests.
  - Verify: Playwright suite at desktop/mobile widths with zero console errors.
- [ ] **T13 (P1, human: ~2h / Codex: ~20m)** — Documentation — Update
  architecture, user-flow, and source comments that still describe Live/All or
  a separate Buildings page.
  - Surfaced by: code-quality documentation audit.
  - Files: `docs/ARCHITECTURE.md`, `docs/USER_FLOWS.md`, touched source comments.
  - Verify: repository search finds no stale Live/All or separate-nav contract.
- [ ] **T14 (P1, human: ~2h / Codex: ~20m)** — Final verification — Run all
  automated and responsive checks against the production implementation.
  - Surfaced by: acceptance and failure-mode review.
  - Files: no product files unless verification finds a defect.
  - Verify: Django + Playwright green; 375/768/1280 visual QA; no console errors.

## Acceptance Criteria

- Only Academic, Admin, and Gym appear as physical buildings.
- Opening `/ifo/rooms` lands on Live; Directory remains one click away.
- `IT-301`, `IT-302`, and `IT-303` retain their IDs and histories and appear as
  IT labs on ACAD Floor 3.
- Search finds rooms by code, name, building, floor, room type, and live faculty.
- Filters are URL-backed, keyboard accessible, and usable at 375 px.
- Virtual and Unassigned records remain reachable but do not inflate physical
  building or room counts.
- IFO can complete existing room, floor, and building actions from the combined
  workspace.
- Closing a room or structure drawer restores prior search, filters, and scroll.
- Existing permissions, QR links, polling, audit logs, and deletion blockers
  continue to work.
- Directory status rendering stays within the asserted query budget for a
  50-row page.
- Building/floor mutations never swap a complete console page into a drawer and
  never expose uniqueness races as 500 responses.
- The full Django and Playwright suites pass, including desktop/mobile user
  journeys and full-page compatibility regressions.

## Not in Scope

- A graphical campus map; the current need is findability and management.
- Bulk room editing; this should follow after the directory proves stable.
- New permissions for non-IFO roles.
- Changing attendance or utilization calculations.
- Renaming historical room codes.
- Changing importer prefix conventions or the existing virtual-room code rule.
- Adding a persisted `Building.kind`; centralized derived classification is
  sufficient and avoids duplicated state.
- Search infrastructure, new substring indexes, or result caching; the current
  119 physical rooms do not justify their invalidation and operations cost.
- Removing building detail or mutation URLs; they remain compatibility and
  non-JavaScript recovery endpoints.
- Production Node.js or browser dependencies. Playwright is development/test
  tooling only and does not change the deployed Django runtime.

## What Already Exists

- `_room_board()` already batches rooms and today's sessions in two queries;
  Live keeps this path rather than rebuilding status logic.
- `web/room_state.py` remains the single room-status oracle for Live and
  Directory.
- The responsive Live board, reconnecting label, local room/faculty filtering,
  and poll-swap reapplication are retained in the Live-only controller.
- The accessible room detail drawer already traps focus and restores it to the
  opener; the shared workspace controller generalizes it for Directory and
  structure management.
- Room create/edit/delete, QR poster, credential rotation, and service-state
  actions remain canonical; room type extends their existing form/audit path.
- Building/floor CRUD already has dependency-aware deletion and audit logging;
  the drawer reuses those mutations through a dual full/partial response
  contract.
- `campus.services` blocker probes remain the deletion authority.
- `web.pagination.paginate` already clamps invalid/out-of-range pages and
  preserves query strings; Directory reuses it.
- The importer already distinguishes ACAD, ADMIN, GYM, ONLINE, and UNASSIGNED;
  its prefix behavior remains unchanged.
- Existing console tokens, responsive patterns, and Django authorization
  decorators are reused rather than replaced.

## Workstream and Dependency Plan

| Step | Modules touched | Depends on |
|---|---|---|
| Campus model and classification | `campus/` | — |
| Data migration and demo seed | `campus/`, `accounts/management/` | Campus model |
| Room-type CRUD | `web/`, `templates/ifo/` | Campus model |
| Workspace modes and directory query | `web/` | Campus model/classification |
| Directory and responsive UI | `templates/ifo/`, `static/` | Workspace contract |
| Structure drawer responses | `web/`, `templates/ifo/` | Workspace contract |
| Compatibility routing | `web/`, `templates/ifo/` | Workspace + structure responses |
| Django coverage | campus/web test modules | Corresponding server contracts |
| Playwright coverage | browser-test tooling | Integrated UI and server contracts |
| Documentation and final QA | `docs/`, verification tooling | Integrated implementation |

Parallel lanes:

- **Lane A:** campus model → guarded migration → seed correction (sequential,
  shared `campus/` state).
- **Lane B:** room-type form/audit + mutation-race hardening, after the model.
- **Lane C:** workspace modes → directory query → structure responses →
  compatibility (sequential, shared `web/ifo.py` and routes).
- **Lane D:** responsive templates/styles → split JavaScript, after the
  workspace HTML contract; it can run alongside the latter half of Lane C with
  careful template ownership.
- **Lane E:** Django tests are written beside A–C; Playwright begins after C+D
  integrate; documentation/final QA run last.

Execution order: complete Lane A first. Launch B and the first half of C in
parallel. Once the workspace contract is stable, launch D while C finishes
structure compatibility. Merge and run Django coverage, then Playwright and
final responsive QA.

Conflict flags: Lanes C and D both touch IFO templates, and B/C both touch
`web/ifo.py`. Assign explicit function/template ownership or run those overlap
points sequentially; do not treat them as conflict-free worktrees.

## Distribution and Inline Documentation

No production artifact or deployment topology changes. Django continues to
serve server-rendered HTML and collected static assets. The Playwright harness
is development-only, documented with its browser-install and test commands; it
must not enter production requirements.

Keep concise inline ASCII comments in two non-obvious implementation points:

1. the Live-versus-Directory request/data-flow dispatcher in `web/ifo.py`;
2. the HTMX-versus-full-page structure mutation response helper.

Update or remove existing comments that say the page has a Live/All scope or
that `board.js` owns both filtering and drawer behavior.

## Engineering Review Summary

- Step 0 Scope Challenge: full implementation explicitly accepted.
- Architecture Review: 5 issues found; all recommended complete options
  accepted.
- Code Quality Review: 4 issues found, including the concurrency failure-mode
  finding; all complete fixes accepted.
- Test Review: coverage diagram produced; 37 new/changed branches and 6 browser
  journeys required.
- Performance Review: 1 issue found; bounded page-first batching and a
  query-count test accepted.
- Failure modes: 10 realistic paths documented; 0 silent critical gaps remain
  in the plan.
- NOT in scope: written.
- What already exists: written with explicit reuse decisions.
- TODOS.md updates: 0. Every review finding is included in this implementation,
  so no deferred engineering TODO was created.
- Outside voice: Codex preflight succeeded, but execution was skipped when the
  environment refused transmitting the internal plan; no external payload was
  sent.
- Parallelization: 5 lanes; B/C and later C/D can overlap, with shared-module
  conflict points kept sequential.
- Retrospective: recent commits fixed mobile action reachability, hidden
  columns, and ambiguous room-state language in these same surfaces. This plan
  therefore treats responsive actions, explicit state labels, and regression
  coverage as ship-blocking rather than cosmetic follow-up.
- Lake Score: 15/15 recommendations chose the complete option.

## Design Review Summary

| Pass | Initial | Final | Resolution |
|---|---:|---:|---|
| Information architecture | 8/10 | 10/10 | Live confirmed as the default; Directory remains adjacent and URL-backed. |
| Interaction states | 8/10 | 9/10 | Loading, empty, error, success, and partial behavior specified per feature. |
| User journey | 8/10 | 9/10 | Five-second, five-minute, and long-term behavior documented. |
| AI-slop risk | 8/10 | 9/10 | Uses a workspace hierarchy and dense rows rather than a decorative card grid. |
| Design-system alignment | 8/10 | 9/10 | Reuses the current console, board, drawer, tokens, and action vocabulary. |
| Responsive and accessibility | 8/10 | 9/10 | Mobile filter sheet, tablet collapse, keyboard, focus, live regions, and 44 px targets specified. |
| Unresolved decisions | 1 open | 0 open | Default mode resolved as Live. |

Overall design score: **8/10 → 9/10**.

## Design Reference

The responsive, local-only wireframe is
[`docs/rooms-buildings-wireframe.html`](rooms-buildings-wireframe.html). It was
verified at 375, 768, and 1280 px with no console errors. It is an interaction
and hierarchy reference, not production markup.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|---|---|---|---:|---|---|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | Not run | Full product scope was explicitly accepted during engineering review. |
| Codex Review | `/codex review` | Independent second opinion | 0 | Skipped | External transmission was refused; no plan payload was sent. |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | Clear | 47 issues/gaps resolved; 0 critical gaps and 0 unresolved decisions. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | Clear | Score 8/10 → 9/10; default mode resolved as Live. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | Not required | No production developer workflow changes. |

**VERDICT:** DESIGN + ENG CLEARED — ready to implement the full approved scope.

NO UNRESOLVED DECISIONS

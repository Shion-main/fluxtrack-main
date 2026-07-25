# Rooms & Buildings UX Plan

Status: Design-approved; ready for engineering review  
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

Implement a reversible data migration:

1. Ensure Academic Building Floor 3 exists.
2. Move `IT-301`, `IT-302`, and `IT-303` to Academic Building Floor 3 by
   updating their floor foreign key. Preserve room IDs, schedules, sessions,
   QR tokens, manual codes, and audit history.
3. Classify those rooms as `IT lab`.
4. Delete the now-empty `IT` floor and building records.
5. Update `seed_demo` so it creates those rooms under ACAD Floor 3.
6. Keep importer prefix behavior unchanged: `R` → ACAD, `A` → ADMIN,
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

## System Records

`ONLINE` and `UNASSIGNED` remain in the database because they serve distinct
operational purposes, but the UI presents them under **System records**:

- **Virtual rooms** — online-only schedule placeholders; never physical
  capacity.
- **Unassigned rooms** — import records requiring data cleanup.

They are excluded from the physical building count and physical building
filter. An Unassigned count badge should link directly to
`record_type=unassigned`.

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
- Keep `/ifo/buildings` and building detail URLs as redirects or compatibility
  routes during migration.
- Keep all existing room detail, edit, poster, rotation, and delete URLs.

## Implementation Tasks

- [ ] **T1 (P1)** — Campus data — Move IT lab rooms to ACAD Floor 3 and correct
  demo seeding without changing room identities.
- [ ] **T2 (P1)** — Room model — Add and backfill `room_type`.
- [ ] **T3 (P1)** — Navigation — Merge Rooms and Buildings into one
  Rooms & buildings entry with Live and Directory modes.
- [ ] **T4 (P1)** — Directory query — Add URL-backed search and filters with
  physical/system record separation.
- [ ] **T5 (P1)** — Directory UI — Build responsive building hierarchy, room
  results, active filters, and states.
- [ ] **T6 (P2)** — Structure management — Move building/floor CRUD into a
  contextual drawer/sheet while preserving audit and blockers.
- [ ] **T7 (P2)** — Compatibility — Redirect old building pages and preserve
  room deep links.
- [ ] **T8 (P1)** — Verification — Add model/migration/view tests and run visual
  QA at 375, 768, and 1280 px.

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

## Not in Scope

- A graphical campus map; the current need is findability and management.
- Bulk room editing; this should follow after the directory proves stable.
- New permissions for non-IFO roles.
- Changing attendance or utilization calculations.
- Renaming historical room codes.

## What Already Exists

- A responsive live room board with polling and accessible state labels.
- Client-side room/faculty search and building/attention chips.
- An accessible room detail drawer with focus return.
- Room create/edit/delete, QR poster, credential rotation, and service-state
  actions.
- Building/floor CRUD with dependency-aware deletion and audit logging.
- Existing console tokens and responsive patterns that this plan reuses.

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
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | Not run | Product scope is sufficiently defined for this change. |
| Codex Review | `/codex review` | Independent second opinion | 0 | Not run | No external design payload was sent. |
| Eng Review | `/plan-eng-review` | Architecture & tests | 0 | Required next | Validate migration, query shape, compatibility routes, and test plan. |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | Clear | Score 8/10 → 9/10; one default-mode decision resolved. |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | Not required | No developer-facing workflow change in this plan. |

**VERDICT:** DESIGN CLEARED — engineering review required before implementation.

NO UNRESOLVED DECISIONS

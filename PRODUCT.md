# Product

## Register

product

## Users

Staff of **Malayan Colleges Mindanao (MMCM), Davao City**, across seven roles:

- **Faculty** — check in to their scheduled class sessions (on campus or online); mostly on a phone, often rushed between rooms.
- **Checkers & Guards** — roam floors verifying that the right faculty is in the right room; phone-first, sometimes offline, need fast scan-and-confirm.
- **IFO admins** (Information & Facilities Office) — assign duties, manage rooms/schedules, watch live campus occupancy; desktop, task-focused.
- **Deans** — approve modality-shift requests; occasional, decision-oriented.
- **HR admins** — receive flags, monitor attendance records.
- **System admins** — operate the platform.

Shared context: an authenticated institutional tool used during the working day. The person is almost always *in a task* (verify a room, approve a request, check a schedule), not browsing.

## Product Purpose

FluxTrack is MMCM's **Faculty Attendance & Facility Utilization Information System**. It records whether faculty actually attend their scheduled sessions and how campus rooms are used, replacing manual roving-checker paperwork with a server-authoritative scan/verify flow, live occupancy, and reporting. Success = trustworthy attendance records that hold up as an official source of truth, captured with minimal friction on the floor.

## Brand Personality

Institutional, trustworthy, precise, calm. Three words: **official, dependable, unfussy.** It should feel like an accredited campus system of record — the tone of a registrar or facilities office, not a consumer app. Confidence comes from clarity and correctness, not decoration. The login is the one screen where MMCM's institutional identity is expressed; the working surfaces stay quiet so the task leads.

## Anti-references

- Generic SaaS login with a gradient hero, floating illustration, and "Welcome back 👋" copy.
- Consumer-app playfulness (bright multi-color, mascots, bouncy motion).
- Dark "developer tool" aesthetic — this is an institutional record system, not a terminal.
- Over-decorated dashboards: card grids of identical tiles, big-number hero metrics, decorative charts.
- Anything that makes an attendance record feel casual or unofficial.

## Design Principles

- **Trust is the product.** Attendance and facility records are used as official evidence. The UI must read as credible and precise everywhere it shows state — especially the entry (login) and verification screens.
- **Earned familiarity.** Behave like the institutional/enterprise tools staff already trust. Standard affordances, no invented controls, no strangeness without purpose.
- **The tool disappears into the task.** Identity and warmth live at entry points (login); working surfaces stay quiet and dense so the task, not the chrome, leads.
- **State-complete by default.** Every interactive element ships default/hover/focus/active/disabled/loading/error. In an attendance system, an ambiguous state is a correctness bug.
- **Phone-first reality.** Checkers, guards, and faculty use this on phones, on the floor, sometimes offline. Layouts collapse to a real single-column experience, not a squeezed desktop.

## Accessibility & Inclusion

Target **WCAG 2.1 AA** (institutional/public-sector expectation): body text ≥4.5:1, large text/UI ≥3:1, visible keyboard focus on every control, full keyboard operability, and honored `prefers-reduced-motion` (motion conveys state only). Touch targets ≥44px for floor use. No information conveyed by color alone (attendance/verification states also carry text/icon).

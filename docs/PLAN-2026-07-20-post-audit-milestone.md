# Proposed Milestone v1.3 — "Operational Trust" (post-audit)

**Status:** PROPOSAL for review. Nothing here is committed to `.planning/ROADMAP.md`
yet. Once the shape and sequence are approved, these become real GSD phases.

**Where it came from:** the two audits in `docs/AUDIT-2026-07-19.md` (the SRS pass +
the 2026-07-20 mission-fit/UI addendum), minus the quick-wins already shipped
(H1, H2, M4, M7, seed_demo guard, red tests, dead utilities, offline drain).

**Framing.** The app is ~95% feature-built and the check-in/verify/utilization core
is sound. What remains is the difference between "demoable" and "a school can run a
real term on it": the record has to survive Philippine campus reality (typhoon
suspensions, holidays, corrections), the numbers the product promises have to be
visible (lateness, coverage), IFO has to manage the campus without a superuser, and
the whole thing has to deploy safely. That's this milestone.

**Recommended sequence (why this order):** mission-critical trust first, deploy last —
the same principle your ROADMAP already states ("deploy last so cutover never blocks
feature work"), reinforced by the fact that deploying a system that mass-marks Absent
on the first storm day would discredit it faster than shipping late would. The one
decision to make explicitly: **if the capstone defense needs a live URL sooner, we
pull the deploy phase forward — but Phase 9 should land before any real use regardless.**

```
9  Attendance Trust Under Real Operations   [CRITICAL — first]
        |
   +----+----+----------------+
   v         v                v
10 Campus  11 Mission       13 UX Finish     (10/11/13 can overlap)
   Structure   Metrics
   |         |
   +----+----+
        v
12 Term Lifecycle       (before the current term ends)
        v
14 Correctness & Concurrency Hardening
        v
15 Deploy Hardening & Cutover   (expands old Phase 8 — LAST)
        v
16 Documentation Pass           (documents the finished system)
```

---

## Phase 9 — Attendance Trust Under Real Operations  *(CRITICAL)*
**Addresses:** A1 (typhoon/suspension mass-absent), A2 (Absent-correction false promise),
A5 (IFO holiday/break entry).
**Goal:** the attendance record survives real operations — a class suspension or a
holiday never mass-marks the campus Absent, IFO can declare both without a superuser,
and a wrongly-Absent record has a real, audited correction path instead of a message
that lies.
**Depends on:** nothing new.
**Success criteria (what must be TRUE):**
1. A new terminal `CANCELLED` session status exists; a cancelled/suspended meeting is
   neither Absent nor held nor counted as booked in any report or utilization number.
2. IFO can suspend classes for a date or date range (optionally scoped to a building):
   affected already-materialized SCHEDULED sessions flip to CANCELLED, audit-logged,
   and future materialization skips those dates.
3. `sweep_no_shows` honors `AcademicBreak` **and** suspensions — no session on a
   covered date is ever marked Absent (closes the core typhoon-day defect).
4. IFO can create/edit/delete academic breaks & holidays from the console (no Django
   admin), and the sweep + materialize both respect them.
5. A checker or IFO admin can correct a wrongly-Absent session (reinstate → present or
   back to scheduled), audit-logged; the faculty "a Checker can correct it" message is
   now true (or is rewritten to match reality).
**Rough plans:** CANCELLED status + migration · IFO suspend-classes action + sweep/
materialize break+suspension guard · IFO break/holiday CRUD · Absent-correction action
+ message fix · report/utilization CANCELLED handling + tests.

## Phase 10 — Campus Structure Management
**Addresses:** Building/Floor CRUD (the just-confirmed gap), A7 (room out-of-service),
A9 (mid-term schedule edits).
**Goal:** IFO can manage the physical campus and the timetable end-to-end without a
superuser — buildings, floors, rooms (already done), out-of-service, and single-class
corrections.
**Depends on:** Phase 9 (reuses CANCELLED for a cancelled schedule meeting).
**Success criteria:**
1. IFO can create/edit/delete buildings and floors from the console, with PROTECT-aware
   delete (a building/floor still holding floors/rooms refuses by name, mirroring
   `room_delete`); the room-create form's floor picker shows newly-created floors.
2. A room can be taken out of service (`Room.is_active`/`out_of_service`): scans refuse
   with a clear reason, it cannot be booked, and it is dropped from the utilization
   denominator so a renovated room doesn't read as "wasted."
3. IFO can add / edit / cancel a single schedule meeting mid-term from a surface (not
   Django admin), and the safe mid-term re-import procedure is documented so a re-import
   can't duplicate sessions or orphan attendance.
**Rough plans:** building/floor CRUD + PROTECT probe · room out-of-service flag wired
into resolver/availability/utilization · single-schedule edit surface + re-import doc.

## Phase 11 — Metrics the Mission Promises
**Addresses:** A3 (lateness), A6 (verification coverage), A8 (utilization depth + the
deferred 06.1-07 CSV export).
**Goal:** the numbers the product exists to produce are actually visible — lateness,
how much was physically verified, and utilization deep enough for facilities to act.
**Depends on:** Phase 9 (CANCELLED excluded from denominators). Reuses
`scheduling/reporting.py`.
**Success criteria:**
1. Lateness (minutes late; chronic-lateness flag) is computed in the aggregate layer and
   shown on the faculty scorecard, the weekly report, and the HR export.
2. Verification coverage is an aggregate (verified / held, by building and day, incl.
   zero-coverage floors) on the IFO dashboard — a low-coverage week is visibly distinct
   from a well-covered one.
3. Utilization gains a capacity-vs-enrollment fit signal (room chronically too big/small),
   an actionable booked-but-never-used ("ghost room") list, and per-room CSV export
   (finishing 06.1-07); week-over-week trend if cheap.
**Rough plans:** lateness aggregate + 3 surfaces · coverage aggregate + dashboard card ·
capacity-fit + ghost-room list + CSV export.

## Phase 12 — Term Lifecycle
**Addresses:** A4 (no term rollover; reset_term destroys history).
**Goal:** a term can be closed and archived read-only and the next term created &
activated, without ever deleting attendance history.
**Depends on:** nothing — but must land before the current term ends.
**Success criteria:**
1. A term-close flow marks a term inactive and preserves its Schedule/Session rows
   read-only (no delete); `DEFAULT_TERM` is no longer hardcoded.
2. A next-term create/activate flow stands up a new active term without touching prior
   terms' data; import/materialize target the active term.
3. All reports/exports scope to a selectable term (HR already filters by term — verify &
   extend to Dean/IFO where missing), so last term's records stay retrievable.
**Rough plans:** term-close + next-term commands/UI · DEFAULT_TERM de-hardcode · report
term-scope audit.

## Phase 13 — UX Finish
**Addresses:** B1 (error pages), B2 (orphan plain-base pages on phones), B3 (profile
reachability), B4 (login navy), B5 (global htmx errors), B6 (PWA theme).
**Goal:** the app reads as finished — no bare error pages, no shell jumps, one brand.
**Depends on:** nothing; can overlap Phases 10–12.
**Success criteria:**
1. Branded 403/404/500 templates + wired handlers keep a user oriented (a phone user who
   taps a wrong-role link gets a way home, not Django's white "Forbidden").
2. Floor roles (faculty/checker/guard) never jump into a desktop-family page — the
   notifications list/settings get a navy variant or floor-appropriate routing.
3. Profile is reachable from every faculty screen (account menu), not home-only; login
   uses the brand-navy token; the global htmx error listener shows a failure on every
   surface; the PWA theme_color matches the navy shell.
**Rough plans:** error templates + handlers · navy notifications · profile menu + login
token + global htmx error + PWA theme (batched polish).

## Phase 14 — Correctness & Concurrency Hardening
**Addresses:** the remaining traced edge-cases from the main audit — M3, M5, M6, H3.
**Goal:** close the last known ways the record can go wrong under real multi-user/offline
load.
**Depends on:** nothing; H3 has a client change, so before real offline checkers deploy.
**Success criteria:**
1. A booking beyond the materialize horizon can no longer silently collide with a
   timetabled class (booking checks Schedule occurrences, or materialize flags the clash) — M3.
2. The scan resolver prefers a window-containing candidate whose room matches the scanned
   room, so back-to-back sessions can't hijack each other's check-in — M5.
3. Modality withdraw/approve/reject use `select_for_update`, closing the last-writer-wins
   race — M6.
4. Offline replay applies a queued verification to the session the checker actually saw
   (client queues session_id; mismatch → replay_conflict), not whatever is in the room
   now — H3.
**Rough plans:** booking/schedule oracle · resolver room-prefer · select_for_update ·
replay retargeting (client + server).

## Phase 15 — Deploy Hardening & Cutover  *(expands the current Phase 8 — LAST)*
**Addresses:** the original Phase 8 (Entra SSO, EC2/RDS, Tailwind build) **plus** the ops
gaps the audit found that its scope would miss.
**Goal:** the feature-complete app deploys to AWS safely, over HTTPS, multi-worker-correct,
with a real operational story.
**Depends on:** Phases 9–14 (deploy the finished system).
**Success criteria:**
1. Original Phase 8: Entra ID SSO (Auth Code + PKCE) replaces the dev-login stub with a
   break-glass superuser; single EC2 (Nginx + Gunicorn + scheduler unit) over HTTPS
   against RDS SQL Server Express; Node-free Tailwind build replaces the CDN.
2. A shared cache backend (Redis or DB cache) backs every idempotency, rate-limit, and
   offline-replay-dedupe key — none rely on per-worker LocMem; multi-worker is correct.
3. HTTPS/proxy config is complete: `CSRF_TRUSTED_ORIGINS`, `SECURE_PROXY_SSL_HEADER`,
   secure cookies + HSTS, fail-fast on placeholder `SECRET_KEY`/`DEBUG=True`, env-driven
   SSO redirect URI, and a media public/private split (photos vs auth-gated report/import
   files).
4. Operational baseline: htmx + Franken JS + html5-qrcode vendored (not just Tailwind);
   scheduler resilience (`close_old_connections`, staleness alert, weekly-report startup
   backfill); LOGGING + error reporting; retention jobs (JobRun/session) + a written
   backup story incl. EC2-local media; gunicorn + a lock file; a health endpoint.
**Rough plans:** the original Phase 8 plans + a settings/cache/proxy plan + a vendoring
plan + a scheduler-resilience plan + a retention/backup plan.

## Phase 16 — Documentation Pass
**Addresses:** the whole "docs drift" section of the main audit + this milestone's new
features.
**Goal:** the SRS and planning docs match the built system for the defense.
**Depends on:** features complete (documents the final state).
**Success criteria:**
1. SRS v1.3 records every code-vs-spec divergence: MySQL→MSSQL, sessions-vs-JWT,
   S3→filesystem, JOB-02 room-release cut, CHK-02 online path, IFO-07 board, MOD-01
   window, **shadcn-via-Franken UI**, plus the new suspension/holiday/campus/lifecycle
   features.
2. IFO-04, SYS-01..03, and IFO-03's schedule-CRUD half are restored to the traceability
   register — either marked built (Phases 9–12 build most of them) or recorded
   out-of-scope with rationale, so "57/57, 0 orphans" is true of the SRS, not just a
   curated list.
3. PROJECT.md Active/Key-Decisions is refreshed; USE_CASES.md is marked superseded.
**Rough plans:** SRS v1.3 edit map + regenerate · traceability restore · planning-doc refresh.

---

## Open decision for you
**Deploy timing.** The sequence above puts deploy (Phase 15) last, matching your own
ROADMAP principle. The only reason to reorder: if the capstone defense needs a live,
deployed URL to demo, we pull Phase 15 forward. My strong recommendation is to still
land **Phase 9 first regardless** — a deployed system that mass-marks Absent on a
suspension day is a worse defense story than a late one. Everything else can flex.

*Proposed 2026-07-20 against code at `3acff75`.*

# Phase 2: Correctness Foundations - Context

**Gathered:** 2026-07-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend correctness infrastructure. This phase delivers:
1. A single shared `notify()` write-path service that creates `Notification` rows for any role/event, replacing the ad-hoc `_notify_ifo` in `web/scan.py`.
2. The JOB-02 status sweep: mark no-show sessions Absent independent of any scan, using the **same grace predicate the live scanner uses**, and raise room-conflict flags to IFO when occupancy is contradictory.
3. One dedicated APScheduler process running all scheduled jobs (materialize / sweep / weekly-report), never duplicated across web workers, with last-run status recordable.

No new user-facing surfaces ship this phase. The point is that "Absent" becomes trustworthy without relying on a scan, every notification flows through one write path, and all jobs run from one scheduler process.

**Scope change decided this session (see Deferred + Requirements Amendment below):** timer-based automatic room release is **cut from Phase 2**. Rooms are only released when a modality shift is approved (MOD-03, Phase 4). The `release_room()` helper is still built here for Phase 4 to call, but the sweep does not call it.

</domain>

<decisions>
## Implementation Decisions

### Sweep cadence & Absent latency
- The status sweep runs **every 5 minutes** via APScheduler. This interval IS the "within one sweep interval" guarantee in the success criterion — worst-case ~5 min from grace expiry to Absent.
- Chosen over 1 min (needless DB churn when grace is already 15 min) and 15 min (too slow for a live Checker/Dean view later).

### No-show detection (JOB-02a / JOB-02b)
- The sweep reuses the scan resolver's grace predicate (`now > scheduled_start + grace`, `grace = get_policy("grace_minutes")`) — extract/share ONE predicate so scan-time and sweep-time can never disagree on the same session. This is the highest-risk coupling in the phase.
- A pure decision function determines, for a given session and time, whether it is a no-show past grace (JOB-02a). The sweep (JOB-02b) applies it.
- **Backfill:** the sweep marks Absent **any** still-`scheduled` session whose grace has expired, regardless of date — not just today's. A scheduler outage self-heals on the next run; no ghost `scheduled` sessions linger from prior days.
- Only `SCHEDULED` sessions transition to `ABSENT`. `active`, `completed`, and already-`absent` sessions are never touched (idempotent — re-running the sweep changes nothing already decided). Mirrors the existing scan-time `_apply` guard (`if session.status == SessionStatus.SCHEDULED`).

### Room conflict flags (JOB-02c — release portion cut)
- The sweep **still raises room-conflict notifications** to IFO when occupancy is contradictory (e.g., two `active` sessions holding one room, or an `active` session overrunning into another session's scheduled slot). This safety net is independent of auto-release and stays in Phase 2.
- Conflict notifications are **deduped until resolved**: one notification per distinct conflict; do NOT re-notify on later sweeps while the same conflict is still unresolved. (Detect "already flagged" via an existing open flag/notification lookup — planner decides the exact dedup key/mechanism.)
- **No timer-based auto-release.** The sweep does NOT free rooms after a hold window. `room_released_at` is never stamped by the sweep.

### `release_room()` occupancy helper
- Build the shared `release_room()` helper in Phase 2 (stamps `Session.room_released_at`, single source of truth for releasing a room), fully tested.
- The sweep does NOT call it. Phase 4's modality-shift approval (MOD-03) calls it when a →Online shift is approved. Building it now keeps Phase 4 from re-opening this module.

### Shared `notify()` write path (NOTIF-00)
- One `notify()` service creates `Notification` rows for any role/event. It replaces `_notify_ifo` entirely — after this phase, `_notify_ifo` is gone from `web/scan.py` and no other inline `Notification.objects.create(...)` notifier remains outside `notify()`.
- Existing call sites to migrate: the two `_notify_ifo(...)` calls in `web/scan.py` (Room change ~L113, Force handover ~L129). Both must route through `notify()` with equivalent title/body/link.
- The new sweep conflict flags and the job-failure alerts (below) also go through `notify()`.
- Preserve the existing `Notification` fields (`user`, `type`, `title`, `body`, `link`) — no model changes required for NOTIF-00 itself. `notify()` targets a role (e.g. all active IFO admins) or a specific user.

### Scheduler process & job observability (ENV-04)
- APScheduler runs as **one dedicated process** — a second systemd service in prod (per the deployment spec), never inside a Gunicorn web worker. Jobs must not double-fire across workers.
- Jobs registered: materialize (JOB-01, existing command logic), sweep (JOB-02, new), weekly report (JOB-03, later phase — register the slot/wiring even if the report body lands in Phase 6).
- **Last-run status is recorded** (ok/failed, rows affected, timestamp) so the future SYS-04 dashboard (Phase 7) can read it. Introduce a small `JobRun`-style record (planner names/models it).
- **Job failure surfacing:** on a job **failure only**, fire `notify()` to System Admins (record every run's status, but only notify on failure). No success/heartbeat notifications.

### Claude's Discretion
- Exact module/function placement for the extracted grace predicate (likely `scheduling/resolver.py` or a small shared helper it imports).
- The `notify()` signature (role vs user targeting, kwargs) and where it lives (likely `ops/`).
- The `JobRun` model shape and where last-run status is stored.
- The conflict-detection query and the exact dedup key for room-conflict notifications.
- APScheduler wiring details (jobstore, executor, how the dedicated process is launched in dev vs prod).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing code to reuse / modify (source of truth)
- `scheduling/resolver.py` — pure scan resolver; the grace predicate (`now > scheduled_start + grace`, L89) MUST be the single shared no-show predicate. Stays a pure function, no side effects.
- `web/scan.py` — `_notify_ifo` (L63) + its two call sites (L113, L129) to migrate onto `notify()`; the `_apply` SCHEDULED→ABSENT guard (L90-94) is the idempotency pattern the sweep mirrors.
- `ops/models.py` — `Notification` model (L25), `AuditLog` (L56), `SystemSetting` (L76); the new `JobRun`-style record lands here or in `ops/`.
- `scheduling/models.py` — `Session` (L84), `SessionStatus` (L70), `Session.room_released_at` field (L112) that `release_room()` stamps.
- `scheduling/management/commands/materialize_sessions.py` — JOB-01 logic the scheduler wraps; the sweep should follow its ASCII-only, idempotent, `get_or_create` conventions.
- `config/settings.py` §FLUXTRACK_POLICY (L146) — `grace_minutes=15`, `room_hold_minutes=30` (kept for future use even though auto-release is cut), `materialization_horizon_days`. Values come from `get_policy()`, never hardcoded.

### Design specs
- `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md` §2 (L51-60) — APScheduler as a **second systemd service / dedicated process** on the same instance; satisfies SRS §6.7 "dedicated process."
- `docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md` — MOD-03 is the ONLY room-release path (why auto-release is cut here); shows how Phase 4 will call `release_room()`.

### Conventions
- `.planning/codebase/CONVENTIONS.md` — resolver stays pure; every write logs `AuditLog`; policy via `get_policy()`/`SystemSetting`; management commands print ASCII only (Windows cp1252); htmx partials `_name.html`.
- `FluxTrack_SRS.md` §6.6 (pure resolver), §6.7 (dedicated scheduler process).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `scheduling/resolver.py::resolve_faculty_scan` — already computes ABSENT via `now > scheduled_start + grace`. Extract this comparison into a shared pure predicate both the resolver and the sweep import.
- `ops.models.Notification` — target model for `notify()`; fields already sufficient (`user/type/title/body/link/read_at/created_at`).
- `web/scan.py::_notify_ifo` — the exact behavior `notify()` must subsume (fan out to all active IFO admins); becomes the first caller migrated.
- `materialize_sessions` command — proven idempotent job body the scheduler wraps as JOB-01; template for the sweep's structure and ASCII output.
- Policy defaults already present: `grace_minutes`, `room_hold_minutes`, `materialization_horizon_days`, `poll_interval_seconds`.

### Established Patterns
- Pure-decision-core + thin-apply-layer (resolver decides, `web/scan.py::_apply` mutates + audits). The sweep should follow the same split: pure `is_no_show(session, now, grace)` → sweep applies + audits.
- Idempotency guards on status transitions (`if session.status == SessionStatus.SCHEDULED`).
- Every state change writes an `AuditLog` row (e.g. `session.marked_absent`).
- No APScheduler, no `JobRun` model, and no shared `notify()`/`release_room()` exist yet — all net-new this phase.

### Integration Points
- Scan flow (`web/scan.py`) and the sweep share the grace predicate — change one, both move.
- `notify()` becomes the chokepoint for: scan-time room/handover events, sweep conflict flags, job-failure alerts, and every later phase's notifications (NOTIF-01/02/03, MOD-05, RPT-02).
- `release_room()` built here, consumed by Phase 4 (MOD-03).
- Last-run `JobRun` status consumed by Phase 7 (SYS-04 dashboard).

</code_context>

<specifics>
## Specific Ideas

- "No released room — we only release a room if the change modality was approved; no auto release for now." → auto-release cut from Phase 2; `release_room()` reserved for MOD-03 (Phase 4).
- Sweep must be safe to run repeatedly and must self-heal after a scheduler outage (backfill all past un-decided no-shows).
- Keep IFO's notification list clean — dedupe persistent room conflicts rather than re-flagging every 5 minutes.

</specifics>

<requirements_amendment>
## Requirements Amendment (approved this session)

The user approved amending the written requirements to match the no-auto-release decision. **The planner/orchestrator should apply these before or during planning so the plan-checker and verifier don't fail Phase 2 for an intentionally-cut capability:**

- **JOB-02c** (`REQUIREMENTS.md` L35) — reword: remove "releases a room after the room-hold window"; keep "raises a room-conflict flag (via `notify()`) when occupancy is contradictory." Note the `release_room()` helper is built in Phase 2 but **invoked by MOD-03 (Phase 4)**, not by the sweep.
- **Phase 2 Success Criterion #2** (`ROADMAP.md`) — reword from "A room is automatically released after its hold window through a single `release_room()` helper, and contradictory occupancy raises an IFO room-conflict notification" to: "Contradictory room occupancy raises a single (deduped) IFO room-conflict notification; the shared `release_room()` helper exists and is tested but is invoked only by the modality-approval flow (Phase 4), not on a timer."
- Rationale: auto-releasing a held room on a timer is unsafe when a class simply runs long; room lifecycle should be driven by explicit approved events (modality shift), not a clock.

</requirements_amendment>

<deferred>
## Deferred Ideas

- **Timer-based automatic room release** — moved out of Phase 2. Room release now happens only via approved modality shift (MOD-03, Phase 4). `room_hold_minutes` policy retained for possible future use.
- **SYS-04 job-monitoring dashboard** — the `JobRun` last-run status is recorded in Phase 2, but the dashboard that reads it is Phase 7 (SYS-04).
- **Weekly-report job body** — the scheduler registers/wires the JOB-03 slot in Phase 2, but the report generation itself is Phase 6 (RPT-01/02).

</deferred>

---

*Phase: 02-correctness-foundations*
*Context gathered: 2026-07-03*

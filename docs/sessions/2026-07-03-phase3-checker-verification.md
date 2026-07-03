# Session — 2026-07-03: Phase 3 executed, code-reviewed, fixed + verified

## What was done

- **Phase 3 executed** (`/gsd-execute-phase 3`): all 6 plans across 3 dependency
  waves, TDD (RED→GREEN), atomic commits. Requirements IFO-06 + CHK-01..05/07/08
  delivered.
- **Execution ran sequentially on `main`, not in parallel worktrees.** The worktree
  base-check auto-degraded (`shouldDegrade=true`, #683 — `origin/HEAD` unresolved on
  this local-only repo). This was the *lucky* outcome: the six plans heavily overlap
  on `web/checker.py`, `web/urls.py`, `web/views.py`, `verification/tests.py`, so
  parallel worktrees would have collided. Each plan ran in its own `gsd-executor`
  that committed and updated STATE/ROADMAP itself.
- **Model economy (per user):** Opus for delicate/high-blast-radius plans, Sonnet for
  self-contained work, every Sonnet result audited (spot-check + integration tests).
  03-05 (Opus), 03-06 (Sonnet, audited clean). Recorded as a durable preference.
- **Standard code review run** (`/gsd-code-review 03`) — surfaced 5 Critical + 3
  Warning findings below the (clean) pure core. **All verified real against the code,
  then fixed** with 8 atomic `fix(03)` commits + 8 regression tests.
- **Phase verified** (`gsd-verifier`): 6/6 success criteria + all 8 requirement IDs
  confirmed against actual source, full suite re-run green. Phase marked complete.

## Plans shipped (Phase 3)

- **03-01** (wave 1) — foundation: pure `resolve_checker_scan` gating core +
  `distribute_online_sessions` round-robin (both ORM-free), `Assignment.scope`
  (FLOOR/ONLINE), `Session.online_checker` FK, retired dead `ValidationAction`
  members; 3 migrations clean on MSSQL.
- **03-02** (wave 2) — Checker room scan (`web/checker.py`): server-side re-gate via
  the pure core on every action, room state + faculty photo, Verify / Verified-empty /
  Flag-identity / Flag-not-present → IFO **and** HR via `notify()` (CHK-01..05).
- **03-03** (wave 2) — IFO non-admin duty-assignment UI (`web/ifo.py`) + round-robin
  online pre-assignment (`verification/services.py`) over the pure distributor (IFO-06).
- **03-04** (wave 3) — CHK-07 htmx floor board: color+icon+label cards, coverage %,
  oldest-unverified-first queue, Absent excluded.
- **03-05** (wave 3) — online verification via Teams link (a Verify **activates** the
  session) **and** removal of the JOB-02 sweep's online exclusion in lockstep with its
  tests (CHK-02/03, ROADMAP #6). *Recovered from an interrupted partial run:* the RED
  test commit was already on disk with GREEN unstarted — preserved the committed
  lockstep test rewrite, discarded a stray import, completed GREEN cleanly.
- **03-06** (wave 3) — CHK-08 offline IndexedDB scan queue + reconnect replay endpoint
  that re-validates each item against current state through the pure core (never trusts
  the offline snapshot), idempotent by client uuid, original scan time preserved.

## Code review — 5 real correctness/robustness bugs caught below the pure core

The pure gating core and the JOB-02 sweep coupling were confirmed sound. The bugs were
in the web/service layer, and all were fixed with regression tests (commits
`2c7d470`..`5279c79`):

- **CR-01** — `_room_session_state` returned the earliest non-completed session ignoring
  `now`, so a stale earlier-in-the-day **ABSENT** class permanently blocked verifying a
  later **ACTIVE** class in the same room. Now prefers ACTIVE, else the in-window session.
- **CR-02** — `action`/`replay` checked `actionable` but not that the submitted action
  matched the outcome — a forged POST could record `verified_empty` on an occupied
  session. Added an outcome→action congruence gate.
- **CR-03 / CR-04** — non-numeric `room_id` and unvalidated `date`/`time`/`floors` in
  IFO assignment-create raised unhandled 500s (violating the "never a 500" contract).
  Guarded both.
- **CR-05** (most serious) — the online round-robin ignored the shift `start_time`/
  `end_time` window that the real-time on-duty gate enforces, so a shift-scoped online
  checker could be handed sessions outside their window → **false ABSENT** for
  genuinely-attended online classes. Fixed by extracting a shared pure
  `assignment_covers_now` predicate reused by all three on-duty call sites, and gating
  each session's eligibility by its `scheduled_start`.
- **WR-01/02/03** — TOCTOU idempotency race (→ atomic `cache.add`), missing replay
  rate-limit (code enumeration), and empty-`client_uuid` guard bypass. All fixed.

Lesson worth keeping: **a clean pure core is necessary but not sufficient — the
thin apply/service layer around it is where authz-congruence, input-format, and
cross-helper-drift bugs hide.** The CR-05 false-ABSENT bug came from three copies of
the on-duty-window logic drifting; the fix collapsed them to one shared predicate.

## State at session end

- **Phases 1–3 of 8 complete**, all verified against real SQL Server.
- Requirements complete this milestone: ENV-01/02, NOTIF-00, JOB-02a/b/c, ENV-04,
  IFO-06, CHK-01/02/03/04/05/07/08 (15 of 57).
- Full Django suite: **103 tests green** (`py -3.12 manage.py test`).
- Docs refreshed: `README.md` (Status + progress banner), `docs/PROGRESS.md` (board +
  Phase 3 detail), `.planning/PROJECT.md` (Validated/Active moved).
- Artifacts: `03-REVIEW.md` (status: resolved), `03-VERIFICATION.md` (passed).

## Next up

**Phase 4 — Modality Shift Approval & SRS v1.2** (can run parallel to Phase 3; depends
only on Phase 2's `release_room()` + `notify()`). Start with `/gsd-discuss-phase 4`.

# Codebase Concerns

**Analysis Date:** 2026-07-02

Concerns are grouped by category. Each entry states what it is, why it
matters, and which requirement/phase should address it. Everything below was
verified against the code, not inferred from docs alone. Requirement IDs
trace to `docs/FluxTrack_SRS.md` §4; build-sequencing status lives in
`docs/USE_CASES.md`.

---

## Deployment Blockers

These prevent a real production deployment as-is. None block continued local
feature development (a working dev-login stand-in already exists).

### Authentication is a DEBUG-only stub, not a security boundary

- **What it is:** The only sign-in path is a dev-login stub in
  `web/views.py:login_view` (lines 47-63). It signs in *any* seeded, active
  user by username with **no password**, and only inside `if
  settings.DEBUG`. `web/views.py:_login_ctx` (lines 66-68) even lists every
  active user for one-click selection. Entra ID SSO (AUTH-01/02) is not
  started. `requirements.txt` lists `PyJWT`, `cryptography`, `requests`
  ("wired in Phase 2") but no OIDC/Entra code exists.
- **Why it matters:** In production (`DEBUG=False`) the POST branch is dead,
  so there is literally no way to authenticate — the app is not deployable.
  In DEBUG it is a passwordless open door. This is explicitly a stub, not a
  boundary.
- **Unresolved divergence to decide first:** SRS §2.1 / AUTH-02 specifies a
  backend-issued **JWT** for API calls. The implementation uses Django
  **session auth** throughout (`login()` / `request.user`), because the UI is
  server-rendered HTML, not an API-consuming SPA. `docs/USE_CASES.md`
  (lines 59-67) flags this: decide explicitly whether to keep session auth
  (treating the SRS's JWT language as describing only the Entra exchange) or
  layer a real backend JWT on top. Don't let the SSO library's default pick
  this implicitly.
- **Also note:** AUTH-04 (role/data scoping) is enforced *per view* via
  `faculty_required` / `ifo_required` decorators (`web/faculty.py`,
  `web/ifo.py`), not framework-wide — every new surface must add its own.
- **Addressed by:** AUTH-01/02 (Entra ID), plus a scoping-model decision
  before that work starts. Per suggested build order, can run in parallel
  with feature work.

### MSSQL migration is unproven — compatibility spike required first

- **What it is:** Production must run on SQL Server via `mssql-django` +
  `pyodbc` (per `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`
  §1). Today `config/settings.py` (lines 78-95) only branches on
  `DB_ENGINE` for `mysql` and falls through to `sqlite3`; there is **no
  mssql branch**. `requirements.txt` contains **neither** `mssql-django`
  **nor** `pyodbc` (only a commented-out `mysqlclient`).
- **Why it matters:** `mssql-django` compatibility with the SRS-recorded
  Django version (6.0.6) is **unconfirmed** — and `requirements.txt` pins
  `Django>=5.0,<7.0`, a range, not the SRS's exact version. The deployment
  spec calls this the **#1 spike-first item**: install `mssql-django pyodbc`,
  point the `DB_ENGINE` switch at a throwaway instance, run `migrate`. If
  incompatible, Django must be pinned back to the newest minor `mssql-django`
  supports. Committing to AWS/RDS before this spike risks a forced downgrade
  late.
- **Addressed by:** A spike phase before AWS deployment (SRS §6.7). Add the
  `mssql` branch to `config/settings.py`'s `DB_ENGINE` switch and the two
  packages to `requirements.txt` only after the spike passes.

### Franken UI / Tailwind / htmx loaded via CDN, no build step

- **What it is:** `templates/base.html` (lines 12-16) loads Franken UI CSS/JS
  and htmx from `cdn.jsdelivr.net`; `templates/faculty/scan.html` (line 4)
  loads `html5-qrcode` from the same CDN. SRS §2.4 requires Tailwind be
  **compiled with the standalone CLI as a build step** before deploy.
- **Why it matters:** CDN dependencies mean external runtime reliance, no
  offline PWA guarantee for styles, no version pinning under our control, and
  a production posture the SRS explicitly rules out. PWA service workers
  (already present in `web/views.py` `SW_JS`) can't reliably cache
  cross-origin CDN assets.
- **Addressed by:** A build-step/deployment phase — add standalone Tailwind
  compilation, vendor Franken UI/htmx/html5-qrcode into `static/`, serve via
  WhiteNoise (already a dependency).

---

## Correctness Gaps

The built happy-path works, but two gaps make recorded data untrustworthy.

### JOB-02 status sweep does not exist — "Absent" is only reactive

- **What it is:** Absent is currently detected **only at scan time**, inside
  the pure resolver `scheduling/resolver.py` (grace-window branch), applied
  by `web/scan.py:_apply` (lines 90-94, `R.ABSENT`). There is **no status
  sweep**: `find` shows only two `scheduling` management commands
  (`import_offerings.py`, `materialize_sessions.py`) — no `status_sweep`
  logic anywhere.
- **Why it matters:** A faculty member who **never scans** is **never marked
  Absent**, because nothing triggers the resolver without a scan. This makes
  the "Absent" status untrustworthy for any un-scanned session — a
  high-impact correctness gap that undermines all downstream reporting
  (RPT-01/04, HR, Dean). `docs/USE_CASES.md` (UC-JOB-2, lines 496-508) calls
  this out as a real gap, "not just not automated."
- **What JOB-02 must do:** mark no-show sessions Absent after grace
  (scan-independent), release rooms after `room_hold_minutes`, raise
  room-conflict flags. Per the modality-shift spec, Absent is now **final**
  (CHK-06 override removed) and room release runs on the normal timer.
- **Addressed by:** JOB-02 (SRS §6.7). Suggested build order ranks this #1 —
  it's a prerequisite for trustworthy Absent before Checker/reporting work.

### Notification write path exists but there is no read surface

- **What it is:** `web/scan.py:_notify_ifo` (lines 63-67) genuinely creates a
  real `Notification` row per active IFO Admin — fired on FAC-10 wrong-room
  confirm (line 113) and FAC-09 force-handover (line 129). Verified: grep for
  `Notification.objects` finds **only `.create` calls** in `web/scan.py` and
  **zero reads** anywhere. No `notif` URL exists in any `urls.py`.
- **Why it matters:** Those rows are written and then **invisible** — no
  in-app list (NOTIF-01), no push delivery (NOTIF-02). Confirming a
  wrong-room change or a force handover today produces a database row no IFO
  Admin can ever see. Already-built flows are silently incomplete.
- **Addressed by:** NOTIF-01 (polled in-app list, all roles) then NOTIF-02
  (VAPID web push). The `Notification` and `PushSubscription` models already
  exist in `ops/models.py`.

---

## Dependency Blockers

### IFO-06 (Checker/Guard floor assignments) is unbuilt — hard-blocks Checker

- **What it is:** The `Assignment` model exists (`verification/models.py`
  line 16, with `AssignmentType` line 11) and is registered in
  `verification/admin.py` — but there is **no IFO-facing view** to create
  assignments and no `assignment` URL anywhere. It's admin-only /
  effectively unused.
- **Why it matters:** CHK-01 on-duty gating requires an **active
  `Assignment` row** to grant a Checker verification powers on a floor.
  Without IFO-06, the **entire Checker slice** (CHK-01-08) cannot function —
  every Checker scenario in `docs/USE_CASES.md` depends on it. It also blocks
  Guard floor-scoping (GRD-01). This must land before or alongside Checker
  work, not after.
- **Addressed by:** IFO-06 (assign by shift or standing posting). Suggested
  build order ranks it #2, immediately before the Checker surface.

### Scheduled jobs (JOB-01/02/03) run only as manual commands — none automated

- **What it is:** `APScheduler>=3.10` is in `requirements.txt`, but grep for
  `apscheduler`/`APScheduler` across all `.py` finds **zero code
  references**. JOB-01 exists only as `scheduling/management/commands/
  materialize_sessions.py` (manual), JOB-02 doesn't exist (above), JOB-03
  isn't started.
- **Why it matters:** SRS §6.7 requires APScheduler run as a **single
  dedicated process**, separate from web workers, to avoid duplicate job
  execution. Nothing is wired. This is infrastructure work that blocks all
  three jobs regardless of which is built first, and blocks SYS-04 job
  monitoring (no job-run tracking exists to monitor).
- **Addressed by:** A scheduler-process phase (SRS §6.7) — per the
  deployment spec, a second systemd service on the EC2 instance.

---

## Testing Debt

### Only the resolver is unit-tested; no view/integration/e2e coverage

- **What it is:** `scheduling/tests.py` is the only real test file (117
  lines, covering the pure resolver `scheduling/resolver.py`). Every other
  app's `tests.py` is a 3-line Django stub with no tests:
  `accounts/tests.py`, `campus/tests.py`, `ops/tests.py`,
  `verification/tests.py`, `web/tests.py`.
- **Why it matters:** The entire scan side-effect layer (`web/scan.py`:
  idempotency, two-step signed confirm, rate limiting, `_apply` state
  transitions, `_notify_ifo`), all view auth decorators, and the management
  commands are **verified only manually in-browser** (the `DEVELOPMENT.md`
  definition-of-done even codifies "verified end-to-end in-browser"). Any
  regression in confirm-token handling, idempotency keys, or audit writes
  would pass unnoticed. The resolver's pure-function testability is a good
  pattern to extend (RPT-05 mandates the same for aggregates).
- **Priority:** High for `web/scan.py` (the only closed-loop write path),
  Medium for view auth-scoping, before each new slice adds more untested
  surface area.
- **Addressed by:** Fold view/integration tests into each slice's definition
  of done; backfill `web/scan.py` coverage first.

---

## Data / Privacy

### Real registrar data under `data/raw/` may contain PII

- **What it is:** `data/raw/` is gitignored (`.gitignore` line 26
  `/data/raw/`) and **currently contains real registrar exports** —
  confirmed present: `2T-25-26-Course Offerring.xlsx`,
  `2T-25-26-Offering Schedules(Sheet1).csv`, room-schedule CSVs. The
  importer `scheduling/management/commands/import_offerings.py` (line 174)
  calls `u.set_unusable_password()` for imported faculty, so those accounts
  can't be logged into until Entra ID SSO exists.
- **Why it matters:** These files hold faculty names / institutional emails
  (PII). They are correctly gitignored, but their presence in the working
  tree means care is needed never to commit them or echo their contents.
  Only an R3 test slice has been imported so far, not the full campus —
  scaling to full import multiplies the PII footprint. (Contrast:
  `accounts/management/commands/seed_demo.py` line 71 sets a **usable**
  `devpass123` for the 7 demo users — fine for dev, must never reach prod.)
- **Addressed by:** Keep `data/raw/` out of git (already enforced); when
  Entra ID lands, ensure imported-faculty accounts stay password-unusable
  (SSO-only). Ensure `seed_demo` never runs against production.

---

## Doc Drift

### SRS is at v1.1 but three approved specs require a v1.2 revision

- **What it is:** Three approved design specs dated 2026-07-02 amend formally
  specified requirements but have **not** been folded into the SRS:
  - `docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md` —
    adds a `MOD-01..0N` requirement area (`ModalityShiftRequest` workflow +
    `modality_shift_lead_days` policy), **amends FAC-07** (no longer a
    self-declare — replaced by the approval workflow), **amends CHK-03**
    (drops "Confirm absent"), and **removes CHK-06** entirely (Absent is now
    final).
  - `docs/superpowers/specs/2026-07-02-dean-dashboard-design.md` — adds
    `DEAN-04` (Dean Dashboard) and **amends RPT-02** (notify Deans too, not
    just IFO).
  - `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`
    — records the MSSQL/AWS decisions.
- **Why it matters:** `docs/FluxTrack_SRS.md` (and the `.docx` deliverable)
  is the traceability source of truth for requirement IDs; planning that
  reads only the SRS would build the **superseded** FAC-07 self-declare and
  the **removed** CHK-06 override. The specs themselves flag the needed
  edits: new `MOD-*`/`DEAN-04` areas, FAC-07/CHK-03 amendments, CHK-06
  removal, `modality_shift_lead_days` (default 2 days) added to the §8 Policy
  Assumptions Register, and a v1.2 Revision History row.
- **Addressed by:** An SRS v1.2 revision task (edit both `.md` and `.docx`,
  preserving `.docx` formatting as done for v1.1) — called out as
  implementation work in both amending specs, not yet performed.

---

*Concerns audit: 2026-07-02*

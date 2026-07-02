# Pitfalls Research

**Domain:** Attendance/facility-utilization PWA (Django + htmx) — SQLite→MSSQL cutover, timezone-correct attendance, offline Checker queue, Entra ID SSO, single-EC2 AWS deploy
**Researched:** 2026-07-02
**Confidence:** HIGH (library-specific claims verified against mssql-django/pyodbc/APScheduler docs and issue trackers; domain claims cross-checked against the codebase's own CONCERNS.md and the resolver/scan code)

> Scope note: this file goes *deeper* than `.planning/codebase/CONCERNS.md`, which already catalogues the known "it's a stub / not built" gaps (auth stub, no MSSQL branch, no JOB-02, no notif read surface, CDN not build-step, only-resolver-tested, PII in `data/raw/`, SRS drift). Those are **not** repeated as pitfalls here. What follows are the *specific ways the unbuilt work will silently produce wrong behavior* even when it looks like it's working.

---

## Critical Pitfalls

### Pitfall 1: MSSQL is case-insensitive by default — SQLite tests hide duplicate/uniqueness bugs

**What goes wrong:**
Code and migrations that pass on SQLite start rejecting or mis-matching rows on SQL Server. SQL Server's default collation `SQL_Latin1_General_CP1_CI_AS` is **case-insensitive**; SQLite is **case-sensitive** by default. Concretely for FluxTrack:
- `Room.manual_code` (six-digit, fine) and `Room.qr_token` (opaque unique) — a token differing only in letter case collides on MSSQL but not SQLite. If `qr_token` generation ever uses mixed-case base64/hex, two "distinct" tokens can violate the unique constraint on MSSQL only.
- Faculty lookup "by institutional email" in `import_offerings.py` — `set_unusable_password()` accounts keyed by email. On SQLite `Jdoe@…` and `jdoe@…` are two users; on MSSQL they're one. The importer's get-or-create behavior *changes* across the migration, silently merging or colliding faculty identities.
- `azure_oid` / `email` uniqueness for Entra provisioning (Pitfall 12) inherits the same difference.
- Ordering (`ORDER BY`) and `__exact`/`__contains` lookups become case-insensitive, changing which "first" row `.first()` returns in `web/scan.py`.

**Why it happens:**
Developers use SQLite for "quick local runs" (explicitly allowed in PROJECT.md constraints) and treat it as equivalent to production. Collation is invisible until a real duplicate arrives.

**How to avoid:**
- Run the compatibility spike (already the #1 item) on a **real SQL Server Express instance**, and make the CI/dev "source of truth" MSSQL, not SQLite — SQLite is for throwaway runs only.
- Decide per-column whether case-insensitivity is *desired* (email/username: yes) or *dangerous* (opaque tokens: must stay case-sensitive). For tokens, either generate case-normalized (lowercase hex only) or set a case-sensitive collation (`…_CS_AS`) on that column via a migration `RunSQL`.
- Add a test that inserts case-variant duplicates and asserts the intended behavior — run it on MSSQL.

**Warning signs:**
`IntegrityError` on unique constraints that never fired locally; the faculty count after import differs between SQLite and MSSQL; two posters resolve to the same room.

**Phase to address:** MSSQL migration spike (Environment & platform).

---

### Pitfall 2: mssql-django + pyodbc drop/garble timezone on datetime — Asia/Manila attendance can shift by 8 hours

**What goes wrong:**
`Session.scheduled_start`, `actual_start`, `actual_end`, `room_released_at`, `AuditLog.created_at` etc. round-trip incorrectly. mssql-django maps `DateTimeField` to SQL Server `datetime2` (which has **no offset**), and pyodbc has documented, still-open issues where timezone-aware datetimes lose their offset and revert to UTC on write, and `DATETIMEOFFSET` columns aren't cleanly round-trippable for non-UTC zones (pyodbc #810, #1141; mssql-django #371). With `USE_TZ=True` and `TIME_ZONE='Asia/Manila'` (UTC+8), a grace-window comparison done against a mis-stored timestamp can be **8 hours off** — turning an on-time faculty member Absent, or vice-versa.

**Why it happens:**
The resolver is *pure* and takes `now` as an argument (good) — but the **web layer fetches `timezone.now()` and reads session timestamps from the DB**, and that boundary is where the offset gets lost. On SQLite everything is naive local and "just works," masking the bug until MSSQL.

**How to avoid:**
- **Store UTC, `USE_TZ=True`, never store local.** Do all grace/Absent math in UTC; convert to Asia/Manila only for display/reports. This is the single most important correctness decision for the whole system.
- During the MSSQL spike, write an explicit round-trip test: save an aware `datetime` at a Manila local time straddling midnight, re-read it, assert equality to the second. Do this *before* building JOB-02, because JOB-02 correctness depends on it.
- Confirm the mssql-django version in use maps `DateTimeField`→`datetime2` and that `USE_TZ=True` stores UTC (mssql-django 1.7 adds Django 6.0 support; verify tz behavior on that exact version, don't assume).
- Keep the "reporting week Mon–Sun" boundary (SRS §8) computed in Manila local, not UTC, or a Sunday-night session lands in the wrong week.

**Warning signs:**
Sessions flip Absent/Present when the server is restarted in a different tz; `actual_start` displays 8 hours off; a session scheduled 08:00 shows `scheduled_start` of 00:00; week-boundary sessions appear in the adjacent week's report.

**Phase to address:** MSSQL migration spike, then hard-gate JOB-02 on it.

---

### Pitfall 3: JOB-02 must mark Absent scan-independently *and idempotently* — the sweep is the real correctness fix, and easy to get subtly wrong

**What goes wrong:**
Today Absent is only reactive (resolver at scan time). JOB-02 fixes that, but the sweep itself has three failure modes:
1. **Re-marking / clobbering:** a session already `active`/`completed` (faculty scanned in on time) or already Checker-corrected must **not** be flipped to Absent on the next sweep. Absent is now *final* (CHK-06 removed) — but "final" means the sweep must be idempotent and must never overwrite a real outcome.
2. **Grace boundary drift:** the sweep computes "past grace" using the same policy (`grace_minutes`) and the same `now` semantics as the resolver — if the sweep uses local time and the resolver uses UTC (Pitfall 2), a session sits in a dead zone marked Absent by one path and Present by the other.
3. **Room release ordering:** JOB-02 also releases rooms after `room_hold_minutes` and raises conflict flags. Releasing a room whose session is *still active* (long-running class) because the sweep only looked at `scheduled_end` is a facility-status corruption.

**Why it happens:**
The sweep is net-new logic with no resolver test coverage to lean on, and it runs frequently (every few minutes) so any non-idempotency compounds fast.

**How to avoid:**
- Implement the sweep's decision as a **pure function** mirroring the resolver (CONVENTIONS.md rule #1): inputs = candidate sessions + policy + `now` (UTC); output = list of transitions. Unit-test it exhaustively like `scheduling/resolver.py` before wiring APScheduler.
- Guard the write: only transition `status == SCHEDULED` (and past grace, no `actual_start`) → `ABSENT`. Never touch `active`/`completed`/already-`absent`.
- Emit an `AuditLog` row per transition (`session.marked_absent` with `payload={"source":"sweep"}`) — CONVENTIONS.md rule #2 — so a runaway sweep is visible and diagnosable.
- Room release keyed off actual session completion + hold window, not raw `scheduled_end`.
- Make the sweep interval a policy value (`get_policy`), not a magic number (rule #3).

**Warning signs:**
Absent counts climb on every sweep tick; a faculty member who checked in shows Absent in reports; a room releases mid-class; audit log floods with duplicate `marked_absent` rows for the same session.

**Phase to address:** JOB-02 status sweep (Correctness foundations) — build order #1.

---

### Pitfall 4: Offline Checker queue replays stale scans — must re-validate server-side, not blindly apply

**What goes wrong:**
The Checker works under intermittent connectivity (SRS §2.3) and queues scans in IndexedDB (CHK-08). On reconnect the naive implementation POSTs the queued findings in order and applies them. But the room's state may have changed while offline: the session ended, was force-handed-over, the faculty already got verified by another Checker, or the room was released. Blindly replaying writes a `CheckerValidation` against a stale session — recording "verified present" for a session that completed 40 minutes ago, or double-verifying.

**Why it happens:**
Offline-first UIs optimize for "never lose the user's action," which biases toward replay-and-apply. Clock skew between the device and server (Pitfall 5) makes "when did this scan happen" ambiguous, so the server can't trust the client's `scanned_at`.

**How to avoid:**
- SRS CHK-08 already mandates the right pattern: **re-validate each queued scan on the server before applying, or flag for IFO if it can't be cleanly applied.** Build the server endpoint to treat a queued scan as a *proposal*, re-run the room-state resolution against *current* server state, and either apply or route to a conflict/flag surface — never a blind write.
- Carry a **client-generated idempotency key** per queued scan (e.g. `checker_id:session_id:scanned_at_rounded`) so a partially-succeeded batch that re-sends doesn't double-apply. This mirrors the existing `user:session:minute` idempotency in `web/scan.py`.
- Store `scanned_at` **and** `offline_queued=true` on `CheckerValidation` (the field already exists in the model) so the record is honest about provenance and reviewable.
- Design the batch endpoint to return a per-item result (applied / flagged / rejected) so the client can clear only the successfully-handled items.

**Warning signs:**
`CheckerValidation` rows with `validated_at` long after the session `completed`; verifications against absent/released sessions; duplicate validations after a flaky reconnect; IFO conflict queue empty despite known offline usage (means stale scans are being silently applied instead of flagged).

**Phase to address:** Checker surface (CHK-08) — depends on IFO-06 and JOB-02 landing first.

---

### Pitfall 5: Device clock skew and idempotency-key trust — the client's timestamp is not authoritative

**What goes wrong:**
Two related concurrency/correctness holes:
1. The existing scan idempotency is keyed `user:session:minute` using the **server** clock (`web/scan.py`) — good for online scans. But an offline Checker scan carries a *device* timestamp. If the device clock is skewed (common on phones), a scan "made at 09:03 device time" replayed at 09:20 server time can bypass the minute-window idempotency, or a grace decision made client-side disagrees with the server.
2. Force-handover (FAC-09) and "two scans same minute" races: the current idempotency is per user/session/minute via **locmem cache**. On a single EC2 with one Gunicorn worker this holds; with **multiple workers** locmem is per-process, so the idempotency and manual-code rate-limit (SCAN-05) counters are **not shared** — two workers can each let a duplicate through.

**Why it happens:**
Locmem cache silently works in dev (one process) and in single-worker deploys, then breaks when workers scale. Client timestamps are trusted because they're convenient.

**How to avoid:**
- **Never trust client time for business decisions.** Use `scanned_at` only as advisory metadata; make Absent/grace/handover decisions on server `now` (UTC). For offline scans, re-derive outcome server-side at replay time (Pitfall 4).
- If Gunicorn runs >1 worker, move the idempotency + rate-limit cache off locmem to a shared backend (DB-backed cache table, or a `unique_together` DB constraint on `(user, session, minute_bucket)` that turns a race into a caught `IntegrityError`). A DB unique constraint is the most robust idempotency guarantee and survives worker count changes.
- Force-handover race: wrap the "complete prior active session + start new" in a DB transaction with `select_for_update()` on the prior session row so two simultaneous handovers can't both win. SQLite doesn't enforce `select_for_update`; MSSQL does — another reason to test on MSSQL.

**Warning signs:**
Duplicate `checked_in` audit rows for one session; rate limit "5/min" occasionally allows 8–10; two `active` sessions in one room after concurrent handover; idempotency works in dev, fails under load test.

**Phase to address:** MSSQL spike (surfaces `select_for_update` + shared-cache need), Checker/offline (CHK-08), scheduler/deploy phase (worker count decision).

---

### Pitfall 6: APScheduler running inside Gunicorn workers → every job fires N times

**What goes wrong:**
If APScheduler is started in the Django app process (e.g. in `AppConfig.ready()` or a module import), Gunicorn's pre-fork model gives **each worker its own scheduler**, so JOB-01 materializes sessions N times, JOB-02 sweeps N times (compounding Pitfall 3's idempotency need), JOB-03 generates N weekly reports. Verified as a well-known APScheduler/Gunicorn failure mode (APScheduler FAQ explicitly warns sharing a jobstore across processes causes duplicate execution).

**Why it happens:**
Starting the scheduler in `ready()` is the most-Googled Django+APScheduler recipe, and it *looks* fine with `runserver` (single process) and even with 1 worker — the duplication only appears when workers > 1.

**How to avoid:**
- SRS §6.7 already mandates the correct design: **APScheduler runs in a single dedicated process, separate from web workers** — a second systemd service on the EC2 box (per the deployment spec). Wire it as a standalone management command (`manage.py run_scheduler`) that the web workers never import.
- Belt-and-suspenders: make each job idempotent anyway (JOB-01 already is; JOB-02 must be per Pitfall 3) so a stray duplicate is harmless.
- Add SYS-04 job-run tracking (last run, success/failure, rows affected) from day one — it's the only way to *notice* double execution in production, and it's a listed requirement with no model yet.

**Warning signs:**
Session/report counts are exact multiples of the worker count; `--preload` "fixes" it (a smell that the scheduler is inside the web process); job-run log shows N near-simultaneous runs.

**Phase to address:** APScheduler dedicated-process phase (Environment & platform); SYS-04 monitoring.

---

### Pitfall 7: Service worker caching navigations/redirects — the bug already hit once

**What goes wrong:**
The PWA service worker (`SW_JS` in `web/views.py`) can cache a navigation response or a redirect, so after login/logout or a role change the user gets a **stale cached page or a cached redirect loop**. CONVENTIONS.md notes the team already learned to never precache `/` and to use network-first for navigations — regressing this (e.g. adding a new authenticated route to the precache list, or cache-first for HTML) re-breaks it. Cross-origin CDN assets (Franken UI/htmx/html5-qrcode, currently CDN) **can't be reliably cached by the SW**, so offline styling/scanning silently fails.

**Why it happens:**
Copy-pasted SW recipes default to cache-first for everything; redirects (302 to login) are opaque to naive caching and get frozen.

**How to avoid:**
- Keep **network-first for navigations**, cache-first only for hashed static assets. Never cache authenticated HTML or redirect responses.
- **Vendor the CDN assets into `static/` and serve via WhiteNoise** (already a dependency) so the SW can cache same-origin, versioned files — this is also the CDN→Tailwind-build item and is a prerequisite for any real offline PWA guarantee.
- Version the cache name and clean old caches on `activate`, or a deploy leaves users on stale JS.
- Test install/scan flow with DevTools "Offline" after a fresh deploy.

**Warning signs:**
Users see an old page after deploy until hard-refresh; login redirects loop; QR scanner or styles break with no network; SW cache holds `text/html` for `/` or a 302.

**Phase to address:** Tailwind-build / vendor-assets phase; revisit when adding push (NOTIF-02) since the SW gains a push handler.

---

### Pitfall 8: Entra ID cutover locks you out of production — DEBUG dev-login is the *only* door

**What goes wrong:**
The dev-login stub only works under `DEBUG=True` (`web/views.py`). Flip `DEBUG=False` for production **before** Entra ID SSO actually works end-to-end, and there is **literally no way to authenticate** — including no way for the System Admin to log in to fix it. Compounding: imported faculty have `set_unusable_password()` (SSO-only, correct), and `seed_demo` sets a **usable** `devpass123` that must never reach prod. If the Entra app registration's redirect URI, tenant, or client secret is misconfigured, everyone is locked out at once.

**Why it happens:**
The stub-vs-real boundary is a single `if settings.DEBUG`, so "turn off debug for prod" is a one-line change that removes the only working login before the replacement is proven.

**How to avoid:**
- Build and verify Entra Auth-Code-+-PKCE **against the real project-owned tenant on a staging deploy with `DEBUG=False`** before cutover — never trust that "it'll work in prod."
- Keep **one break-glass Django superuser** with a real password (Django admin login, not the dev stub) provisioned in prod so you can recover if SSO breaks. Rotate/audit it; it's the recovery path Pitfall says you'll need.
- Handle the **unprovisioned-but-authenticated** identity explicitly (AUTH-03): a valid Entra token with no matching `User` must be rejected at the boundary with a clear message, not 500 and not auto-created. Today AUTH-03 is "trivially true" only because the stub can't produce unknown identities — real SSO can.
- Ensure `seed_demo` and its `devpass123` users can never run against prod (guard on `DEBUG` or an explicit env flag).

**Warning signs:**
Staging with `DEBUG=False` has no login path; the only tested login is `DEBUG=True`; no non-SSO recovery account exists; unknown Entra identity throws 500.

**Phase to address:** Entra ID SSO phase; pair with the session-vs-JWT decision (Pitfall 9).

---

### Pitfall 9: Letting the SSO library implicitly pick session-vs-JWT

**What goes wrong:**
SRS §2.1/AUTH-02 says "backend-issued JWT for API calls," but the actual app is **server-rendered HTML using Django session auth throughout** (`login()` / `request.user`), not an API-consuming SPA. If you drop in an SSO library and adopt whatever it defaults to (often JWT-in-header), you end up with two half-wired auth models: session-based views plus a JWT nobody validates, or CSRF/session assumptions broken by a token flow. AUTH-05 (deactivation invalidates tokens) is trivial with sessions (`is_active` gates the backend) but **hard with stateless JWTs** (you need a denylist), so an implicit JWT choice quietly breaks a stated requirement.

**Why it happens:**
The SRS language predates the Next.js→Django-templates pivot (v1.1); the JWT wording describes an architecture that no longer exists, but it's still "the spec."

**How to avoid:**
- **Decide explicitly before writing SSO code** (CONCERNS.md flags this): use Django **session auth**, treating the SRS's JWT language as describing only the Entra token exchange (recommended — matches the real architecture, AUTH-05 stays easy). Record the decision in the SRS v1.2 revision.
- Use Entra purely for the OIDC handshake → verify ID token against JWKS → map to `User` → `login()` (session). Don't mint or require a second backend JWT for the server-rendered UI.
- If any genuine API surface (DRF) needs tokens later, layer it deliberately with a revocation story, not by default.

**Warning signs:**
Both a session cookie and a bearer token in flight; deactivating a user doesn't immediately block them; CSRF errors on htmx POSTs after the SSO change; "why do we have JWTs" with no validation code.

**Phase to address:** Entra ID SSO phase (decision gates the implementation).

---

### Pitfall 10: Single-EC2 + RDS SQL Server Express hard limits bite late (10 GB cap, single point of failure, no offline styling)

**What goes wrong:**
- **RDS SQL Server Express caps at 10 GB per database.** `AuditLog` is written on *every* write event (rule #2) plus a `Session` per class per day plus `Notification` rows — this table grows unbounded. At campus scale over a term/year, audit + sessions + notifications can approach the cap; when hit, **all writes fail** and the app is down with no obvious cause.
- **Single EC2 = single point of failure:** the web workers, the APScheduler process, and TLS termination all live on one box. A reboot/crash stops the scheduler (JOB-02 stops marking Absent, JOB-01 stops materializing) *silently* — attendance data quietly rots.
- **CDN dependency** means a jsdelivr outage or offline client breaks styling and QR scanning (ties to Pitfall 7).

**Why it happens:**
"Simplest possible for capstone scale" (a legitimate constraint) optimizes for demo, and Express's 10 GB limit is invisible until months of audit rows accumulate.

**How to avoid:**
- Plan an **audit/notification retention policy** (SRS §6.8 already requires DPA data minimization + disposal) — e.g. archive/prune `AuditLog` and read `Notification` rows older than N months. Add it as a scheduled job, not an afterthought.
- **Monitor DB size** and scheduler liveness (SYS-04) — a dead scheduler must be *visible*, since its failure is silent (no Absent marks ≠ everyone present).
- Vendor CDN assets (Pitfall 7) to remove the runtime external dependency.
- Accept the SPOF for capstone scale, but **document it as a known limitation** and ensure the scheduler restarts on boot (systemd `Restart=always`).
- Note the SRS still says **MySQL 8.0** in several places (§2.4/§3.3/§5) while the deployment decision is **SQL Server Express** — this drift must be reconciled in SRS v1.2, or someone builds against the wrong engine.

**Warning signs:**
`AuditLog` row count in the millions; RDS free-storage metric trending to zero; writes start failing with no code change; Absent counts drop to ~0 for a day (scheduler died); SRS says MySQL but RDS is SQL Server.

**Phase to address:** AWS deployment phase; retention job under Scheduled Jobs; SRS v1.2 reconciliation.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Develop/test only on SQLite, defer MSSQL | Fast local runs | Case-sensitivity (P1), tz (P2), `select_for_update` (P5) bugs surface only in prod | Never for the migration/JOB-02/Checker slices; OK for pure-UI tweaks |
| Keep Franken UI/htmx/html5-qrcode on CDN | No build step | Breaks SW offline caching (P7), no version pinning, PWA can't guarantee assets | Only until the Tailwind-build phase; not for deploy |
| APScheduler in `AppConfig.ready()` | One-file wiring | N× job execution under multi-worker (P6) | Never; use dedicated process from the start |
| Trust client `scanned_at` for offline decisions | Simpler replay | Stale/duplicate validations, skew bugs (P4/P5) | Never; re-validate server-side |
| locmem cache for idempotency/rate-limit | Zero infra | Not shared across workers; silent duplicate scans (P5) | Only guaranteed-single-worker deploy; document the constraint |
| Store attendance in local time | "It just works" on SQLite | 8-hour Absent errors on MSSQL (P2) | Never; store UTC |
| Flip `DEBUG=False` before Entra is proven | Ships sooner | Total lockout (P8) | Never; verify SSO on staging first |
| Unbounded `AuditLog`/`Notification` growth | No pruning code | Hits 10 GB Express cap, writes fail (P10) | OK short-term; needs retention job before real use |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| mssql-django / pyodbc | Assuming SQLite behavior transfers; ignoring datetime2/offset handling | Spike on real SQL Server; store UTC (`USE_TZ=True`); round-trip test aware datetimes; verify tz on the exact mssql-django version (1.7 = Django 6.0 support) |
| SQL Server collation | Relying on case-sensitive uniqueness (tokens, emails) | Choose collation per column; normalize token case; test case-variant duplicates on MSSQL |
| Microsoft Entra ID (OIDC) | Adopting library's default JWT flow; auto-creating unknown users | Session auth + Entra for handshake only; verify ID token vs JWKS; reject unprovisioned identities (AUTH-03); keep break-glass superuser |
| APScheduler + Gunicorn | Scheduler in web process → N× runs | Dedicated systemd scheduler process (SRS §6.7); idempotent jobs; SYS-04 tracking |
| Web Push (VAPID) | HTTPS/SW assumptions; caching the SW itself | Requires HTTPS + same-origin SW; version SW cache; push handler must not break navigation caching (P7) |
| RDS SQL Server Express | Ignoring 10 GB/db cap with per-write audit logging | Retention/pruning job; monitor free storage; DPA disposal (§6.8) |
| WhiteNoise + vendored assets | Leaving assets on CDN, SW can't cache cross-origin | Vendor into `static/`, hashed filenames, WhiteNoise serve, SW cache-first on same-origin |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Frequent JOB-02 sweep re-scanning all sessions | Sweep runtime grows each term; DB CPU spikes | Filter to `status=SCHEDULED` in a bounded time window (today ± grace), indexed on `(status, scheduled_start)` | Full-term session table (thousands of rows) |
| `AuditLog` write-amplification | Slow writes, DB bloat toward 10 GB | Index `created_at`; retention/pruning; don't audit non-security no-ops beyond what's needed | Months of operation |
| Polling live surfaces (IFO-07/GRD-01) at 8s with N clients | DB load scales with admins × 1/8s | Cheap, indexed "today" query; `select_related` (already the convention); cache the rows briefly | 50 concurrent admins (SRS §6.1 target) |
| N+1 on session/room/faculty in loops | Slow list/report pages | `select_related`/`prefetch_related` (established convention) — enforce in new Checker/reporting/Guard views | Any list view over sessions |
| Offline queue batch replay all-at-once | Reconnect stalls, timeouts | Chunk the batch; per-item idempotency + result; server re-validates each | Checker offline for a full shift |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Committing/echoing `data/raw/` registrar exports | PII leak (faculty names/emails), DPA violation | Keep gitignored (already); never `cat`/echo contents; scale import raises footprint (CONCERNS.md) |
| `seed_demo`'s `devpass123` reaching production | Passworded backdoor accounts in prod | Guard command behind `DEBUG`/env flag; imported faculty stay `set_unusable_password()` (SSO-only) |
| Per-view decorators missed on a new surface | Unauthorized access; role scope bypass (AUTH-04) | Every new Checker/HR/Dean/Guard view gets its own `<role>_required`; scoping is per-view, not framework-wide |
| Guard locator exposing live faculty location broadly | Over-exposure of location data (§6.8 accepted only for Guard) | Restrict GRD-03 to `guard_required`; don't reuse the query in other roles' views |
| QR token / manual code becoming client-readable | Forgeable check-ins | Keep resolver-only, never render token in HTML/JS (SCAN-07); rotate on compromise (IFO-02) |
| Stateless JWT without revocation | Deactivated user keeps access (breaks AUTH-05) | Prefer session auth (P9); if JWT, add denylist tied to `is_active` |
| Break-glass superuser with weak/shared password | Full-system compromise via recovery account | Strong unique password, audited, rotated; it's the only non-SSO door (P8) |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent offline queue (no feedback) | Checker doesn't know if a scan was recorded or is pending | Show pending/queued/synced state per scan; surface conflicts routed to IFO |
| Absent marked but faculty was present (missed scan) | Faculty distrust; wrong reports — and CHK-06 override was *removed* | JOB-02 correctness (P3) + Checker verification path must be the safety net; make Absent reasons visible in FAC-11 history |
| Stale page after deploy (SW cache) | Users act on old data | Network-first navigations; versioned cache; visible "update available" (P7) |
| Wrong-room/handover notification written but invisible | IFO never sees critical events (already true today) | NOTIF-01 read surface before relying on any `_notify_ifo` write |
| Force-handover with no confirmation clarity | Faculty accidentally closes another's session | Two-step signed confirm already in place — keep it; clear copy on what handover does |
| Off-duty Checker scan silently denied | Confused Checker (CHK-01) | Reject with an explicit "not on duty on this floor" reason, not a blank denial |

## "Looks Done But Isn't" Checklist

- [ ] **MSSQL migration:** Migrations apply on SQLite but verify on real SQL Server — check case-sensitivity (P1), datetime round-trip (P2), `select_for_update` (P5), boolean/identity columns.
- [ ] **JOB-02 sweep:** Marks Absent — but verify it's idempotent (re-run twice, no change), doesn't clobber active/completed, uses UTC, releases rooms only post-completion, emits audit rows.
- [ ] **Offline Checker queue:** Replays on reconnect — but verify each scan is **re-validated server-side**, stale scans are flagged not applied, idempotency key prevents double-apply.
- [ ] **Entra SSO:** Login works in DEBUG — but verify it works with `DEBUG=False` on staging, unprovisioned identity is rejected (AUTH-03), deactivation blocks access (AUTH-05), a break-glass account exists.
- [ ] **APScheduler:** Jobs run — but verify they run **once** under the production worker count, and SYS-04 shows last-run/success/rows.
- [ ] **Service worker:** App installs — but verify network-first navigations, no cached redirects, assets vendored same-origin, cache versioned and cleaned on deploy.
- [ ] **Notifications:** Rows are created — but verify a read surface (NOTIF-01) exists so IFO can actually see wrong-room/handover/conflict events.
- [ ] **Idempotency/rate-limit:** Works in dev — but verify under multi-worker (locmem is per-process) or move to DB-backed constraint.
- [ ] **Reports (when built):** Week boundary computed in Manila local, not UTC; a single failed aggregate shows an error state, not a blank page (RPT-05).
- [ ] **AuditLog:** Written everywhere — but verify a retention/pruning plan exists before the 10 GB Express cap.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Timezone mis-storage discovered post-launch (P2) | HIGH | Determine offset applied; write a one-off migration to correct affected timestamps; re-run JOB-02 for affected dates; re-generate reports |
| Case-collation duplicate/merge on MSSQL (P1) | MEDIUM | Set correct per-column collation via migration; de-dupe or re-import affected rows; re-key faculty by canonical email |
| Duplicate job execution shipped (P6) | LOW-MEDIUM | Move scheduler to dedicated process; rely on job idempotency to bound damage; prune duplicate materialized/report rows |
| Locked out after `DEBUG=False` (P8) | HIGH if no break-glass, LOW if present | Use break-glass superuser to log in and fix Entra config; if none, requires server/DB access to create one |
| RDS Express hit 10 GB, writes failing (P10) | HIGH | Emergency prune `AuditLog`/`Notification`; scale to Standard edition or larger storage; then add retention job |
| Stale SW cache breaking users (P7) | LOW | Bump cache version + `activate` cleanup; deploy; force SW update |
| Stale offline scans applied wrongly (P4) | MEDIUM | Query `offline_queued` validations against completed/released sessions; void the bad ones; add server re-validation |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| P1 Case-insensitive collation | MSSQL migration spike | Case-variant duplicate test passes as intended on real SQL Server |
| P2 Timezone/datetime loss | MSSQL spike (gates JOB-02) | Aware-datetime round-trip test to the second; grace decision identical on SQLite vs MSSQL |
| P3 JOB-02 correctness/idempotency | JOB-02 status sweep (build order #1) | Pure-function unit tests; double-run sweep is a no-op; audit shows one transition per session |
| P4 Stale offline replay | Checker surface (CHK-08) | Queued scan against completed session is flagged, not applied |
| P5 Clock skew / multi-worker idempotency | MSSQL spike + Checker + deploy | DB unique constraint catches duplicate; `select_for_update` prevents double handover |
| P6 APScheduler N× execution | Scheduler dedicated-process phase | Counts match single execution under prod worker count; SYS-04 shows one run |
| P7 SW caching navigations | Tailwind-build / vendor-assets phase | Offline test after deploy; no cached HTML/redirects; assets same-origin |
| P8 Entra lockout | Entra ID SSO phase | Staging `DEBUG=False` login works; unprovisioned rejected; break-glass verified |
| P9 Session-vs-JWT drift | Entra ID SSO phase (decision first) | Documented decision in SRS v1.2; deactivation blocks immediately |
| P10 Express cap / SPOF | AWS deployment + retention job | DB-size monitor; scheduler restarts on boot; retention job prunes; SRS engine reconciled |

## Sources

- [mssql-django 1.7: Django 6.0, SQL Server 2025 (Microsoft Community Hub)](https://techcommunity.microsoft.com/blog/sqlserver/mssql-django-1-7-django-6-0-sql-server-2025-and-a-lot-of-catching-up/4503166) — confirms Django 6.0 support arrives in mssql-django 1.7 (HIGH)
- [microsoft/mssql-django (GitHub) + Django 6.0 support issue #483](https://github.com/microsoft/mssql-django/issues/483) — version/compat tracking (HIGH)
- [mssql-django #371 — USE_TZ + non-UTC TIME_ZONE datetime conversion](https://github.com/microsoft/mssql-django/issues/371) — timezone mis-handling (HIGH)
- [pyodbc #810 / #1141 — timezone-aware datetime / DATETIMEOFFSET not round-trippable](https://github.com/mkleehammer/pyodbc/issues/1141) — offset loss on non-UTC (HIGH)
- [Django time zones documentation](https://docs.djangoproject.com/en/6.0/topics/i18n/timezones/) — store UTC, USE_TZ guidance (HIGH)
- [Collations and case sensitivity (Microsoft Learn)](https://learn.microsoft.com/en-us/ef/core/miscellaneous/collations-and-case-sensitivity) — SQL Server default `SQL_Latin1_General_CP1_CI_AS` is case-insensitive (HIGH)
- [Django databases notes (case-sensitivity across backends)](https://docs.djangoproject.com/en/stable/ref/databases.html) — SQLite case-sensitive vs SQL Server case-insensitive (HIGH)
- [APScheduler FAQ — sharing a jobstore across processes causes duplicate execution](https://apscheduler.readthedocs.io/en/3.x/faq.html) — Gunicorn multi-worker duplication (HIGH)
- [Reliable Django Scheduled Jobs on Gunicorn (Medium)](https://medium.com/@akbarnotopb/realiable-django-scheduled-jobs-on-gunicorn-90686e4d2882) — dedicated-process pattern (MEDIUM)
- `.planning/codebase/CONCERNS.md`, `.planning/codebase/CONVENTIONS.md`, `docs/USE_CASES.md`, `FluxTrack_SRS.md` — codebase-verified gaps and conventions (HIGH)

---
*Pitfalls research for: FluxTrack attendance PWA (SQLite→MSSQL, timezone-correct attendance, offline queue, Entra SSO, single-EC2 AWS)*
*Researched: 2026-07-02*

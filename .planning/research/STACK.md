# Stack Research

**Domain:** Django 6 faculty-attendance PWA — integration/infra pieces for MSSQL + Entra SSO + scheduler + web push + Tailwind build
**Researched:** 2026-07-02
**Confidence:** HIGH (mssql-django, Django, allauth, APScheduler, pywebpush versions verified against PyPI/official blogs) / MEDIUM (Franken UI + standalone-CLI build path — genuine tension, spike required)

> **Scope note:** This file covers ONLY the five not-yet-built integration/infra pieces. The shipped stack (Django 6 + DRF + htmx + Franken UI CDN + WhiteNoise + SQLite dev) is already documented in `.planning/codebase/STACK.md` and is not re-researched here.

---

## HEADLINE FINDING (resolves the #1 spike-first risk)

**mssql-django 1.7.3 (released 2026-06-19) officially supports Django 6.0. NO Django pin-back is required.**

- Officially supported Django versions in 1.7.x: **3.2, 4.0, 4.1, 4.2, 5.0, 5.1, 5.2, 6.0**.
- Django 6.0 support landed in mssql-django **1.7** (mid-2026), with **1.7.3** as the current patch.
- SRS target **Django 6.0.6** is inside this window. The existing `requirements.txt` pin `Django>=5.0,<7.0` is compatible; **tighten it to `>=6.0,<6.1`** (or `==6.0.6`) to match the SRS and keep out of any future 6.1 that mssql-django hasn't yet certified.
- **Fallback (only if the spike surprises us):** pin to **Django 5.2 LTS** (supported to Apr 2028). 5.2 is inside every mssql-django 1.6+ support matrix, so it is a guaranteed-safe floor. But based on the published matrix this fallback should not be needed.

**Verdict for roadmap:** The MSSQL phase does **not** force a Django downgrade. Still run the compatibility spike (install + `migrate` against a throwaway SQL Server) because *runtime* behavior (composite keys, specific field types, migrations) is what the spec calls the #1 risk — but the version-ceiling blocker is cleared.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **mssql-django** | **1.7.3** (2026-06-19) | Django DB backend for SQL Server (`sql_server.pyodbc`) | Microsoft-maintained; the only actively-maintained MSSQL backend; explicitly certifies Django 6.0. Add an `mssql` branch to the `DB_ENGINE` switch. |
| **pyodbc** | **≥5.2** (auto-pulled by mssql-django) | Native ODBC connectivity Python↔SQL Server | Hard dependency of mssql-django; installed transitively. On Windows dev it needs a matching ODBC driver installed system-wide. |
| **Microsoft ODBC Driver 18 for SQL Server** | **18.x** | System-level ODBC driver (not a pip package) | mssql-django supports Driver 17 **or** 18; use **18** (current, TLS-1.2+ default). Install on Windows dev and on the Linux EC2 host (`msodbcsql18` from Microsoft's apt repo). Driver 18 defaults `Encrypt=yes` — set `TrustServerCertificate` appropriately for RDS. |
| **django-allauth** | **65.18.0** (2026-05-29) | Entra ID SSO via OpenID Connect (Auth Code + PKCE) | Supports Django 6.0; battle-tested OIDC provider; handles the full server-side redirect/callback/session flow that a server-rendered app needs. Enable PKCE via `OAUTH_PKCE_ENABLED: True`. |
| **APScheduler** | **3.11.x** (3.x series) | Single dedicated scheduler process for JOB-01/02/03 | Already declared. Use **BlockingScheduler** inside a custom management command run as its own systemd service — the canonical "one scheduler, separate from web workers" pattern. **Avoid 4.0 (still pre-release).** |
| **pywebpush** | **2.3.0+** | Send VAPID web-push messages from Django | De-facto standard Python web-push sender; pulls in `py-vapid` for JWT/ECDSA signing. Pairs with the existing `PushSubscription` model. |
| **Tailwind CSS (standalone CLI)** | **v4.x** | Compile CSS as a build step, replacing the Franken UI CDN | SRS §2.4 mandate. Franken UI 2.1 is built on **Tailwind v4**, so the build must be v4 (not v3). Produces one hashed CSS file served by WhiteNoise. |
| **Franken UI** | **2.1.x** | Component CSS + web components (self-hydrating, survive htmx swaps) | Already in use at 2.1.2 via CDN. Keep the version; vendor its `*.iife.js` and compiled CSS into `static/` instead of CDN. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **py-vapid** | **1.9.x** (auto-pulled by pywebpush) | Generates/signs VAPID JWT auth headers | Installed with pywebpush; also provides the CLI to generate the VAPID keypair once (store public key in settings/env, private key as a secret). |
| **msal** | 1.31+ | Direct Microsoft Authentication Library | ONLY if you reject allauth and hand-roll the flow, or need on-behalf-of Graph calls. Not recommended as the primary path (more glue code, you own token/session plumbing). |
| **PyJWT / cryptography / requests** | already pinned | Manual JWKS/JWT verification | Only needed if you go the **hand-rolled** Entra route. If you adopt allauth, these become largely redundant for auth (allauth verifies the ID token itself). Keep `cryptography` — pywebpush needs it. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| **Tailwind standalone CLI binary** | Compile `input.css` → `static/css/app.css` | Single self-contained binary, no Node runtime needed to *run* it. **Caveat below:** Franken UI's Tailwind v4 plugin resolution may still require an npm/`node_modules` step at build time. |
| **msodbcsql18 + unixODBC** (Linux) / **ODBC Driver 18 MSI** (Windows) | System ODBC layer for pyodbc | Must be installed on both dev (Windows) and prod (EC2 Ubuntu) hosts before `pip install pyodbc` will connect. |
| **systemd** | Run Gunicorn and APScheduler as two separate services | `fluxtrack-web.service` (Gunicorn) + `fluxtrack-scheduler.service` (BlockingScheduler command). |

## Installation

```bash
# --- MSSQL (after ODBC Driver 18 is installed system-wide) ---
py -3.12 -m pip install "mssql-django==1.7.3"   # pulls pyodbc automatically

# --- Entra ID SSO (server-rendered) ---
py -3.12 -m pip install "django-allauth==65.18.0"

# --- Scheduler (already in requirements; pin to 3.x) ---
py -3.12 -m pip install "APScheduler>=3.11,<4.0"

# --- Web Push (VAPID) ---
py -3.12 -m pip install "pywebpush>=2.3"         # pulls py-vapid + cryptography
# one-time key generation:
vapid --gen                                      # writes private/public keypair

# --- Tailwind standalone CLI (download binary, no pip) ---
#   Windows dev: download tailwindcss-windows-x64.exe (v4)
#   EC2 build:   curl -L tailwindcss-linux-x64 (v4)
```

> **Django pin change (do this in the MSSQL phase):**
> `Django>=5.0,<7.0`  →  `Django==6.0.6`  (matches SRS; inside mssql-django 1.7 support matrix)

---

## Per-Piece Prescriptions

### 1. MSSQL — RESOLVED, no pin-back
- **Use:** `mssql-django==1.7.3` + `pyodbc` (transitive) + **ODBC Driver 18**.
- **Settings branch:** add a third `mssql` arm to the `DB_ENGINE` switch in `config/settings.py`:
  ```python
  # ENGINE: "mssql", OPTIONS: {"driver": "ODBC Driver 18 for SQL Server",
  #   "extra_params": "TrustServerCertificate=yes"}  # RDS: prefer Encrypt=yes + CA bundle
  ```
- **Spike (still required, but not a version blocker):** install, point at a throwaway SQL Server Express / RDS instance, run `migrate`, then exercise the existing models (esp. any `JSONField`, unique constraints, and datetime/tz handling — SQL Server `datetime2` + `USE_TZ=True` is the classic gotcha).
- **Confidence:** HIGH on version compat; MEDIUM on migration-runtime behavior (that's what the spike de-risks).

### 2. Entra ID SSO — use django-allauth + Django sessions (NOT backend JWT)
- **Recommendation:** **django-allauth OpenID Connect** (single-tenant: `server_url = https://login.microsoftonline.com/<TENANT_ID>/v2.0`), **`OAUTH_PKCE_ENABLED: True`**, `token_auth_method: client_secret_basic`. This is a **confidential client** (server holds the client secret) doing Auth Code + PKCE server-side — the correct shape for a server-rendered app.
- **Session vs JWT — decide SESSION.** The app is server-rendered HTML with htmx, not an API-consuming SPA. Keep **Django session auth** end-to-end (DRF already uses `SessionAuthentication`). Treat the SRS §3.3 "backend verifies against JWKS / issues JWT" language as describing **the Entra token exchange only** (allauth verifies the ID token against Microsoft's JWKS during callback), not a mandate to mint app-level JWTs. Introducing a backend JWT layer for a same-origin server-rendered app adds token storage/refresh/rotation complexity with zero benefit.
- **Wiring notes:** map Entra `oid` claim → existing `accounts.User.azure_oid`. Keep imported-faculty accounts `set_unusable_password()` (SSO-only). Retire the DEBUG dev-login stub behind SSO (or keep it DEBUG-gated for local runs).
- **Alternative:** `msal` / `django-azure-auth` if you need Graph API on-behalf-of calls later — not for baseline login.
- **Confidence:** HIGH (allauth Django 6.0 support + PKCE support both verified).

### 3. APScheduler — dedicated BlockingScheduler process, separate systemd unit
- **Process model:** a custom management command (e.g. `manage.py run_scheduler`) that instantiates a **`BlockingScheduler`** and blocks. Run it as **`fluxtrack-scheduler.service`**, entirely separate from `fluxtrack-web.service` (Gunicorn).
- **Avoid duplicate execution:** the root cause of double-runs is a scheduler started *inside* Gunicorn workers (N workers → N schedulers). By running the scheduler ONLY in its own process and **never** starting it in web-worker startup, you guarantee exactly one instance. Do NOT rely on Gunicorn `--preload` tricks — the dedicated-process model is cleaner and survives web-server changes.
- **Job store:** in-memory default is fine for a single scheduler process; JOB-01/02/03 are idempotent (re-materialization/sweeps are safe to repeat). Add DB-backed job tracking later for SYS-04 monitoring (a small custom `JobRun` model or `django-apscheduler` if you want the admin surface — optional, not required).
- **systemd wiring:** `ExecStart=/path/venv/bin/python manage.py run_scheduler`, `Restart=on-failure`, same env/user as web. Guard against overlap with `max_instances=1` + `misfire_grace_time` per job.
- **Version:** `APScheduler>=3.11,<4.0` — 4.0 is a ground-up rewrite still in pre-release; do not adopt.
- **Confidence:** HIGH.

### 4. Web Push (VAPID) — pywebpush + py-vapid, direct (no wrapper needed)
- **Use:** `pywebpush>=2.3` (pulls `py-vapid` + `cryptography`). The `PushSubscription` model (endpoint + `keys` JSON) already exists in `ops/models.py`, so a heavyweight wrapper like `django-webpush` is unnecessary — call `webpush()` directly from the notification send path.
- **Keys:** generate one VAPID keypair (`vapid --gen`); public key → client `PushManager.subscribe({applicationServerKey})`; private key + `sub` mailto claim → server, kept as a secret (env/secrets, never committed).
- **Service worker:** add a `push` event listener (`self.registration.showNotification(...)`) and a `notificationclick` handler to the existing inline `SW_JS` in `web/views.py`. Client subscribes via `PushManager.subscribe()` and POSTs the subscription to a Django endpoint that upserts a `PushSubscription` row.
- **Sequencing:** NOTIF-02 (push) builds on NOTIF-01 (in-app read surface) — push is delivery, the in-app list is the source of truth. Handle `410 Gone` from the push service by deleting stale subscriptions.
- **Confidence:** HIGH on libraries; the send path is standard.

### 5. Tailwind standalone CLI + Franken UI 2.x — biggest integration risk, spike it
- **Key fact:** Franken UI **2.1 is built on Tailwind CSS v4**, so the build MUST use the **Tailwind v4** standalone CLI, not v3. (v3→v4 changed config from `tailwind.config.js` to CSS-first `@theme`/`@plugin`.)
- **The tension (flag clearly):** Franken UI's official install is **npm-first** (`npx franken-ui init`, PostCSS plugin). The Tailwind **standalone CLI binary cannot resolve npm plugins** (`@plugin "franken-ui"` needs `node_modules`). So the pure "standalone-CLI, zero-Node" path and "Franken UI as a Tailwind plugin" are partly in conflict.
- **Recommended resolution:** distinguish **build-time** from **runtime**. The real project constraint is *no Node.js in the production runtime* — not "never run npm on the dev machine." So:
  - **Option A (pragmatic, recommended):** Use **npm at build-time only** on the dev/CI machine to run Franken UI's Tailwind v4 pipeline, producing a single compiled, hashed CSS file. Commit/collect that file; serve via **WhiteNoise**. Production stays Node-free. Vendor Franken UI's `core.iife.js` / `icon.iife.js` and htmx/html5-qrcode into `static/`.
  - **Option B (strict standalone):** Use the Tailwind v4 standalone binary for utility classes, and **pre-vendor Franken UI's prebuilt CSS** (its published `core.min.css`/`utilities.min.css`) into `static/` rather than compiling it as a plugin. Less "tree-shaken" but fully Node-free even at build time.
- **Either way:** replace all four CDN `<link>`/`<script>` tags in `templates/base.html` with `{% static %}` references so the PWA service worker can cache same-origin assets (cross-origin CDN caching is unreliable — this is the stated CONCERNS.md driver).
- **Confidence:** MEDIUM. Franken-UI-2.1-on-Tailwind-v4 is confirmed; the exact standalone-vs-npm build ergonomics need a short spike. Recommend a dedicated build-step spike in the deploy phase.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| mssql-django 1.7.3 | django-mssql-backend / django-pyodbc-azure | Never — both are abandoned/unmaintained; mssql-django is Microsoft's official successor. |
| Django 6.0.6 (pinned) | Django 5.2 LTS | Only if the MSSQL spike reveals a 6.0-specific runtime break (not expected). 5.2 is the guaranteed-safe LTS floor to Apr 2028. |
| django-allauth (session) | MSAL / django-azure-auth; hand-rolled PyJWT+JWKS | MSAL if you later need Graph on-behalf-of; hand-rolled only if you must avoid allauth's model footprint. Backend-JWT layer only if a true separate SPA/mobile client appears. |
| BlockingScheduler in dedicated systemd unit | Gunicorn `--preload` single scheduler; django-apscheduler; Celery beat | `--preload` is fragile (breaks on worker recycling). Celery is over-engineered for 3 idempotent jobs at capstone scale (adds a broker). Add `django-apscheduler` only for admin/monitoring UI (SYS-04). |
| pywebpush direct | django-webpush / django-pwa-webpush | Wrapper libs if you had no existing subscription model — but `PushSubscription` already exists, so direct is less indirection. |
| Tailwind v4 standalone (build-time npm ok) | Keep Franken UI CDN | CDN violates SRS §2.4 and breaks PWA offline caching — must be replaced before deploy. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Pinning Django back to 5.x "to be safe" | Unnecessary — mssql-django 1.7 supports 6.0; downgrading loses 6.0 features for no reason | `Django==6.0.6` |
| APScheduler 4.0 | Pre-release rewrite, API churn, not production-proven | `APScheduler>=3.11,<4.0` |
| Starting the scheduler inside Gunicorn workers | N workers → N schedulers → duplicate/missed jobs (the exact SRS §6.7 failure mode) | Dedicated `run_scheduler` systemd service |
| Backend app-issued JWT for the server-rendered UI | Adds token storage/refresh complexity with no benefit for same-origin htmx pages | Django session auth |
| Tailwind v3 config for Franken UI 2.x | Franken UI 2.1 requires Tailwind **v4** (CSS-first config); v3 config won't apply | Tailwind v4 standalone CLI |
| ODBC Driver 13/17-only assumptions | Driver 18 changes TLS/encrypt defaults; older drivers lack current TLS | ODBC Driver 18 (17 acceptable but not preferred) |
| django-mssql-backend, django-pyodbc-azure | Abandoned | mssql-django |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| mssql-django 1.7.3 | Django 3.2–6.0; Python 3.8–3.14 | Django 6.0 requires Python 3.12+ (project already on 3.12 ✓). ODBC Driver 17 or 18. |
| Django 6.0.6 | mssql-django 1.7.x, django-allauth 65.18.0, DRF ≥3.15 | All three certify Django 6.0. |
| django-allauth 65.18.0 | Django 4.2–6.0; Python ≥3.10 | PKCE via `OAUTH_PKCE_ENABLED`; OIDC provider for Entra single-tenant. |
| pywebpush 2.3+ | py-vapid 1.9.x, cryptography ≥42 | cryptography already pinned in requirements. |
| Franken UI 2.1.x | Tailwind CSS v4 | Set Tailwind `preflight=false`, `layer=true` when combining; requires v4-specific `@theme` config. |
| APScheduler 3.11.x | Python 3.8+; framework-agnostic | Not <4.0. |

## Stack Patterns by Variant

**If the MSSQL spike passes cleanly (expected):**
- Pin `Django==6.0.6`, add `mssql` branch, ship on SQL Server Express RDS. No downstream changes.

**If the MSSQL spike hits a Django-6.0-specific runtime break (unlikely):**
- Fall back to `Django==5.2` (LTS to 2028); everything else (allauth, APScheduler, pywebpush) still supports 5.2. This is the only scenario that touches the Django pin.

**If build-time Node is truly unacceptable even on the dev machine:**
- Use Tailwind-standalone Option B: vendor Franken UI's prebuilt CSS into `static/`, run standalone CLI only for project utility classes.

## Sources

- [mssql-django 1.7: Django 6.0, SQL Server 2025 — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/sqlserver/mssql-django-1-7-django-6-0-sql-server-2025-and-a-lot-of-catching-up/4503166) — Django 6.0 support confirmation (HIGH)
- [mssql-django · PyPI](https://pypi.org/project/mssql-django/) — v1.7.3 (2026-06-19), Django 3.2–6.0, Python 3.8–3.14, ODBC 17/18 (HIGH)
- [Announcing mssql-django 1.7.2 — Microsoft Community Hub](https://techcommunity.microsoft.com/blog/sqlserver/announcing-mssql-django-1-7-2/4522336) — patch cadence (HIGH)
- [Django 6.0 released — djangoproject.com](https://www.djangoproject.com/weblog/2025/dec/03/django-60-released/) — 6.0 GA 2025-12-03; 5.2 is the LTS (HIGH)
- [Django | endoflife.date](https://endoflife.date/django) — 5.2 LTS to Apr 2028; 6.0 to Apr 2027 (HIGH)
- [OpenID Connect — django-allauth docs](https://docs.allauth.org/en/dev/socialaccount/providers/openid_connect.html) — Entra single-tenant OIDC + PKCE config (HIGH)
- [Microsoft — django-allauth docs](https://docs.allauth.org/en/dev/socialaccount/providers/microsoft.html) — Entra provider guidance (HIGH)
- [django-allauth · PyPI](https://pypi.org/project/django-allauth/) — 65.18.0 (2026-05-29), Django 4.2–6.0 (HIGH)
- [APScheduler FAQ — readthedocs](https://apscheduler.readthedocs.io/en/3.x/faq.html) — no interprocess sync → one scheduler only (HIGH)
- [django-apscheduler — GitHub (jcass77)](https://github.com/jcass77/django-apscheduler) — dedicated-process / duplicate-execution guidance (MEDIUM)
- [pywebpush · PyPI](https://pypi.org/project/pywebpush/) — 2.3.x, py-vapid dependency (HIGH)
- [Browser Push Notifications for a Django Website — DjangoTricks (2026-06)](https://www.djangotricks.com/blog/2026/06/browser-push-notifications-for-a-django-website/) — service-worker push pattern (MEDIUM)
- [Franken UI 2.1 Installation](https://franken-ui.dev/docs/2.1/installation) / [Theming](https://franken-ui.dev/docs/2.1/theming) — built on Tailwind v4, preflight/layer config (MEDIUM, page partly gated)
- [Standalone CLI: Tailwind without Node.js — tailwindcss.com](https://tailwindcss.com/blog/standalone-cli) — standalone binary capabilities/limits (MEDIUM)
- [django-tailwind-cli — GitHub (django-commons)](https://github.com/django-commons/django-tailwind-cli) — standalone-CLI Django integration option (MEDIUM)

---
*Stack research for: Django 6 integration/infra additions (MSSQL, Entra SSO, scheduler, web push, Tailwind build)*
*Researched: 2026-07-02*

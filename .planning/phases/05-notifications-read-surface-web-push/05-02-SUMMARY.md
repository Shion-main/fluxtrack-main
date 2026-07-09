---
phase: 05-notifications-read-surface-web-push
plan: 02
subsystem: infra
tags: [web-push, vapid, pywebpush, py-vapid, http-ece, notifications, secrets, django-settings]

# Dependency graph
requires:
  - phase: 02-correctness-foundations
    provides: "notify() single Notification write path (NOTIF-00) that the push outbox will drain"
provides:
  - "pywebpush>=2.3,<3 pinned + installed (pulls py-vapid + http-ece; reuses existing cryptography)"
  - "settings.VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY_PATH / VAPID_SUB read from env with empty-safe defaults"
  - "FLUXTRACK_POLICY['push_outbox_interval_seconds']=15 — policy-driven scheduler cadence (D-09)"
  - ".gitignore hardened (*.pem + keys/) so the VAPID private key can never be committed (T-05-03)"
  - "Locally-generated, gitignored VAPID keypair (keys/private_key.pem + public_key.pem) with .env populated"
affects: [05-03-outbox-sender, 05-04-context-processor, 05-05-client-subscription]

# Tech tracking
tech-stack:
  added: [pywebpush, py-vapid, http-ece, aiohttp]
  patterns:
    - "Secret material referenced by env path, never inlined; PEM gitignored via *.pem + keys/"
    - "Empty-safe VAPID defaults so the app boots when push is unconfigured (sender treats empty key path as 'push off')"
    - "Scheduler cadence sourced from FLUXTRACK_POLICY, never a magic number (Convention rule #3)"

key-files:
  created:
    - "keys/private_key.pem (gitignored, secret — never committed)"
    - "keys/public_key.pem (gitignored)"
  modified:
    - "requirements.txt — pywebpush pin under Web push (NOTIF-02) heading"
    - "config/settings.py — VAPID_* config block + push_outbox_interval_seconds policy default"
    - ".gitignore — *.pem + keys/"
    - ".env.example — VAPID placeholders"
    - ".env — real (gitignored) VAPID values populated"

key-decisions:
  - "VAPID public key exposed via env (from `vapid --applicationServerKey`); private key referenced by path only, never inlined in settings (T-05-03)"
  - "push_outbox_interval_seconds=15 lives in FLUXTRACK_POLICY (SystemSetting-overridable), not hardcoded in the future scheduler job (D-09/Convention #3)"
  - "Empty-string defaults for all three VAPID_* values so an unconfigured environment still boots; the 05-03 sender interprets an empty key path as push-disabled"
  - "Task 1 package-legitimacy gate (T-05-SC) satisfied: operator approved pywebpush 2.3.0 / py-vapid 1.9.4 / http-ece 1.2.1 after pypi.org verification against web-push-libs / mozilla-services"

patterns-established:
  - "Secret-by-path: VAPID private key is a gitignored PEM referenced through VAPID_PRIVATE_KEY_PATH; git check-ignore is the proof gate"
  - "New third-party dependency isolated behind a blocking-human legitimacy checkpoint before install (supply-chain gate)"

requirements-completed: [NOTIF-02]

coverage:
  - id: D1
    description: "pywebpush>=2.3,<3 pinned in requirements.txt and importable (pulls py-vapid + http-ece; cryptography already present)"
    requirement: "NOTIF-02"
    verification:
      - kind: automated_ui
        ref: "py -3.12 -c \"import pywebpush; import py_vapid; import http_ece; print('ok')\" -> ok"
        status: pass
    human_judgment: false
  - id: D2
    description: "settings exposes VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY_PATH / VAPID_SUB from env with empty-safe defaults, plus FLUXTRACK_POLICY push_outbox_interval_seconds cadence"
    requirement: "NOTIF-02"
    verification:
      - kind: integration
        ref: "django.setup() + assert all three VAPID_* attrs present and FLUXTRACK_POLICY['push_outbox_interval_seconds']==15 -> True / 15"
        status: pass
    human_judgment: false
  - id: D3
    description: "VAPID private key PEM is gitignored (*.pem + keys/) and never staged/committed"
    requirement: "NOTIF-02"
    verification:
      - kind: integration
        ref: "git check-ignore keys/private_key.pem -> keys/private_key.pem; git status --porcelain shows no .pem/.env staged"
        status: pass
    human_judgment: false
  - id: D4
    description: "VAPID keypair generated locally and .env populated with non-empty VAPID_PUBLIC_KEY + VAPID_PRIVATE_KEY_PATH pointing at an existing PEM"
    requirement: "NOTIF-02"
    verification:
      - kind: integration
        ref: "py -3.12 load_dotenv('.env') + assert VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY_PATH and Path(p).exists() -> vapid ok"
        status: pass
    human_judgment: false

# Metrics
duration: 3min
completed: 2026-07-09
status: complete
---

# Phase 05 Plan 02: Web-push VAPID prerequisites Summary

**pywebpush pinned + installed, VAPID public/private-key-path/subject wired from env with empty-safe defaults, a policy-driven push-outbox cadence added, and a locally-generated VAPID keypair whose private PEM is provably gitignored.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-07-09T14:14:18Z
- **Completed:** 2026-07-09T14:17:31Z
- **Tasks:** 2 executed (Task 1 legitimacy gate pre-approved by operator)
- **Files modified:** 5 (2 created, 3 modified in git; .env + .env.example also touched)

## Accomplishments
- Installed and pinned `pywebpush>=2.3,<3` (pulled py-vapid 1.9.4 + http-ece 1.2.1; reused existing cryptography wheel — no Windows build gotcha), all three importable.
- Wired the VAPID config block in `config/settings.py` (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY_PATH / VAPID_SUB via `env()` with empty-string defaults) and added `push_outbox_interval_seconds=15` to `FLUXTRACK_POLICY` (D-09, policy-driven cadence).
- Hardened `.gitignore` with `*.pem` + `keys/` and generated a real VAPID keypair locally; `git check-ignore keys/private_key.pem` confirms the private key can never be committed (T-05-03).
- Populated the gitignored `.env` with the base64url application server key + key path + subject; `.env.example` carries the matching placeholders for other environments.

## Task Commits

1. **Task 1: Package legitimacy gate (T-05-SC)** — no commit; blocking-human checkpoint pre-approved by the operator after pypi.org verification of pywebpush 2.3.0 / py-vapid 1.9.4 / http-ece 1.2.1 against web-push-libs / mozilla-services. Recorded in the Task 2 commit trailer.
2. **Task 2: Pin + install pywebpush; wire VAPID config, cadence, gitignore** — `a975c39` (feat)
3. **Task 3: Generate the VAPID keypair and populate .env** — no git commit by design. All artifacts are gitignored (`keys/private_key.pem`, `keys/public_key.pem`, and the appended `.env`); the `.env.example` placeholder note was already shipped in the Task 2 commit. The plan itself notes ".env.example note ... but the runtime effect is the populated .env + generated PEM."

**Plan metadata:** `docs(05-02): complete ...` (final docs commit — this SUMMARY + STATE + ROADMAP)

## Files Created/Modified
- `requirements.txt` — added `pywebpush>=2.3,<3` under a `# Web push (NOTIF-02)` heading.
- `config/settings.py` — new `# --- Web push (VAPID, NOTIF-02) ---` block (three env-read values, empty-safe) + `push_outbox_interval_seconds` in `FLUXTRACK_POLICY`.
- `.gitignore` — `*.pem` + `keys/` so the VAPID private key is never committed.
- `.env.example` — VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY_PATH / VAPID_SUB placeholders + note that the PEM is never committed.
- `.env` (gitignored) — real VAPID values populated (public key, key path, subject).
- `keys/private_key.pem` + `keys/public_key.pem` (gitignored) — generated VAPID keypair; private PEM is secret.

## Decisions Made
- Private key referenced by path only (`VAPID_PRIVATE_KEY_PATH`), never inlined; the PEM lives under gitignored `keys/` and its contents were never echoed (T-05-03).
- Cadence lives in `FLUXTRACK_POLICY` (SystemSetting-overridable) rather than being hardcoded into the future scheduler job — consistent with Convention rule #3 (policy via `get_policy()`, never magic numbers).
- Empty-string VAPID defaults keep the app booting when push is unconfigured; the 05-03 outbox sender will treat an empty key path as "push disabled".

## Deviations from Plan
None - plan executed exactly as written. Task 3 produced no git commit because every artifact it touches is gitignored (`.env` + `keys/`) and the `.env.example` placeholders were committed in Task 2; this is the plan's stated intent, not a deviation.

## Issues Encountered
- The permission sandbox denies all read operations (Read tool, Grep, `cat`/`tail`/`sed`) on `.env*` files as a secret-protection guard. Existence tests and append writes are permitted, so `.env.example` and `.env` were updated via `printf >>` append (no overwrite, no secret ever read back or echoed). The VAPID private key contents were never printed at any point — only the public application server key (safe to expose) was captured to populate `.env`.

## User Setup Required
None for local dev — the keypair is generated and `.env` is populated. For each **new environment** (staging/prod), regenerate a distinct keypair with `vapid --gen` inside a gitignored `keys/`, set `VAPID_PUBLIC_KEY` from `vapid --applicationServerKey`, point `VAPID_PRIVATE_KEY_PATH` at the PEM, and set `VAPID_SUB` to the real admin contact URI. The private PEM must never be committed. (See the VAPID block in `.env.example`.)

## Next Phase Readiness
- `settings.VAPID_PRIVATE_KEY_PATH` + `settings.VAPID_SUB` are ready to be consumed by the 05-03 outbox sender; `settings.VAPID_PUBLIC_KEY` is ready to reach the client via the 05-04 context processor.
- No context processor was registered here (that is 05-04's job, per the plan).
- No blockers.

## Self-Check: PASSED

- requirements.txt, config/settings.py, .gitignore — present
- keys/private_key.pem, keys/public_key.pem — present (gitignored, not staged)
- 05-02-SUMMARY.md — present
- Commit a975c39 — present in git history

---
*Phase: 05-notifications-read-surface-web-push*
*Completed: 2026-07-09*

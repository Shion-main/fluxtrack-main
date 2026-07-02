# Session — 2026-07-02: Planning, new features, and GSD roadmap

## What was done

- **Deployment/dev-practice design** — decided MSSQL (school IT requirement) via
  `mssql-django`, single AWS EC2 + RDS SQL Server Express, solo development.
  Dropped an earlier collaborator-driven frontend/backend folder split (cosmetic
  only). Spec: `docs/superpowers/specs/2026-07-02-deployment-and-dev-practice-design.md`.
- **Documentation** — wrote `docs/USE_CASES.md` (technical, per-requirement
  built/not status) and `docs/SCENARIOS.md` (plain-language per-role narratives);
  updated README with a maintained "Project Structure" section.
- **Two new features designed + spec'd:**
  - Modality shift approval (Faculty→Dean→IFO, auto room-release) — removes
    CHK-06, amends CHK-03/FAC-07. `.../2026-07-02-modality-shift-approval-design.md`.
  - Dean dashboard (DEAN-04) + RPT-02 Dean notification. `.../2026-07-02-dean-dashboard-design.md`.
  - Both require an SRS v1.2 revision (tracked as DOC-01, Phase 4).
- **GSD project initialized** (`/gsd:do` → new-project): codebase mapped (7 docs),
  4-dimension project research (Opus) + synthesis, PROJECT.md, REQUIREMENTS.md
  (57 reqs), ROADMAP.md (8 phases), config (yolo/standard/quality/all-agents).
- **Phase 1 discussed** — `01-CONTEXT.md` captured: SQL Server Express 2022 native,
  dedicated DB+login in .env, ODBC 18 TrustServerCertificate locally, clean rebuild,
  automated R3 parity test, fix-forward migrations, MSSQL-only (drop SQLite),
  column-level CS collation on qr_token/manual_code, case-insensitive email,
  datetime2/UTC + round-trip test.

## Key findings

- **mssql-django 1.7.3 supports Django 6.0** → pin `Django==6.0.6`, no downgrade
  (this was the flagged #1 risk; now cleared).
- **New risk:** Franken UI 2.1 needs Tailwind v4 with npm-first plugin path —
  spike in the deploy phase, keep prod Node-free.
- **Ordering correction from research:** a shared `notify()` write-path must land
  early (Phase 2) as a prerequisite for JOB-02 conflict flags AND modality notices;
  the read/push UI stays in Phase 5. JOB-02's Absent rule must reuse the resolver's
  grace predicate or scan-time and sweep-time contradict.
- **Correctness hole confirmed:** JOB-02 doesn't exist — Absent is only detected
  reactively at scan time today, so an un-scanned session is never marked Absent.

## What's left / next

- `/gsd:plan-phase 1` — turn Phase 1 CONTEXT into an executable plan, then execute.
- Open thread: user chose "all tests against MSSQL"; captured as "no SQLite test
  path" (resolver SimpleTestCase tests stay DB-free). Confirm if they meant every
  test through a live SQL Server connection.
- SRS v1.2 revision still pending (Phase 4).

## Commits this session

Design docs + USE_CASES/SCENARIOS + README, then GSD artifacts under `.planning/`
(codebase map, research, PROJECT/REQUIREMENTS/ROADMAP/STATE, config, Phase 1 CONTEXT).

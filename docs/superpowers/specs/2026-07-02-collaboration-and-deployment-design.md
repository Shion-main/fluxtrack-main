# FluxTrack: Collaboration Model & Deployment Design

**Date:** 2026-07-02
**Status:** Approved, pending implementation plan

## Context

FluxTrack now has two active contributors: the user (frontend-leaning) and a
collaborator (backend-leaning). Development so far has been solo. This design
covers four things needed before parallel work starts:

1. How the repository is physically organized for two people working at once.
2. What database engine and cloud target production runs on.
3. What rules both contributors follow so work stays consistent without a
   shared session history.
4. How project state (structure, decisions, session-to-session context) stays
   discoverable instead of living only in chat history.

Everything here builds on the existing stack decision already recorded in
`FluxTrack_SRS.md`/`.docx` v1.1: Django + DRF backend, server-rendered Django
templates + htmx + Franken UI (no React/Node runtime), PWA, mobile-first for
Faculty/Checker surfaces. Nothing in this design reopens that decision.

## 1. Repository structure: physical frontend/backend folders

The collaborator wants a visible frontend/backend folder split in the repo.
Django's views and templates are tightly coupled — a literal split doesn't
create real independence — but a **physical reorganization that keeps a
single Django project/server** is achievable and satisfies the ask without
reintroducing a second server or build system.

Target layout:

```
fluxtrack-main/
├── manage.py
├── config/                  # settings.py, urls root, wsgi/asgi — belongs to neither side
├── backend/
│   ├── __init__.py
│   ├── accounts/
│   ├── campus/
│   ├── scheduling/          # includes resolver.py
│   ├── verification/
│   ├── ops/
│   └── web/                 # views.py, faculty.py, ifo.py, scan.py, urls.py
├── frontend/
│   ├── templates/           # all .html (Franken UI + htmx)
│   ├── static/               # custom CSS/JS beyond the Franken UI CDN
│   └── manifest/             # PWA manifest + service worker source
├── data/                     # gitignored registrar source data (unchanged)
├── poc/                      # retained reference POC (unchanged)
└── docs/                     # this design, DEVELOPMENT.md, session logs
```

Mechanics:

- Each backend app's `apps.py` sets `name = "backend.<app>"`; `INSTALLED_APPS`
  in `config/settings.py` lists the dotted paths.
- `TEMPLATES[0]["DIRS"]` points to `frontend/templates`; `STATICFILES_DIRS`
  points to `frontend/static`.
- `manage.py` and `config/` stay at repo root. There is still exactly one
  `runserver` / one Gunicorn process / one deployment — this decision does
  **not** reopen the "no separate frontend server" decision from the SRS.

Known limitation, documented so it doesn't get rediscovered as a surprise:
this split is organizational, not functional. Adding a new page still touches
a view under `backend/web/` and a template under `frontend/templates/`. It
does not remove the coordination need described in Section 2 — it makes the
existing vertical-slice ownership visible in the folder tree, nothing more.

## 2. Team collaboration model: vertical slices by surface

Rejected: strict layer split (frontend-only touches templates, backend-only
touches views) — causes constant conflicts on the same view files, since a
Django view and its template are one feature.

Adopted: each contributor owns a *surface* end-to-end (views + templates +
tests within that surface), leaning toward stated strengths where the work
naturally splits that way:

| Owner | Slices |
|---|---|
| User (frontend-leaning) | Checker surface (CHK-01–08): floor view, verify/flag actions, offline IndexedDB queue; Guard + Dean surfaces; notifications UI, PWA polish; HR surface + CSV export UI |
| Collaborator (backend-leaning) | MSSQL migration; AWS deployment; Entra ID SSO; Reporting engine |

This table is a starting point, not fixed — it moves to `DEVELOPMENT.md` and
gets updated as slices complete or get reassigned; the design doc is not the
source of truth for current ownership.

Git rules:

- Branch per surface off `main`: `feature/checker-surface`,
  `feature/mssql-migration`, etc. No direct pushes to `main`.
- PR into `main` once a slice's core flow works end-to-end, not necessarily
  100% of its use-cases — smaller PRs, less drift.
- Shared files (`config/settings.py`, `backend/web/urls.py`,
  `frontend/templates/base.html`, `requirements.txt`) get small, frequent
  commits. Rebase on latest `main` before opening a PR that touches them.
- Before a PR: gstack's `/review` skill for a pre-landing diff review, then
  `/ship` to run tests, bump version, and open the PR.
- When a slice is done: `finishing-a-development-branch` skill decides
  merge vs. PR vs. cleanup.
- `verify` skill before committing any nontrivial change — drive the flow
  end-to-end in-browser, not just run tests (this is how the Faculty
  check-in slice was validated).
- `using-git-worktrees` when either contributor needs to context-switch to a
  second slice without losing in-progress state on the first.

## 3. Database engine: MSSQL

Driven by a school/registrar IT requirement (not a technical preference).

- **Engine:** SQL Server, via `mssql-django` (Microsoft's maintained Django
  backend) on top of `pyodbc` + Microsoft ODBC Driver 18.
- **Local dev:** SQL Server Express (or LocalDB) installed on each
  contributor's machine, replacing SQLite for dev/prod parity. ODBC driver
  setup is more straightforward on Windows than on the Linux deployment
  target.
- **Open risk, first task before anything else depends on it:** `mssql-django`
  compatibility with Django 6.0.6 (the version recorded in the SRS) is
  unconfirmed. Spike: `pip install mssql-django pyodbc`, point
  `config/settings.py`'s existing `DB_ENGINE` switch at a throwaway instance,
  run `manage.py migrate`. If incompatible, fall back to pinning Django to
  the newest minor version `mssql-django` supports — decide only after the
  spike, not in advance.
- `config/settings.py`'s existing `DB_ENGINE` env switch (already built for
  SQLite/MySQL) gains a third branch for `mssql`. `requirements.txt` gains
  `mssql-django` and `pyodbc`.

## 4. Deployment target: AWS, single EC2 + RDS SQL Server Express

Chosen for "simplest possible" given capstone scope (small, single-campus
user base: faculty, checkers, IFO staff).

- **EC2** (`t3.micro`, free-tier eligible): Nginx (TLS via certbot; PWA
  service workers require HTTPS) → Gunicorn running the Django app as one
  systemd service. APScheduler runs as a **second systemd service on the
  same instance** — a second process, not a second server, satisfying the
  SRS §6.7 "dedicated process" requirement without adding infrastructure.
- **RDS for SQL Server, Express edition** (`db.t3.micro`, free-tier eligible,
  20GB storage; SQL Server Express itself caps a single DB at 10GB, which is
  fine at this scale). A managed resource specifically so neither
  contributor owns DB patching/backups.
- **AWS surface kept minimal:** EC2 + one Security Group (80/443 open, 22
  restricted to admin IP) + RDS + a second Security Group restricting RDS to
  only the EC2 instance's security group + optional Elastic IP. No Elastic
  Beanstalk, no S3 — media files live on the EC2 instance's EBS volume.

## 5. Development documentation: `docs/DEVELOPMENT.md`

One file both contributors (and any future session, human or AI) read before
starting work. Sections:

1. Stack recap (cross-reference SRS v1.1, don't duplicate it).
2. Environment setup — Windows `py -3.12`, `.env` vars, local run
   instructions (cross-reference README, don't duplicate).
3. Surface ownership table (Section 2 above), kept current.
4. Git rules (Section 2 above).
5. Codebase conventions already established in the code — not invented here:
   - `scheduling/resolver.py` stays a pure function, no side effects.
   - Every state-changing action writes an `AuditLog` row.
   - Policy values come from `get_policy()` / `SystemSetting`, never
     hardcoded constants.
   - Management commands print ASCII only (Windows console is cp1252).
6. Definition of done for a slice: tests pass; verified end-to-end in-browser
   (not just unit tests); README "Project Structure" updated if the change
   added/removed an app or top-level directory; a session log entry written.

## 6. README maintenance rule

Add a clearly delimited `## Project Structure` section to `README.md`
(directory tree + one-line purpose per app/folder, matching Section 1's
layout once the restructure lands). Rule, enforced via the definition of done
in `DEVELOPMENT.md` rather than a hook or CI check: **any PR that adds,
removes, or renames a Django app, top-level directory, or surface updates
this section in the same PR.**

## 7. Session log convention

`docs/sessions/YYYY-MM-DD-<short-topic>.md`, one file per session — not a
single shared log, since two contributors appending to one file guarantees
merge conflicts. Each entry covers: what was done, decisions made and why,
problems hit and how they were solved, what's left. `docs/sessions/README.md`
indexes them newest-first.

Rule: the last thing before ending any work session is writing this entry.
It becomes the first thing a new session — a returning contributor or a new
Claude Code session — reads to pick up context, cheaper than re-reading the
whole codebase or this design doc.

## Out of scope for this design

- Actually performing the folder move, settings changes, `mssql-django`
  spike, or AWS provisioning — these are implementation, covered by the plan
  that follows this design.
- Reopening the Django-templates-over-React decision — not on the table.
- Guard/Dean/HR surface *content* design — only their ownership is decided
  here; their UX is designed when that slice starts.

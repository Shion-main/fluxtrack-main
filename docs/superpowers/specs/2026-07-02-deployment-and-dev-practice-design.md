# FluxTrack: Deployment & Development Practice Design

**Date:** 2026-07-02
**Status:** Approved, pending implementation plan

## Context

FluxTrack is developed solo (an earlier draft of this design assumed a second
contributor and included a frontend/backend folder split and surface
ownership model — dropped once that changed). This design now covers three
things:

1. What database engine and cloud target production runs on.
2. What rules keep development consistent across sessions, given work
   happens in discrete Claude Code sessions rather than one continuous
   sitting.
3. How project state (structure, decisions, session-to-session context) stays
   discoverable instead of living only in chat history that gets compacted
   or lost.

Everything here builds on the existing stack decision already recorded in
`FluxTrack_SRS.md`/`.docx` v1.1: Django + DRF backend, server-rendered Django
templates + htmx + Franken UI (no React/Node runtime), PWA, mobile-first for
Faculty/Checker surfaces. Nothing in this design reopens that decision. The
repository structure also stays as-is (flat Django apps at root:
`accounts/`, `campus/`, `scheduling/`, `verification/`, `ops/`, `web/`,
`templates/`, `static/`) — no folder reorganization.

## 1. Database engine: MSSQL

Driven by a school/registrar IT requirement (not a technical preference),
and unrelated to team size — this stays regardless of solo vs. team
development.

- **Engine:** SQL Server, via `mssql-django` (Microsoft's maintained Django
  backend) on top of `pyodbc` + Microsoft ODBC Driver 18.
- **Local dev:** SQL Server Express (or LocalDB) installed locally,
  replacing SQLite for dev/prod parity. ODBC driver setup is more
  straightforward on Windows than on the Linux deployment target.
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

## 2. Deployment target: AWS, single EC2 + RDS SQL Server Express

Chosen for "simplest possible" given capstone scope (small, single-campus
user base: faculty, checkers, IFO staff).

- **EC2** (`t3.micro`, free-tier eligible): Nginx (TLS via certbot; PWA
  service workers require HTTPS) → Gunicorn running the Django app as one
  systemd service. APScheduler runs as a **second systemd service on the
  same instance** — a second process, not a second server, satisfying the
  SRS §6.7 "dedicated process" requirement without adding infrastructure.
- **RDS for SQL Server, Express edition** (`db.t3.micro`, free-tier eligible,
  20GB storage; SQL Server Express itself caps a single DB at 10GB, which is
  fine at this scale). A managed resource so DB patching/backups aren't
  manual work.
- **AWS surface kept minimal:** EC2 + one Security Group (80/443 open, 22
  restricted to admin IP) + RDS + a second Security Group restricting RDS to
  only the EC2 instance's security group + optional Elastic IP. No Elastic
  Beanstalk, no S3 — media files live on the EC2 instance's EBS volume.

## 3. Development documentation: `docs/DEVELOPMENT.md`

One file read at the start of any work session — the point is consistency
across sessions, not across people. Sections:

1. Stack recap (cross-reference SRS v1.1, don't duplicate it).
2. Environment setup — Windows `py -3.12`, `.env` vars, local run
   instructions (cross-reference README, don't duplicate).
3. Codebase conventions already established in the code — not invented here:
   - `scheduling/resolver.py` stays a pure function, no side effects.
   - Every state-changing action writes an `AuditLog` row.
   - Policy values come from `get_policy()` / `SystemSetting`, never
     hardcoded constants.
   - Management commands print ASCII only (Windows console is cp1252).
4. Definition of done for a slice of work: tests pass; verified end-to-end
   in-browser (not just unit tests); README "Project Structure" updated if
   the change added/removed an app or top-level directory; a session log
   entry written.

If a second contributor joins later, this file gains a surface-ownership
table and git branching rules at that point — not speculatively now.

## 4. README maintenance rule

Add a clearly delimited `## Project Structure` section to `README.md`
(directory tree + one-line purpose per app/folder, matching the existing flat
layout). Rule, enforced via the definition of done in `DEVELOPMENT.md` rather
than a hook or CI check: **any change that adds, removes, or renames a
Django app or top-level directory updates this section in the same session.**

## 5. Session log convention

`docs/sessions/YYYY-MM-DD-<short-topic>.md`, one file per session.
Each entry covers: what was done, decisions made and why, problems hit and
how they were solved, what's left. `docs/sessions/README.md` indexes them
newest-first.

Rule: the last thing before ending any work session is writing this entry.
It becomes the first thing the next session — a new Claude Code session,
most likely, given context gets compacted or dropped between sessions —
reads to pick up context, cheaper than re-reading the whole codebase or
reconstructing decisions from git history.

## Out of scope for this design

- Actually performing the `mssql-django` spike or AWS provisioning — these
  are implementation, covered by the plan that follows this design.
- Reopening the Django-templates-over-React decision — not on the table.
- Team collaboration model — dropped; revisit only if a second contributor
  actually joins.

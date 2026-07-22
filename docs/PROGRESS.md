# FluxTrack — Current Status

**Last updated:** 2026-07-22

**Specification:** [`FluxTrack_SRS.md`](../FluxTrack_SRS.md) v1.3

**Repository state:** feature and documentation implementation complete; external
production cutover pending credentials.

This page is the short status entry point. The roadmap and per-phase evidence under
[`.planning/`](../.planning/) remain the detailed implementation record.

## Outcome at a glance

| Area | Status | Evidence |
|---|---|---|
| Attendance and verification | Complete | Faculty QR/manual/Online flows, Checker physical/Online verification, offline replay |
| IFO operations | Complete | Imports, individual schedules, campus structure, rooms/codes, bookings, assignments, breaks, suspensions, terms |
| Oversight and reporting | Complete | IFO/Dean/HR reports, scorecards, lateness, coverage, utilization, exports |
| Guard and notifications | Complete | Floor monitor, room schedules, locator, in-app/web push, mute controls |
| Operational trust | Complete | Excused days, corrections, room service state, term lifecycle, concurrency guards |
| Production package | Complete in repository | HTTPS settings, shared cache, Nginx/Gunicorn/systemd, watchdog, health, retention, backup/rollback runbook |
| Live Entra/AWS cutover | Pending external access | Institutional callback/UAT, AWS/RDS/DNS/TLS provisioning, restore drill, smoke test |
| SRS/documentation | Complete | SRS v1.3, restored traceability, current project/architecture/status docs |

## Verification baseline

- Full Microsoft SQL Server suite: **1,259 tests passed**, **2 expected skips**.
- `manage.py migrate --check`: no unapplied model changes at the Phase 15 baseline.
- Production `manage.py check --deploy`: no issues with a complete production-like
  environment.
- `collectstatic`: 180 assets copied and 516 post-processed, including vendored
  htmx 2.0.6, Franken UI 2.1.2, and html5-qrcode 2.3.8.
- SRS `.docx` is generated from the Markdown source by
  `manage.py regenerate_srs_docx`; it is not edited independently.

## Milestone progress

All feature phases through Phase 14 are complete. Phase 15's five repository
workstreams are complete; its status remains open only because live cutover cannot
be performed without institutional Entra and AWS access. Phase 16 reconciles the
documentation with the implementation.

| Phase group | Result |
|---|---|
| 1–4.2: foundation, correctness, verification, auth proof, modality, real-data/merge | Complete |
| 5–7: notifications, reporting, operational role surfaces | Complete |
| 9: attendance trust under real operations | Complete |
| 10: campus structure management | Complete |
| 11: mission metrics | Complete |
| 12: term lifecycle | Complete |
| 13: UX finish | Complete |
| 14: correctness and concurrency hardening | Complete |
| 15: deploy hardening and cutover | Repository complete; external cutover pending |
| 16: documentation pass | Complete |

## Remaining production checklist

1. Register the exact HTTPS callback in the institutional Entra application and
   run provisioned/unprovisioned/deactivated-user UAT.
2. Provision the documented EC2, private-subnet RDS, security groups, DNS, and TLS
   certificate; install the reviewed commit and production environment.
3. Restore an RDS snapshot and media copy into the target topology, then record the
   recovery time and findings.
4. Run the deployment smoke checks: `/healthz/`, Entra login, one role-scoped page
   per role, one authorized report and profile photo, scheduler heartbeat, and
   audit history.
5. Validate the policy register and report format against the official MMCM IRR
   before real institutional attendance records are treated as authoritative.

## Start and verify locally

Follow the [README](../README.md) for SQL Server setup, then run:

```powershell
py -3.12 manage.py migrate
py -3.12 manage.py seed_demo
py -3.12 manage.py runserver 8000
```

In a second terminal, start the single scheduler process:

```powershell
py -3.12 manage.py runscheduler
```

Run the full suite with:

```powershell
py -3.12 manage.py test
```

For production deployment, rollback, monitoring, and recovery, follow the
[`deploy/README.md`](../deploy/README.md) runbook.

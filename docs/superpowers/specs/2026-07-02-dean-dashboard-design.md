# FluxTrack: Dean Dashboard + Weekly Report Notification

**Date:** 2026-07-02
**Status:** Approved, pending implementation plan

## Context

The SRS currently gives IFO Admin a dashboard (IFO-09: summary cards +
faculty-scorecard drill-down) but gives Dean no equivalent landing view —
DEAN-02/DEAN-03 only specify reporting screens the Dean has to navigate to.
This adds a Dean-facing dashboard, department-scoped, and surfaces the
weekly consolidated report on it directly rather than requiring the Dean
to go find it. Neither IFO-09 nor DEAN-02/03 nor RPT-01–05 have any
existing code (`docs/USE_CASES.md` marks all of Reporting and Dean as not
started), so this is a specification addition, not a migration of working
behavior.

## 1. Dean Dashboard scene

New scene, mirroring IFO-09's shape but scoped to the Dean's department(s)
(`User.department`, per DEAN-01's existing scoping rule):

- Summary cards: Faculty count, Sessions (scheduled vs. held), Absences,
  Attendance %.
- A "Latest weekly report" card: the most recent `WeeklyReport` for the
  Dean's department, with view/export links (DEAN-03).

The summary cards reuse the same aggregate functions IFO-09 and RPT-04
need — built once, filtered by department for Dean and unfiltered (or
all-department) for IFO. This was already the intended reuse per
`docs/USE_CASES.md`'s UC-DEAN-2; this design just gives it a concrete home
(a dashboard scene) instead of leaving it implicit.

## 2. RPT-02 amendment: notify Deans too

RPT-02 currently only notifies IFO when the weekly report auto-generates.
This extends it: on generation, each Dean whose department has a report
in that batch gets a `Notification` row for it — same pattern as the
existing IFO notification (and the `_notify_ifo`-style pattern already
used for FAC-10's wrong-room case in `web/scan.py`), one row per relevant
Dean, scoped to their department's report only.

## SRS revision

Adds to the same v1.2 revision already flagged in
`docs/superpowers/specs/2026-07-02-modality-shift-approval-design.md`
(no separate revision needed — both land together):

- New `DEAN-04`: Dean Dashboard.
- `RPT-02` amended: notification target becomes "IFO and the relevant
  Dean(s)," not IFO alone.

## Out of scope

- Building IFO-09/RPT-01–05/DEAN-02/03 themselves — this only adds the
  dashboard scene and the notification amendment on top of specs that
  already exist for those.

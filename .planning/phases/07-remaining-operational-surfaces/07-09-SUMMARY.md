---
phase: 07-remaining-operational-surfaces
plan: 09
subsystem: faculty-online-start
tags: [FAC-08, online, teams-link, self-start, checkin-method]
status: complete
requires:
  - scheduling.models.CheckinMethod
  - scheduling.resolver.is_no_show_past_grace (read-only)
  - web.checker.online_open (read-side counterpart)
provides:
  - CheckinMethod.ONLINE_SELF
  - web.faculty.online_list / web.faculty.online_start
  - url names faculty_online, faculty_online_start
  - AuditLog event session.teams_link_set
affects:
  - web/faculty.py
  - web/urls.py
  - templates/base.html (faculty tab bar)
  - templates/faculty/_outcome.html (online-reject branch)
tech-stack:
  added: []
  patterns:
    - hand-validated write ladder + 400 partial re-render (PATTERNS 2.3)
    - server-computed display-state dict, colour never the only signal (PATTERNS 3.2)
    - AuditLog on every domain state change (PATTERNS 2.4)
key-files:
  created:
    - scheduling/migrations/0005_alter_session_checkin_method.py
    - templates/faculty/online.html
    - templates/faculty/_online_start.html
    - web/tests_faculty_online.py
  modified:
    - scheduling/models.py
    - web/faculty.py
    - web/urls.py
    - templates/base.html
    - templates/faculty/_outcome.html
decisions:
  - D-01/D-02/D-03 honored: starting and verifying stay two separate acts
  - ONLINE_SELF is a new CheckinMethod value, deliberately not ONLINE_MANUAL
  - the shared grace predicate is reused rather than a second online-only rule
metrics:
  duration: ~35m
  completed: 2026-07-19
---

# Phase 07 Plan 09: Faculty Online "Verify & Start" Summary

Faculty start their own Online class by pasting the Teams link; the Checker
verifies independently against that same field, and the two acts stay separable
in the data.

## What was built

`CheckinMethod.ONLINE_SELF` ("online_self") joins the enum as a value distinct
from `ONLINE_MANUAL`, which means "a Checker activated this session" (03-05).
Migration `scheduling/0005` is metadata-only — `sqlmigrate` emits `-- (no-op)`,
exactly matching the `0004` precedent that added `CheckinMethod.MERGED`.

`web.faculty.online_list` (GET) shows the requesting faculty member's
effective-online sessions for today, scoped server-side to `faculty=request.user`
and today's date, `select_related` on schedule and room. Each card gets a
server-computed state token (`upcoming` / `startable` / `active` / `past-grace` /
`absent` / `completed`) resolved through `_ONLINE_STYLES`, mirroring
`web/checker.py` `_CARD_STYLES`: every state carries a Lucide icon and a text
label alongside its colour, and the template never branches on colour.

`web.faculty.online_start` (POST) runs the whole validation ladder before any
write: ownership re-gated on the re-fetched row (a forged pk is a 404, so the
surface does not even confirm another faculty's session exists), effective
modality re-derived server-side, status must be SCHEDULED, the start must be
inside grace, and only then the link. On success it writes exactly four columns
inside `transaction.atomic()` — `teams_link`, `status`, `actual_start`,
`checkin_method` — with `update_fields` naming them, and audits
`session.teams_link_set` with the previous link in the payload.

## Decisions and how they were honored

**D-03 (one field, both roles).** The pasted link is written to
`Session.teams_link`, the exact field `web/checker.py` `online_open` reads. The
test `test_checker_sees_the_link_the_faculty_pasted` drives this end to end: it
self-starts as faculty, then requests `/checker/online/<pk>` as the assigned
online checker and asserts both that the link renders and that
`data-outcome="no-link"` is absent. `_online_session` has no status filter, so
the now-ACTIVE session opens for the Checker without any change to checker code.

**D-02 (starting is not verifying).** `verified_by_checker` is never written —
it is a derived property over `CheckerValidation` rows — and no
`CheckerValidation` is created. `online_checker` is untouched; online duty stays
IFO's to assign. Two tests assert the property stays false and the validation
count stays zero after a start.

**D-02 (no sweep change).** `sweep_no_shows` only moves SCHEDULED rows to ABSENT,
so a self-started ACTIVE session is skipped for free.
`OnlineSweepInteractionTests` proves this with a control: the self-started
session survives a sweep run 60 minutes past its grace window, while an
unstarted online session in the same shape is still swept to ABSENT — so the
skip is the ACTIVE status doing the work, not the sweep having stopped looking
at online sessions.

**Link validation (T-07-48).** `urllib.parse`, `https` required, and the HOST
matched against a Teams allow-list with an exact-or-dot-boundary test
(`host == d or host.endswith("." + d)`). Four refusal tests cover a non-Teams
URL, an http Teams URL, `https://example.com/teams.microsoft.com/meet` (which a
substring search would accept), and a lookalike host.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 3 — Blocking] The worktree had no `.env`, so nothing could connect to the DB.**
- **Found during:** Task 1, first `makemigrations` run.
- **Issue:** `.env` is gitignored, so `git worktree add` did not carry it over.
  Django fell back to `127.0.0.1,1433` and every DB command failed with ODBC
  08001.
- **Fix:** Copied the main tree's `.env` into the worktree. It is gitignored
  there too, so it is not committed and cannot leak into the merge.
- **Files modified:** none tracked.

**2. [Rule 2 — Missing critical functionality] The refusal path rendered an empty card for a non-Online session.**
- **Found during:** Task 2, self-review before running tests.
- **Issue:** The 400 re-render originally rebuilt the row through `_online_rows`,
  which filters to effective-online sessions. A refused Blended session is not in
  that list, so the refusal message would have swapped an empty box into the
  page — the user would see the Start silently do nothing.
- **Fix:** The refusal path now builds the row directly from the re-fetched
  session via `_online_row`, so the refusal is always shown. Covered by
  `test_blended_and_f2f_refused_and_point_at_qr`, which asserts the response body
  actually mentions QR.
- **Commit:** e372c2c.

### Touched outside `files_modified`

- **`templates/base.html`** — the plan asked for an Online entry in the faculty
  navigation, and that navigation lives in `base.html`. Added `faculty_online` to
  the headerless-shell URL-name list and to the faculty tab bar (a fourth tab,
  `monitor` icon). No existing line was reordered or reformatted.
- **`templates/faculty/_outcome.html`** — the plan explicitly asked for this: the
  scan surface's `online-reject` branch already told the user to use Verify &
  Start, and it is now a working link to `faculty_online`. It is listed in the
  plan's action text but not in the frontmatter `files_modified`.

### Plan assumptions that turned out wrong

- The plan's `<verification>` step 9 anticipated a possible `static/` change. No
  CSS was needed — every class used (`.ft-card--*`, `.ft-pill--*`, `.ft-form`,
  `.ft-field`, `.ft-control`, `.ft-outcome*`, `.ft-btn-navy`) already exists in
  `static/faculty/faculty.css`. **`collectstatic` was therefore not run and is
  not needed for this plan.**
- The plan named five display states; six were needed. `past-grace` is a real
  distinct state — SCHEDULED, the sweep has not run yet, but a start is already
  refused — and collapsing it into `upcoming` would have offered a Start button
  that the POST would then refuse. Display and the write ladder now read the same
  tokens (`_STARTABLE_STATES`).

### Discretion calls recorded for the operator

- **Grace reuse.** Refusing an online start past the F2F/Blended grace window is
  a consistency choice, not a requirement handed down. It is implemented by
  *calling* `is_no_show_past_grace`, never copying it, so if the operator later
  wants a different online grace it becomes a policy question rather than a
  second rule to keep in sync. `test_past_grace_refused_and_matches_the_shared_predicate`
  asserts the view's behaviour against the predicate itself rather than a
  hard-coded number.
- **Merged siblings are not propagated.** `scheduling.merge.propagate_merged_present`
  fills co-scheduled siblings on a room check-in. A self-start does not do this,
  because the plan scoped the write to `update_fields` on one session and put
  `web/scan.py` out of bounds. A faculty member teaching two merged online
  sections must start each one. Flagging it rather than fixing it silently.

## TDD Gate Compliance

Task 3 was marked `tdd="true"`, but the plan orders it *after* Task 2 builds the
implementation, so a genuine RED phase was not reachable as written. Tests were
authored after the implementation and committed separately (`test(07-09)`,
6fa9884). One test did fail on first run and was fixed — but that was a defect in
the test's own string assertion, not a RED gate. Recording the gap rather than
claiming a cycle that did not happen.

## Verification

| Check | Result |
|---|---|
| `makemigrations --check --dry-run` | No changes detected |
| `sqlmigrate scheduling 0005` | `-- (no-op)` — metadata only |
| `manage.py check` | 0 issues |
| `test scheduling.tests` | Ran 83, OK |
| `test web.tests_faculty_online` | Ran 25, OK |
| Full suite | **Ran 604 — FAILED (failures=3, skipped=26), 0 errors** |

The 3 failures are the known pre-existing `DevLoginCoexistTests`,
`DevLoginCuratedDemoTests` and `HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

**On the skip count.** The briefed baseline was `skipped=2`; this worktree runs
`skipped=26`. The 24 extra skips are all `registrar .xlsx not present (gitignored
data/raw)` and `live full-term load not present`. `data/raw/` is gitignored and
therefore absent from the worktree, exactly like `.env`. Verified by listing the
directory in both trees. Environmental, unrelated to this plan, and skips rather
than failures. Test delta is exactly +25, which is precisely this plan's new
tests.

Manual browser verification (steps 3-8 of the plan's verification block) was NOT
performed — the concurrent IFO agent holds the dev server, and starting a second
one against the same DB was judged not worth the interference. Recommended before
the phase closes.

## Commits

| Task | Commit | Description |
|---|---|---|
| 1 | b155351 | `CheckinMethod.ONLINE_SELF` + metadata-only migration 0005 |
| 2 | e372c2c | Online surface, start action, URLs, templates, nav |
| 3 | 6fa9884 | `web/tests_faculty_online.py` — 25 tests |

## Self-Check: PASSED

All created files confirmed present on disk; all three commit hashes confirmed
in `git log`.

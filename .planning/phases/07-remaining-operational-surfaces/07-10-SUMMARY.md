---
phase: 07-remaining-operational-surfaces
plan: 10
subsystem: faculty-attendance-history
tags: [FAC-11, read-only, checker-flags, pagination, shared-helper]
status: complete
requires:
  - web.reporting_common (shared pure helpers)
  - web.pagination.paginate
  - verification.models.CheckerValidation / ValidationAction
provides:
  - web.reporting_common.status_label (lifted from web/hr.py)
  - web.faculty.history
  - url name faculty_history
affects:
  - web/hr.py (import only, no behaviour change)
  - templates/base.html (faculty tab bar)
tech-stack:
  added: []
  patterns:
    - Exists() annotations instead of the per-object verified_by_checker property
    - list()-materialize before a follow-up query (MSSQL MARS-off HY010 guard)
    - FK-id and date__range filters only, never pk__in (2100-parameter trap)
key-files:
  created:
    - templates/faculty/history.html
    - web/tests_faculty_history.py
  modified:
    - web/reporting_common.py
    - web/hr.py
    - web/faculty.py
    - web/urls.py
    - templates/base.html
decisions:
  - D-15 honored: read-only, flags visible, no dispute affordance of any kind
  - status_label has exactly one implementation, shared with HR
  - VERIFIED_EMPTY is not counted as a flag against the faculty member
metrics:
  duration: ~25m
  completed: 2026-07-19
---

# Phase 07 Plan 10: Faculty Attendance History Summary

A faculty member reads their own session-level attendance — paginated, filterable,
Checker flags visible with their reason — and there is no way to argue with a flag
from inside the app.

## What was built

**`status_label` moved to `web/reporting_common.py`.** HR's private
`_status_label` becomes public in the module that already exists for pure,
role-agnostic logic. The mapping and its docstring are unchanged: ACTIVE and
COMPLETED are the two held states mapping to Present, ABSENT maps to Absent, and
everything else maps to Scheduled because a future session is not yet a payroll
fact. `web/hr.py` calls it at the same two points; only the import moved, and
`SessionStatus` dropped out of HR's imports because nothing else there used it.

**`web.faculty.history`.** GET-only behind `faculty_required`, modelled on
`web/hr.py` `attendance` with the one structural difference that is the whole
point: the queryset filters `faculty=request.user` and the surface accepts no
faculty parameter at all — not a defaulted one, not an ignored one.

Verification and flags come from two `Exists()` annotations resolved in the main
query, never from `Session.verified_by_checker`, which issues a subquery per
object. Flag reasons for the page's flagged rows are fetched in ONE additional
query, issued only after `list()`-materializing the page — MSSQL runs with MARS
off, so a follow-up query while an outer cursor is open raises HY010. The id list
is bounded by the page size (25), so it cannot approach the 2100-parameter
ceiling.

**`templates/faculty/history.html`.** Navy `.ft-*` shell matching
`faculty/schedule.html`, `.tbl` inside `.table-wrap`, `{% include "_pager.html" %}`.
Status and Checker columns render `.ft-pill--*` chips each carrying an icon and a
text label, so colour is never the only signal.

## Decisions and how they were honored

**D-15 (read-only, no dispute control).** There is no contest, dispute, appeal or
"request review" control anywhere on the page. The flag renders as a `<span>`
chip with no href and no button inside it. The only `<form>` on the page is the
GET filter bar. The page's closing note says flags are permanent records shared
with IFO and HR and that a mistaken one should be raised with HR directly —
naming the out-of-band path rather than pretending there is an in-app one.

`test_page_offers_no_actionable_control_against_a_flag` asserts this
behaviourally: no `method="post"` anywhere, no `hx-post` anywhere, every `<form>`
tag is `method="get"`, and the flag chip's inner HTML contains no `<a>` and no
`<button>`. Keyed to actionability rather than to particular words, so it stays
meaningful if the copy changes.

**One shared vocabulary.** `test_labels_agree_with_hr_for_the_same_session`
renders the same three sessions (COMPLETED / ABSENT / SCHEDULED) through both
this page and `/hr/attendance` and asserts the label appears on both, comparing
against `status_label` itself rather than hard-coding "Present" in two test
files.

**`VERIFIED_EMPTY` is not a flag.** The flag annotation covers only
`FLAG_IDENTITY_MISMATCH` and `FLAG_NOT_PRESENT`. "The Checker found the room
empty" is not the claim "this faculty member was not present", and counting it
would put a mark on a record that nobody actually made. Covered by
`test_verified_empty_is_not_a_flag_against_the_faculty`.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 1 — Bug] `.ft-muted` does not exist.**
- **Found during:** Task 2, class audit against `static/faculty/faculty.css`.
- **Issue:** The empty-actual-start cell used `class="ft-muted"`, which is not a
  class this design system defines. It would have rendered unstyled.
- **Fix:** Replaced with a plain dash carrying `aria-label="No actual start
  recorded"`, so the empty cell is announced rather than silently blank.
- **Commit:** 57d535b.

Every other class used was verified present in `static/faculty/faculty.css` or
`static/css/app.css` before writing the template.

### Touched outside `files_modified`

- **`templates/base.html`** — the plan asked to "link it from the faculty
  navigation", which lives in `base.html`. Added `faculty_history` to the
  headerless-shell URL-name list and a fifth tab (`clipboard-list` icon). No
  existing line reordered or reformatted.

### Plan assumptions that turned out wrong

- The plan listed `web/hr.py` under `files_modified` expecting only an import
  change. That held, but `SessionStatus` also became an unused import there once
  the label function left, so its import line changed too. Behaviour is
  unaffected and `web.tests_hr` is green (14 tests).
- **No `static/` file was added or edited, so `collectstatic` was NOT run and is
  not needed** for this plan (the plan's verification step 8 was conditional on a
  static change).

## Verification

| Check | Result |
|---|---|
| `manage.py check` | 0 issues |
| `test web.tests_hr` (after the lift) | Ran 14, OK |
| `test web.tests_faculty_history` | Ran 14, OK |
| Full suite | **Ran 618 — FAILED (failures=3, skipped=26), 0 errors** |

The 3 failures are the known pre-existing `DevLoginCoexistTests`,
`DevLoginCuratedDemoTests` and
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`. The 26 skips are
the 2 baseline skips plus 24 that require the gitignored `data/raw/*.xlsx`, which
is absent from this worktree exactly like `.env` — environmental, explained in
full in the 07-09 summary.

Test delta across both plans is +39 (579 -> 618), matching exactly the 25 tests
added by 07-09 and the 14 added here.

Manual browser verification (steps 2-7 of the plan's verification block) was NOT
performed — the concurrent IFO agent holds the dev server. Recommended before the
phase closes, particularly step 7 (comparing rows against the HR attendance page),
though the label-agreement test covers the same property automatically.

## Commits

| Task | Commit | Description |
|---|---|---|
| 1 | 9547eda | `status_label` lifted into `web/reporting_common.py` |
| 2 | 57d535b | `history` view, URL, template, nav |
| 3 | d19feb6 | `web/tests_faculty_history.py` — 14 tests |

## Self-Check: PASSED

All created files confirmed present on disk; all three commit hashes confirmed
in `git log`.

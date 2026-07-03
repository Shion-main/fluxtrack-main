---
phase: 04-modality-shift-approval-srs-v1-2
plan: 02
subsystem: docs
tags: [srs, pandoc, pypandoc, django-management-command, documentation]

# Dependency graph
requires:
  - phase: 04-01
    provides: ModalityShiftRequest model + migration (the code the SRS MOD area documents)
provides:
  - FluxTrack_SRS.md revised to v1.2 (MOD area MOD-01..06, DEAN-04, FAC-07 superseded, CHK-03 amended, CHK-06 removed, RPT-02 notifies Deans, modality_shift_lead_days policy row)
  - regenerate_srs_docx management command (repeatable .md -> .docx via bundled pandoc)
  - FluxTrack_SRS.docx regenerated at v1.2
  - pypandoc_binary==1.17 pinned in requirements.txt
  - SrsV12DocTests marker + regeneration smoke test
affects: [04-05, 04-07, doc-01, mod-06, dean-04]

# Tech tracking
tech-stack:
  added: [pypandoc_binary==1.17 (bundled pandoc 3.9 engine)]
  patterns: ["generated-artifact: .docx is produced only from the .md via a management command, never hand-edited"]

key-files:
  created:
    - scheduling/management/commands/regenerate_srs_docx.py
    - scheduling/tests_srs.py
  modified:
    - FluxTrack_SRS.md
    - FluxTrack_SRS.docx
    - requirements.txt

key-decisions:
  - "SRS MOD area inserted as new Section 4.4; subsequent subsections renumbered 4.5..4.13 and the two inline cross-refs (SCAN-03 -> 4.5, IFO-10 -> 4.10) updated, rather than using a non-sequential number."
  - "FluxTrack_SRS.docx is a generated artifact regenerated only by manage.py regenerate_srs_docx from the .md (bundled pypandoc_binary, no system pandoc / no PATH); pandoc output is not byte-deterministic."
  - "MOD-06 documentation half shipped here (FAC-07 superseded, CHK-06 removed in the SRS); the code half lands in 04-05/04-07, so MOD-06 stays open in REQUIREMENTS.md while DOC-01 is closed."

patterns-established:
  - "Doc-as-code: edit the Markdown SRS, regenerate the DOCX via a repeatable Django command so the two never drift (D-14)."

requirements-completed: [DOC-01]

coverage:
  - id: D1
    description: "FluxTrack_SRS.md revised to v1.2 (MOD-01..06 area, DEAN-04 row, FAC-07 superseded, CHK-03 amended, CHK-06 removed, RPT-02 notifies Deans, modality_shift_lead_days policy row)"
    requirement: "DOC-01"
    verification:
      - kind: unit
        ref: "scheduling/tests_srs.py#SrsV12DocTests.test_md_has_v12_markers"
        status: pass
    human_judgment: false
  - id: D2
    description: "regenerate_srs_docx command deterministically rebuilds a non-empty FluxTrack_SRS.docx from the .md via bundled pandoc"
    requirement: "DOC-01"
    verification:
      - kind: unit
        ref: "scheduling/tests_srs.py#SrsV12DocTests.test_regenerate_srs_docx_writes_nonempty"
        status: pass
      - kind: other
        ref: "py -3.12 manage.py regenerate_srs_docx (exit 0, 29265-byte docx)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Rendered FluxTrack_SRS.docx renders the MOD area, DEAN-04, policy row, and removed CHK-06 correctly (tables/headings intact)"
    requirement: "DOC-01"
    verification: []
    human_judgment: true
    rationale: "Visual fidelity of the generated DOCX (table/heading rendering) is a per-04-VALIDATION Manual-Only check; automation confirms non-empty output but not visual layout."

# Metrics
duration: ~6m
completed: 2026-07-03
status: complete
---

# Phase 4 Plan 02: SRS v1.2 Regeneration (DOC-01) Summary

**FluxTrack_SRS revised to v1.2 in Markdown (new MOD-01..06 area, DEAN-04, FAC-07 superseded, CHK-06 removed, policy row) with a repeatable regenerate_srs_docx command rebuilding the DOCX via the bundled pypandoc_binary pandoc engine.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-03T15:26:41Z
- **Completed:** 2026-07-03T15:32:07Z
- **Tasks:** 4 (Task 0 checkpoint pre-cleared by human)
- **Files modified:** 5

## Accomplishments
- Installed and pinned `pypandoc_binary==1.17` (bundled pandoc 3.9, no system pandoc / no PATH) under the Media / reports section of requirements.txt.
- Revised FluxTrack_SRS.md to v1.2 with all seven anchored edits plus DEAN-04: MOD area (MOD-01..06) as new Section 4.4, subsections renumbered 4.5..4.13, DEAN-04 dashboard row, FAC-07 marked superseded, CHK-03 amended (Confirm absent dropped; applies to online), CHK-06 requirement row removed, RPT-02 notifies IFO + Deans, and modality_shift_lead_days=2 added to the Section 8 policy register.
- Added the `regenerate_srs_docx` management command (paths from settings.BASE_DIR, missing-.md guard writes ERROR without raising) and regenerated FluxTrack_SRS.docx from the v1.2 markdown.
- Added SrsV12DocTests (scheduling/tests_srs.py): a marker test and a regeneration test, both green.

## Task Commits

Each task was committed atomically:

1. **Task 1: Install and pin pypandoc_binary** - `8f55bad` (chore)
2. **Task 2: Apply the SRS v1.2 edit map to FluxTrack_SRS.md** - `31adef6` (docs)
3. **Task 3: Add regenerate_srs_docx command and regenerate DOCX** - `16e4939` (feat)
4. **Task 4: SRS v1.2 marker smoke test (TDD)** - `ec1e730` (test)

_Note: Task 0 was a blocking package-legitimacy human-verify checkpoint for pypandoc_binary==1.17; the human approved it ("approved") before this run, so install proceeded without re-prompting._

## Files Created/Modified
- `requirements.txt` - Pinned `pypandoc_binary==1.17` under Media / reports.
- `FluxTrack_SRS.md` - Revised to v1.2 (MOD area, DEAN-04, FAC-07 superseded, CHK-03 amended, CHK-06 removed, RPT-02 Deans, policy row, renumbered §4.4..4.13, Revision History + Document Control version 1.2).
- `FluxTrack_SRS.docx` - Regenerated v1.2 binary from the .md (generated artifact, 29 KB).
- `scheduling/management/commands/regenerate_srs_docx.py` - BaseCommand converting the .md to .docx via pypandoc; ASCII-only output; missing-source guard.
- `scheduling/tests_srs.py` - SrsV12DocTests marker + regeneration smoke test.

## Decisions Made
- **Insert-and-renumber over non-sequential numbering:** the MOD area was inserted as Section 4.4 and the following subsections renumbered 4.5..4.13, with the only two inline cross-references (SCAN-03's "Section 4.4" and IFO-10's "Section 4.9") updated to 4.5 and 4.10. This keeps the SRS numbering sequential and professional; grep verified no stale references remain.
- **Package checkpoint:** the pypandoc_binary==1.17 legitimacy checkpoint (Task 0) was human-approved before this run; recorded here per protocol.
- **DOCX is generated-only:** never hand-edited; produced solely by `manage.py regenerate_srs_docx`. pandoc output is not byte-deterministic (re-running the command produces a byte-different but semantically identical docx).

## Deviations from Plan

### Scope adjustment (not an auto-fix)

**1. MOD-06 not marked complete in REQUIREMENTS.md (only DOC-01 marked)**
- **Found during:** State updates (requirements mark-complete step)
- **Issue:** The plan frontmatter lists `requirements: [DOC-01, MOD-06]`, but the plan's own `must_haves.key_links` states the SRS FAC-07 amendment + CHK-06 removal is only the **documentation half** of MOD-06; the code half (declared_modality as approval override) ships in 04-05/04-07.
- **Fix:** Marked only DOC-01 complete. MOD-06 stays open (Pending) in REQUIREMENTS.md so traceability is not falsely closed before its code half lands. Documented as a decision in STATE.md.
- **Files modified:** .planning/REQUIREMENTS.md (DOC-01 only), .planning/STATE.md
- **Verification:** DOC-01 shows `[x]` and "Complete" in the traceability table; MOD-06 remains Pending.

---

**Total deviations:** 1 (scope/traceability correction; no code auto-fixes)
**Impact on plan:** All four tasks executed exactly as written. The only adjustment prevents over-reporting MOD-06 as done. No scope creep.

## Issues Encountered
- `state.record-metric` and `state.add-decision` required named flags (`--phase/--plan/--duration/--tasks/--files` and `--summary`) rather than positional args; re-invoked with flags. A stray "TESTPROBE" decision line created while discovering the flag was removed from STATE.md.

## TDD Gate Compliance
Task 4 is `tdd="true"`, but the plan sequences the implementation (Tasks 2 and 3: the .md edits and the regenerate command) **before** the test. The smoke test therefore passed on first run against already-shipped implementation — expected here, not a fail-fast RED violation, because the implementation legitimately exists by design of the plan's task order. Both assertions (markers present / CHK-06 row absent; docx regenerates non-empty) are green. The MVP+TDD runtime gate was not active for this run (orchestrator did not pass MVP_MODE/TDD_MODE), and this is a docs/command plan with no behavior-adding source under test.

## User Setup Required
None - the one dependency (pypandoc_binary==1.17) is pinned in requirements.txt and installs via `pip install -r requirements.txt`; the bundled pandoc engine needs no system install or PATH entry.

## Next Phase Readiness
- DOC-01 is closed: the SRS reads v1.2 in both `.md` and `.docx`, and the `.docx` is reproducible from the `.md` via one command.
- MOD-06's documentation half is in the spec; its code half (declared_modality as the approval override, FAC-07 entry-point retirement) is owned by 04-05/04-07.
- Manual verification recommended (per 04-VALIDATION Manual-Only): open the regenerated FluxTrack_SRS.docx and confirm the MOD area, DEAN-04, policy row, and removed CHK-06 render with tables/headings intact.

## Self-Check: PASSED
- FOUND: scheduling/management/commands/regenerate_srs_docx.py
- FOUND: scheduling/tests_srs.py
- FOUND: FluxTrack_SRS.md (v1.2 markers present, `| CHK-06 |` row absent)
- FOUND: FluxTrack_SRS.docx (29265 bytes, non-empty)
- FOUND commit 8f55bad (Task 1), 31adef6 (Task 2), 16e4939 (Task 3), ec1e730 (Task 4)

---
*Phase: 04-modality-shift-approval-srs-v1-2*
*Completed: 2026-07-03*

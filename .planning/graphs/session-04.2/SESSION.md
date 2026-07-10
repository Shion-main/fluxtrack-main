---
source: gsd-execute-phase 04.2 session
captured_at: 2026-07-07
author: Claude (Opus 4.8 orchestrator)
contributor: Joshua Sabuero (project owner)
---

# Session: Execute Phase 04.2 — Co-Scheduled Session Attendance

This document records the `/gsd-execute-phase 04.2` run of FluxTrack: what was built,
the design decisions, the verification gap that surfaced, the owner's decision, and the
inline gap-closure fix. It is the ingest source for the session knowledge graph.

## The Problem (Phase Goal)

FluxTrack is a Django attendance system for MMCM. **Co-scheduled sessions** occur when one
instructor teaches 2+ sections at the same instant in different rooms (or online). Without
handling, a single check-in marks one section present and the **JOB-02 no-show sweep**
falsely marks the sibling section **Absent**. Phase 04.2 makes a single scan or verification
cover the whole co-scheduled group so the sweep never falsely marks siblings Absent.

## The Orchestration Process

The `execute-phase` workflow ran the phase in **two waves** using the **GSD wave model**.
Because `workflow.use_worktrees` was `false`, all plans executed **sequentially on the main
git tree** rather than in parallel worktrees. The **orchestrator** (Claude) discovered plans,
grouped them into waves, and dispatched a **gsd-executor** subagent per plan; after all plans
it dispatched a **gsd-verifier** subagent. Model policy: executors ran on **Opus**, the
verifier on **Sonnet**.

- **Wave 1** built the foundation: Plan 04.2-01.
- **Wave 2** built three seams that depend on Wave 1: Plans 04.2-02, 04.2-03, 04.2-04.

Each plan produced a **SUMMARY.md** and atomic commits. A **post-merge test gate** ran the
Django test suite after each wave. The tests use `manage.py test` (not pytest) against
**MSSQL LocalDB**, invoked with a specific Python 3.12 interpreter (bare `python` lacks Django).

## Plan 04.2-01 — Merge Core (Wave 1, foundation)

Built the shared merge core that every Wave-2 seam imports. Artifacts in `scheduling/merge.py`:

- **merged_sibling_ids** — the PURE **D-01 detector**. Takes Session-like objects, returns the
  set of sibling ids that merge with an anchor. No ORM, no `timezone.now()` (pure, coupling-tested,
  mirrors `scheduling.resolver.is_no_show_past_grace`).
- **propagate_merged_present** — atomic ORM helper: flips only SCHEDULED siblings to ACTIVE with
  shared `actual_start` and `checkin_method=MERGED`, writing one `session.merged_present` AuditLog
  per filled row. Faculty-scoped, status-guarded, MSSQL HY010-safe (materialize-before-mutate).
- **propagate_merged_absent** — the online counterpart: flips SCHEDULED siblings to ABSENT with a
  `session.merged_absent` AuditLog.
- **CheckinMethod.MERGED** — new enum choice in `scheduling/models.py`, added via a metadata-only
  migration `0004_alter_session_checkin_method` (no DDL on MSSQL).
- **make_merge_fixture** — the GARAY test fixture in `scheduling/test_support.py`.

propagate_merged_present and propagate_merged_absent both **call merged_sibling_ids** (impure seam
calls the pure detector). Result: 15 tests green.

## Plan 04.2-02 — Faculty Scan Seam (Wave 2)

Wired `web/scan.py` `_apply`: the CHECKED_IN and force-handover ROOM_OCCUPIED branches now call
**propagate_merged_present** inside the same `transaction.atomic()` as the anchor save. One faculty
scan flips the whole GARAY merged group present; the scanned anchor keeps its REAL checkin_method
(never MERGED); non-merged sessions are untouched; re-scans are idempotent. This delivers ROADMAP
**criterion #1** (single event marks the group present). 6 tests green.

## Plan 04.2-03 — Checker Online Seam (Wave 2)

Wired `web/checker.py` `_apply_action`: an online VERIFIED action calls **propagate_merged_present**;
an online FLAG_NOT_PRESENT calls **propagate_merged_absent** (both in `transaction.atomic()`). The
**F2F Checker flag stays record-only** (unchanged) — the sweep handles the F2F none-held case.
Merge-filled siblings get **no CheckerValidation** row, so CHK-04 coverage is not inflated. This
delivers ROADMAP **criterion #3** (online analog) mechanism. 6 tests green.

## Plan 04.2-04 — Sweep-Unchanged Proof + Audit Command (Wave 2)

Proved the **JOB-02 sweep** (`scheduling/jobs.py`) needs NO change: it already skips ACTIVE merged
siblings (criterion #2) and absents a no-event SCHEDULED group together via shared scheduled_start
(decision **D-08**), while still absenting genuine non-merged misses (criterion #4). `scheduling/jobs.py`
is byte-unchanged. Also shipped **audit_merge_coverage** — a read-only management command that classifies
every online same-start group in the active term as CAUGHT or MISSED by D-01. 6 tests green.

## Design Decisions

- **D-01** — merge detection key: same faculty + exact scheduled_start + (same room OR same course_code).
  Detection is dynamic from existing fields; no merge-group model.
- **D-04** — anchor write and sibling fill occur in one transaction.
- **D-05** — status guard: only SCHEDULED siblings flip; ACTIVE/ABSENT/COMPLETED are left untouched.
- **D-07** — not-present is per-modality: F2F flag record-only, online flag propagates ABSENT immediately.
- **D-08** — a no-event merged group shares one scheduled_start and crosses grace together in the sweep.
- **D-09** — merge-filled siblings get no CheckerValidation; recorded only via AuditLog + checkin_method=MERGED.

## ROADMAP Success Criteria

- **Criterion #1** — a single event marks the whole merged group present (delivered by Plan 04.2-02).
- **Criterion #2** — the sweep never falsely marks present siblings Absent (delivered by Plan 04.2-04).
- **Criterion #3** — the online analog holds (the criterion that FAILED then was FIXED).
- **Criterion #4** — genuinely-missed non-merged sessions are still marked Absent.
- **Criterion #5** — sessions stay distinct rows; reporting integrity preserved.

## The Verification Gap (criterion #3 FAILED)

The **gsd-verifier** did not trust the executor's "operator follow-up, non-blocking" deferral. It
RAN **audit_merge_coverage** against the live term '2nd Term SY 2025-2026' and found the D-01 key
missed **48 of 152 online groups (~32%)** — real sessions where an instructor's simultaneous online
sections share neither room (both online) nor course_code, and teams_link is blank. For those, one
Checker Verify would not cover the siblings and the sweep would falsely mark them Absent — the exact
failure the phase exists to prevent. **Verification status: gaps_found. Score 15/16.**

## The Owner Decision

The owner (Joshua Sabuero) was shown the empirical result and decided:
**"If two online sessions start at the same time and is the same instructor, that is a merge session."**
An instructor is one live presence and cannot attend two different online classes at the same instant.

## D-01 Refinement #2 (the fix)

**D-01 refinement #2** amends **merged_sibling_ids** with a per-modality ONLINE arm: two effective-online
sessions with the same faculty + exact scheduled_start merge on faculty + start alone (room/course dropped
for online). **F2F is unchanged** (the GARAY case keeps room-OR-course). Effective modality =
`declared_modality` if set else `schedule.modality`. `_materialize_candidates` now hydrates each row's
`is_online`. **audit_merge_coverage** attaches is_online and becomes a live regression guard. Reporting
distinctness (criterion #5) is preserved — merge shares only the presence signal, never section identity.

**Evidence after fix:** live audit_merge_coverage reports **152/152 CAUGHT, 0 MISSED, exit 0**; full suite
237 tests with only 2 pre-existing unrelated login-static errors. **Verification status: passed. Score 16/16.**
The gap-closure landed in commit 571eb97; the owner decision is recorded in 04.2-CONTEXT.md.

## Requirements Delivered

Plans traced these requirement IDs to REQUIREMENTS.md: JOB-02b, SCAN-01, CHK-02, CHK-03, CHK-04, FAC-03,
FAC-04, FAC-09. No orphans. Phase 04.2 is an inserted correctness fix to already-delivered requirements,
surfaced by the Phase 04.1 real-data term load.

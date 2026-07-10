# Graph Report - .planning/graphs/session-04.2  (2026-07-07)

## Corpus Check
- 1 files · ~1,098 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 47 nodes · 69 edges · 8 communities detected
- Extraction: 78% EXTRACTED · 22% INFERRED · 0% AMBIGUOUS · INFERRED: 15 edges (avg confidence: 0.71)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_D-01 Detector & Refinement|D-01 Detector & Refinement]]
- [[_COMMUNITY_Merge Core & Transaction Rules|Merge Core & Transaction Rules]]
- [[_COMMUNITY_Live-Term Coverage Audit|Live-Term Coverage Audit]]
- [[_COMMUNITY_Sweep Invariant (JOB-02)|Sweep Invariant (JOB-02)]]
- [[_COMMUNITY_Faculty Scan Seam|Faculty Scan Seam]]
- [[_COMMUNITY_Checker Online Seam|Checker Online Seam]]
- [[_COMMUNITY_Verification Gap & Owner Decision|Verification Gap & Owner Decision]]
- [[_COMMUNITY_Execution Orchestration|Execution Orchestration]]

## God Nodes (most connected - your core abstractions)
1. `Plan 04.2-01 (Merge Core)` - 10 edges
2. `propagate_merged_present` - 9 edges
3. `Plan 04.2-02 (Faculty Scan Seam)` - 8 edges
4. `merged_sibling_ids` - 7 edges
5. `Plan 04.2-03 (Checker Online Seam)` - 7 edges
6. `Plan 04.2-04 (Sweep-Unchanged Proof + Audit)` - 7 edges
7. `D-01 Refinement #2 (online arm)` - 7 edges
8. `audit_merge_coverage` - 5 edges
9. `web/checker.py _apply_action` - 5 edges
10. `Wave 2` - 5 edges

## Surprising Connections (you probably didn't know these)
- `propagate_merged_present` --depends_on--> `MSSQL LocalDB`  [INFERRED]
  .planning/graphs/session-04.2/SESSION.md → .planning/graphs/session-04.2/SESSION.md  _Bridges community 0 → community 4_
- `merged_sibling_ids` --calls--> `propagate_merged_present`  [EXTRACTED]
  .planning/graphs/session-04.2/SESSION.md → .planning/graphs/session-04.2/SESSION.md  _Bridges community 6 → community 0_
- `audit_merge_coverage` --implements--> `Plan 04.2-04 (Sweep-Unchanged Proof + Audit)`  [EXTRACTED]
  .planning/graphs/session-04.2/SESSION.md → .planning/graphs/session-04.2/SESSION.md  _Bridges community 7 → community 1_
- `audit_merge_coverage` --references--> `D-01 (merge detection key)`  [EXTRACTED]
  .planning/graphs/session-04.2/SESSION.md → .planning/graphs/session-04.2/SESSION.md  _Bridges community 7 → community 6_
- `audit_merge_coverage` --calls--> `gsd-verifier`  [EXTRACTED]
  .planning/graphs/session-04.2/SESSION.md → .planning/graphs/session-04.2/SESSION.md  _Bridges community 7 → community 5_

## Hyperedges (group relationships)
- **Wave-2 seams import the merge core** — session_scan_apply, session_checker_apply_action, session_audit_merge_coverage, session_merged_sibling_ids [INFERRED 0.85]
- **D-decisions governing merge behavior** — session_d01, session_d04, session_d05, session_d07, session_d08, session_d09 [EXTRACTED 0.90]
- **Verification gap closure loop** — session_verification_gap, session_gsd_verifier, session_owner_decision, session_d01_refinement2 [INFERRED 0.85]

## Communities

### Community 6 - "D-01 Detector & Refinement"
Cohesion: 0.6
Nodes (5): merged_sibling_ids, _materialize_candidates, resolver.is_no_show_past_grace, D-01 (merge detection key), D-01 Refinement #2 (online arm)

### Community 0 - "Merge Core & Transaction Rules"
Cohesion: 0.24
Nodes (11): propagate_merged_present, propagate_merged_absent, CheckinMethod.MERGED, make_merge_fixture, web/scan.py _apply, web/checker.py _apply_action, 0004_alter_session_checkin_method, Plan 04.2-01 (Merge Core) (+3 more)

### Community 7 - "Live-Term Coverage Audit"
Cohesion: 1.0
Nodes (2): audit_merge_coverage, '2nd Term SY 2025-2026'

### Community 1 - "Sweep Invariant (JOB-02)"
Cohesion: 0.33
Nodes (6): scheduling/jobs.py sweep, Plan 04.2-04 (Sweep-Unchanged Proof + Audit), D-08 (shared scheduled_start absent), Criterion #2, Criterion #4, JOB-02b

### Community 2 - "Faculty Scan Seam"
Cohesion: 0.33
Nodes (6): Plan 04.2-02 (Faculty Scan Seam), Criterion #1, SCAN-01, FAC-03, FAC-04, FAC-09

### Community 3 - "Checker Online Seam"
Cohesion: 0.33
Nodes (6): Plan 04.2-03 (Checker Online Seam), D-09 (no CheckerValidation for merge-fill), Criterion #5, CHK-02, CHK-03, CHK-04

### Community 5 - "Verification Gap & Owner Decision"
Cohesion: 0.4
Nodes (5): Criterion #3, gsd-verifier, Owner Joshua Sabuero, The Verification Gap (criterion #3 FAILED), The Owner Decision

### Community 4 - "Execution Orchestration"
Cohesion: 0.4
Nodes (6): execute-phase orchestrator, gsd-executor, GSD wave model, Wave 1, Wave 2, MSSQL LocalDB

## Knowledge Gaps
- **19 isolated node(s):** `make_merge_fixture`, `0004_alter_session_checkin_method`, `resolver.is_no_show_past_grace`, `D-04 (single transaction)`, `D-05 (status guard)` (+14 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Live-Term Coverage Audit`** (2 nodes): `audit_merge_coverage`, `'2nd Term SY 2025-2026'`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Plan 04.2-01 (Merge Core)` connect `Merge Core & Transaction Rules` to `Sweep Invariant (JOB-02)`, `Faculty Scan Seam`, `Checker Online Seam`, `Execution Orchestration`, `D-01 Detector & Refinement`?**
  _High betweenness centrality (0.401) - this node is a cross-community bridge._
- **Why does `Plan 04.2-04 (Sweep-Unchanged Proof + Audit)` connect `Sweep Invariant (JOB-02)` to `Merge Core & Transaction Rules`, `Execution Orchestration`, `Live-Term Coverage Audit`?**
  _High betweenness centrality (0.253) - this node is a cross-community bridge._
- **Why does `Plan 04.2-02 (Faculty Scan Seam)` connect `Faculty Scan Seam` to `Merge Core & Transaction Rules`, `Execution Orchestration`?**
  _High betweenness centrality (0.222) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `propagate_merged_present` (e.g. with `MSSQL LocalDB` and `propagate_merged_absent`) actually correct?**
  _`propagate_merged_present` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 4 inferred relationships involving `Plan 04.2-02 (Faculty Scan Seam)` (e.g. with `SCAN-01` and `FAC-03`) actually correct?**
  _`Plan 04.2-02 (Faculty Scan Seam)` has 4 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `merged_sibling_ids` (e.g. with `resolver.is_no_show_past_grace` and `_materialize_candidates`) actually correct?**
  _`merged_sibling_ids` has 2 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `Plan 04.2-03 (Checker Online Seam)` (e.g. with `CHK-02` and `CHK-03`) actually correct?**
  _`Plan 04.2-03 (Checker Online Seam)` has 3 INFERRED edges - model-reasoned connections that need verification._
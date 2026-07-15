---
phase: 06-reporting-engine-reporting-surfaces
plan: 02
subsystem: infra
tags: [reportlab, pdf, reporting, supply-chain, requirements, package-legitimacy]

# Dependency graph
requires:
  - phase: 06-reporting-engine-reporting-surfaces
    provides: "06-RESEARCH decision A3 — ReportLab chosen as the pure-Python PDF path over WeasyPrint (rejected) and xhtml2pdf (fallback only)"
provides:
  - "reportlab>=4.2,<5 pinned + installed (4.5.1); pure-Python, only image dep is Pillow (already present)"
  - "reportlab.platypus (Table, SimpleDocTemplate) importable under py -3.12 for 06-03's PDF builder"
affects: [06-03-report-pdf-builder, 06-05-weekly-report-surface, 06-06-dean-export]

# Tech tracking
tech-stack:
  added: [reportlab]
  patterns:
    - "New third-party dependency isolated behind a blocking-human package-legitimacy checkpoint before any pip command (supply-chain gate, mirrors 05-02 pywebpush)"
    - "Conservative pin range excludes a brand-new major (>=4.2,<5 avoids the ~1-month-old 5.0.0)"

key-files:
  modified:
    - "requirements.txt — reportlab>=4.2,<5 under the Media / reports heading (next to Pillow)"

key-decisions:
  - "Task 1 package-legitimacy gate (T-06-SC) approved by the operator after pypi.org verification: reportlab is the ~18-year-established ReportLab library (official reportlab.com), and its SUS audit verdict is a download-telemetry false positive (unknown-downloads seam + newness of 5.0.0), not a slopsquatting signal"
  - "Pinned reportlab>=4.2,<5 to land on the mature 4-series and exclude the brand-new 5.0.0; resolved to 4.5.1"
  - "No WeasyPrint / GTK / Pango / Cairo dependency introduced; ReportLab's only image dep (Pillow 12.3.0) was already installed, so no system libraries were pulled"

patterns-established:
  - "Supply-chain gate: every new third-party package is verified on pypi.org behind a blocking-human checkpoint before install; never auto-approved regardless of auto_advance"

requirements-completed: [RPT-03]

coverage:
  - id: D1
    description: "reportlab>=4.2,<5 pinned in requirements.txt and importable under py -3.12 (reportlab.platypus Table + SimpleDocTemplate load); Pillow already satisfied, no system libs"
    requirement: "RPT-03"
    verification:
      - kind: automated_ui
        ref: "py -3.12 -c \"import reportlab; from reportlab.platypus import Table, SimpleDocTemplate; print(reportlab.Version)\" -> reportlab 4.5.1"
        status: pass
    human_judgment: false
  - id: D2
    description: "Install gated behind an approved blocking-human legitimacy checkpoint (T-06-SC) before any pip command ran; Django still checks clean"
    requirement: "RPT-03"
    verification:
      - kind: integration
        ref: "operator typed 'approved' after pypi.org verification; manage.py check -> System check identified no issues (0 silenced)"
        status: pass
    human_judgment: true

# Metrics
duration: 2min
completed: 2026-07-15
status: complete
---

# Phase 06 Plan 02: ReportLab PDF Engine Prerequisite Summary

**ReportLab pinned `reportlab>=4.2,<5` (installed 4.5.1) as the pure-Python PDF engine for RPT-03, gated behind an approved blocking-human package-legitimacy checkpoint (T-06-SC); no system libraries introduced.**

## Performance

- **Duration:** ~2 min (continuation execution, post-approval)
- **Completed:** 2026-07-15
- **Tasks:** 2 (Task 1 = blocking legitimacy checkpoint, operator-approved; Task 2 = install + pin)
- **Files modified:** 1 (requirements.txt)

## Accomplishments
- Presented the ReportLab package-legitimacy checkpoint (T-06-SC) and blocked on it — the operator approved after pypi.org verification (official reportlab.com maintainers, multi-year version history, SUS verdict confirmed as a download-telemetry false positive).
- Installed `reportlab` under py -3.12 with the conservative pin `reportlab>=4.2,<5`, resolving to **4.5.1**; Pillow (its only image dependency) was already present (12.3.0), so no extra system libraries were pulled.
- Pinned `reportlab>=4.2,<5   # printable weekly-report PDF (RPT-03); pure-Python, no system libs` under the `# Media / reports` heading in requirements.txt, next to Pillow — no other pin touched.
- Verified `import reportlab` plus `reportlab.platypus.Table` / `SimpleDocTemplate` load cleanly, and `manage.py check` reports no issues.

## Task Commits

1. **Task 1: Package-legitimacy gate (T-06-SC)** — no commit; blocking-human checkpoint approved by the operator after pypi.org verification of reportlab. Recorded in the Task 2 commit trailer.
2. **Task 2: Install + pin reportlab** — `5cdb397` (feat)

## Files Created/Modified
- `requirements.txt` — added `reportlab>=4.2,<5` under `# Media / reports` (installed 4.5.1). No other pin modified.

## Decisions Made
- Approved the SUS-flagged reportlab as a telemetry false positive rather than dropping it: the automated audit could not read PyPI weekly-download telemetry (`unknown-downloads`) and `5.0.0` is recent — neither is a slopsquatting/malicious signal. reportlab is an ~18-year-established library (official reportlab.com).
- Pinned `>=4.2,<5` to stay on the mature 4-series and exclude the brand-new 5.0.0 (per RESEARCH A3 and the plan prohibition).
- Kept the WeasyPrint path rejected — no GTK/Pango/Cairo system dependency introduced; ReportLab's pure-Python wheels are identical on Windows dev and Linux EC2.

## Deviations from Plan
None - plan executed exactly as written. requirements.txt was intentionally left untouched at the checkpoint and edited only in Task 2 after approval, per the plan's prohibition on any pre-approval package action.

## Issues Encountered
None. reportlab installed from a pre-built wheel (no Windows build step); Pillow and charset-normalizer were already satisfied. Git reported a benign LF->CRLF normalization notice on requirements.txt.

## Next Phase Readiness
- `reportlab.platypus` (Table, SimpleDocTemplate) is available for 06-03's PDF builder and the 06-05 weekly-report surface / 06-06 Dean export.
- No blockers.

## Self-Check: PASSED

- requirements.txt — present, reportlab pin verified via grep
- Commit 5cdb397 — present in git history
- 06-02-SUMMARY.md — present

---
*Phase: 06-reporting-engine-reporting-surfaces*
*Completed: 2026-07-15*

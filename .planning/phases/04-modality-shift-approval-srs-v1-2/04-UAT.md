---
status: testing
phase: 04-modality-shift-approval-srs-v1-2
source: [04-VERIFICATION.md]
started: 2026-07-03T16:57:25Z
updated: 2026-07-03T16:57:25Z
---

## Current Test

number: 1
name: SRS DOCX visual fidelity
expected: |
  Open the regenerated FluxTrack_SRS.docx and confirm the v1.2 content renders correctly:
  the new MOD area (MOD-01..06), the DEAN-04 row, the modality_shift_lead_days policy-register
  row, and the removed CHK-06 — all with tables and headings intact (no broken markdown-table
  artifacts from the pandoc conversion). Regenerate first with
  `py -3.12 manage.py regenerate_srs_docx` if needed.
awaiting: user response

## Tests

### 1. SRS DOCX visual fidelity
expected: FluxTrack_SRS.docx opens and the v1.2 content — MOD area (MOD-01..06), DEAN-04 row, modality_shift_lead_days policy-register row — renders with intact tables/headings; the CHK-06 requirement row is absent.
result: [pending]

### 2. Faculty availability-first picker UI
expected: As a faculty user, open the modality-shift submit form (modality_new). The availability-first room/time picker offers only free rooms/times, is consistent with the project's Franken-UI styling, and is usable on mobile. Submitting creates a pending request; "my requests" (modality_mine) lists it with a working withdraw action.
result: [pending]

### 3. Dean approval queue UI
expected: As the department Dean, open the approval queue (dean_queue). Pending requests are listed department-scoped; Approve and Reject act via htmx with a clear in-place swap after the decision; Reject requires a reason. Approving a ->Online request releases the room; approving a ->F2F request with no free room shows the terminal denial cleanly.
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps

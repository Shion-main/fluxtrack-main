# Session 2026-07-20 — Full audit, quick wins, milestone v1.3, Phase 9

## Arc
1. **Five-lens audit** (requirements, security, correctness, frontend, ops) run in
   parallel against the codebase → `docs/AUDIT-2026-07-19.md`. Verdict: feature
   surface ~95% built, roadmap claims held up; real gaps are wrong-record bugs,
   Phase 8 under-scoping, pre-cutover security, SRS drift, floor-UX trust.
2. **Quick-wins batch** shipped (7 commits): H1 (online self-start propagates merged
   siblings), H2 (grace-gate merged-absent), M4 (released-room no false handover),
   M7 (status-guarded sweep write), seed_demo DEBUG guard, the 3 long-standing red
   tests (one root cause: home() 302-redirects), dead Tailwind utilities incl. the
   transparent global header, offline-queue drain-on-load.
3. **Second audit** (first-principles mission-fit + UI/UX) → addendum in the same
   doc. Headline: a typhoon/suspension day mass-marked the campus Absent; the
   "a Checker can correct it" message was a false promise; lateness captured but
   never surfaced; no term rollover; building/floor CRUD is admin-only.
4. **Milestone v1.3 "Operational Trust"** (phases 9-16) proposed
   (`docs/PLAN-2026-07-20-post-audit-milestone.md`) and committed to ROADMAP. Deploy
   renumbered 8→15 (expanded), runs last.
5. **Phase 9 built + verified complete** (the critical one).

## Decisions locked this session
- **UI is shadcn-via-Franken** (Franken UI IS shadcn ported to non-React). Not a
  swap; SRS clarification queued for Phase 16. See memory `ui-token-foundation`.
- **Deploy sequencing:** mission-critical features first, deploy (Phase 15) last;
  Phase 9 before any real use. (Owner did not require a live URL for the defense
  this session — revisit if that changes.)
- **D3 Absent corrections = IFO-only** (custodian of the record; not roaming checkers).
- **D4 suspension notifies faculty** (one coalesced notify per faculty).

## Phase 9 shipped (typhoon fix)
- `SessionStatus.CANCELLED` (terminal; 0 booked hours, not held, not absent).
- `ClassSuspension` model (date range, optional building, reversible via lifted_at)
  + `Session.cancelled_reason`. Migrations 0006, 0007.
- `scheduling/suspensions.py`: `excused_checker` (shared by sweep + materialize),
  `suspend_classes` (flip + coalesced notify), `lift_suspension`.
- Sweep + materialize skip excused (date, building); reporting excludes CANCELLED.
- IFO consoles: `/ifo/suspensions`, `/ifo/breaks`, `/ifo/corrections` (+ Campus
  calendar nav). Faculty online-start Absent message now points to IFO.
- 30 new tests. Suite 965 green. 09-VERIFICATION.md: 5/5.
- **Open:** browser UAT of the 3 new console pages not yet run.

## Resume pointer
Next: **Phase 10 — Campus Structure Management** (building/floor CRUD [the
still-admin-only gap], room out-of-service flag A7, single-schedule edit A9;
reuses CANCELLED for a cancelled meeting). STATE.md current_phase=10.
Consider a browser UAT of Phase 9 consoles before stacking more IFO work.

## Env gotchas (see memory)
- Running `manage.py test` **regenerates `FluxTrack_SRS.docx`** (a test invokes
  `regenerate_srs_docx`); `git checkout -- FluxTrack_SRS.docx` after full runs.
- Interpreter: full `Python312\python.exe` path for manage.py (bare python lacks Django).

# Phase 07: Remaining Operational Surfaces — Discussion Log

**Gathered:** 2026-07-18
*Human reference only — not consumed by downstream agents (see 07-CONTEXT.md for the canonical decisions).*

## Areas selected for discussion
FAC-08 online start · Guard duty scope + alerts · IFO booking + release · IFO-03b import surface · (then) QR rotation · Faculty profile + history · Room CRUD.

---

## FAC-08 online start
**Q: Who has authority to mark an online session started/active?**
Options: Checker only (retire FAC-08, recommended) / Both — faculty start + Checker verifies / Faculty starts but not evidence.
→ **Both — faculty start, Checker verifies.**

**Q: Self-started but never Checker-verified — what happens?**
Options: Stays active, flagged unverified (recommended) / Sweep can still mark absent / Stays active, no distinction.
→ **Stays active, flagged unverified** (04.2 D-09 precedent).

**Q: Where does the Teams link come from?**
Options: Pre-filled faculty confirms (recommended) / Faculty pastes every time / Pre-filled only, no editing.
→ **Faculty pastes it every time.**

**Q: What happens to Session.teams_link (which the Checker reads) on paste?**
Options: Overwrites audit-logged (recommended) / Stored separately / Overwrites only if empty.
→ User paused: *"wait lets discuss this cause i think we are not on the right track."* Discussed the drift — the chain of hard questions was a symptom of FAC-08 predating the Phase-3 Checker-verified decision. User then stated the model plainly: *"the faculty will paste a link and when they click start it will be marked as its started and checkers can see that link to verify."*
→ **Resolved:** pasted link IS Session.teams_link (no competing official link); write audit-logged by convention; starting ≠ verifying, so the CHK-02/FAC-08 contradiction closes without retiring FAC-08. (D-01/D-02/D-03)

---

## Guard duty scope + alerts
**Q: How does a Guard get assigned to floor(s)?**
Options: Reuse CheckerAssignment (recommended) / Separate GuardAssignment / Guards see whole building.
→ **Reuse CheckerAssignment.** (D-04)

**Q: What triggers a push alert to an on-duty Guard?** (multi-select)
Options: Room conflict on my floor / Ghost booking-no-show / Unscheduled room occupied / Every check-in.
→ **Room conflict + Ghost booking/no-show** (both already-emitted events). (D-05)

**Q: What should "debounced" mean?**
Options: Coalesce per sweep run (recommended) / Per-room cooldown / Fixed window per guard.
→ **Coalesce per sweep run** — one summary push per job run per Guard. (D-06)

**Q: What can a Guard see when locating a faculty member?**
Options: Now + next class only (recommended) / Add today's schedule / Add attendance status.
→ **Add today's schedule** (but not attendance status). (D-07)

---

## IFO booking + release
*Noted the area was largely pre-decided by `ops/availability.py` — skipped re-deciding "what is a conflict."*

**Q: IFO booking covers a room; scheduled faculty scans QR — what happens?**
Options: Scan wins, IFO warned at booking (recommended) / Booking blocks scan / Both allowed, conflict flag.
→ **Scan wins, IFO warned at booking time** — resolver untouched. (D-09)

**Q: IFO manual release — what else does it do?**
Options: Release + auto-resolve flag (recommended) / Release + immediately close flag / Separate release and resolve.
→ **Release + let existing sweep auto-resolve the flag.** (D-11)

---

## IFO-03b import surface
**Q: What formats + how does import run?**
Options: Both formats preview-then-commit (recommended) / Both formats one-shot / CSV only preview-then-commit.
→ **Both (.xlsx + .csv), preview then commit.** (D-12)

**Q: Should the web upload be able to clear the term (reset_term) first?**
Options: Additive only — no reset on web (recommended) / Reset double-confirmed / Reset no special guard.
→ **Additive only — no reset reachable from the browser.** (D-13)

---

## QR rotation (IFO-02)
**Q: Rotation invalidates every printed poster — what should the flow do?**
Options: Confirm + reprint worklist (recommended) / Confirm only / Rotate immediately.
→ **Confirm + land on the poster page to reprint.** (D-14)

---

## Faculty profile + history (FAC-11/FAC-12)
**Q: Faculty sees a Checker flag against them — what can they do?**
Options: View only read-only (recommended) / View + contest / Hide flags.
→ **View only, read-only** (dispute flow = own phase). (D-15)

**Q: Profile photo (identity evidence) — how much validation?**
Options: Basic validation (recommended) / Validation + approval / Accept anything.
→ **Basic validation + server-side re-encode.** (D-16)

---

## Room CRUD (IFO-01b)
**Q: Delete a room with schedules/sessions/bookings — what happens?**
Options: Refuse if referenced (recommended) / Soft deactivate / Cascade delete.
→ **Refuse if referenced.** (D-17)

---

## Deferred ideas
Faculty flag dispute workflow · profile-photo moderation queue · web-reachable term reset/replace-term import · unscheduled-room-occupied Guard alert. (See 07-CONTEXT.md `<deferred>`.)

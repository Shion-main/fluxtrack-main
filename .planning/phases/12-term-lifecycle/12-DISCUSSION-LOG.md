# Phase 12: Term Lifecycle - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md; this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 12-term-lifecycle
**Areas discussed:** Term states and transitions, Preparing the next term, Historical reporting, Rollover safeguards

---

## Term states and transitions

| Question | Selected | Alternatives considered |
|----------|----------|-------------------------|
| Lifecycle model | Draft → Active → Archived; exactly one active | Reuse inactive/active only; add Scheduled state |
| Reopening archives | IFO may reopen with confirmation, reason, and audit | Break-glass only; never reopen |
| Close eligibility | After end date and with no active sessions | Early-close and cancel future sessions; freeze anytime |
| Archive enforcement | Application-wide write freeze | Allow attendance corrections; UI-only freeze |

**User's choices:** The user explicitly selected the options above one by one.
**Notes:** Reopening returns the term to Draft. Archived data stays frozen until that explicit transition.

---

## Preparing the next term

| Question | Selected recommended default | Alternatives considered |
|----------|------------------------------|-------------------------|
| Pre-activation preparation | Import schedules into Draft; materialize on activation | Materialize Draft sessions; prohibit preparation before activation |
| Switching terms | Close/archive first, then activate separately | One-click archive-and-activate; overlapping active terms |
| Draft creation | Blank term with validated unique name and non-overlapping dates | Clone prior schedules; derive term only from import metadata |
| Activation completion | Initial materialization must succeed | Wait for next scheduler cycle; activate without materialization |

**User's choice:** “do all recommended.”
**Notes:** Recommended options were applied in one pass. Activation failure leaves the term Draft.

---

## Historical reporting

| Question | Selected recommended default | Alternatives considered |
|----------|------------------------------|-------------------------|
| Selectable surfaces | All IFO/Dean/HR reports and exports; live boards stay active-only | Exports only; every operational surface |
| Default selection | Active term via explicit query parameter | Remember in session; require choice every visit |
| Date behavior | Clamp to term; archived defaults full term, active keeps useful current defaults | Always full term; allow dates outside term |
| Cross-term aggregation | Exactly one term per report/export | Optional comparison; unbounded cross-term ranges |

**User's choice:** “do all recommended.”
**Notes:** Term selection must propagate through filters, pagination, drill-downs, and exports.

---

## Rollover safeguards

| Question | Selected recommended default | Alternatives considered |
|----------|------------------------------|-------------------------|
| Authority | IFO Admin, with superuser break-glass | System Admin only; IFO plus Dean |
| Confirmation | Preflight + typed term name; reasons for close/reopen | Simple dialog; two-person approval |
| Findings | Hard blockers plus acknowledged noncritical warnings | Block on all warnings; warn-only |
| Failure/recovery | Atomic transitions; failed activation remains Draft; reopen returns Draft | Partial progress; automatic reactivation of old term |

**User's choice:** “do all recommended.”
**Notes:** Audit records capture actor, reason, and before/after lifecycle state. No transition deletes historical records.

---

## Claude's Discretion

- Exact lifecycle field/migration representation and SQL Server constraint strategy.
- Service decomposition, route names, template layout, warning copy, and audit event names.
- Exact term query-parameter name and reusable selector implementation.

## Deferred Ideas

- Scheduled activation.
- One-click archive-and-activate.
- Automatic schedule cloning from the prior term.
- Multi-term comparison reports.
- Two-person lifecycle approval.


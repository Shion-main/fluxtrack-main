# FluxTrack application audit

**Audit date:** 2026-07-25  
**Scope:** attendance capture, room-utilization reporting, usability, and role/action fit  
**Method:** rendered browser walkthrough of all seven roles, source inspection of the critical write/report paths, Django system checks, and the full automated test suite.

## Executive verdict

**Attendance capture: yes, for faculty/class-session attendance.** FluxTrack can record a faculty member starting and ending a physical or online class, the actual timestamps, the check-in method, absence, early ending, room changes, handovers, checker verification, and audit events. It does **not** capture student attendance or room headcount.

**Room utilization: yes, but not yet operationally complete.** The calculation is well designed: used room-hours come from actual check-in/out timestamps, booked-but-absent time becomes waste, cancelled classes do not distort the denominator, and time is clamped to the scheduled window. However, a class that is checked in but never checked out stays `ACTIVE` and is excluded as “in flight.” There is no automatic end-of-class reconciliation or IFO correction for stale active sessions. Utilization will therefore be incomplete unless checkout compliance is consistently high.

**Usability: good overall, with several correctable issues.** Navigation, terminology, filters, empty states, and role-specific dashboards are generally clear and consistent. The global push-notification prompt obstructs primary content, HR has a visible but unusable Admin action, and a zero-denominator attendance percentage is presented as a red 0%.

**Role/action design: largely correct.** Server-side role checks are consistently applied, and the seven roles mostly receive the right level of authority. The main role UX defect is the dead HR Admin link.

**Release position:** suitable for controlled pilot/UAT, but not yet ready to be treated as a production source of truth for room utilization until stale/missing checkouts are explicitly handled and live Entra sign-in is proven.

## What the system actually measures

| Question | Answer |
|---|---|
| Does it record faculty attendance? | Yes. A class session becomes Active/Completed/Absent and stores actual start/end, method, verification, and audit history. |
| Does it record student attendance? | No. There is no student roster or per-student attendance event in this workflow. |
| Does it detect physical presence automatically? | No. Presence is inferred from authenticated faculty/checker actions: QR, room code, online start, or verification. |
| Does it measure room occupancy time? | Yes, for sessions with usable actual start and end timestamps. |
| Does it measure seat utilization/headcount? | No. The KPI is room-time utilization, not people or seats used. |
| Can a shared manual code be abused? | It is a weaker signal than QR/checker verification. Authentication and auditability help, but a code alone is not proof of physical presence. |

## Critical data flows

### Attendance

The physical scan flow re-resolves the current session, limits it to the signed-in faculty member and active term, then writes status, `actual_start`/`actual_end`, method, and an audit event. Confirmations are signed, short-lived, user-bound, state-revalidated, nonce-protected, and replay-resistant.

Online attendance has equivalent start/end records. Checker verification is stored separately, so reporting can distinguish “held” from “checker verified.”

No-show sweeping changes still-scheduled sessions to Absent after the allowed window. Attendance reporting treats Active and Completed as held and Absent as missed.

### Room utilization

The reporting engine uses one shared per-session calculation:

- Active sessions without an end timestamp are excluded and counted as in flight.
- Absent sessions contribute booked time and zero used time.
- Cancelled sessions contribute neither booked nor used time.
- Completed sessions use the overlap between their actual interval and scheduled interval.
- Available capacity is derived from physical rooms and the term's real timetable cells, rather than a hard-coded day/block count.

This is a sound definition of utilization, but it exposes the missing-checkout dependency described in Finding F-01.

## Findings

### F-01 — High: missing checkout can permanently understate utilization

When a session is Active with `actual_start` but no `actual_end`, the utilization engine excludes it from both booked and used hours and reports it as in flight. This avoids inventing occupancy while the class is genuinely running, but there is no scheduled job that finalizes stale Active sessions after their scheduled end, and the IFO correction workflow covers Absent records rather than stale Active ones.

**Impact:** one forgotten checkout can remove the entire class from historical booked and used room-hours. Enough missed checkouts make utilization materially incomplete even though attendance still counts the session as held.

**Recommendation:** add an explicit stale-active reconciliation policy. Options include an IFO review queue, automatic close at scheduled end marked as estimated, or both. Show “data completeness / sessions missing checkout” beside every utilization result and export.

**Evidence:** `web/scan.py:160-179`, `scheduling/reporting.py:744-798`, `scheduling/reporting.py:849-940`, and `scheduling/jobs.py:48`.

### F-02 — Medium: HR sees an Admin link that leads to a permission dead end

The HR demo account is staff, so the shared header renders **Admin**. Opening it produces Django's “You don't have permission to view or edit anything” page.

**Impact:** the action implies authority HR does not have and interrupts a payroll/reporting workflow.

**Recommendation:** render Admin only when the user has a useful admin permission (or only for System Admin), not merely when `is_staff` is true.

**Evidence:** `templates/base.html:103-116`; [HR dead-end screenshot](screenshots/hr-admin-link-result.png).

### F-03 — Medium: notification opt-in obstructs primary work

The fixed notification prompt appeared across Faculty, Checker, Guard, IFO, HR, Dean, and System Admin surfaces. It overlays the faculty check-in card, report rows, and room tiles.

**Impact:** the first-run prompt competes with the task the user came to complete, particularly check-in and dense reporting.

**Recommendation:** use a non-overlay banner or place the opt-in in Profile/notification settings after the user's first successful task. At minimum, suppress it on scan/check-in and table-heavy pages.

**Evidence:** `templates/base.html:211-239`; [faculty screenshot](screenshots/faculty-home.png), [HR screenshot](screenshots/hr-home.png), and [IFO screenshot](screenshots/ifo-home.png).

### F-04 — Medium: zero-denominator attendance is shown as a failing 0%

The Dean dashboard showed `0 / 126 held / scheduled` and a red `0%`. This can occur when the selected sessions have not happened yet. The display does not distinguish “no eligible sessions yet” from actual zero attendance.

**Impact:** a Dean can interpret future/unstarted sessions as department failure.

**Recommendation:** calculate percentage over elapsed/eligible sessions and render `N/A` or `—` when the denominator is zero. Add a “through [timestamp/date]” label.

**Evidence:** `scheduling/reporting.py:546-562`, `templates/dean/dashboard.html:31-49`; [Dean screenshot](screenshots/dean-home.png).

### F-05 — Medium: the automated booking test is time-zone-flaky

The full suite produced one failure: a scheduled-class overlap test expected HTTP 400 but received 200. At the audit time, UTC was 2026-07-24 while local Philippine time was 2026-07-25. The shared fixture stores `Session.date` using the UTC datetime's `.date()`, while the failing request combines that date with a locally formatted time. Around local midnight, the test asks about the prior local day and does not overlap the session.

The production booking path itself calls the shared room-availability oracle, which checks overlapping scheduled/active physical sessions, bookings, recurring schedules, and approved room reservations.

**Impact:** CI can fail depending on execution time, obscuring real regressions.

**Recommendation:** use `timezone.localdate(scheduled_start)` in the fixture or use a fixed aware local datetime.

**Evidence:** `scheduling/tests.py:199-221`, `web/tests_ifo_ops.py:332-342`, `web/ifo.py:856-928`, `ops/availability.py:197-227`.

### F-06 — Low: imported identity data is visible without sufficient cleanup

The HR report contains a faculty row named `fac-`, indicating a provisioned/imported account with no useful display name.

**Impact:** payroll exports and filters can contain ambiguous identities.

**Recommendation:** reject or quarantine users without a full name and institutional identifier during provisioning/import, and add an identity-data quality report.

**Evidence:** [HR screenshot](screenshots/hr-home.png).

### F-07 — Low: IFO room-board summary wording is ambiguous

The board says “74 rooms running clean” while the displayed room cards are labeled “FREE.” The intended meaning appears to be rooms included in the live operational set, not rooms currently occupied.

**Impact:** an operator can read the summary as 74 occupied/running rooms.

**Recommendation:** use wording such as “74 monitored rooms shown · 144 idle rooms hidden.”

**Evidence:** [IFO room-board screenshot](screenshots/ifo-home.png).

## Role/action audit

| Role | Current responsibility and actions | Verdict |
|---|---|---|
| Faculty | View own schedule/history; QR or room-code check-in/out; start/end own online classes; submit and withdraw own modality requests. | Correct. Ownership and active-term checks are enforced server-side. Manual codes remain a weaker physical-presence signal. |
| Checker | View assigned floors/online queue; scan and verify presence or empty-room state. | Correct. Verification is a distinct record and duty scope is server-derived. This is the key independent control over self-reported attendance. |
| Guard | Read assigned-floor monitor, room schedule, and locate faculty. | Correct. Every Guard route is GET-only and off-scope data is refused. |
| IFO Admin | Manage rooms/buildings, schedules/imports, bookings, conflicts, assignments, terms, breaks/suspensions, attendance corrections, and utilization reports. | Correct for facilities operations. This is appropriately the broadest operational role, but stale Active reconciliation is missing. |
| Dean | View own department, review modality requests, perform department-scoped overrides, and export department reports. | Correct. Department scoping is rechecked server-side. The KPI treatment needs clarification. |
| HR Admin | Read and export session-level attendance across departments. | Correct and appropriately read-only. Remove the unusable Admin link. |
| System Admin | Monitor scheduled jobs, inspect audit/system settings, and use Django admin. | Correct. Operational and account-management authority is separated from academic decisions. |

Roles are owned by the pre-provisioned FluxTrack `User` record. Entra authenticates the identity, associates it by email, and stores the durable Entra `oid`; the current pipeline does not retrieve arbitrary MMCM accounts or derive roles from Entra keys/groups. This is a safe allow-list model, but it means account provisioning and role assignment remain an explicit administrative process.

## Usability assessment

**Overall: 7.5/10 for desktop pilot use.**

Strengths:

- Consistent MMCM/FluxTrack visual language across all roles.
- Clear role badges, page titles, filters, exports, empty states, and sign-out.
- Faculty actions are prominent and the invalid room-code flow gives clear feedback.
- IFO and reporting screens expose useful operational detail without console errors.
- Forms and buttons were represented with accessible labels in browser snapshots, and pages include a skip-to-content target.

Weaknesses:

- Global notification opt-in is too intrusive.
- HR has a dead navigation action.
- Some status language and zero-value KPIs are misleading.
- Dense desktop reports need a verified responsive/mobile pass.

## Verification results

- `manage.py check`: **passed**, no system-check issues.
- Migration drift check: **passed**, no model changes requiring migrations.
- Full test suite: **1,315 tests**, **1,312 passed**, **1 failed**, **2 skipped**, completed in 887.648 seconds.
- The single failure is the time-zone-dependent test described in F-05, not a confirmed production collision bug.
- Browser walkthrough covered login plus Faculty, Checker, Guard, IFO, HR, Dean, and System Admin primary pages.
- Harmless invalid room-code submission was rejected with clear inline feedback.
- No browser console errors were observed on the audited pages.

Test logs:

- [stdout](tests.out.log)
- [stderr](tests.err.log)

## Release gates

Before calling FluxTrack a production source of truth:

1. Add stale-Active/missing-checkout reconciliation and a utilization completeness indicator.
2. Fix the time-zone-flaky test and return the full suite to green.
3. Remove the HR Admin dead end and correct the zero-denominator KPI.
4. Move or suppress the notification prompt on critical workflows.
5. Run real-device/mobile tests for Faculty, Checker, and Guard.
6. Complete production UAT with real MMCM Entra users: successful login, refusal of an unprovisioned tenant user, role routing, logout, and redirect URI validation.
7. Run an end-to-end campus scenario: materialize schedule → faculty check-in/out → checker verification → no-show sweep → HR/Dean attendance export → IFO utilization reconciliation.

## Final answer to the audit questions

- **Can attendance be captured successfully?** Yes, for faculty/class sessions, with good auditability and optional independent checker verification.
- **Can room utilization be captured successfully?** The math and reports can, but operational completeness is not guaranteed until missed checkouts are reconciled.
- **Is the app user-friendly?** Generally yes for a desktop pilot; the major workflows are understandable, but the notification overlay and a few misleading/dead UI elements should be corrected.
- **Are actions and requests right for each role?** Yes overall. Server-side role boundaries are strong and responsibilities are sensibly separated; HR's Admin link is the notable mismatch.

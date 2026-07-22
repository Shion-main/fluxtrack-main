  
MAPÚA MALAYAN COLLEGES MINDANAO

**FluxTrack**

Software Requirements Specification

*Faculty Attendance and Facility Utilization Information System*

College of Computer and Information Science

IEEE 830 · ISO/IEC/IEEE 29148

**Document Control**

| Item | Detail |
| :---- | :---- |
| Document title | FluxTrack — Software Requirements Specification |
| System | Faculty Attendance and Facility Utilization Information System |
| Status | For review |
| Version | 1.3 |
| Standard basis | IEEE 830 / ISO/IEC/IEEE 29148 |

**Revision History**

| Version | Date | Author | Description |
| :---- | :---- | :---- | :---- |
| 1.0 | 2026-06-25 | Research Team (Mayo, Ong, Sabuero) | Initial specification. |
| 1.1 | 2026-07-02 | Research Team (Mayo, Ong, Sabuero) | Frontend stack changed from Next.js/React SPA to server-rendered Django templates + htmx + Franken UI (Tailwind CSS). PWA, mobile-first, QR, and offline capabilities unchanged. Affects §2.1, §2.4, §3.3, §6.6, §6.7. |
| 1.2 | 2026-07-03 | Research Team (Mayo, Ong, Sabuero) | Modality-shift approval workflow (MOD-01..06); DEAN-04 added; FAC-07 superseded by MOD approval; CHK-03 amended (Confirm absent removed, actions apply to online sessions); CHK-06 removed; RPT-02 notifies Deans; modality_shift_lead_days added to the policy register. |
| 1.3 | 2026-07-22 | Research Team (Mayo, Ong, Sabuero) | Reconciled the specification with the completed system: Microsoft SQL Server replaces MySQL; Django sessions replace a backend JWT; instance filesystem storage replaces S3; JOB-02 no longer releases rooms on a timer; CHK-02 includes the online verification path; IFO-07 is a semantic live board rather than a spatial map; MOD-01 uses a single occurrence or next-N-week window; the shadcn design language is delivered through Franken UI; and suspension, holiday, campus-management, schedule-CRUD, and term-lifecycle capabilities are recorded. Adds implementation conformance and traceability in §10. |

**Approval and Sign-off**

| Role | Name | Signature | Date |
| :---- | :---- | :---- | :---- |
| Prepared by (Research Team) | Mayo, J. L. S.; Ong, C. J. S.; Sabuero, J. R. C. |  |  |
| Reviewed by (Capstone Adviser) | Christopher Josh L. Dellosa, MIS |  |  |
| Approved by (Panel / Program) |  |  |  |

**1\. Introduction**

**1.1 Purpose**

This Software Requirements Specification (SRS) defines the functional and non-functional requirements of FluxTrack, the internal class-scheduling and attendance-monitoring platform for Mapúa Malayan Colleges Mindanao (MMCM). It is intended to give developers, the capstone adviser, the review panel, and prospective institutional stakeholders a single, unambiguous description of what the system does, the constraints under which it operates, and the assumptions on which it rests. It serves as the agreed basis for design, implementation, testing, and evaluation.

**1.2 Scope**

FluxTrack reduces a faculty member's class check-in to a single action — scanning a room's Quick Response (QR) code or entering a six-digit room code — and treats an independent Checker's physical verification as the authoritative record of presence. It correlates scheduled room occupancy against actual detected presence to address three operational gaps: ghost bookings (rooms reserved but physically unused), unverified hybrid presence (a digital check-in that is not physically confirmed), and the lateness-visibility gap (no room-level record of on-time arrival). It provides administrators with trustworthy, exportable attendance reporting, including a weekly per-department consolidated attendance report.

The product is a Progressive Web Application (PWA) backed by a Django service, deployed on Amazon Web Services (AWS) infrastructure, with identity provided by Microsoft Entra ID. It does not perform payroll processing, student grading, or student-performance monitoring; the boundaries of the product are stated in Sections 2.5 and 7\.

**1.3 Definitions, Acronyms, and Abbreviations**

| Term | Meaning |
| :---- | :---- |
| API | Application Programming Interface |
| AWS | Amazon Web Services (RDS, EC2, and EBS-backed instance storage) |
| Claim | A faculty check-in: an assertion of presence, not yet independently confirmed |
| Checker | A roving staff member who physically verifies presence on an assigned floor; the source of truth |
| CSV | Comma-Separated Values file format |
| DPA | Philippine Data Privacy Act of 2012 (Republic Act No. 10173\) |
| DRF | Django REST Framework |
| EC2 | AWS Elastic Compute Cloud (application hosting) |
| Entra ID | Microsoft Entra ID (formerly Azure Active Directory), the identity provider |
| ERD | Entity Relationship Diagram |
| F2F | Face-to-face instructional modality |
| Force handover | System action transferring an occupied room from a prior session to a new one |
| Ghost booking | A reserved session for which no presence is established |
| Grace | Configurable window after the scheduled start during which check-in counts as Present |
| HR | Human Resources |
| IFO | Integrated Facilities Office |
| IRR | Implementing Rules and Regulations |
| ITO | Information Technology Office |
| JWKS | JSON Web Key Set (used to verify Entra ID tokens) |
| JWT | JSON Web Token |
| MMCM | Mapúa Malayan Colleges Mindanao |
| Modality | Instructional mode: Face-to-face (F2F), Blended, or Online |
| PDF | Portable Document Format |
| PKCE | Proof Key for Code Exchange (OAuth 2.0 extension) |
| PWA | Progressive Web Application |
| QR | Quick Response code |
| RBAC | Role-Based Access Control |
| RDS | AWS Relational Database Service (hosting Microsoft SQL Server Express) |
| Room hold | Configurable window a room stays reserved before it may be released |
| SQL Server | Microsoft SQL Server, accessed through ODBC Driver 18 |
| Schedule | A recurring class slot (faculty, room, course, day-of-week, time, modality) for a term |
| Session | A single dated occurrence of a scheduled class |
| SSO | Single Sign-On |
| SRS | Software Requirements Specification |
| VAPID | Voluntary Application Server Identification (web-push authentication) |
| Verification | A Checker's recorded confirmation or contradiction of a claim |
| WCAG | Web Content Accessibility Guidelines |

**1.4 References**

1\. IEEE Std 830-1998, \*IEEE Recommended Practice for Software Requirements Specifications.\*

2\. ISO/IEC/IEEE 29148:2018, \*Systems and software engineering — Life cycle processes — Requirements engineering.\*

3\. ISO/IEC 25010:2023, \*Systems and software engineering — SQuaRE — Product Quality Model.\*

4\. Republic Act No. 10173, \*Data Privacy Act of 2012\* (Philippines).

5\. IFO subject-matter-expert requirement: weekly per-department consolidated attendance report.

6\. MMCM Implementing Rules and Regulations (IRR) / attendance policy — not currently available (see Section 8).

**1.5 Document Overview and Conventions**

Section 2 gives an overall description of the product, its users, environment, and constraints. Section 3 specifies external interfaces. Section 4 specifies functional requirements by feature area. Section 5 specifies data requirements. Section 6 specifies non-functional requirements. Section 7 lists out-of-scope items, Section 8 records policy assumptions, Section 9 lists open items, and Section 10 records implementation conformance and requirement traceability.

Functional requirements are stated using "shall." Each requirement carries a stable identifier of the form \`AREA-NN\` (for example, \`SCAN-01\`). Preconditions state what must hold before the requirement applies; postconditions state the resulting system state. Where a precondition or postcondition does not meaningfully apply, it is shown as "—." Configurable policy values are referenced by name (for example, the grace window) and enumerated in Section 8\.

**2\. Overall Description**

**2.1 Product Perspective**

FluxTrack is a new, self-contained system. It is a client–server web application in which Django is the system of record: it owns the data, business rules, authorization, and server-rendered interface. Django templates are progressively enhanced with htmx for partial updates and polling. Franken UI supplies a non-React implementation of the shadcn design language on Tailwind CSS tokens. Small, isolated vanilla-JavaScript modules provide camera QR scanning, the Checker offline queue, web-push subscription, and focused interface behavior. No Node.js runtime or client-side single-page-application framework is required. The backend is layered into models, pure decision functions, transactional services, and thin views. Microsoft Entra ID supplies identity; Django establishes a server-side authenticated session after the OAuth exchange. Persistence uses Microsoft SQL Server in every environment. Profile photographs, staged imports, and generated reports use Django filesystem storage; production places `MEDIA_ROOT` on backed-up EC2/EBS storage. The application runs on AWS EC2 and uses AWS RDS for SQL Server Express. Live surfaces use periodic polling rather than persistent connections.

**2.2 Product Functions**

At a high level, FluxTrack shall:

* Authenticate users through institutional single sign-on and authorize them by role and data scope.

* Materialize dated class sessions from imported recurring schedules.

* Record faculty presence claims through a single QR scan or a six-digit code, and record independent Checker verifications as the authoritative presence record.

* Detect ghost bookings, unverified presence, and lateness, and maintain session and room status automatically.

* Present live room-status and schedule views to facilities and security staff.

* Produce attendance reporting and exports, including a weekly per-department consolidated report.

* Notify users of relevant events in-app and by web push.

* Provide administrative configuration, auditing, and scheduled-job monitoring.

**2.3 User Classes and Characteristics**

FluxTrack defines seven user classes. Each is authenticated through SSO and scoped server-side.

* **Faculty** are the primary end users. They interact through a mobile-first interface to view their daily and weekly schedule and to check in and out. They require minimal training and minimal interaction burden.

* **Checkers** are roving facilities staff who physically verify presence on assigned floors. They work mobile-first, often under intermittent connectivity, and constitute the system's source of truth.

* **IFO Admins** (Integrated Facilities Office) configure and monitor the system from a desktop interface: rooms, codes, schedules, bookings, assignments, live monitoring, and reporting.

* **HR Admins** consume verified attendance and export it for external payroll processing; they do not perform payroll within FluxTrack.

* **Guards** view live floor status and per-room schedules and locate faculty across campus; their access is read-only.

* **Deans** have read-only oversight scoped to their department(s): attendance reporting, per-faculty scorecards, and the weekly report for their department(s).

* **System Admins** manage users, system settings, the audit log, and scheduled-job monitoring.

**2.4 Operating Environment**

* **Backend:** Django with Django REST Framework for the limited JSON endpoints (Python).

* **Frontend:** Server-rendered Django templates enhanced with htmx and vendored Franken UI 2.1.2 (the shadcn design language implemented for non-React HTML on Tailwind CSS tokens); PWA-enabled via a service worker; camera QR scanning and the Checker offline queue implemented in vanilla JavaScript. Runs on modern mobile and desktop browsers. No Node.js runtime or CDN is required to serve the interface.

* **Database:** Microsoft SQL Server only, accessed through \`mssql-django\`, \`pyodbc\`, and ODBC Driver 18. Local development uses LocalDB or SQL Server Express; production targets AWS RDS for SQL Server Express.

* **File storage:** Django \`FileSystemStorage\`. Production stores profile photos, private imports, and generated report files below an EBS-backed \`MEDIA_ROOT\`; media requires a separate backup because it is not part of RDS snapshots.

* **Hosting:** AWS EC2, served over HTTPS using a managed certificate.

* **Identity:** Microsoft Entra ID single sign-on via a project-owned application registration.

* **Live data:** periodic polling; no WebSockets or realtime channels.

* **Client devices:** smartphones with a camera (Faculty, Checker) and desktop browsers (administrative roles).

**2.5 Design and Implementation Constraints**

* The system shall support all seven user classes while keeping flows, the data model, and the screen and API surface lean.

* QR check-in shall be the primary check-in mechanism, with a six-digit manual code as fallback.

* The system shall not implement a payroll lifecycle; it provides attendance reporting and export only.

* The interface shall be mobile-first for Faculty and Checker and desktop-first (responsive) for the remaining roles.

* All policy values shall be configurable (see Section 8\) rather than hardcoded.

* The system shall meet WCAG 2.1 AA and shall enforce all role and data scoping on the server.

* Live surfaces shall use polling; no realtime transport shall be required.

**2.6 Assumptions and Dependencies**

* A project-owned Microsoft Entra ID tenant and application registration are available.

* The official MMCM IRR / attendance policy is unavailable; all policy values are documented assumptions to be validated before real-world use (Section 8).

* Recurring schedules are provided as CSV; dated sessions are generated from them.

* Faculty profile photographs are available for Checker identity confirmation.

**3\. External Interface Requirements**

**3.1 User Interfaces**

The system shall provide a mobile-first interface for Faculty and Checker that is camera-first and reachable one-handed, and a desktop-first responsive interface for IFO Admin, HR Admin, Guard, Dean, and System Admin. The interface shall meet WCAG 2.1 AA contrast, keyboard-navigation, and visible-focus requirements. Principal surfaces include: the faculty day/week and check-in screens; the checker floor, room-state, and Online-session screens; the IFO semantic room board, today's room timeline, dashboard, campus/term/schedule management, and reporting; the guard floor monitor and faculty locator; the dean department oversight; and the system-admin user, settings, audit, and job-monitoring screens.

**3.2 Hardware Interfaces**

The system shall use the device camera of a smartphone to scan room QR codes; no other specialized hardware is required of users. Room QR codes and six-digit codes shall be distributed as printed posters generated by the system.

**3.3 Software Interfaces**

* **Microsoft Entra ID (identity provider):** The server shall initiate and complete the OAuth 2.0 Authorization Code flow with PKCE through `python-social-auth`; Entra shall return identity claims used to associate a pre-provisioned User.

* **AWS RDS (Microsoft SQL Server Express):** The backend shall persist all relational data through `mssql-django`, `pyodbc`, and ODBC Driver 18 with encrypted production connections.

* **Instance filesystem:** Django storage shall place profile photographs, private import staging, and generated CSV/PDF reports below `MEDIA_ROOT`. Production shall keep that directory on persistent EBS-backed storage and back it up separately from RDS.

* **AWS EC2:** The application shall run on EC2 compute instances.

* **Microsoft Teams:** Online sessions shall reference an MS Teams meeting link supplied by the faculty member.

* **Web Push (VAPID):** The system shall deliver push notifications to subscribed clients using the VAPID scheme.

* **Browser platform services:** The PWA shall use a service worker for installability and push, and IndexedDB for the Checker offline scan queue. The interface shall be delivered as server-rendered HTML enhanced with vendored htmx for partial updates and polling and styled with vendored Franken UI; camera QR decoding shall use vendored html5-qrcode.

**3.4 Communications Interfaces**

All production client–server communication shall occur over HTTPS (TLS 1.2 or higher). The application shall exchange server-rendered HTML, htmx fragments, and JSON from narrowly scoped endpoints. Live surfaces shall obtain updates by polling at a configurable interval (default approximately 8 seconds). Push notifications shall be delivered using the web-push protocol.

**4\. Functional Requirements**

**4.1 Authentication and Identity (AUTH)**

This area governs sign-in, identity mapping, authorization, and account deactivation.

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| AUTH-01 | The system shall authenticate users via Microsoft Entra ID single sign-on using the server-side Authorization Code flow with PKCE. | The user holds a valid institutional Microsoft account. | Entra returns authenticated identity claims to the application callback. |
| AUTH-02 | The system shall validate the Entra exchange through the identity provider library, map the identity to a pre-provisioned User, and establish a Django server-side session. No application-issued bearer JWT is required. | Valid Entra identity claims have been received. | An authenticated Django session is established. |
| AUTH-03 | The system shall prevent any identity without a provisioned User record from proceeding past sign-in. | The identity has been authenticated by Entra ID. | Unprovisioned identities receive no application access. |
| AUTH-04 | The system shall enforce role and data scope on the server for every request. | The request carries a valid authenticated session. | Out-of-scope data and actions are denied. |
| AUTH-05 | The system shall block login and subsequent application access for a deactivated User. Existing session authentication shall be re-checked against the user's active state. | A System Admin deactivates the user. | The user can no longer access authenticated application surfaces. |

**4.2 Scan Resolver (SCAN)**

A single role-aware endpoint resolves the scanner, room, current schedule, and current time into a discrete outcome.

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| SCAN-01 | The system shall expose a single role-aware scan endpoint that accepts exactly one of a QR token or a six-digit manual code and resolves it against the authenticated user, room, current schedule, and current time. | The user is authenticated; a valid token or code is supplied. | A discrete, role-appropriate outcome is returned. |
| SCAN-02 | The system shall return, for Faculty scans, one of: checked-in, absent (after grace), too-early, wrong-room confirmation, room-occupied, checked-out, early-end confirmation, online-reject, or no-schedule. | The scanner is a Faculty user. | The session state reflects the resolved outcome. |
| SCAN-03 | The system shall return, for Checker scans, the room's current state to support verification (see Section 4.5). | The scanner is an on-duty Checker on the assigned floor. | The current room state is presented for action. |
| SCAN-04 | The system shall issue a short-lived signed resolution token for two-step outcomes (wrong-room, room-occupied, early-end) and shall apply the action only upon a confirming call to the scan-confirm endpoint. | A two-step outcome has been resolved. | The action is applied only after explicit confirmation. |
| SCAN-05 | The system shall rate-limit the manual-code path (configurable; default five attempts per minute per user) and shall audit-log repeated failures. | A manual code is submitted. | Excess attempts are rejected; failures are logged. |
| SCAN-06 | The system shall make scans idempotent per user, session, and minute. | A scan is received. | Duplicate scans within the window cause no additional state change. |
| SCAN-07 | The system shall encode the QR as a deep link that opens the scan flow, logging the user in if necessary; QR tokens and manual codes shall be resolver-only and never client-readable. | A room QR is scanned by the device camera. | The user is routed to the resolved outcome without exposing the token. |

**4.3 Faculty (FAC)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| FAC-01 | The system shall present each faculty member their classes for the day and their schedule for the week (read-only). | The user is authenticated as Faculty. | The faculty schedule is displayed. |
| FAC-02 | The system shall allow faculty to check in by scanning a room QR code or entering the room's six-digit code. | A session is scheduled for the faculty member in that room. | A check-in claim is recorded. |
| FAC-03 | The system shall transition a session to active (Present) when check-in occurs within the grace window. | Check-in occurs at or after the scheduled start and within grace. | The session is active; actual start is stamped. |
| FAC-04 | The system shall mark a session Absent and not start it when check-in occurs after the grace window. | Check-in occurs after grace. | The session is or remains Absent; no active session starts. |
| FAC-05 | The system shall allow faculty to check out by re-scanning the room (F2F/Blended) or tapping check-out (Online), completing the session. | The session is active. | The session is completed; actual end is stamped. |
| FAC-06 | The system shall require a reason when check-out occurs earlier than the configurable early-end threshold, recording the session as ended early with that reason. | Check-out occurs before the threshold. | The early-end flag and reason are recorded. |
| FAC-07 (superseded) | Superseded by the Dean-approved modality-shift workflow (Section 4.4, MOD area). A per-session modality change is no longer made by faculty self-declaration; a faculty member instead submits a modality-shift request that the department Dean approves or rejects (MOD-01..MOD-06). | The session exists. | Modality changes are recorded only through an approved modality-shift request. |
| FAC-08 | The system shall require a valid MS Teams link to start an Online session via a "Verify and Start" action (no QR), while Blended sessions check in by QR exactly as F2F. | The session modality is Online (or Blended). | The Online session is started with its Teams link, or the Blended session checks in by QR. |
| FAC-09 | The system shall, on a room-occupied outcome, allow a Force Handover that auto-completes the prior active session and starts the new session, recording the handover and auditing it, with no faculty-to-faculty interaction. | The room holds a prior active session. | The prior session is completed; the new session is active with handover recorded. |
| FAC-10 | The system shall, on a wrong-room confirmation, update the session's room and notify IFO. | The faculty member confirms the room change. | The session room is updated; IFO is notified. |
| FAC-11 | The system shall allow faculty to view their own attendance history, including any Checker flags, read-only with no dispute. | The user is authenticated as Faculty. | The faculty member's own history is displayed. |
| FAC-12 | The system shall allow faculty to manage their profile, including the profile photo used for Checker identity matching, and their notification preferences. | The user is authenticated as Faculty. | The profile and preferences are updated. |

**4.4 Modality Shift Approval (MOD)**

This area governs the request-and-approval workflow for changing a session's modality (F2F/Blended to/from Online) with the room consequence applied automatically. It replaces the FAC-07 faculty self-declare path.

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| MOD-01 | The system shall allow a faculty member to submit a modality-shift request (F2F/Blended to/from Online) for either one selected session date or the next N weekly occurrences (1–16). The recurring option begins after the `modality_shift_lead_days` cutoff (default 2 whole calendar days, Asia/Manila); a single date that violates the cutoff is refused. | The user is authenticated as Faculty; the affected session(s) exist within the derived window. | One atomic pending request records the derived date window, or the request is refused as too late. |
| MOD-02 | The system shall route each request to the requesting faculty member's department Dean, who shall approve or reject it with a reason; there is no dispute workflow. | A pending request exists and the faculty member has an assigned department Dean. | The Dean approves or rejects the request, recording a reason. |
| MOD-03 | The system shall, on approval of a shift to Online, set the affected in-window session(s) to Online and release the room immediately (`room_released_at` stamped), not on a hold timer; Online sessions later materialized within the window are born released. | The Dean approves a to-Online request. | The affected sessions are Online and their rooms are released. |
| MOD-04 | The system shall, on approval of a shift to F2F/Blended, auto-assign a free room in the same building at approval time; if no room is free, the approval fails with a clear reason and no session is changed (no silent partial apply). | The Dean approves a to-F2F/Blended request. | A room is assigned to the affected session(s), or the approval fails cleanly with a stated reason. |
| MOD-05 | The system shall, on approval, notify IFO informationally (not a gate) via the single notification write path, and shall allow the requesting faculty member to withdraw a request while it is still pending. | A request is approved, or a pending request is withdrawn by its requester. | IFO is notified on approval; a pending request may be withdrawn by its owner. |
| MOD-06 | The system shall make this Dean-approved modality-shift workflow the sole path for changing a session's modality, replacing the FAC-07 self-declare; same-day changes have no formal path and fall back to existing scan-time behavior. | A modality change is required for one or more sessions. | The change occurs only through an approved modality-shift request; the FAC-07 self-declare entry point is retired. |

**4.5 Checker (CHK)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| CHK-01 | The system shall grant verification powers only while a Checker is on duty (active shift or standing posting) on an assigned floor. | The Checker has an active assignment on the floor. | Verification actions are permitted on that floor. |
| CHK-02 | The system shall return, on a Checker room scan, the room's current state together with the faculty member's profile photo for identity matching. For Online sessions, the assigned online-duty Checker shall receive a separate list, open the public Teams link, and apply the same Verify/Flag decision without scanning a physical room. | The Checker is on duty for the assigned floor or owns the Online session. | The room state and faculty photo, or the assigned Online session and Teams link, are presented. |
| CHK-03 | The system shall offer room-state actions: Verify, Flag identity mismatch, Flag not present, and Confirm empty / Verified empty; these actions apply to online sessions as well as to F2F/Blended sessions. | A room or online session state has been retrieved. | The selected finding is recorded. |
| CHK-04 | The system shall mark a session as checker-verified when a Verify finding is recorded. | A Verify finding is submitted. | The session is marked verified by checker. |
| CHK-05 | The system shall record a Flag identity mismatch as a flag visible to IFO and HR, with no dispute workflow. | A mismatch finding is submitted. | The flag is recorded and surfaced to IFO/HR. |
| CHK-07 | The system shall present a floor view with coverage progress, a priority queue of the oldest unverified active sessions, and color-coded room cards. | The Checker is on duty on the floor. | The floor view reflects current coverage and priorities. |
| CHK-08 | The system shall queue scans locally when offline and replay them in batch on reconnect, re-validating each on the server before applying or flagging for IFO. | Connectivity is intermittent. | Queued scans are applied or flagged on reconnection. |

**4.6 IFO Admin (IFO)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| IFO-01 | The system shall allow IFO to create, read, update, and delete rooms and to generate a printable QR poster per room (QR, six-digit code, instructions). | The user is an IFO Admin. | Room records and posters are maintained. |
| IFO-02 | The system shall allow IFO to rotate a room's codes (regenerating its QR token and six-digit code, audit-logged), immediately invalidating prior posters. | A room exists. | New codes are issued; old codes stop resolving. |
| IFO-03 | The system shall allow IFO to stage and import schedule files with validation, reconciliation, and conflict detection, and to add, edit, move, or cancel/archive individual recurring schedules. | A valid staged import or schedule edit request is provided. | Schedules are created or modified; conflicts are refused or reported; affected future sessions remain consistent. |
| IFO-04 | The system shall allow IFO to manage course offerings and sections as schedule entries, create and transition academic terms through Draft/Active/Archived states, and manage academic breaks and holidays that suppress materialization and absence marking. | The user is an IFO Admin. | Schedules, terms, and breaks are maintained without Django-admin access. |
| IFO-05 | The system shall allow IFO to create and cancel ad-hoc room bookings, conflict-checked against reserved sessions and other bookings. | The requested window is specified. | Bookings are created or cancelled; conflicts are prevented. |
| IFO-06 | The system shall allow IFO to assign Checkers and Guards to floors by shift and/or standing posting. | The target users and floors exist. | Assignments are recorded. |
| IFO-07 | The system shall present a polled semantic room-status board grouped by building and floor. Each room panel shall show today's session timeline, Checker verification state, session status, and recurring schedule. A spatial floor-plan map is not required because the system stores no room geometry and must remain usable across 200+ rooms. | The user is an IFO Admin. | Current room and session status is displayed in an operationally sortable board. |
| IFO-08 | The system shall allow IFO to manually release a held room and to resolve room-conflict notifications. | A held room or conflict exists. | The room is released or the conflict is resolved. |
| IFO-09 | The system shall present a dashboard of summary cards (Faculty, Room Occupancy in session-hours, Sessions, Absences) over a selectable range (default the active term) with a faculty-scorecard drill-down. | The user is an IFO Admin. | Summary metrics and drill-downs are displayed. |
| IFO-10 | The system shall produce the Weekly Consolidated Faculty Attendance Report, per department (see Section 4.10). | Attendance data exist for the period. | The report is available and exportable. |
| IFO-11 | The system shall allow IFO to view a selected room's fixed per-term schedule — its recurring classes (faculty, course/section, day-of-week, time, modality) for the active term — together with the room's current and upcoming sessions and any ad-hoc bookings, read-only. The same per-room schedule view is available to Guards (GRD-02) and, scoped to their department(s), to Deans. | A room and active term exist. | The room's per-term schedule is displayed. |
| IFO-12 | The system shall allow IFO to declare and lift campus-wide or building-scoped class suspensions. Covered materialized sessions shall become Cancelled, faculty shall be notified, and reporting shall exclude those sessions from held/absent denominators. | An Active term exists and the user is an IFO Admin. | Covered sessions are cancelled or restored consistently and the action is audited. |
| IFO-13 | The system shall allow IFO to manage buildings, floors, rooms, and a room's in-service/out-of-service state with dependency-aware deletion refusals. | The user is an IFO Admin. | Campus structure is maintained without deleting referenced operational records. |
| IFO-14 | The system shall provide an explicit Draft → Active → Archived academic-term lifecycle with preflight blockers, warnings, typed confirmation, and auditable close/reopen reasons. | The user is an IFO Admin. | Exactly one term is Active and lifecycle changes are atomic and audited. |

**4.7 HR Admin (HR)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| HR-01 | The system shall allow HR to view verified attendance records per faculty and session, including present/absent status, actual times, check-in method, and checker-verification status. | The user is an HR Admin. | Verified attendance is displayed. |
| HR-02 | The system shall allow HR to filter and search by faculty, department, date range, and term. | The user is an HR Admin. | Filtered results are displayed. |
| HR-03 | The system shall allow HR to export detailed, session-level attendance as CSV for external payroll processing. | A result set is selected. | A CSV export is produced. |
| HR-04 | The system shall not implement payroll periods, locks, or finalization. | — | No payroll lifecycle exists in the system. |

**4.8 Guard (GRD)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| GRD-01 | The system shall present a live, read-only room-status monitor for the Guard's assigned floor(s), updated by polling. | The Guard is assigned to the floor(s). | Current floor status is displayed. |
| GRD-02 | The system shall allow a Guard to view the schedule of each room on the assigned floor, including current and upcoming classes. | The Guard is assigned to the floor(s). | Per-room schedules are displayed. |
| GRD-03 | The system shall provide a campus-wide faculty locator: searching a professor by name returns their current location (room/building/floor, course, end time) or "Online — not on campus" or "Not in a class" with the next class, plus today's schedule. | The user is a Guard. | The located faculty member's status is displayed. |
| GRD-04 | The system shall deliver debounced web-push alerts to Guards for floor activity. | The Guard has a push subscription. | Relevant alerts are delivered. |
| GRD-05 | The system shall restrict Guards to read-only access, with no verification, editing, or incident logging. | The user is a Guard. | Write actions are denied. |

**4.9 Dean (DEAN)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| DEAN-01 | The system shall restrict Deans to read-only access scoped to their assigned department(s), as set by a System Admin. | The Dean's department scope is configured. | Access is limited to in-scope data. |
| DEAN-02 | The system shall allow Deans to view department-scoped attendance reporting and per-faculty scorecards. | The user is a Dean. | Department reporting is displayed. |
| DEAN-03 | The system shall allow Deans to view and export the weekly consolidated attendance report for their department(s). | The report exists for the department(s). | The report is viewed or exported. |
| DEAN-04 | The system shall present a Dean dashboard of department-scoped summary cards (Faculty, Sessions, Absences, Attendance percentage) plus a latest-weekly-report card, reusing the reporting aggregates (Section 4.10). | The user is a Dean with a configured department scope. | The department-scoped dashboard is displayed. |

**4.10 Reporting (RPT)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| RPT-01 | The system shall produce a Weekly Consolidated Faculty Attendance Report grouped per department: one row per faculty (classes scheduled, held/present, absent, attendance percentage, checker-verified count) plus itemized absence detail (date, course/section, room, time). | Attendance data exist for the week and department. | The consolidated report is generated. |
| RPT-02 | The system shall make the report available on demand (by week and department/all) and shall auto-generate it weekly, storing it and notifying IFO and the relevant Dean(s). | The reporting period has elapsed (for auto-generation). | The report is available and IFO and the relevant Dean(s) are notified. |
| RPT-03 | The system shall export the report in both CSV and printable PDF, one per department or for all departments. | A report exists. | CSV and PDF exports are produced. |
| RPT-04 | The system shall produce a faculty scorecard (scheduled vs. held, attendance percentage, absences, early-ends, modality breakdown) over a selectable period. | Attendance data exist for the faculty member. | The scorecard is displayed. |
| RPT-05 | The system shall compute report aggregates with pure, independently tested functions and shall degrade gracefully so that a single failed aggregate does not blank the page. | A report is requested. | Available sections render; failed sections show error states. |

**4.11 Notifications (NOTIF)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| NOTIF-01 | The system shall present an in-app notification list (updated by polling) for all roles. | The user is authenticated. | Notifications are listed. |
| NOTIF-02 | The system shall deliver web-push notifications (VAPID) for floor activity (Checker/Guard) and key events (wrong-room change, force handover, room conflict, weekly report ready). | The user has a push subscription. | Relevant push notifications are delivered. |
| NOTIF-03 | The system shall honor per-user notification mute preferences. | The user has set preferences. | Muted notifications are suppressed. |

**4.12 System Admin (SYS)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| SYS-01 | The system shall allow System Admins to provision users (mapping an Entra identity to a User), assign roles and departments, and deactivate users. | The user is a System Admin. | User accounts and roles are maintained. |
| SYS-02 | The system shall allow System Admins to edit system settings, including all configurable policy values. | The user is a System Admin. | Settings are updated. |
| SYS-03 | The system shall allow System Admins to view the audit log of all write events. | The user is a System Admin. | The audit log is displayed. |
| SYS-04 | The system shall allow System Admins to monitor scheduled-job status (last run, success/failure, rows affected). | The user is a System Admin. | Job status is displayed. |

**4.13 Scheduled Jobs (JOB)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| JOB-01 | The system shall materialize sessions daily, N days ahead, from schedules, skipping academic breaks and active class suspensions. | Active schedules and an Active term exist. | Future session rows are created or suppressed by the academic calendar. |
| JOB-02 | The system shall run a frequent status sweep that marks non-excused no-show sessions Absent after grace and raises deduplicated room-conflict flags. It shall never release a room on a timer; rooms are released only by an approved shift to Online or an explicit IFO action. | Sessions and rooms exist. | Session statuses and conflict flags are maintained without inferring physical vacancy from elapsed time. |
| JOB-03 | The system shall generate and store per-department reports weekly and notify IFO. | The reporting week has elapsed. | Reports are stored; IFO is notified. |

**5\. Data Requirements**

The system shall persist the following principal entities in Microsoft SQL Server. Attributes shown are notable, not exhaustive; Django migrations are the authoritative schema definition and relationships are described where relevant.

**Identity and organization**

* **User** — azure\_oid, email, name, role, department (nullable), is\_active, profile\_photo. Each User holds exactly one role; a User may belong to a Department.

* **Department** — name, code.

* **AcademicTerm** — name, start\_date, end\_date, status (Draft/Active/Archived). Exactly one term is Active at a time.

* **AcademicBreak** — term, start\_date, end\_date, reason. Breaks suppress session materialization and absence marking.

* **ClassSuspension** — term, inclusive date range, optional building scope, reason, declaring/lifting actors and timestamps. Active suspensions cancel covered materialized sessions and suppress later materialization/absence marking.

**Spaces**

* **Building** — name, code.

* **Floor** — building, number. A Floor belongs to one Building.

* **Room** — floor, code, name, capacity, qr\_token (opaque, unique), manual\_code (six-digit, unique), code\_rotated\_at, code\_rotated\_by, out\_of\_service. A Room belongs to one Floor.

**Academics**

* **Schedule** — term, course\_code, section, enrolled\_count, faculty, room, day\_of\_week, start\_time, end\_time, modality, status. Created via CSV import; sections are captured as fields (no separate Section entity).

* **Session** — schedule, faculty, room, date, scheduled\_start, scheduled\_end, status (scheduled/active/completed/absent/cancelled), actual\_start, actual\_end, checkin\_method, declared\_modality, modality\_changed\_at, modality\_changed\_by, handover\_from\_session\_id, teams\_link, online\_checker, ended\_early, early\_end\_reason, room\_released\_at, cancelled\_reason. A Session derives from one Schedule.

**Verification and duty**

* **Assignment** — user, role (checker/guard), floors, type (shift/standing), date, start\_time, end\_time, term, status.

* **CheckerValidation** — session, room, checker, action (verified/flag\_identity\_mismatch/flag\_not\_present/confirmed\_absent/confirmed\_empty/verified\_empty), identity\_match, note, scanned\_at, validated\_at, offline\_queued. A Session's \`verified\_by\_checker\` status is derived: true if any verified validation exists.

**Operations**

* **Booking** — room, created\_by, occupant\_name, purpose, start\_datetime, end\_datetime, status.

* **Notification** — user, type, title, body, link, read\_at, created\_at.

* **PushSubscription** — user, endpoint, keys, created\_at.

* **AuditLog** — actor, event\_type, target\_type, target\_id, payload, ip\_address, created\_at. Written on every write event.

* **SystemSetting** — key, value, description. Stores configurable policy values (Section 8).

* **WeeklyReport** — term, week\_start, department, generated\_at, csv\_path, pdf\_path. Report files reside below Django's configured `MEDIA_ROOT` and are downloaded only through authorized views.

* **SharedCacheEntry** — cache\_key, serialized value, expiry. Backs Django's database cache so rate limits and idempotency work across Gunicorn workers.

* **CheckerReplayReceipt** — Checker, client UUID, terminal replay status/reason, created timestamp. Provides durable exactly-once handling when the shared cache is cleared or workers restart.

Personal data shall be limited to presence-level records and the single profile photograph; retention shall follow Section 6.8.

**6\. Non-Functional Requirements**

Quantitative targets marked "(target; to be confirmed in testing)" are provisional and shall be validated and fixed during system testing.

**6.1 Performance**

The system shall refresh live surfaces within the configured poll interval (default approximately 8 seconds). The scan endpoint shall return a resolved outcome within 3 seconds (target; to be confirmed in testing). List and read endpoints shall paginate and shall return within 2 seconds at the 95th percentile under an expected load of 50 concurrent administrative users (target; to be confirmed in testing). Report aggregates shall be computed efficiently and shall not block unrelated page sections.

**6.2 Security**

All production traffic shall use HTTPS (TLS 1.2 or higher). The system shall enforce role and data scoping on the server for every endpoint and authenticate requests with secure Django session cookies after Entra sign-in. CSRF protection shall apply to state-changing requests. The manual-code path shall be rate-limited (default five per minute per user) through a shared database cache. QR tokens and manual codes shall be resolver-only and never client-readable. All domain write events shall be audit-logged. User credentials shall be delegated to Microsoft Entra ID; the system shall not store institutional passwords. A separately controlled Django superuser is retained only as a production break-glass account.

**6.3 Reliability and Availability**

The Checker offline queue shall tolerate connectivity loss and replay on reconnect. Scheduled jobs shall be monitored, with last-run status visible to System Admins. Reporting shall degrade gracefully so that a single failed aggregate does not blank a page. The system should be available throughout institutional operating hours (target; to be confirmed).

**6.4 Usability**

A faculty check-in shall require a single action (a QR scan or six-digit code) and should complete within 10 seconds end to end (target; to be confirmed). Administrative roles should be operable without specialized technical training.

**6.5 Accessibility**

The interface shall meet WCAG 2.1 AA contrast, keyboard-navigation, and visible-focus requirements.

**6.6 Maintainability**

The interface shall be delivered as server-rendered Django templates with progressive enhancement (htmx for partial updates and Franken UI for shadcn-compatible styling). Client-side JavaScript shall remain limited to focused modules such as QR scanning, offline replay, web-push subscription, board interaction, and modality forms. The backend shall be layered into models, pure decision functions, transactional services, and thin views; resolver and reporting aggregates shall remain independently testable, with request tests for HTTP boundaries.

**6.7 Portability and Deployment**

The system shall be deployed as a single Django application that serves the server-rendered interface, limited JSON endpoints, and vendored/manifested static assets; there is no separate Node.js frontend service to build or host. It shall run on one AWS EC2 instance over HTTPS behind Nginx and Gunicorn, with Microsoft SQL Server Express on private-subnet AWS RDS and EBS-backed filesystem media. TLS shall terminate at Nginx. Scheduled jobs shall run through APScheduler in exactly one lock-protected systemd process, separate from web workers, with an independent heartbeat watchdog. Shared database cache state shall keep rate limits and idempotency correct across Gunicorn workers.

**6.8 Privacy and Compliance**

The system shall comply with the Data Privacy Act of 2012 and shall apply data minimization, storing only presence-level data plus a single profile photograph used solely for Checker identity confirmation, with no video feeds, biometric processing, or continuous location tracking. Access shall be governed by RBAC. The faculty live-location exposure available through the Guard locator (GRD-03) is a noted, accepted consideration for the academic context and shall be limited to the Guard role. Personal data shall be retained only as long as necessary and then securely disposed of.

**7\. Out of Scope (Future Enhancements)**

The following are not implemented in the current scope and are recorded as candidate future enhancements: disputes and appeals workflow; faculty help requests (assists); guard incident log; payroll lifecycle (periods, locks, finalize); email notifications; substitute-teacher flow; advance modality-declaration page; coverage analytics; an interactive room booking and availability calendar grid (a per-room week or month calendar combining recurring sessions and ad-hoc bookings for direct reservation management on the calendar surface — distinct from the read-only per-room schedule view in IFO-11, which is in scope); ad-hoc booking directly from a scan; faculty-initiated room requests; and dark-mode refinement.

**8\. Policy Assumptions Register**

The official MMCM IRR / attendance policy is not currently available. Every value below is configurable in System Settings and is recorded as an assumption to be validated before any real-world use.

| Policy / value | Default | Status / source |
| :---- | :---- | :---- |
| Attendance grace (grace\_minutes) | 15 minutes | Assumption — cited in the expert FGD as MMCM practice; no written source on hand |
| Attendance model \= Present/Absent only (no tardy category) | — | Assumption — the IRR may define a tardy category; must verify |
| Room hold before release (room\_hold\_minutes) | 30 minutes (deprecated, no runtime effect) | Retained for migration/configuration compatibility; JOB-02 does not infer vacancy or auto-release rooms |
| Early check-out threshold | 15 minutes before end | Assumption — carried from prior practice |
| Manual-code rate limit | 5 per minute per user | Operational (technical), not policy |
| Session materialization horizon | e.g., 14 days | Operational, not policy |
| Modality definitions (F2F/Blended/Online; Blended \= instructor on site) | per FGD | Confirmed (expert FGD) |
| Weekly per-department consolidated attendance report | — | Confirmed (IFO subject-matter expert) |
| Reporting week definition (Mon–Sun) | Mon–Sun | Assumption — confirm the institutional week |
| Modality-shift lead time (modality_shift_lead_days) | 2 days | Operational - whole calendar days, Asia/Manila |

Before any production use, all assumption and placeholder values shall be validated against the official MMCM IRR / attendance policy and the institutional report format.

**9\. Open Items**

* Obtain the MMCM IRR / attendance policy to convert the Section 8 assumptions to confirmed values.

* Confirm the institutional reporting-week boundary.

* Confirm the exact department report column template (interim columns are used until provided).

* Confirm the provisional performance targets in Section 6 during system testing.

**10\. Implementation Conformance and Traceability**

**10.1 Reconciled Architecture Decisions**

Version 1.3 records the implemented repository and approved deployment design rather than preserving superseded implementation assumptions. Live production cutover remains subject to the external gate in Section 10.4.

| Earlier specification | Version 1.3 conformance decision | Implementation evidence |
| :---- | :---- | :---- |
| MySQL 8.0 / `mysqlclient` | Replaced by Microsoft SQL Server only. Local development and tests use LocalDB/Express; production targets RDS SQL Server Express through ODBC Driver 18. | `config/settings.py`, `requirements.txt`, `campus/migrations/0002_cs_collation_tokens.py` |
| Application-issued JWT | Replaced by Django server-side sessions after the Entra Authorization Code + PKCE exchange. This matches the server-rendered architecture and preserves CSRF protection. | `config/settings.py`, `accounts/backends.py`, `accounts/pipeline.py` |
| S3 object storage | Replaced for current scope by Django filesystem storage. Production media lives on persistent EBS-backed storage and has a separate backup/restore requirement. | `config/settings.py`, `ops/reports.py`, `deploy/README.md` |
| Timer-based room release in JOB-02 | Removed. Elapsed time does not prove that a room is physically vacant. Only an approved Online shift or explicit IFO release stamps `room_released_at`. | `scheduling/jobs.py`, `ops/occupancy.py`, `scheduling/services.py`, `web/ifo.py` |
| CHK-02 described physical room scans only | Extended with an assigned-online-session queue. The Checker opens the public Teams link and Verify activates the Online session; the same Flag actions remain available. | `web/checker.py`, `templates/checker/online_open.html`, `verification/tests.py` |
| IFO-07 spatial live map | Implemented as a polled semantic board grouped by building/floor, with attention sorting and a room panel containing today's timeline and recurring schedule. No geometry is stored. | `web/ifo.py`, `web/room_state.py`, `templates/ifo/_board.html` |
| MOD-01 arbitrary recurring date range | Implemented as either one selected occurrence or the next 1–16 weekly occurrences after the lead-time cutoff. The persisted request still records the exact inclusive window. | `web/faculty.py`, `scheduling/services.py`, `templates/faculty/_modality_form.html` |
| “shadcn” and “Franken UI” treated as alternatives | Reconciled as shadcn-via-Franken UI: Franken UI carries the shadcn design language and tokens into server-rendered, non-React HTML. Runtime assets are vendored and require no CDN. | `static/vendor/franken-ui/2.1.2/`, `static/css/tokens.css`, `templates/base.html` |

**10.2 Restored Requirement Traceability**

| Requirement | Conformance | User-facing surface / evidence |
| :---- | :---- | :---- |
| IFO-03 schedule import | Built. IFO stages a file, reviews validation/reconciliation, and explicitly applies it; private staged bytes are stored below `MEDIA_ROOT`. | `/ifo/import`; `web/ifo.py`; `ops/import_staging.py` |
| IFO-03 individual schedule CRUD | Built. IFO can add, edit/move, and cancel/archive a recurring class. Conflict checks cover materialized and not-yet-materialized occurrences, and future Session rows are updated atomically. | `/ifo/schedules/new`; `/ifo/schedules/<id>/edit`; `/ifo/schedules/<id>/cancel`; `scheduling/schedule_ops.py` |
| IFO-04 offerings, terms, breaks | Built without a separate CourseOffering or Section table: course/section fields belong to Schedule. IFO manages Draft/Active/Archived terms and academic breaks/holidays directly. | `/ifo/terms`; `/ifo/breaks`; `web/ifo_terms.py`; `web/ifo.py` |
| SYS-01 user provisioning | Built as a trusted-operator Django-admin workflow plus `link_entra`. System Admins create pre-provisioned users, map Entra identity, assign role/department, and deactivate access. A second custom user-management UI is out of scope because it would duplicate Django admin without changing authority or capability. | `/admin/accounts/user/`; `accounts/admin.py`; `accounts/management/commands/link_entra.py` |
| SYS-02 system settings | Built through Django admin. Every supported policy key is editable in `SystemSetting` and read through the single `get_policy()` path. A duplicate custom settings editor is out of scope. | `/admin/ops/systemsetting/`; `ops/admin.py`; `ops/policy.py` |
| SYS-03 audit log | Built as a read-only Django-admin record browser. Add/delete operations are disabled, while filtering by event type remains available. | `/admin/ops/auditlog/`; `ops/admin.py` |

**10.3 Operational-Trust Additions**

The completed system adds requirements that were absent from versions 1.0–1.2:

* **Suspensions and holidays (IFO-12):** campus-wide or building-scoped suspension declarations cancel covered sessions, notify faculty, and prevent false Absent records. Academic breaks also suppress both materialization and the no-show sweep.
* **Campus management (IFO-13):** IFO manages buildings, floors, rooms, code rotation, and service state through role-scoped screens with dependency-aware delete refusals.
* **Term lifecycle (IFO-14):** terms use Draft, Active, and Archived states with one Active term, preflight blockers/warnings, typed confirmation, audit coupling, and term ownership on reports and operational queries.
* **Production correctness:** the shared SQL Server cache and durable Checker replay receipts preserve rate limits and exactly-once replay across multiple Gunicorn workers and restarts.

The authoritative executable evidence is the Django model/migration history and automated test suite. `docs/db_schema.sql` is retained as a 2026-07-07 schema snapshot and is not authoritative for later migrations.

**10.4 External Production Gate**

The code and deployment package are complete, but this SRS does not claim that a live institutional environment has been provisioned. Production acceptance still requires the institutional Entra application registration and user UAT, AWS EC2/RDS/network/DNS/TLS provisioning, an RDS-and-media restore rehearsal, and the production smoke checklist in `deploy/README.md`.

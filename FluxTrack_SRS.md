  
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
| Version | 1.2 |
| Standard basis | IEEE 830 / ISO/IEC/IEEE 29148 |

**Revision History**

| Version | Date | Author | Description |
| :---- | :---- | :---- | :---- |
| 1.0 | 2026-06-25 | Research Team (Mayo, Ong, Sabuero) | Initial specification. |
| 1.1 | 2026-07-02 | Research Team (Mayo, Ong, Sabuero) | Frontend stack changed from Next.js/React SPA to server-rendered Django templates + htmx + Franken UI (Tailwind CSS). PWA, mobile-first, QR, and offline capabilities unchanged. Affects §2.1, §2.4, §3.3, §6.6, §6.7. |
| 1.2 | 2026-07-03 | Research Team (Mayo, Ong, Sabuero) | Modality-shift approval workflow (MOD-01..06); DEAN-04 added; FAC-07 superseded by MOD approval; CHK-03 amended (Confirm absent removed, actions apply to online sessions); CHK-06 removed; RPT-02 notifies Deans; modality_shift_lead_days added to the policy register. |

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
| AWS | Amazon Web Services (RDS, S3, EC2) |
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
| RDS | AWS Relational Database Service (hosting MySQL 8.0) |
| Room hold | Configurable window a room stays reserved before it may be released |
| S3 | AWS Simple Storage Service (object storage) |
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

Section 2 gives an overall description of the product, its users, environment, and constraints. Section 3 specifies external interfaces. Section 4 specifies functional requirements by feature area. Section 5 specifies data requirements. Section 6 specifies non-functional requirements. Section 7 lists out-of-scope items, Section 8 records policy assumptions, and Section 9 lists open items.

Functional requirements are stated using "shall." Each requirement carries a stable identifier of the form \`AREA-NN\` (for example, \`SCAN-01\`). Preconditions state what must hold before the requirement applies; postconditions state the resulting system state. Where a precondition or postcondition does not meaningfully apply, it is shown as "—." Configurable policy values are referenced by name (for example, the grace window) and enumerated in Section 8\.

**2\. Overall Description**

**2.1 Product Perspective**

FluxTrack is a new, self-contained system. It is a client–server web application in which a Django (Django REST Framework) backend is the system of record — it owns the data, the business rules, and authorization — and renders the interface for all user roles server-side using Django templates, progressively enhanced with htmx (for partial updates and live-surface polling) and the Franken UI component library (Tailwind CSS) for a consistent, accessible design system. A small, isolated amount of vanilla JavaScript provides the two genuinely interactive client-side capabilities: the camera QR scanner and the Checker offline scan queue. No separate Node.js runtime or client-side single-page-application framework is required. The backend is layered into models, serializers, services (business rules), and views; the scan resolver and reporting aggregates are implemented as pure, independently testable functions. Identity is delegated to Microsoft Entra ID; persistence uses MySQL 8.0 on AWS RDS; binary objects (profile photos, generated reports) reside in AWS S3; the application runs on AWS EC2. Live surfaces use periodic polling rather than persistent connections.

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

* **Backend:** Django with Django REST Framework (Python).

* **Frontend:** Server-rendered Django templates enhanced with htmx and Franken UI (Tailwind CSS); PWA-enabled via a service worker; camera QR scanning and the Checker offline queue implemented in vanilla JavaScript. Runs on modern mobile and desktop browsers. No Node.js runtime is required to serve the interface; Tailwind CSS is compiled with its standalone CLI as a build step.

* **Database:** MySQL 8.0 on AWS RDS, accessed via \`mysqlclient\`.

* **Object storage:** AWS S3 (profile photos and generated report files).

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

The system shall provide a mobile-first interface for Faculty and Checker that is camera-first and reachable one-handed, and a desktop-first responsive interface for IFO Admin, HR Admin, Guard, Dean, and System Admin. The interface shall meet WCAG 2.1 AA contrast, keyboard-navigation, and visible-focus requirements. Principal surfaces include: the faculty day/week and check-in screens; the checker floor view and room-state screen; the IFO live map, live calendar, dashboard, room and schedule management, and reporting; the guard floor monitor and faculty locator; the dean department oversight; and the system-admin user, settings, audit, and job-monitoring screens.

**3.2 Hardware Interfaces**

The system shall use the device camera of a smartphone to scan room QR codes; no other specialized hardware is required of users. Room QR codes and six-digit codes shall be distributed as printed posters generated by the system.

**3.3 Software Interfaces**

* **Microsoft Entra ID (identity provider):** The client shall perform the OAuth 2.0 Authorization Code flow with PKCE to obtain an ID token; the backend shall verify the token against Microsoft's JWKS endpoint.

* **AWS RDS (MySQL 8.0):** The backend shall persist all relational data through \`mysqlclient\`.

* **AWS S3:** The backend shall store and retrieve profile photographs and generated report files (CSV and PDF).

* **AWS EC2:** The application shall run on EC2 compute instances.

* **Microsoft Teams:** Online sessions shall reference an MS Teams meeting link supplied by the faculty member.

* **Web Push (VAPID):** The system shall deliver push notifications to subscribed clients using the VAPID scheme.

* **Browser platform services:** The PWA shall use a service worker for installability and push, and IndexedDB for the Checker offline scan queue. The interface shall be delivered as server-rendered HTML enhanced with htmx for partial updates and polling and styled with Franken UI; camera QR decoding shall use a client-side QR library (for example, html5-qrcode).

**3.4 Communications Interfaces**

All client–server communication shall occur over HTTPS (TLS 1.2 or higher). Application data shall be exchanged as JSON over a REST API. Live surfaces shall obtain updates by polling the API at a configurable interval (default approximately 8 seconds). Push notifications shall be delivered using the web-push protocol.

**4\. Functional Requirements**

**4.1 Authentication and Identity (AUTH)**

This area governs sign-in, identity mapping, authorization, and account deactivation.

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| AUTH-01 | The system shall authenticate users via Microsoft Entra ID single sign-on, with the client performing the Authorization Code flow with PKCE and passing the resulting ID token to the backend. | The user holds a valid institutional Microsoft account. | An ID token is presented to the backend. |
| AUTH-02 | The system shall verify the Microsoft ID token against Microsoft's JWKS, map the verified identity to a provisioned User, and issue its own JWT for subsequent API calls. | A valid ID token has been received. | A backend JWT is issued and bound to the session. |
| AUTH-03 | The system shall prevent any identity without a provisioned User record from proceeding past sign-in. | The identity has been authenticated by Entra ID. | Unprovisioned identities receive no application access. |
| AUTH-04 | The system shall enforce role and data scope on the server for every request. | The request carries a valid backend JWT. | Out-of-scope data and actions are denied. |
| AUTH-05 | The system shall, upon user deactivation, block further API access and invalidate that user's issued tokens. | A System Admin deactivates the user. | The user's tokens are invalidated; access is blocked. |

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
| MOD-01 | The system shall allow a faculty member to submit a modality-shift request (F2F/Blended to/from Online) covering a single session or a recurring, faculty-chosen date range, submitted at least `modality_shift_lead_days` (default 2 whole calendar days, Asia/Manila) before the earliest affected session date; a too-late request is refused at submission. | The user is authenticated as Faculty; the affected session(s) exist within the requested window. | A pending request is recorded, or the request is refused as too late. |
| MOD-02 | The system shall route each request to the requesting faculty member's department Dean, who shall approve or reject it with a reason; there is no dispute workflow. | A pending request exists and the faculty member has an assigned department Dean. | The Dean approves or rejects the request, recording a reason. |
| MOD-03 | The system shall, on approval of a shift to Online, set the affected in-window session(s) to Online and release the room immediately (`room_released_at` stamped), not on a hold timer; Online sessions later materialized within the window are born released. | The Dean approves a to-Online request. | The affected sessions are Online and their rooms are released. |
| MOD-04 | The system shall, on approval of a shift to F2F/Blended, auto-assign a free room in the same building at approval time; if no room is free, the approval fails with a clear reason and no session is changed (no silent partial apply). | The Dean approves a to-F2F/Blended request. | A room is assigned to the affected session(s), or the approval fails cleanly with a stated reason. |
| MOD-05 | The system shall, on approval, notify IFO informationally (not a gate) via the single notification write path, and shall allow the requesting faculty member to withdraw a request while it is still pending. | A request is approved, or a pending request is withdrawn by its requester. | IFO is notified on approval; a pending request may be withdrawn by its owner. |
| MOD-06 | The system shall make this Dean-approved modality-shift workflow the sole path for changing a session's modality, replacing the FAC-07 self-declare; same-day changes have no formal path and fall back to existing scan-time behavior. | A modality change is required for one or more sessions. | The change occurs only through an approved modality-shift request; the FAC-07 self-declare entry point is retired. |

**4.5 Checker (CHK)**

| ID | Requirement | Preconditions | Postconditions |
| :---- | :---- | :---- | :---- |
| CHK-01 | The system shall grant verification powers only while a Checker is on duty (active shift or standing posting) on an assigned floor. | The Checker has an active assignment on the floor. | Verification actions are permitted on that floor. |
| CHK-02 | The system shall return, on a Checker room scan, the room's current state together with the faculty member's profile photo for identity matching. | The Checker scans a room on the assigned floor. | The room state and faculty photo are presented. |
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
| IFO-03 | The system shall allow IFO to import schedules via CSV with validation and conflict detection, and to add, edit, move, or archive individual schedules. | A valid CSV or edit request is provided. | Schedules are created or modified; conflicts are reported. |
| IFO-04 | The system shall allow IFO to manage course offerings and sections (as schedule entries), academic terms (including setting the active term), and academic breaks (skipped by materialization). | The user is an IFO Admin. | Offerings, terms, and breaks are maintained. |
| IFO-05 | The system shall allow IFO to create and cancel ad-hoc room bookings, conflict-checked against reserved sessions and other bookings. | The requested window is specified. | Bookings are created or cancelled; conflicts are prevented. |
| IFO-06 | The system shall allow IFO to assign Checkers and Guards to floors by shift and/or standing posting. | The target users and floors exist. | Assignments are recorded. |
| IFO-07 | The system shall present a live map of room status and a live calendar of today's sessions (with check-in-method icons, verified badges, and status), updated by polling. | The user is an IFO Admin. | Current room and session status is displayed. |
| IFO-08 | The system shall allow IFO to manually release a held room and to resolve room-conflict notifications. | A held room or conflict exists. | The room is released or the conflict is resolved. |
| IFO-09 | The system shall present a dashboard of summary cards (Faculty, Room Occupancy in session-hours, Sessions, Absences) over a selectable range (default the active term) with a faculty-scorecard drill-down. | The user is an IFO Admin. | Summary metrics and drill-downs are displayed. |
| IFO-10 | The system shall produce the Weekly Consolidated Faculty Attendance Report, per department (see Section 4.10). | Attendance data exist for the period. | The report is available and exportable. |
| IFO-11 | The system shall allow IFO to view a selected room's fixed per-term schedule — its recurring classes (faculty, course/section, day-of-week, time, modality) for the active term — together with the room's current and upcoming sessions and any ad-hoc bookings, read-only. The same per-room schedule view is available to Guards (GRD-02) and, scoped to their department(s), to Deans. | A room and active term exist. | The room's per-term schedule is displayed. |

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
| JOB-01 | The system shall materialize sessions daily, N days ahead, from schedules, skipping academic breaks. | Active schedules and term exist. | Future session rows are created. |
| JOB-02 | The system shall run a frequent status sweep that marks no-show sessions Absent after grace, releases rooms after the room-hold window (unless a checker-present override applies), and raises room-conflict flags. | Sessions and rooms exist. | Session and room statuses are maintained. |
| JOB-03 | The system shall generate and store per-department reports weekly and notify IFO. | The reporting week has elapsed. | Reports are stored; IFO is notified. |

**5\. Data Requirements**

The system shall persist the following principal entities in MySQL 8.0. Attributes shown are notable, not exhaustive; relationships are described where relevant.

**Identity and organization**

* **User** — azure\_oid, email, name, role, department (nullable), is\_active, profile\_photo. Each User holds exactly one role; a User may belong to a Department.

* **Department** — name, code.

* **AcademicTerm** — name, start\_date, end\_date, is\_active. Exactly one term is active at a time.

* **AcademicBreak** — term, start\_date, end\_date, reason. Breaks suppress session materialization.

**Spaces**

* **Building** — name, code.

* **Floor** — building, number. A Floor belongs to one Building.

* **Room** — floor, code, name, capacity, qr\_token (opaque, unique), manual\_code (six-digit, unique), code\_rotated\_at, code\_rotated\_by. A Room belongs to one Floor.

**Academics**

* **Schedule** — term, course\_code, section, enrolled\_count, faculty, room, day\_of\_week, start\_time, end\_time, modality, status. Created via CSV import; sections are captured as fields (no separate Section entity).

* **Session** — schedule, faculty, room, date, scheduled\_start, scheduled\_end, status (scheduled/active/completed/absent), actual\_start, actual\_end, checkin\_method (qr\_scan/manual\_code/online\_manual/force\_handover), declared\_modality, modality\_changed\_at, modality\_changed\_by, handover\_from\_session\_id, teams\_link, ended\_early, early\_end\_reason, room\_released\_at. A Session derives from one Schedule.

**Verification and duty**

* **Assignment** — user, role (checker/guard), floors, type (shift/standing), date, start\_time, end\_time, term, status.

* **CheckerValidation** — session, room, checker, action (verified/flag\_identity\_mismatch/flag\_not\_present/confirmed\_absent/confirmed\_empty/verified\_empty), identity\_match, note, scanned\_at, validated\_at, offline\_queued. A Session's \`verified\_by\_checker\` status is derived: true if any verified validation exists.

**Operations**

* **Booking** — room, created\_by, occupant\_name, purpose, start\_datetime, end\_datetime, status.

* **Notification** — user, type, title, body, link, read\_at, created\_at.

* **PushSubscription** — user, endpoint, keys, created\_at.

* **AuditLog** — actor, event\_type, target\_type, target\_id, payload, ip\_address, created\_at. Written on every write event.

* **SystemSetting** — key, value, description. Stores configurable policy values (Section 8).

* **WeeklyReport** — week\_start, department, generated\_at, csv\_path, pdf\_path. Report files reside in S3.

Personal data shall be limited to presence-level records and the single profile photograph; retention shall follow Section 6.8.

**6\. Non-Functional Requirements**

Quantitative targets marked "(target; to be confirmed in testing)" are provisional and shall be validated and fixed during system testing.

**6.1 Performance**

The system shall refresh live surfaces within the configured poll interval (default approximately 8 seconds). The scan endpoint shall return a resolved outcome within 3 seconds (target; to be confirmed in testing). List and read endpoints shall paginate and shall return within 2 seconds at the 95th percentile under an expected load of 50 concurrent administrative users (target; to be confirmed in testing). Report aggregates shall be computed efficiently and shall not block unrelated page sections.

**6.2 Security**

All traffic shall use HTTPS (TLS 1.2 or higher). The system shall enforce role and data scoping on the server for every endpoint and shall authenticate API calls with a backend-issued JWT. The manual-code path shall be rate-limited (default five per minute per user). QR tokens and manual codes shall be resolver-only and never client-readable. All write events shall be audit-logged. User credentials shall be delegated to Microsoft Entra ID; the system shall not store passwords.

**6.3 Reliability and Availability**

The Checker offline queue shall tolerate connectivity loss and replay on reconnect. Scheduled jobs shall be monitored, with last-run status visible to System Admins. Reporting shall degrade gracefully so that a single failed aggregate does not blank a page. The system should be available throughout institutional operating hours (target; to be confirmed).

**6.4 Usability**

A faculty check-in shall require a single action (a QR scan or six-digit code) and should complete within 10 seconds end to end (target; to be confirmed). Administrative roles should be operable without specialized technical training.

**6.5 Accessibility**

The interface shall meet WCAG 2.1 AA contrast, keyboard-navigation, and visible-focus requirements.

**6.6 Maintainability**

The interface shall be delivered as server-rendered Django templates with progressive enhancement (htmx for partial updates, Franken UI for styling), keeping client-side JavaScript limited to two isolated, independently testable modules: the QR scanner and the Checker offline queue. The backend shall be layered (models, serializers, services, views), with the scan resolver and reporting aggregates implemented as pure functions covered by unit tests, and with API tests per endpoint.

**6.7 Portability and Deployment**

The system shall be deployed as a single Django application that serves the server-rendered interface, the REST API, and compiled static assets — there is no separate Node.js frontend service to build or host. It shall run on AWS EC2 over HTTPS, with MySQL 8.0 on AWS RDS and AWS S3 for object storage. TLS shall be terminated either at an AWS load balancer (managed certificate) or on the instance (for example, Let's Encrypt). Scheduled jobs shall be executed by APScheduler in a single dedicated scheduler process, separate from the web workers, to prevent duplicate job execution.

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
| Room hold before release (room\_hold\_minutes) | 30 minutes (≥ grace) | Placeholder — operational estimate, no policy source |
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
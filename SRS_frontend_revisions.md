# FluxTrack SRS — Frontend Stack Revision (Next.js/React → Django templates + htmx + Franken UI)

**Rationale:** Move the interface from a separate Next.js/React single-page application to
server-rendered Django templates, progressively enhanced with **htmx** (partial updates +
polling) and the **Franken UI** component library (Tailwind CSS, shadcn-style design system).
This removes the second runtime/build pipeline (no Node.js to host), collapses the system to a
single Django deployable, and keeps the team on one language. All PWA capabilities in the
original SRS are retained: installable service worker, web-push, camera QR scanning, and the
Checker offline queue (IndexedDB). Validated by the working proof-of-concept in `poc/`
(SCAN-07 QR decode + resolver, CHK-08 offline queue replay, htmx polling, Franken UI modal +
datepicker, zero console errors).

**Suggested revision-history entry:** `1.1 | <date> | Research Team | Frontend stack changed
from Next.js/React SPA to server-rendered Django templates + htmx + Franken UI; PWA, QR, and
offline capabilities unchanged.`

---

## §2.1 Product Perspective

**Before:**
> …and a Next.js client renders the interface for all user roles. The backend is layered into
> models, serializers, services (business rules), and views; the scan resolver and reporting
> aggregates are implemented as pure, independently testable functions.

**After:**
> …and renders the interface for all user roles **server-side using Django templates,
> progressively enhanced with htmx (for partial updates and live-surface polling) and the
> Franken UI component library (Tailwind CSS) for a consistent, accessible design system**. A
> small, isolated amount of vanilla JavaScript provides the two genuinely interactive
> client-side capabilities: the camera QR scanner and the Checker offline scan queue. **No
> separate Node.js runtime or client-side single-page-application framework is required.** The
> backend is layered into models, serializers, services (business rules), and views; the scan
> resolver and reporting aggregates are implemented as pure, independently testable functions.

---

## §2.4 Operating Environment

**Before:**
> - **Frontend:** Next.js (App Router), React, PWA-enabled; modern mobile and desktop browsers.

**After:**
> - **Frontend:** Server-rendered **Django templates enhanced with htmx and Franken UI
>   (Tailwind CSS)**; PWA-enabled via a service worker; camera QR scanning and the offline
>   queue implemented in vanilla JavaScript. Runs on modern mobile and desktop browsers. **No
>   Node.js runtime is required to serve the interface**; Tailwind CSS is compiled with its
>   standalone CLI as a build step.

---

## §3.1 User Interfaces  — *no framework change required*

This section describes the interface by device, role, and WCAG target, and does not name the
implementation framework. It stays as written. (The framework detail lives in §2.1, §2.4, and
§3.3.)

## §3.3 Software Interfaces — *amend the browser-services bullet*

**Before:**
> - **Browser platform services:** The PWA shall use a service worker for installability and
>   push, and IndexedDB for the Checker offline scan queue.

**After:**
> - **Browser platform services:** The PWA shall use a service worker for installability and
>   push, and IndexedDB for the Checker offline scan queue. The interface shall be delivered as
>   server-rendered HTML enhanced with **htmx** for partial updates and polling and styled with
>   **Franken UI**; camera QR decoding shall use a client-side QR library (e.g. html5-qrcode).

---

## §6.6 Maintainability

**Before:**
> The backend shall be layered (models, serializers, services, views), with the scan resolver
> and reporting aggregates implemented as pure functions covered by unit tests, and with API
> tests per endpoint.

**After:**
> The interface shall be delivered as **server-rendered Django templates with progressive
> enhancement** (htmx for partial updates, Franken UI for styling), keeping client-side
> JavaScript limited to two isolated, independently testable modules: the QR scanner and the
> Checker offline queue. The backend shall be layered (models, serializers, services, views),
> with the scan resolver and reporting aggregates implemented as pure functions covered by unit
> tests, and with API tests per endpoint.

---

## §6.7 Portability and Deployment

**Before:**
> The system shall run on AWS EC2 with HTTPS, MySQL 8.0 on AWS RDS, and AWS S3 for object
> storage, with scheduled jobs executed by APScheduler.

**After:**
> The system shall be deployed as a **single Django application** that serves the
> server-rendered interface, the REST API, and compiled static assets — **there is no separate
> Node.js frontend service to build or host**. It shall run on AWS EC2 over HTTPS, with MySQL
> 8.0 on AWS RDS and AWS S3 for object storage. TLS shall be terminated either at an AWS load
> balancer (managed certificate) or on the instance (e.g. Let's Encrypt). Scheduled jobs shall
> be executed by **APScheduler in a single dedicated scheduler process, separate from the web
> workers, to prevent duplicate job execution**.

---

## Sections that do NOT change

- **§1.2 Scope** — already says "Progressive Web Application (PWA) backed by a Django service"
  (no framework named). Unchanged.
- **§2.2 Product Functions, §2.3 User Classes** — unaffected.
- **§2.5 Constraints** — mobile-first/desktop-first, WCAG 2.1 AA, server-side scoping, and
  polling for live surfaces all still hold. Unchanged.
- **§3.4 Communications** — HTTPS + JSON REST + polling + web-push all still hold; htmx polls
  the same REST/partial endpoints. Unchanged.
- **§4 Functional Requirements** — all IDs (AUTH, SCAN, FAC, CHK, …) are implementation-agnostic
  and unchanged. SCAN-07 (QR deep link) and CHK-08 (offline queue) are validated by `poc/`.
- **§6.5 Accessibility** — WCAG 2.1 AA target unchanged (Franken UI ships accessible components).

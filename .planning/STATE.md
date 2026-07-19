---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: "**Goal**: Faculty can request a lead-time-gated modality shift that a Dean approves, with rooms auto-released or auto-assigned, and the SRS brought back in sync with reality."
current_phase: 07
current_phase_name: Remaining Operational Surfaces
status: complete
stopped_at: n/a — phase 07 executed end-to-end 2026-07-19
last_updated: "2026-07-19T08:46:09.019Z"
last_activity: 2026-07-19
last_activity_desc: Phase 07 executed end-to-end
progress:
  total_phases: 11
  completed_phases: 9
  total_plans: 59
  completed_plans: 58
  percent: 82
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-02)

**Core value:** A faculty member checks in with one action, and the resulting attendance record is trustworthy — presence physically verified, lateness captured, ghost bookings detected.
**Current focus:** Phase 06 — Reporting Engine & Reporting Surfaces

## Current Position

Phase: 07 (Remaining Operational Surfaces) — ALL PLANS COMPLETE (12/12)
Next: Phase 08 (Auth Cutover & AWS Deployment). Two inserted items queued first:
Phase 06.1 room utilization / IFO-09, and the Phase 07 follow-ups below.
Status: Phase 07 complete — suite 790 tests, 3 pre-existing failures, 0 errors
Last activity: 2026-07-19 — Phase 07 executed end-to-end

**Suite baseline moved 515 -> 790 tests across this phase; the failure set never
changed.** The only failures are the 3 long-standing dev-login/home-redirect
ones (`DevLoginCoexistTests`, `DevLoginCuratedDemoTests`,
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`), which predate
Phase 07 and remain out of scope.

## Performance Metrics

**Velocity:**

- Total plans completed: 23
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 02 | 5 | - | - |
| 03 | 6 | - | - |
| 04 | 8 | - | - |
| 04.2 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 20 | 3 tasks | 3 files |
| Phase 01 P02 | 3 | 2 tasks | 2 files |
| Phase 01 P03 | 15 | 2 tasks | 3 files |
| Phase 02 P01 | 2 | 2 tasks | 2 files |
| Phase 02 P02 | 2 | 3 tasks tasks | 4 files files |
| Phase 02 P04 | 2 | 2 tasks | 2 files |
| Phase 02 P03 | 4 | 3 tasks | 5 files |
| Phase 02 P05 | 6 | 3 tasks | 8 files |
| Phase 03 P01 | 25m | 2 tasks | 7 files |
| Phase 03 P02 | ~6m | 3 tasks | 6 files |
| Phase 03 P03 | ~14m | 3 tasks | 8 files |
| Phase 03 P04 | ~9m | 2 tasks | 5 files |
| Phase 03 P05 | ~14m | 3 tasks | 7 files |
| Phase 03 P06 | ~5m | 3 tasks | 4 files |
| Phase 03.1 P01 | ~3m | 2 tasks | 4 files |
| Phase 03.1 P02 | 2 | 2 tasks | 2 files |
| Phase 03.1 P03 | ~6m | 2 tasks | 3 files |
| Phase 03.1 P04 | ~14m | 2 tasks | 2 files |
| Phase 04 P01 | 20 | 3 tasks | 5 files |
| Phase 04 P02 | ~6m | 4 tasks | 5 files |
| Phase 04 P03 | 35m | 3 tasks | 2 files |
| Phase 04 P04 | 30 min | 3 tasks | 2 files |
| Phase 04 P05 | 20min | 3 tasks | 2 files |
| Phase 04 P06 | 4min | 2 tasks | 2 files |
| Phase 04 P07 | 35min | 3 tasks | 6 files |
| Phase 04 P08 | 30min | 3 tasks | 5 files |
| Phase 04.1 P01 | 14min | 3 tasks | 3 files |
| Phase 04.1 P02 | 30min | 2 tasks | 3 files |
| Phase 04.1 P03 | 40min | 3 tasks | 3 files |
| Phase 04.1 P04 | 35min | 4 tasks | 3 files |
| Phase 04.2 P01 | 20min | 3 tasks tasks | 5 files files |
| Phase 04.2 P02 | 15min | 2 tasks | 2 files |
| Phase 04.2 P03 | 15min | 2 tasks | 2 files |
| Phase 04.2 P04 | 15min | 2 tasks | 2 files |
| Phase 05 P01 | 10min | 3 tasks | 4 files |
| Phase 05 P02 | 3min | 2 tasks tasks | 5 files files |
| Phase 05 P03 | 14min | 3 tasks | 4 files |
| Phase 05 P04 | 7min | 3 tasks | 10 files |
| Phase 06 P01 | 35min | 2 tasks | 3 files |
| Phase 06 P02 | 2min | 2 tasks | 1 file |
| Phase 06 P04 | ~20min | 3 tasks | 8 files |
| Phase 06 P05 | 18min | 2 tasks | 4 files |
| Phase 06 P06 | ~20min | 3 tasks | 6 files |
| Phase 06 P07 | ~20min | 3 tasks | 6 files |
| Phase 06.1 P01 | 40m | 3 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: notify() write path (NOTIF-00) pulled forward into Phase 2 (correctness foundations) — it is a prerequisite for JOB-02 conflict flags AND modality approval notices; only NOTIF-01/02/03 read+push stay in Phase 5.
- [Roadmap]: JOB-02's Absent rule and the scan resolver's Absent rule must share ONE extracted predicate (Phase 2) — highest-risk coupling in the milestone.
- [Roadmap]: IFO-06 floor assignments land at the start of Phase 3 — they hard-block Checker on-duty gating (CHK-01).
- [Roadmap]: Reporting aggregates (RPT-01/04) built once in Phase 6; IFO-09, DEAN-04, and HR consume them — DEAN-04 dashboard therefore sits in Phase 6, not Phase 4.
- [Roadmap]: Auth (Entra) + AWS/Tailwind deploy deferred to Phase 8 so cutover risk never blocks feature work; dev-login stub carries every earlier phase.
- [Phase 01]: Local dev DB is SQL Server 2025 LocalDB + Windows auth (DB_TRUSTED_CONNECTION), not Express + SQL login — settings made env-driven so prod SQL-auth is unchanged
- [Phase 01]: No fix-forward migration needed: all 0001_initial migrations applied cleanly on MSSQL (nullable-unique azure_oid as filtered unique index); 7 users seeded, surface serves 200
- [Phase 01]: [Phase 01]: MSSQL datetime2 stores UTC and an aware Asia/Manila instant round-trips with zero 8h drift — proven by DatetimeRoundTripTests (16:30 UTC and 00:00 UTC cases)
- [Phase 01]: [Phase 01]: R3-slice import+materialize parity (17/10/15/18/18) reproduced on SQL Server; CI-safe synthetic fixture (data/fixtures/r3_synthetic.csv) keeps the import path testable without the gitignored PII CSV
- [Phase 01]: [Phase 01]: CS token collation landed via hand-written RunSQL migration — mssql-django 1.7.3 db_collation AlterField emits no-op SQL (sqlmigrate confirmed); RunSQL owns DROP/ALTER/re-ADD
- [Phase 01]: [Phase 01]: qr_token/manual_code are NOT NULL → backed by UNIQUE CONSTRAINTS (not filtered indexes); recollation drops/re-adds the constraint by dynamically-discovered name
- [Phase 02]: JOB-02a shared no-show predicate extracted: is_no_show_past_grace(scheduled_start, now, grace_min) is the single atom resolve_faculty_scan and the Phase-2 sweep both use; strictly >-past-grace boundary; coupling-integrity test blocks drift
- [Phase 02]: notify() (NOTIF-00) is the single Notification write path; web/scan.py IFO notifications migrated onto it and _notify_ifo deleted; notify() emits no AuditLog (triggering domain action carries the audit)
- [Phase 02]: release_room() (ops/occupancy.py) built + fully tested in Phase 2 with ZERO callers by design; timer-based auto-release cut 2026-07-03, only MOD-03 (Phase 4) will call it — grep guard proves the cut
- [Phase 02]: session.room_released AuditLog is the room-release audit contract (target_type=session, target_id=pk, payload.released_at ISO); actor=None denotes a system-initiated release
- [Phase 02]: JOB-02 sweep marks unscanned F2F/Blended no-shows Absent via the shared is_no_show_past_grace predicate; online EXCLUDED with a Phase-3 hook (not Phase 7); backfilled, idempotent (SCHEDULED->ABSENT only), AuditLog(by=sweep); never stamps room_released_at
- [Phase 02]: Room-conflict dedup via RoomConflictFlag (filtered UniqueConstraint uniq_open_conflict_per_key, key room:{room_id}); one notify(role=IFO_ADMIN, type=room_conflict) per open conflict, auto-resolves on clear (JOB-02c)
- [Phase ?]: [Phase 02]: ENV-04 dedicated scheduler — one manage.py runscheduler BlockingScheduler+MemoryJobStore process wires exactly 3 jobs (materialize/6h via call_command, sweep/policy-driven 5min running sweep_no_shows+detect_room_conflicts, weekly_report Mon06:00 stub); scheduler built ONLY in build_scheduler(), never AppConfig.ready (NoImplicitSchedulerTests guards no per-worker double-fire); run_job records a JobRun per run + notifies SYSTEM_ADMIN on failure only, never crashes the scheduler; APScheduler pinned >=3.10,<4
- [Phase ?]: VERIFIED_EMPTY is the canonical empty checker action; confirmed_absent and confirmed_empty retired (03-01)
- [Phase ?]: AssignmentScope (FLOOR/ONLINE) additive field; Session.online_checker nullable one-owner FK (03-01)
- [Phase ?]: 03-02: Checker action endpoint re-identifies the room from POST room_id and unconditionally re-runs resolve_checker_scan against current _active_floor_ids before any write (server-side re-gate; never trusts client gating).
- [Phase ?]: 03-02: _active_floor_ids treats a standing FLOOR posting (date NULL) as always on-duty; a shift is on-duty when date==today and start<=now<=end (either bound may be NULL).
- [Phase ?]: 03-03: online round-robin apply (assign_online_sessions) writes Session.online_checker via the pure distributor; empty roster leaves NULL + flags IFO, never guesses
- [Phase ?]: 03-04: CHK-07 floor board uses ONE shared queryset (exclude ABSENT, active-floor scoped, effective-online dropped in Python) feeding cards + queue + coverage denominator (Pitfall 5)
- [Phase ?]: 03-04: card display state computed server-side (flagged wins over verified for the face); coverage counts any verified validation, matching Session.verified_by_checker
- [Phase 03]: 03-05: online Verify activates the session (status=ACTIVE + actual_start + checkin_method=ONLINE_MANUAL) — the online analog of a room check-in — and records CheckerValidation(verified); Flag-not-present drives ABSENT authoritatively + notifies IFO/HR.
- [Phase 03]: 03-05: the JOB-02 sweep online-exclusion guard is REMOVED (online joins the shared is_no_show_past_grace path); shipped in lockstep with the online Verify path so only un-verified online no-shows fall to Absent while ACTIVE (verified) online is skipped — ROADMAP #6.
- [Phase 03]: 03-05: the online /checker/action branch (session_id, no room_id) re-gates server-side — ownership (online_checker_id==user) + active online-duty + actionable — before _apply_action, mirroring the 03-02 floor re-gate; online validations reuse session.room for the NOT-NULL CheckerValidation.room (no migration).
- [Phase ?]: 03-06: replay re-runs resolve_checker_scan against CURRENT server-derived state per item (active floors + room session state), never the client offline snapshot; stale items write AuditLog(checker.replay_conflict) + notify(IFO), idempotent via cache keyed on client_uuid (no expiry).
- [Phase ?]: 03-06: IndexedDB offline queue (vanilla JS, no wrapper lib) captures Verify/Confirm-empty/Flag-not-present locally when offline; drain batch-POSTs to /checker/replay, applied/flagged/duplicate are all terminal and removed locally; feature-detects window.indexedDB and degrades without crashing.
- [Phase 03.1]: 03.1-01: real PKCE requires accounts.backends.AzureADTenantOAuth2PKCE(BaseOAuth2PKCE, AzureADTenantOAuth2) — the stock AzureADTenantOAuth2 does NOT inherit the PKCE mixin so SOCIAL_AUTH_..._USE_PKCE is silently ignored (Pitfall 1); the subclass keeps name='azuread-tenant-oauth2' so the callback URL + env prefix are unchanged.
- [Phase 03.1]: 03.1-01: SocialAuthExceptionMiddleware sits between AuthenticationMiddleware and MessageMiddleware AND SOCIAL_AUTH_RAISE_EXCEPTIONS=False, so an AuthForbidden refusal redirects to SOCIAL_AUTH_LOGIN_ERROR_URL=/login with a message instead of a raw 500 (D-06/D-09#2).
- [Phase 03.1]: 03.1-01: SOCIAL_AUTH_PIPELINE has associate_by_email then accounts.pipeline.deny_unprovisioned then accounts.pipeline.write_azure_oid with create_user REMOVED (D-05/D-06); the accounts.pipeline.* refs are lazy dotted-strings resolved only at auth time, so check/migrate/tests pass before Plan 02 creates them.
- [Phase 03.1]: 03.1-01: all 17 social_django migrations applied cleanly on MSSQL LocalDB (5 social_auth_* tables) — no fix-forward RunSQL needed, resolving research assumption A2.
- [Phase 03.1]: 03.1-01: REDIRECT_URI pinned to http://localhost:8000/auth/complete/azuread-tenant-oauth2/ (localhost not 127.0.0.1, trailing slash) to avoid AADSTS50011 (Pitfall 3); DRF left on SessionAuthentication+IsAuthenticated (D-10).
- [Phase 03.1]: 03.1-02: deny_unprovisioned (after associate_by_email, create_user removed) refuses user=None/inactive with AuthForbidden + auth.entra_refused AuditLog(actor=None); write_azure_oid persists response['oid'] (durable Entra oid, NOT the sub uid), idempotent, + auth.entra_login AuditLog on success (D-05/D-06/AUTH-03/05; Convention #2 audit honored).
- [Phase 03.1]: 03.1-02: link_entra <username> <upn> repoints seeded User.email to a real MMCM UPN (D-07) so associate_by_email binds the slot; validates UPN, rejects unknown username + cross-user email clash, idempotent no-change exits 0, ASCII-only; seed_demo.py untouched.
- [Phase 03.1]: 03.1-03: dev-login login() names django.contrib.auth.backends.ModelBackend so it no longer raises ValueError under two AUTHENTICATION_BACKENDS (Pitfall 2, D-09#3); logout_view untouched (D-11 session-only).
- [Phase 03.1]: 03.1-03: "Sign in with Microsoft" button moved out of the {% else %} branch — always visible in DEBUG and non-DEBUG, wired to {% url social:begin azuread-tenant-oauth2 %}; login.html renders Django messages so a refused Entra login is visible (D-08/D-06); dev-login forms stay under DEBUG.
- [Phase 03.1]: 03.1-03: .env.example replaces ENTRA_* with SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY/SECRET/TENANT_ID (client id->_KEY, secret->_SECRET per D-04), drops the "Phase 2" label (Pitfall 8).
- [Phase 03.1]: 03.1-04: 22 network-free tests lock the Plan 01/02/03 wiring as regression-guarded invariants — accounts/tests.py (PkceBackendTests/AuthWiringTests/DenyUnprovisionedTests/WriteAzureOidTests/LinkEntraCommandTests) + web/tests.py (DevLoginCoexistTests/LogoutTests); pure-function pipeline tests use fake response/details dicts (no live Entra/network/browser — that round-trip is Plan 05). Full suite 125 green.
- [Phase 03.1]: 03.1-04: AuthWiringTests asserts settings.SOCIAL_AUTH_RAISE_EXCEPTIONS is False + SocialAuthExceptionMiddleware positioned after AuthenticationMiddleware/before MessageMiddleware (refusal redirects, not 500) AND REST_FRAMEWORK still SessionAuthentication (D-10 negative guard) — the two invariants most likely to silently regress.
- [Phase 04]: Migration file renamed to plan artifact name 0003_modality_shift_request.py via unapply/rename/re-apply
- [Phase 04]: Competitor occupant in make_shift_fixture is a second F2F Session with a distinct faculty (avoids D-17 self-double-book)
- [Phase 04]: 04-02: FluxTrack_SRS revised to v1.2 -- MOD area (MOD-01..06) added as new Section 4.4 with 4.5..4.13 renumbered (SCAN-03 and IFO-10 cross-refs updated); DEAN-04 dashboard row; FAC-07 marked superseded by the Dean-approved modality-shift workflow; CHK-03 drops Confirm absent and applies to online; CHK-06 removed (Absent is final); RPT-02 notifies IFO + Deans; modality_shift_lead_days=2 in the Section 8 policy register.
- [Phase 04]: 04-02: FluxTrack_SRS.docx is a GENERATED artifact -- produced only by 'manage.py regenerate_srs_docx' from the .md via bundled pypandoc_binary==1.17 (pandoc 3.9, no system pandoc / no PATH); never hand-edit the .docx; pandoc output is not byte-deterministic.
- [Phase 04]: 04-02: MOD-06 documentation half (FAC-07 superseded + CHK-06 removed in SRS) shipped here; the code half (declared_modality as approval override) lands in 04-05/04-07, so MOD-06 stays open in REQUIREMENTS.md while DOC-01 is closed.
- [Phase 04]: 04-04: creation-side refusals raise ModalityShiftError (friendly-400 seam); submit persists a PENDING ticket + item-per-schedule, notifies the Dean once, mutates no sessions (apply is 04-05)
- [Phase ?]: 04-05: no-room/double-book apply raises _NoRoomAvailable caught outside a nested savepoint -> terminal DENIED commits while all session/item writes roll back (D-07 REVISED, no partial apply)
- [Phase ?]: 04-05: ->F2F room re-resolved server-side INSIDE the approval transaction (TOCTOU-safe); item.assigned_room stores the D-18 reservation
- [Phase ?]: 04-06: materialize_sessions APPLIES the reserved room (D-18), never re-resolves; no-room is a defensive guard only
- [Phase ?]: 04-06: JOB-01 born-released/born-assigned hook fires only on get_or_create was_created, making materialize idempotent
- [Phase ?]: 04-07: Faculty modality submit is htmx-driven (HX-Redirect on success, 302 fallback); preferred room is a preference only (server re-resolves at approval); withdraw guard delegated to withdraw_modality_shift (IDOR-safe); FAC-07 self-declare retired
- [Phase 04]: 04-08: Dean approve/reject views delegate all state changes to apply_approval/reject_modality_shift; the view only fetches by pk and renders the outcome (TOCTOU/IDOR-safe)
- [Phase 04]: 04-08: the D-07 no-room denial is a returned request.status==DENIED surfaced at 200 with a message; only a genuine service refusal (cross-department/non-pending) renders at 400
- [Phase ?]: [Phase 04.1]: 04.1-01: stdlib zipfile+xml.etree .xlsx reader (no openpyxl/pandas, D1) + pure importing helpers; reconcile() four-bucket partition reproduces the real file exactly (1211 = 1042 + 44 + 14 + 111, 2021 meetings, 168 rooms, 200 instructors, 10 email-less). Section-label guard demotes room==Sec only when Unassigned (C110), keeping real rooms that share their Sec (A298).
- [Phase ?]: 04.1-02: load_room_master tab-skip keys on classify_room fields (known building OR is_typo OR floor>0) so only the 2 summary tabs skip while U101/P101 import; reset_term is --yes-guarded, PROTECT-aware, reversible (D10)
- [Phase 04.1]: 04.1-03: import_offerings hardened to read the real offerings .xlsx by default (extension dispatch keeps the .csv+--building/--floor regression) and consume Plan 01's shared helpers instead of private parsing; keeps virtual/gym meetings, stamps per-meeting modality by room (blended yields physical+online), dedups instructors email-then-name (57 blank-email -> 10 Users), routes roomless-physical to a shared TBA room (Unassigned) and roomless-online to a VTBA Online placeholder. Real dry-run lands 1042+44+14+111=1211 / 2021 meetings / 200 instructors exactly; reconcile()-driven report flags typo 404/516 + the 10 email-less. R3ParityTests retired (ENV-02 now carried at full-term scale). materialize_sessions untouched (D8).
- [Phase 04.1]: 04.1-04: full D10 clean-load ran live against MSSQL LocalDB (reset_term --yes cleared 2113+2113 under the batched param cap, load_room_master, import_offerings real run, materialize_sessions --days 14 -> 4226 sessions). Reconciliation balanced exactly (1042+44+14+111=1211, 2021 meetings); live term = 2113 schedules / 200 instructors / 218 rooms / 5 term buildings. Scale checks are TERM-SCOPED (active-term buildings == 5), NOT a global Building count — the dormant seed_demo IT building (0 active-term schedules) is expected and must not trip them. DEBUG dev-login curated to a per-role allowlist (DEMO_USERNAMES) with the real professor GARAY (cdgaray) as faculty replacing fake mayo; passwordless-by-username POST unchanged so any imported instructor stays typeable. Human-verify gate approved. Downstream finding (NOT a load defect): co-scheduled sections (same instructor/time, different rooms — e.g. GARAY MMA116 A301/A302) create sibling sessions the sweep would falsely mark Absent — tracked in follow-up Phase 04.2.
- [Phase 04.2]: 04.2-01: shared merge core built - pure merged_sibling_ids (faculty_id + exact scheduled_start + same-room-OR-same-course, D-01) mirrors is_no_show_past_grace; propagate_merged_present/absent flip ONLY SCHEDULED siblings via one status-guarded filtered .update() + AuditLog.bulk_create (idempotent, faculty-scoped, HY010-safe on MSSQL); CheckinMethod.MERGED via metadata-only 0004 migration (sqlmigrate no-op); anchor never re-stamped MERGED.
- [Phase 04.2]: Faculty scan seam propagates merged-present on CHECKED_IN and force-handover (ROOM_OCCUPIED); anchor keeps real checkin_method, only siblings become MERGED; propagate runs inside the anchor transaction.atomic() (D-04).
- [Phase ?]: 04.2-03: online Checker Verify propagates present across the online merged group via the D-01 course_code/V-room key (no teams_link clause); online Flag-not-present propagates ABSENT immediately; F2F flag stays record-only (D-07 per-modality)
- [Phase ?]: 04.2-03: merge-filled siblings get NO CheckerValidation (D-09) so verified_by_checker/CHK-04 coverage stays honest
- [Phase 05]: 05-02: pywebpush pinned + installed (py-vapid 1.9.4 + http-ece 1.2.1); VAPID_PUBLIC_KEY/PRIVATE_KEY_PATH/SUB read via env() with empty-safe defaults so the app boots unconfigured; private key referenced by path only, PEM gitignored via *.pem+keys/ and git check-ignore verified (T-05-03); push_outbox_interval_seconds=15 added to FLUXTRACK_POLICY (D-09, policy-driven cadence); package-legitimacy gate T-05-SC approved by operator after pypi.org verification.
- [Phase 05]: 05-03: Web push is fault-isolated by construction (D-09) -- send_push_outbox runs ONLY in the scheduler push_outbox job (4th job on the single BlockingScheduler), never in a web worker, so a hung endpoint cannot touch the triggering request (criterion #4).
- [Phase 05]: 05-03: Prune subscriptions ONLY on WebPushException 404/410; transient 5xx/timeout/network are kept and treated as handled this pass (T-05-08), so a flaky vendor never drops live endpoints.
- [Phase ?]: [Phase 05]: 05-04: global web.context.notifications processor supplies poll_ms (get_policy*1000, never hardcoded) + AnonymousUser-guarded unread + empty-safe vapid_public_key to BOTH shells (RESEARCH Pitfall 4); bell poll is READ-ONLY (D-02), only dropdown/list OPEN marks shown rows read (D-03), audit-silent; mute_toggle POST-only, category-validated, presence-as-mute (D-05); 12 read-surface tests green.
- [Phase 06]: 06-02: reportlab pinned >=4.2,<5 (installed 4.5.1) as the pure-Python PDF engine for RPT-03 (06-03 builder / 06-05 weekly report / 06-06 Dean export); only image dep is Pillow (already present), no WeasyPrint/GTK/Pango/Cairo system libs. Package-legitimacy gate T-06-SC approved by operator after pypi.org verification — the SUS audit verdict is a download-telemetry false positive (unknown-downloads seam + newness of 5.0.0), not slopsquatting; conservative pin excludes the ~1-month-old 5.0.0.
- [Phase 06]: 06-03: pure CSV/PDF render layer (scheduling/report_render.py) turns FacultyRow aggregates into bytes — build_csv() (stdlib csv.writer, header + one row/faculty, UTF-8 bytes) and build_pdf() (ReportLab Platypus, landscape A4, navy #001c43 header, repeatRows=1, %PDF bytes, empty-safe). csv_safe() is the SINGLE shared CSV-injection neutralizer (prefixes ' to leading = + - @ tab CR, T-06-02) imported by 06-05 weekly CSV and 06-07 payroll CSV so the two exports can never disagree. Render is pure: no ORM/default_storage/HttpResponse (caller's job). 11/11 tests green (CsvBuildTests/CsvInjectionTests/PdfBuildTests). RPT-03 complete.
- [Phase ?]: [Phase 06]: 06-01: pure reporting aggregate layer (scheduling/reporting.py) reads Session.status truth (held=ACTIVE/COMPLETED, absent=ABSENT) via DB-side Count(filter=Q); verified via a SEPARATE grouped validations query so status counts stay honest; MERGED siblings held-but-unverified (04.2 D-09); filters local Session.date not UTC scheduled_start; safe_card isolates a raising card with a generic message (RPT-05, no exc-text leak). faculty_scorecard adds early-ends + effective-modality breakdown (declared_modality overrides schedule.modality).
- [Phase 06]: 06-04: IFO-09 dashboard + RPT-04 scorecard drill-down (web/ifo.py dashboard/scorecard, both behind ifo_required). The 4 KPI cards derive from ONE safe_card(dept_summary); the per-faculty table is a SEPARATE safe_card(faculty_attendance) — patching dept_summary to raise proves per-card isolation end-to-end (KPI section errors, table section still renders, raw exception absent, T-06-04). _reporting_range() parses from/to, defaults to reporting_week_start-of-week..today, degrades invalid/reversed ranges to a friendly note (T-06-11, never 500); as_of=today always clamps the denominator. Drill-down is a FULL PAGE (A-DRILL) carrying from/to; attendance pills via --green/--amber/--red at >=90/75/<75 (A-COLOR). templates/reports/_error_card.html (generic copy only) + templates/reports/scorecard.html are shared partials reused by the Dean surface (06-06). 7 view-tests green; 3 web-suite failures are pre-existing dev-login/home-redirect issues (verified at ea3afb2), out of scope.
- [Phase 06]: 06-05: JOB-03 filled via shared ops.reports.generate_week_reports service reused by on-demand generate_weekly_report command; idempotent per-dept + ALL roll-up stored via default_storage (server-built reports/{week}/{code} paths), notify() fans to IFO + dept-scoped Deans; 4-job scheduler invariant + NoImplicitScheduler intact (RPT-02/ENV-04/NOTIF-00). 14 tests green.
- [Phase 06]: 06-07: HR session-level attendance surface (web/hr.py hr_required + attendance() list + attendance_csv() streaming export) is the CROSS-DEPARTMENT, READ-ONLY final reporting surface. Unlike the Dean surface, department is a FILTER not a scope boundary (HR sees all departments). Four independent filters (faculty/dept/date-range/term) + search key on FK id + date__range only (never pk__in, the 2100-param trap, T-06-16); invalid date -> friendly inline notice, never a 500. attendance_csv streams (StreamingHttpResponse + queryset.iterator() + _Echo echo-writer) to bound memory (T-06-03) and reuses scheduling.report_render.csv_safe for formula-injection neutralization (T-06-02). KEY: checker-verified is an is_verified=Exists() ANNOTATION resolved in the main query, NOT the Session.verified_by_checker property — the property runs a per-object subquery that is fatal inside a streaming .iterator() generator on MSSQL (HY010/open-cursor, T-06-15). One shared _filtered_sessions parser keeps the list and export in lock-step. Every view GET-only so POST is 405 (T-06-07). 14 tests green. Phase 06 complete (7/7).
- [Phase 06]: 06-06: Dean reporting surface (web/dean.py dashboard/reports/scorecard/report_export/weekly_download) is the department-scoped, READ-ONLY consumer of the shared aggregate/render layers. Every queryset scopes to request.user.department SERVER-SIDE; scorecard + weekly_download use get_object_or_404(..., department=request.user.department) so a foreign-department id 404s (T-06-01 IDOR/BOLA, refused not hidden). Every view is @require_http_methods(['GET']) so a POST is 405 (DEAN-01 read-only, T-06-07) — a bare Django view otherwise accepts any method. NULL-department Dean gets a zeroed DeptSummary/empty table, NEVER dept_summary(department=None) (edge-case cross-department leak closed). Export reuses build_csv/build_pdf (csv_safe intact, T-06-02); weekly_download streams default_storage bytes. Shared reports/scorecard.html back link parameterized via back_url (default /ifo/dashboard) so a Dean returns to /dean/reports. 12 tests green.
- [Phase ?]: 06.1-01: room-hours 'used' derived from actual timestamps, clamped to the scheduled window; the ended_early flag is display-only

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- [Phase 1]: MSSQL runtime behavior (collation case-insensitivity, datetime2/timezone round-trip) unproven — needs a dedicated spike with real round-trip tests before JOB-02 is built on top. An 8h Asia/Manila drift is possible if UTC storage is not verified.
- [Phase 8]: Tailwind v4 / Franken UI 2.1 build path (npm-plugin vs standalone-CLI) is MEDIUM confidence — needs a short build spike before committing to build-time-npm/Node-free production.
- [Phase 8]: Entra cutover can lock out all production login if DEBUG=False is flipped before SSO is proven end-to-end — keep a break-glass superuser; verify on staging.
- [General]: RDS SQL Server Express 10 GB cap + per-write AuditLog rows needs a retention/pruning job before real usage (address in Phase 8).
- 04.1-04 Task 1 BLOCKED: reset_term --yes fails at full-term scale (2113 schedules/sessions) with pyodbc 07002 'COUNT field incorrect' — exceeds SQL Server 2100-param limit in reset_term.py Session delete cascade. Fix belongs in Plan 02 reset_term. No tasks complete; DB unchanged (atomic rollback).

### Roadmap Evolution

- Phase 03.1 inserted after Phase 3: Entra ID SSO prioritized ahead of Phase 4 — local-dev proof; prod cutover stays in final deploy phase (URGENT)

## Session Continuity

Last session: 2026-07-19T08:46:00.104Z
Stopped at: context exhaustion at 75% (2026-07-18)
Resume file: .planning/phases/07-remaining-operational-surfaces/07-CONTEXT.md

## Phase 07 Follow-ups (deliberate scope calls, not defects)

Recorded so they are decisions on record rather than gaps someone rediscovers:

1. **Merged online siblings are not propagated on faculty self-start (FAC-08).**
   `scheduling.merge.propagate_merged_present` fills co-scheduled siblings on a
   room check-in; a self-start does not, because 07-09 scoped the write to
   `update_fields` on one session and `web/scan.py` was out of bounds. A faculty
   member teaching two merged online sections must start each. Inconsistent with
   the 04.2 co-scheduled work, which exists so one action covers siblings.

2. **No booking override control (IFO-05).** D-09's "absent an explicit
   override" was read as describing the default refusal, not commissioning an
   override. Building one would let the IFO console manufacture exactly the
   contradictory occupancy JOB-02c detects and IFO-08 now cleans up. Recorded as
   threat T-07-27, disposition `accept`.

3. **Manual/browser UAT not performed for most surfaces.** Executors ran
   automated suites but did not drive a browser (concurrent agents contended for
   the dev server and DB). Every plan has automated equivalents, but the visual
   result of the new IFO console pages, the Guard room page, the faculty photo
   page and the import upload flow is unverified by eye. Run `/gsd-verify-work`.

4. **`campus/codes.py` covers `manual_code` only.** `qr_token` uses
   `token_urlsafe(24)` (192 bits) so collision is negligible and it deliberately
   does not retry.

5. **D-19's original rationale was wrong and is corrected in 07-CONTEXT.md.**
   The PROTECT migration did not create a DB-level constraint — Django encodes
   `on_delete` in the Python Collector, not DDL. It closed the ORM path. The
   `room_delete_blockers` probe therefore carries more of the guarantee than
   D-19 credited, which is why D-20's fifth relation matters.

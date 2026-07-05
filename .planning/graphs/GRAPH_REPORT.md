# Graph Report - fluxtrack-main  (2026-07-05)

## Corpus Check
- 93 files · ~89,739 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 928 nodes · 4261 edges · 33 communities detected
- Extraction: 30% EXTRACTED · 70% INFERRED · 0% AMBIGUOUS · INFERRED: 2966 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 45|Community 45]]

## God Nodes (most connected - your core abstractions)
1. `Role` - 233 edges
2. `SessionStatus` - 196 edges
3. `Modality` - 192 edges
4. `Session` - 192 edges
5. `Room` - 186 edges
6. `AuditLog` - 179 edges
7. `ModalityShiftStatus` - 152 edges
8. `ModalityShiftItem` - 142 edges
9. `Floor` - 141 edges
10. `ModalityShiftRequest` - 140 edges

## Surprising Connections (you probably didn't know these)
- `Frontend views: dev-login stub, role-routed home, and the PWA shell.` --uses--> `Role`  [INFERRED]
  web\views.py → accounts\models.py
- `Login surface. Microsoft Entra ID SSO (Authorization Code + PKCE) is the     rea` --uses--> `Role`  [INFERRED]
  web\views.py → accounts\models.py
- `Shared notification write path (NOTIF-00).  `notify()` is the single place a `No` --uses--> `Notification`  [INFERRED]
  ops\notify.py → ops\models.py
- `Create one Notification per recipient and return the created list (NOTIF-00).` --uses--> `Notification`  [INFERRED]
  ops\notify.py → ops\models.py
- `Room occupancy lifecycle: the single source of truth for releasing a room.  JOB-` --uses--> `AuditLog`  [INFERRED]
  ops\occupancy.py → ops\models.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (167): Building, Floor, Room, Seed demo data: departments, campus, term, one user per role, schedules, session, AuditLogAdmin, BookingAdmin, NotificationAdmin, SystemSettingAdmin (+159 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (114): AzureADTenantOAuth2PKCE, Custom python-social-auth backend for Microsoft Entra ID.  D-02 / Pitfall 1: the, Single-tenant Entra ID backend with real PKCE (D-02, Pitfall 1)., Role, deny_unprovisioned(), Custom SOCIAL_AUTH_PIPELINE steps: FluxTrack's app-level identity policy.  Encod, Refuse any tenant identity with no pre-provisioned, active User (D-06/AUTH-03/AU, Persist the durable Entra object id and audit the successful login (D-05). (+106 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (11): _aware(), make_shift_fixture(), _add_session(), _approved_request(), _manila(), _materialize_future(), _occupy_room(), _pending_request() (+3 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (31): parse_time(), 7:00AM' / '12:00P' / '10:45A' / '1:15PM' -> datetime.time, or None., Exception, available_rooms_for(), available_times_for(), _effective_modality(), faculty_has_conflict(), free_rooms_in_building() (+23 more)

### Community 4 - "Community 4"
Cohesion: 0.11
Nodes (10): TestCase, assign_online_sessions(), _candidate_online_sessions(), _online_duty_assignments(), AssignmentCreateTests, _CheckerFixtureMixin, CheckerScanDBTests, DistributeDBTests (+2 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (17): is_no_show_past_grace(), Scan resolver core (SCAN-01/02) — pure functions, no queries, no side effects, u, The SINGLE shared no-show predicate (JOB-02a).      Returns True when `now` is s, sessions_today: the faculty member's Session objects for today, Resolution, resolve_faculty_scan(), FacultyResolverTests, NoShowPredicateTests (+9 more)

### Community 6 - "Community 6"
Cohesion: 0.07
Nodes (39): bannerEls(), countItems(), drain(), enqueue(), extractToken(), getAllItems(), getCookie(), initBanner() (+31 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (23): Command, parse_room(), Import schedules from the MMCM "Course Offering" CSV (IFO-03).  The reliable sou, R415' -> ('R', 4, 'R415'); '' or 'V...' or malformed -> None (skip)., _apply_approved_shift(), Command, Materialize dated Sessions from active Schedules (JOB-01 core logic).  For the a, Born-released / born-assigned hook (MOD-03/MOD-04, D-04/D-18, Pitfall 1).      T (+15 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (9): Command, Run the JOB-02 status sweep once (JOB-02b + JOB-02c).  Thin ASCII-only wrapper a, _job_sweep(), JOB-02: mark F2F/Blended no-shows Absent, then flag room conflicts.      Returns, detect_room_conflicts(), JOB-02b: mark unscanned no-shows ABSENT. Returns count marked.      Idempotent (, JOB-02c: flag contradictory room occupancy once, auto-resolve on clear.      A c, sweep_no_shows() (+1 more)

### Community 9 - "Community 9"
Cohesion: 0.08
Nodes (17): AbstractUser, DepartmentAdmin, FluxUserAdmin, Department, Identity and organization (SRS §5)., Each User holds exactly one role and may belong to a Department (§5).     Identi, User, BaseCommand (+9 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (12): Scheduled-job observability wrapper (ENV-04; feeds SYS-04 in Phase 7).  `run_job, Run `fn` under observability: record a JobRun, notify SysAdmins on failure only., run_job(), JobRun, One row per scheduled-job execution (ENV-04; SYS-04 reads it in Phase 7).      T, notify(), Shared notification write path (NOTIF-00).  `notify()` is the single place a `No, Create one Notification per recipient and return the created list (NOTIF-00). (+4 more)

### Community 11 - "Community 11"
Cohesion: 0.12
Nodes (15): checker(), checker_verify(), icon(), index(), _page(), FluxTrack UI proof-of-concept: Django + htmx + Franken UI (no React, no Node)., Server-generated QR poster (maps to IFO-01). Encodes a resolver deep link., Single role-aware resolver (SCAN-01/02). Returns a discrete outcome as htmx HTML (+7 more)

### Community 12 - "Community 12"
Cohesion: 0.22
Nodes (9): _active_assignments(), assignment_create(), _assignment_form_ctx(), assignments_list(), _deep_link(), live_rows(), room_qr(), rooms_list() (+1 more)

### Community 13 - "Community 13"
Cohesion: 0.15
Nodes (7): AccountsConfig, AppConfig, CampusConfig, OpsConfig, SchedulingConfig, VerificationConfig, WebConfig

### Community 14 - "Community 14"
Cohesion: 0.23
Nodes (1): FacultyModalityAuthzTests

### Community 15 - "Community 15"
Cohesion: 0.22
Nodes (8): assignment_covers_now(), CheckerResolution, distribute_online_sessions(), Checker verification decision cores (CHK-01, IFO-06) - pure functions.  Mirrors, Decide the outcome of a Checker scanning a room (CHK-01).      active_floor_ids:, True iff an on-duty ``Assignment`` is active at ``today``/``now_t`` (IN-03)., Deterministic round-robin of online sessions to online-duty checkers.      Retur, resolve_checker_scan()

### Community 16 - "Community 16"
Cohesion: 0.22
Nodes (4): _login_ctx(), login_view(), Frontend views: dev-login stub, role-routed home, and the PWA shell., Login surface. Microsoft Entra ID SSO (Authorization Code + PKCE) is the     rea

### Community 17 - "Community 17"
Cohesion: 0.29
Nodes (5): BuildingAdmin, FloorAdmin, RoomAdmin, Meta, Spaces: buildings, floors, rooms (SRS §5).

### Community 18 - "Community 18"
Cohesion: 0.29
Nodes (2): CollationRoundTripTests, Collation round-trip proofs (phase success criterion 3).  Proves both directions

### Community 19 - "Community 19"
Cohesion: 0.57
Nodes (1): ScanNotifyTests

### Community 20 - "Community 20"
Cohesion: 0.33
Nodes (1): Migration

### Community 21 - "Community 21"
Cohesion: 0.67
Nodes (3): env(), env_bool(), Django settings for FluxTrack.  Env-driven (see .env / .env.example). SQL Server

### Community 22 - "Community 22"
Cohesion: 0.5
Nodes (1): Migration

### Community 23 - "Community 23"
Cohesion: 0.67
Nodes (2): main(), Run administrative tasks.

### Community 24 - "Community 24"
Cohesion: 1.0
Nodes (1): ASGI config for config project.  It exposes the ASGI callable as a module-leve

### Community 25 - "Community 25"
Cohesion: 1.0
Nodes (1): FluxTrack URL configuration.

### Community 26 - "Community 26"
Cohesion: 1.0
Nodes (1): WSGI config for config project.  It exposes the WSGI callable as a module-leve

### Community 27 - "Community 27"
Cohesion: 1.0
Nodes (1): Migration

### Community 28 - "Community 28"
Cohesion: 1.0
Nodes (1): Migration

### Community 29 - "Community 29"
Cohesion: 1.0
Nodes (1): Migration

### Community 30 - "Community 30"
Cohesion: 1.0
Nodes (1): Migration

### Community 31 - "Community 31"
Cohesion: 1.0
Nodes (1): Migration

### Community 45 - "Community 45"
Cohesion: 1.0
Nodes (1): Derived: true if any 'verified' validation exists (§5).

## Knowledge Gaps
- **63 isolated node(s):** `Run administrative tasks.`, `Custom python-social-auth backend for Microsoft Entra ID.  D-02 / Pitfall 1: the`, `Single-tenant Entra ID backend with real PKCE (D-02, Pitfall 1).`, `Identity and organization (SRS §5).`, `Each User holds exactly one role and may belong to a Department (§5).     Identi` (+58 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 14`** (13 nodes): `FacultyModalityAuthzTests`, `._existing_request_on_f2f()`, `._future_session()`, `.setUp()`, `.test_double_request_while_pending_refused()`, `.test_foreign_withdraw_refused_and_stays_pending()`, `.test_malformed_submit_is_400_not_500()`, `.test_no_faculty_self_declare_route_exists()`, `.test_non_faculty_denied()`, `.test_rerequest_within_cooldown_after_decision_refused()`, `.test_valid_submit_creates_one_pending_routed_to_dean()`, `.test_weeks_mode_submit_derives_window_from_count()`, `.test_withdrawn_allows_immediate_rerequest()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 18`** (7 nodes): `CollationRoundTripTests`, `.setUp()`, `.test_case_variant_emails_dedupe_to_one_faculty()`, `.test_duplicate_token_still_raises_integrityerror()`, `.test_qr_tokens_differing_only_in_case_stay_distinct()`, `tests.py`, `Collation round-trip proofs (phase success criterion 3).  Proves both directions`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 19`** (7 nodes): `ScanNotifyTests`, `._confirm()`, `._room()`, `._session()`, `.setUp()`, `.test_confirmed_force_handover_notifies_ifo()`, `.test_confirmed_room_change_notifies_ifo()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 20`** (6 nodes): `0001_initial.py`, `0001_initial.py`, `Migration`, `0001_initial.py`, `0001_initial.py`, `0001_initial.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 22`** (4 nodes): `_assert_no_retired_actions()`, `Migration`, `_noop_reverse()`, `0003_retire_dead_validation_actions.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 23`** (3 nodes): `main()`, `Run administrative tasks.`, `manage.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 24`** (2 nodes): `asgi.py`, `ASGI config for config project.  It exposes the ASGI callable as a module-leve`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 25`** (2 nodes): `urls.py`, `FluxTrack URL configuration.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 26`** (2 nodes): `wsgi.py`, `WSGI config for config project.  It exposes the WSGI callable as a module-leve`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 27`** (2 nodes): `Migration`, `0002_roomconflictflag.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 28`** (2 nodes): `Migration`, `0003_jobrun.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 29`** (2 nodes): `Migration`, `0002_session_online_checker.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 30`** (2 nodes): `Migration`, `0003_modality_shift_request.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 31`** (2 nodes): `Migration`, `0002_assignment_scope.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (1 nodes): `Derived: true if any 'verified' validation exists (§5).`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Role` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 14`, `Community 16`, `Community 19`?**
  _High betweenness centrality (0.168) - this node is a cross-community bridge._
- **Why does `AuditLog` connect `Community 1` to `Community 0`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 10`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Why does `Room` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 9`, `Community 10`, `Community 14`, `Community 17`, `Community 18`, `Community 19`?**
  _High betweenness centrality (0.060) - this node is a cross-community bridge._
- **Are the 232 inferred relationships involving `Role` (e.g. with `PkceBackendTests` and `AuthWiringTests`) actually correct?**
  _`Role` has 232 INFERRED edges - model-reasoned connections that need verification._
- **Are the 195 inferred relationships involving `SessionStatus` (e.g. with `Command` and `Seed demo data: departments, campus, term, one user per role, schedules, session`) actually correct?**
  _`SessionStatus` has 195 INFERRED edges - model-reasoned connections that need verification._
- **Are the 191 inferred relationships involving `Modality` (e.g. with `Command` and `Seed demo data: departments, campus, term, one user per role, schedules, session`) actually correct?**
  _`Modality` has 191 INFERRED edges - model-reasoned connections that need verification._
- **Are the 189 inferred relationships involving `Session` (e.g. with `Command` and `Seed demo data: departments, campus, term, one user per role, schedules, session`) actually correct?**
  _`Session` has 189 INFERRED edges - model-reasoned connections that need verification._
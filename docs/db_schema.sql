/* =============================================================================
   FluxTrack — Exact Relational Schema (Microsoft SQL Server / T-SQL)
   =============================================================================
   PROVENANCE — this file is the AUTHORITATIVE, machine-generated DDL.
   It is the verbatim output of Django's own schema editor via:

       py -3.12 manage.py sqlmigrate <app> <migration>

   for every migration in the project, concatenated in dependency order.
   Backend: mssql-django (ENGINE="mssql", ODBC Driver 18) — config/settings.py.
   Regenerate any block by re-running the command for that migration.

   NOTES
   -----
   * DateTimeField maps to `datetimeoffset` (tz-aware) under mssql-django.
   * TextChoices enums carry NO CHECK constraint — Django validates choices in
     Python, not the DB. JSONField columns get an `ISJSON(...) = 1` CHECK.
   * Foreign keys are emitted with implicit ON DELETE NO ACTION; on_delete
     (CASCADE / PROTECT / SET_NULL) is enforced by the Django ORM layer.
   * Case-SENSITIVE collation (Latin1_General_100_CS_AS) is applied to
     campus_room.qr_token / manual_code only (migration campus/0002).
   * `accounts_user` inherits Django AbstractUser; its M2M tables reference the
     built-in `auth_group` / `auth_permission`. To run this standalone you must
     FIRST apply Django's built-in migrations (auth, contenttypes, admin,
     sessions) — i.e. run `manage.py migrate` — which create those parent
     tables. This file covers only the FluxTrack application migrations.
   * Each migration is wrapped in its own BEGIN TRANSACTION / COMMIT exactly as
     Django emits it; apply the blocks in the given order.
   ============================================================================= */


-- ============================================================================
-- MIGRATION: accounts 0001
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model Department
--
CREATE TABLE [accounts_department] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [name] nvarchar(120) NOT NULL, [code] nvarchar(20) NOT NULL UNIQUE);
--
-- Create model User
--
CREATE TABLE [accounts_user] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [password] nvarchar(128) NOT NULL, [last_login] datetimeoffset NULL, [is_superuser] bit NOT NULL, [username] nvarchar(150) NOT NULL UNIQUE, [first_name] nvarchar(150) NOT NULL, [last_name] nvarchar(150) NOT NULL, [email] nvarchar(254) NOT NULL, [is_staff] bit NOT NULL, [is_active] bit NOT NULL, [date_joined] datetimeoffset NOT NULL, [azure_oid] nvarchar(64) NULL, [role] nvarchar(20) NOT NULL, [profile_photo] nvarchar(100) NULL, [department_id] bigint NULL);
CREATE TABLE [accounts_user_groups] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [user_id] bigint NOT NULL, [group_id] int NOT NULL);
CREATE TABLE [accounts_user_user_permissions] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [user_id] bigint NOT NULL, [permission_id] int NOT NULL);
CREATE INDEX [accounts_user_groups_group_id_bd11a704] ON [accounts_user_groups] ([group_id]);
ALTER TABLE [accounts_user_groups] ADD CONSTRAINT [accounts_user_groups_group_id_bd11a704_fk_auth_group_id] FOREIGN KEY ([group_id]) REFERENCES [auth_group] ([id]);
CREATE UNIQUE INDEX [accounts_user_azure_oid_585494a3_uniq] ON [accounts_user]([azure_oid]) WHERE [azure_oid] IS NOT NULL;
ALTER TABLE [accounts_user_groups] ADD CONSTRAINT [accounts_user_groups_user_id_52b62117_fk_accounts_user_id] FOREIGN KEY ([user_id]) REFERENCES [accounts_user] ([id]);
CREATE UNIQUE INDEX [accounts_user_user_permissions_user_id_permission_id_2ab516c2_uniq] ON [accounts_user_user_permissions] ([user_id], [permission_id]) WHERE [user_id] IS NOT NULL AND [permission_id] IS NOT NULL;
CREATE INDEX [accounts_user_user_permissions_permission_id_113bb443] ON [accounts_user_user_permissions] ([permission_id]);
ALTER TABLE [accounts_user_user_permissions] ADD CONSTRAINT [accounts_user_user_permissions_permission_id_113bb443_fk_auth_permission_id] FOREIGN KEY ([permission_id]) REFERENCES [auth_permission] ([id]);
CREATE INDEX [accounts_user_groups_user_id_52b62117] ON [accounts_user_groups] ([user_id]);
CREATE INDEX [accounts_user_department_id_8dc06840] ON [accounts_user] ([department_id]);
CREATE UNIQUE INDEX [accounts_user_groups_user_id_group_id_59c0b32f_uniq] ON [accounts_user_groups] ([user_id], [group_id]) WHERE [user_id] IS NOT NULL AND [group_id] IS NOT NULL;
ALTER TABLE [accounts_user_user_permissions] ADD CONSTRAINT [accounts_user_user_permissions_user_id_e4f0a161_fk_accounts_user_id] FOREIGN KEY ([user_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [accounts_user] ADD CONSTRAINT [accounts_user_department_id_8dc06840_fk_accounts_department_id] FOREIGN KEY ([department_id]) REFERENCES [accounts_department] ([id]);
CREATE INDEX [accounts_user_user_permissions_user_id_e4f0a161] ON [accounts_user_user_permissions] ([user_id]);
COMMIT;

-- ============================================================================
-- MIGRATION: campus 0001
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model Building
--
CREATE TABLE [campus_building] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [name] nvarchar(120) NOT NULL, [code] nvarchar(20) NOT NULL UNIQUE);
--
-- Create model Floor
--
CREATE TABLE [campus_floor] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [number] int NOT NULL, [building_id] bigint NOT NULL);
--
-- Create model Room
--
CREATE TABLE [campus_room] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [code] nvarchar(30) NOT NULL UNIQUE, [name] nvarchar(120) NOT NULL, [capacity] int NOT NULL CONSTRAINT campus_room_capacity_21e468f1_check CHECK ([capacity] >= 0), [qr_token] nvarchar(64) NOT NULL UNIQUE, [manual_code] nvarchar(6) NOT NULL UNIQUE, [code_rotated_at] datetimeoffset NULL, [code_rotated_by_id] bigint NULL, [floor_id] bigint NOT NULL);
ALTER TABLE [campus_room] ADD CONSTRAINT [campus_room_floor_id_dae385d8_fk_campus_floor_id] FOREIGN KEY ([floor_id]) REFERENCES [campus_floor] ([id]);
CREATE UNIQUE INDEX [campus_floor_building_id_number_6874e625_uniq] ON [campus_floor] ([building_id], [number]) WHERE [building_id] IS NOT NULL AND [number] IS NOT NULL;
ALTER TABLE [campus_floor] ADD CONSTRAINT [campus_floor_building_id_f9d06dcd_fk_campus_building_id] FOREIGN KEY ([building_id]) REFERENCES [campus_building] ([id]);
CREATE INDEX [campus_room_floor_id_dae385d8] ON [campus_room] ([floor_id]);
CREATE INDEX [campus_room_code_rotated_by_id_5deaced6] ON [campus_room] ([code_rotated_by_id]);
CREATE INDEX [campus_floor_building_id_f9d06dcd] ON [campus_floor] ([building_id]);
ALTER TABLE [campus_room] ADD CONSTRAINT [campus_room_code_rotated_by_id_5deaced6_fk_accounts_user_id] FOREIGN KEY ([code_rotated_by_id]) REFERENCES [accounts_user] ([id]);
COMMIT;

-- ============================================================================
-- MIGRATION: campus 0002
-- ============================================================================
BEGIN TRANSACTION
--
-- Raw SQL operation
--

DECLARE @ct sysname;
SELECT @ct = kc.name
  FROM sys.key_constraints kc
  JOIN sys.index_columns ic
    ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
  JOIN sys.columns c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
 WHERE kc.parent_object_id = OBJECT_ID('campus_room')
   AND kc.type = 'UQ'
   AND c.name = 'qr_token';
IF @ct IS NOT NULL EXEC('ALTER TABLE campus_room DROP CONSTRAINT ' + @ct);
ALTER TABLE campus_room ALTER COLUMN qr_token nvarchar(64) COLLATE Latin1_General_100_CS_AS NOT NULL;
ALTER TABLE campus_room ADD CONSTRAINT UQ_campus_room_qr_token UNIQUE (qr_token);
;
--
-- Raw SQL operation
--

DECLARE @ct sysname;
SELECT @ct = kc.name
  FROM sys.key_constraints kc
  JOIN sys.index_columns ic
    ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
  JOIN sys.columns c
    ON c.object_id = ic.object_id AND c.column_id = ic.column_id
 WHERE kc.parent_object_id = OBJECT_ID('campus_room')
   AND kc.type = 'UQ'
   AND c.name = 'manual_code';
IF @ct IS NOT NULL EXEC('ALTER TABLE campus_room DROP CONSTRAINT ' + @ct);
ALTER TABLE campus_room ALTER COLUMN manual_code nvarchar(6) COLLATE Latin1_General_100_CS_AS NOT NULL;
ALTER TABLE campus_room ADD CONSTRAINT UQ_campus_room_manual_code UNIQUE (manual_code);
;
COMMIT;

-- ============================================================================
-- MIGRATION: scheduling 0001
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model AcademicTerm
--
CREATE TABLE [scheduling_academicterm] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [name] nvarchar(60) NOT NULL, [start_date] date NOT NULL, [end_date] date NOT NULL, [is_active] bit NOT NULL);
--
-- Create model AcademicBreak
--
CREATE TABLE [scheduling_academicbreak] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [start_date] date NOT NULL, [end_date] date NOT NULL, [reason] nvarchar(120) NOT NULL, [term_id] bigint NOT NULL);
--
-- Create model Schedule
--
CREATE TABLE [scheduling_schedule] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [course_code] nvarchar(30) NOT NULL, [section] nvarchar(30) NOT NULL, [enrolled_count] int NOT NULL CONSTRAINT scheduling_schedule_enrolled_count_c7a97689_check CHECK ([enrolled_count] >= 0), [day_of_week] int NOT NULL, [start_time] time NOT NULL, [end_time] time NOT NULL, [modality] nvarchar(10) NOT NULL, [status] nvarchar(10) NOT NULL, [faculty_id] bigint NOT NULL, [room_id] bigint NOT NULL, [term_id] bigint NOT NULL);
--
-- Create model Session
--
CREATE TABLE [scheduling_session] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [date] date NOT NULL, [scheduled_start] datetimeoffset NOT NULL, [scheduled_end] datetimeoffset NOT NULL, [status] nvarchar(10) NOT NULL, [actual_start] datetimeoffset NULL, [actual_end] datetimeoffset NULL, [checkin_method] nvarchar(15) NOT NULL, [declared_modality] nvarchar(10) NOT NULL, [modality_changed_at] datetimeoffset NULL, [teams_link] nvarchar(200) NOT NULL, [ended_early] bit NOT NULL, [early_end_reason] nvarchar(255) NOT NULL, [room_released_at] datetimeoffset NULL, [faculty_id] bigint NOT NULL, [handover_from_session_id] bigint NULL, [modality_changed_by_id] bigint NULL, [room_id] bigint NOT NULL, [schedule_id] bigint NOT NULL);
CREATE INDEX [scheduling_academicbreak_term_id_7d9b41fa] ON [scheduling_academicbreak] ([term_id]);
CREATE INDEX [scheduling_session_handover_from_session_id_a227fdff] ON [scheduling_session] ([handover_from_session_id]);
CREATE INDEX [scheduling_session_schedule_id_cf49caad] ON [scheduling_session] ([schedule_id]);
CREATE INDEX [scheduling_schedule_room_id_42c9dafe] ON [scheduling_schedule] ([room_id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_room_id_61851eee_fk_campus_room_id] FOREIGN KEY ([room_id]) REFERENCES [campus_room] ([id]);
ALTER TABLE [scheduling_schedule] ADD CONSTRAINT [scheduling_schedule_room_id_42c9dafe_fk_campus_room_id] FOREIGN KEY ([room_id]) REFERENCES [campus_room] ([id]);
CREATE INDEX [scheduling__date_f4b818_idx] ON [scheduling_session] ([date], [status]);
CREATE INDEX [scheduling_session_faculty_id_19cba005] ON [scheduling_session] ([faculty_id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_handover_from_session_id_a227fdff_fk_scheduling_session_id] FOREIGN KEY ([handover_from_session_id]) REFERENCES [scheduling_session] ([id]);
CREATE INDEX [scheduling_schedule_faculty_id_a6b4e5f9] ON [scheduling_schedule] ([faculty_id]);
CREATE INDEX [scheduling__room_id_91a2db_idx] ON [scheduling_session] ([room_id], [date]);
CREATE INDEX [scheduling_schedule_term_id_d377d62e] ON [scheduling_schedule] ([term_id]);
ALTER TABLE [scheduling_schedule] ADD CONSTRAINT [scheduling_schedule_term_id_d377d62e_fk_scheduling_academicterm_id] FOREIGN KEY ([term_id]) REFERENCES [scheduling_academicterm] ([id]);
CREATE INDEX [scheduling_session_room_id_61851eee] ON [scheduling_session] ([room_id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_modality_changed_by_id_46169fb5_fk_accounts_user_id] FOREIGN KEY ([modality_changed_by_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_schedule_id_cf49caad_fk_scheduling_schedule_id] FOREIGN KEY ([schedule_id]) REFERENCES [scheduling_schedule] ([id]);
CREATE INDEX [scheduling_session_modality_changed_by_id_46169fb5] ON [scheduling_session] ([modality_changed_by_id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_faculty_id_19cba005_fk_accounts_user_id] FOREIGN KEY ([faculty_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [scheduling_academicbreak] ADD CONSTRAINT [scheduling_academicbreak_term_id_7d9b41fa_fk_scheduling_academicterm_id] FOREIGN KEY ([term_id]) REFERENCES [scheduling_academicterm] ([id]);
ALTER TABLE [scheduling_schedule] ADD CONSTRAINT [scheduling_schedule_faculty_id_a6b4e5f9_fk_accounts_user_id] FOREIGN KEY ([faculty_id]) REFERENCES [accounts_user] ([id]);
COMMIT;

-- ============================================================================
-- MIGRATION: scheduling 0002
-- ============================================================================
BEGIN TRANSACTION
--
-- Add field online_checker to session
--
ALTER TABLE [scheduling_session] ADD [online_checker_id] bigint NULL;
CREATE INDEX [scheduling_session_online_checker_id_f2b83b48] ON [scheduling_session] ([online_checker_id]);
ALTER TABLE [scheduling_session] ADD CONSTRAINT [scheduling_session_online_checker_id_f2b83b48_fk_accounts_user_id] FOREIGN KEY ([online_checker_id]) REFERENCES [accounts_user] ([id]);
COMMIT;

-- ============================================================================
-- MIGRATION: scheduling 0003
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model ModalityShiftRequest
--
CREATE TABLE [scheduling_modalityshiftrequest] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [target_modality] nvarchar(10) NOT NULL, [window_start] date NOT NULL, [window_end] date NOT NULL, [is_time_move] bit NOT NULL, [status] nvarchar(10) NOT NULL, [decision_reason] nvarchar(255) NOT NULL, [decided_at] datetimeoffset NULL, [created_at] datetimeoffset NOT NULL, [dean_id] bigint NULL, [decided_by_id] bigint NULL, [department_id] bigint NULL, [requester_id] bigint NOT NULL);
--
-- Create model ModalityShiftItem
--
CREATE TABLE [scheduling_modalityshiftitem] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [new_start_time] time NULL, [new_end_time] time NULL, [assigned_room_id] bigint NULL, [preferred_room_id] bigint NULL, [schedule_id] bigint NOT NULL, [request_id] bigint NOT NULL);
CREATE INDEX [scheduling_modalityshiftrequest_department_id_66cd780a] ON [scheduling_modalityshiftrequest] ([department_id]);
ALTER TABLE [scheduling_modalityshiftrequest] ADD CONSTRAINT [scheduling_modalityshiftrequest_requester_id_0173645e_fk_accounts_user_id] FOREIGN KEY ([requester_id]) REFERENCES [accounts_user] ([id]);
CREATE INDEX [scheduling_modalityshiftitem_preferred_room_id_f980e3d7] ON [scheduling_modalityshiftitem] ([preferred_room_id]);
ALTER TABLE [scheduling_modalityshiftrequest] ADD CONSTRAINT [scheduling_modalityshiftrequest_dean_id_94d0177a_fk_accounts_user_id] FOREIGN KEY ([dean_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [scheduling_modalityshiftrequest] ADD CONSTRAINT [scheduling_modalityshiftrequest_decided_by_id_619c0101_fk_accounts_user_id] FOREIGN KEY ([decided_by_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [scheduling_modalityshiftrequest] ADD CONSTRAINT [scheduling_modalityshiftrequest_department_id_66cd780a_fk_accounts_department_id] FOREIGN KEY ([department_id]) REFERENCES [accounts_department] ([id]);
CREATE INDEX [scheduling_modalityshiftitem_request_id_2180d153] ON [scheduling_modalityshiftitem] ([request_id]);
CREATE INDEX [scheduling_modalityshiftrequest_decided_by_id_619c0101] ON [scheduling_modalityshiftrequest] ([decided_by_id]);
CREATE INDEX [scheduling_modalityshiftitem_assigned_room_id_c3d3e556] ON [scheduling_modalityshiftitem] ([assigned_room_id]);
CREATE INDEX [scheduling_modalityshiftrequest_requester_id_0173645e] ON [scheduling_modalityshiftrequest] ([requester_id]);
CREATE INDEX [scheduling_modalityshiftitem_schedule_id_de410a2e] ON [scheduling_modalityshiftitem] ([schedule_id]);
ALTER TABLE [scheduling_modalityshiftitem] ADD CONSTRAINT [scheduling_modalityshiftitem_request_id_2180d153_fk_scheduling_modalityshiftrequest_id] FOREIGN KEY ([request_id]) REFERENCES [scheduling_modalityshiftrequest] ([id]);
ALTER TABLE [scheduling_modalityshiftitem] ADD CONSTRAINT [scheduling_modalityshiftitem_preferred_room_id_f980e3d7_fk_campus_room_id] FOREIGN KEY ([preferred_room_id]) REFERENCES [campus_room] ([id]);
ALTER TABLE [scheduling_modalityshiftitem] ADD CONSTRAINT [scheduling_modalityshiftitem_schedule_id_de410a2e_fk_scheduling_schedule_id] FOREIGN KEY ([schedule_id]) REFERENCES [scheduling_schedule] ([id]);
CREATE INDEX [scheduling_modalityshiftrequest_dean_id_94d0177a] ON [scheduling_modalityshiftrequest] ([dean_id]);
ALTER TABLE [scheduling_modalityshiftitem] ADD CONSTRAINT [scheduling_modalityshiftitem_assigned_room_id_c3d3e556_fk_campus_room_id] FOREIGN KEY ([assigned_room_id]) REFERENCES [campus_room] ([id]);
COMMIT;

-- ============================================================================
-- MIGRATION: scheduling 0004
-- ============================================================================
BEGIN TRANSACTION
--
-- Alter field checkin_method on session
--
-- (no-op)
COMMIT;

-- ============================================================================
-- MIGRATION: verification 0001
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model Assignment
--
CREATE TABLE [verification_assignment] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [role] nvarchar(10) NOT NULL, [type] nvarchar(10) NOT NULL, [date] date NULL, [start_time] time NULL, [end_time] time NULL, [status] nvarchar(20) NOT NULL, [term_id] bigint NULL, [user_id] bigint NOT NULL);
CREATE TABLE [verification_assignment_floors] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [assignment_id] bigint NOT NULL, [floor_id] bigint NOT NULL);
--
-- Create model CheckerValidation
--
CREATE TABLE [verification_checkervalidation] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [action] nvarchar(25) NOT NULL, [identity_match] bit NULL, [note] nvarchar(max) NOT NULL, [scanned_at] datetimeoffset NULL, [validated_at] datetimeoffset NOT NULL, [offline_queued] bit NOT NULL, [checker_id] bigint NOT NULL, [room_id] bigint NOT NULL, [session_id] bigint NULL);
CREATE INDEX [verification_assignment_user_id_42f46623] ON [verification_assignment] ([user_id]);
CREATE UNIQUE INDEX [verification_assignment_floors_assignment_id_floor_id_4df1da06_uniq] ON [verification_assignment_floors] ([assignment_id], [floor_id]) WHERE [assignment_id] IS NOT NULL AND [floor_id] IS NOT NULL;
CREATE INDEX [verification_assignment_floors_assignment_id_4a14a5a6] ON [verification_assignment_floors] ([assignment_id]);
CREATE INDEX [verification_checkervalidation_room_id_07db7deb] ON [verification_checkervalidation] ([room_id]);
CREATE INDEX [verification_assignment_term_id_53e32bfb] ON [verification_assignment] ([term_id]);
ALTER TABLE [verification_assignment] ADD CONSTRAINT [verification_assignment_term_id_53e32bfb_fk_scheduling_academicterm_id] FOREIGN KEY ([term_id]) REFERENCES [scheduling_academicterm] ([id]);
ALTER TABLE [verification_assignment] ADD CONSTRAINT [verification_assignment_user_id_42f46623_fk_accounts_user_id] FOREIGN KEY ([user_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [verification_checkervalidation] ADD CONSTRAINT [verification_checkervalidation_checker_id_efa3a758_fk_accounts_user_id] FOREIGN KEY ([checker_id]) REFERENCES [accounts_user] ([id]);
CREATE INDEX [verification_assignment_floors_floor_id_1bb4b194] ON [verification_assignment_floors] ([floor_id]);
CREATE INDEX [verification_checkervalidation_checker_id_efa3a758] ON [verification_checkervalidation] ([checker_id]);
ALTER TABLE [verification_assignment_floors] ADD CONSTRAINT [verification_assignment_floors_floor_id_1bb4b194_fk_campus_floor_id] FOREIGN KEY ([floor_id]) REFERENCES [campus_floor] ([id]);
ALTER TABLE [verification_assignment_floors] ADD CONSTRAINT [verification_assignment_floors_assignment_id_4a14a5a6_fk_verification_assignment_id] FOREIGN KEY ([assignment_id]) REFERENCES [verification_assignment] ([id]);
CREATE INDEX [verification_checkervalidation_session_id_d307c35d] ON [verification_checkervalidation] ([session_id]);
ALTER TABLE [verification_checkervalidation] ADD CONSTRAINT [verification_checkervalidation_session_id_d307c35d_fk_scheduling_session_id] FOREIGN KEY ([session_id]) REFERENCES [scheduling_session] ([id]);
ALTER TABLE [verification_checkervalidation] ADD CONSTRAINT [verification_checkervalidation_room_id_07db7deb_fk_campus_room_id] FOREIGN KEY ([room_id]) REFERENCES [campus_room] ([id]);
COMMIT;

-- ============================================================================
-- MIGRATION: verification 0002
-- ============================================================================
BEGIN TRANSACTION
--
-- Add field scope to assignment
--
ALTER TABLE [verification_assignment] ADD [scope] nvarchar(10) DEFAULT 'floor' NOT NULL;
SELECT d.name FROM sys.default_constraints d INNER JOIN sys.tables t ON d.parent_object_id = t.object_id INNER JOIN sys.columns c ON d.parent_object_id = c.object_id AND d.parent_column_id = c.column_id INNER JOIN sys.schemas s ON t.schema_id = s.schema_id WHERE t.name = 'verification_assignment' AND c.name = 'scope';
ALTER TABLE [verification_assignment] DROP CONSTRAINT [scope];
COMMIT;

-- ============================================================================
-- MIGRATION: verification 0003
-- ============================================================================
BEGIN TRANSACTION
--
-- Raw Python operation
--
-- THIS OPERATION CANNOT BE WRITTEN AS SQL
--
-- Alter field action on checkervalidation
--
-- (no-op)
COMMIT;

-- ============================================================================
-- MIGRATION: ops 0001
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model SystemSetting
--
CREATE TABLE [ops_systemsetting] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [key] nvarchar(60) NOT NULL UNIQUE, [value] nvarchar(255) NOT NULL, [description] nvarchar(255) NOT NULL);
--
-- Create model Booking
--
CREATE TABLE [ops_booking] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [occupant_name] nvarchar(120) NOT NULL, [purpose] nvarchar(255) NOT NULL, [start_datetime] datetimeoffset NOT NULL, [end_datetime] datetimeoffset NOT NULL, [status] nvarchar(20) NOT NULL, [created_by_id] bigint NULL, [room_id] bigint NOT NULL);
--
-- Create model Notification
--
CREATE TABLE [ops_notification] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [type] nvarchar(40) NOT NULL, [title] nvarchar(200) NOT NULL, [body] nvarchar(max) NOT NULL, [link] nvarchar(255) NOT NULL, [read_at] datetimeoffset NULL, [created_at] datetimeoffset NOT NULL, [user_id] bigint NOT NULL);
--
-- Create model PushSubscription
--
CREATE TABLE [ops_pushsubscription] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [endpoint] nvarchar(500) NOT NULL, [keys] nvarchar(max) NOT NULL CONSTRAINT ops_pushsubscription_keys_48479cb8_check CHECK ((ISJSON ("keys") = 1)), [created_at] datetimeoffset NOT NULL, [user_id] bigint NOT NULL);
--
-- Create model AuditLog
--
CREATE TABLE [ops_auditlog] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [event_type] nvarchar(60) NOT NULL, [target_type] nvarchar(60) NOT NULL, [target_id] nvarchar(60) NOT NULL, [payload] nvarchar(max) NOT NULL CONSTRAINT ops_auditlog_payload_9e95299b_check CHECK ((ISJSON ("payload") = 1)), [ip_address] nvarchar(39) NULL, [created_at] datetimeoffset NOT NULL, [actor_id] bigint NULL);
--
-- Create model WeeklyReport
--
CREATE TABLE [ops_weeklyreport] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [week_start] date NOT NULL, [generated_at] datetimeoffset NOT NULL, [csv_path] nvarchar(500) NOT NULL, [pdf_path] nvarchar(500) NOT NULL, [department_id] bigint NULL);
ALTER TABLE [ops_booking] ADD CONSTRAINT [ops_booking_room_id_1e79898e_fk_campus_room_id] FOREIGN KEY ([room_id]) REFERENCES [campus_room] ([id]);
ALTER TABLE [ops_pushsubscription] ADD CONSTRAINT [ops_pushsubscription_user_id_27636dae_fk_accounts_user_id] FOREIGN KEY ([user_id]) REFERENCES [accounts_user] ([id]);
CREATE INDEX [ops_auditlo_event_t_e840ed_idx] ON [ops_auditlog] ([event_type], [created_at]);
ALTER TABLE [ops_weeklyreport] ADD CONSTRAINT [ops_weeklyreport_department_id_8f08f0dc_fk_accounts_department_id] FOREIGN KEY ([department_id]) REFERENCES [accounts_department] ([id]);
CREATE INDEX [ops_pushsubscription_user_id_27636dae] ON [ops_pushsubscription] ([user_id]);
CREATE INDEX [ops_booking_room_id_1e79898e] ON [ops_booking] ([room_id]);
CREATE INDEX [ops_auditlog_actor_id_0084abd8] ON [ops_auditlog] ([actor_id]);
ALTER TABLE [ops_notification] ADD CONSTRAINT [ops_notification_user_id_3f900bb7_fk_accounts_user_id] FOREIGN KEY ([user_id]) REFERENCES [accounts_user] ([id]);
ALTER TABLE [ops_booking] ADD CONSTRAINT [ops_booking_created_by_id_b7516316_fk_accounts_user_id] FOREIGN KEY ([created_by_id]) REFERENCES [accounts_user] ([id]);
CREATE INDEX [ops_notification_user_id_3f900bb7] ON [ops_notification] ([user_id]);
CREATE INDEX [ops_weeklyreport_department_id_8f08f0dc] ON [ops_weeklyreport] ([department_id]);
CREATE UNIQUE INDEX [ops_weeklyreport_week_start_department_id_76c7c970_uniq] ON [ops_weeklyreport] ([week_start], [department_id]) WHERE [week_start] IS NOT NULL AND [department_id] IS NOT NULL;
ALTER TABLE [ops_auditlog] ADD CONSTRAINT [ops_auditlog_actor_id_0084abd8_fk_accounts_user_id] FOREIGN KEY ([actor_id]) REFERENCES [accounts_user] ([id]);
CREATE INDEX [ops_booking_created_by_id_b7516316] ON [ops_booking] ([created_by_id]);
COMMIT;

-- ============================================================================
-- MIGRATION: ops 0002
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model RoomConflictFlag
--
CREATE TABLE [ops_roomconflictflag] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [conflict_key] nvarchar(120) NOT NULL, [detected_at] datetimeoffset NOT NULL, [resolved_at] datetimeoffset NULL, [room_id] bigint NOT NULL);
CREATE INDEX [ops_roomconflictflag_room_id_b3991ee1] ON [ops_roomconflictflag] ([room_id]);
ALTER TABLE [ops_roomconflictflag] ADD CONSTRAINT [ops_roomconflictflag_room_id_b3991ee1_fk_campus_room_id] FOREIGN KEY ([room_id]) REFERENCES [campus_room] ([id]);
CREATE UNIQUE INDEX [uniq_open_conflict_per_key] ON [ops_roomconflictflag] ([conflict_key]) WHERE [resolved_at] IS NULL;
COMMIT;

-- ============================================================================
-- MIGRATION: ops 0003
-- ============================================================================
BEGIN TRANSACTION
--
-- Create model JobRun
--
CREATE TABLE [ops_jobrun] ([id] bigint NOT NULL PRIMARY KEY IDENTITY (1, 1), [job_name] nvarchar(60) NOT NULL, [status] nvarchar(10) NOT NULL, [started_at] datetimeoffset NOT NULL, [finished_at] datetimeoffset NULL, [rows_affected] int NOT NULL, [detail] nvarchar(max) NOT NULL);
CREATE INDEX [ops_jobrun_job_nam_390546_idx] ON [ops_jobrun] ([job_name], [started_at] DESC);
COMMIT;

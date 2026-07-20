from django.urls import path

from . import (checker, dean, faculty, guard, hr, ifo, notifications, push, scan,
               sys, views)

urlpatterns = [
    path("", views.home, name="home"),
    path("login", views.login_view, name="login"),
    path("logout", views.logout_view, name="logout"),
    # Scan resolver (SCAN)
    path("scan", scan.deep_link, name="scan_deep_link"),
    path("scan/resolve", scan.resolve, name="scan_resolve"),
    path("scan/confirm", scan.confirm, name="scan_confirm"),
    # Faculty surfaces
    path("faculty/home", faculty.home, name="faculty_home"),
    path("faculty/schedule", faculty.schedule, name="faculty_schedule"),
    path("faculty/scan", faculty.scan_page, name="faculty_scan"),
    # Faculty modality-shift request surface (MOD-01/MOD-05, D-12)
    path("faculty/modality/new", faculty.modality_new, name="faculty_modality_new"),
    path("faculty/modality/rooms", faculty.modality_rooms, name="faculty_modality_rooms"),
    path("faculty/modality/mine", faculty.modality_mine, name="faculty_modality_mine"),
    path("faculty/modality/<int:pk>/withdraw", faculty.modality_withdraw,
         name="faculty_modality_withdraw"),
    # --- Faculty self-service (FAC-08, FAC-11) ---
    # FAC-08 online "Verify & Start": GET lists today's Online classes, POST
    # starts one from a pasted Teams link (D-01/D-03).
    path("faculty/online", faculty.online_list, name="faculty_online"),
    path("faculty/online/<int:pk>/start", faculty.online_start,
         name="faculty_online_start"),
    # FAC-11 own attendance history: read-only, hard-scoped to request.user,
    # Checker flags visible with no dispute control (D-15).
    path("faculty/history", faculty.history, name="faculty_history"),
    # --- Faculty profile photo (FAC-12) ---
    # GET-only page + POST-only multipart upload. The notification-preferences
    # half of FAC-12 is NOT re-routed here -- it already ships all-roles at
    # notif_settings / notif_mute below, and the profile page links to it.
    path("faculty/profile", faculty.profile, name="faculty_profile"),
    path("faculty/profile/photo", faculty.profile_photo_upload,
         name="faculty_profile_photo"),
    # --- end Faculty profile photo (FAC-12) ---
    # --- end Faculty self-service ---
    # Dean modality-shift approval surface (MOD-02, D-12)
    path("dean/requests", dean.queue, name="dean_queue"),
    path("dean/requests/<int:pk>/approve", dean.approve, name="dean_approve"),
    path("dean/requests/<int:pk>/reject", dean.reject, name="dean_reject"),
    # Dean reporting surface (DEAN-01..04, RPT-03) -- read-only, dept-scoped
    path("dean/dashboard", dean.dashboard, name="dean_dashboard"),
    path("dean/reports", dean.reports, name="dean_reports"),
    path("dean/reports/export/<str:fmt>", dean.report_export,
         name="dean_report_export"),
    path("dean/scorecard/<int:faculty_id>", dean.scorecard,
         name="dean_scorecard"),
    path("dean/scorecard/<int:faculty_id>/export.csv", dean.scorecard_export,
         name="dean_scorecard_csv"),
    path("dean/reports/weekly/<int:pk>/<str:fmt>", dean.weekly_download,
         name="dean_weekly_download"),
    # Checker surfaces (CHK-01..05, CHK-07)
    path("checker/scan", checker.scan_page, name="checker_scan"),
    path("checker/resolve", checker.resolve, name="checker_resolve"),
    path("checker/action", checker.action, name="checker_action"),
    path("checker/replay", checker.replay, name="checker_replay"),
    path("checker/floor", checker.floor_board, name="checker_floor"),
    path("checker/floor/rows", checker.floor_rows, name="checker_floor_rows"),
    path("checker/online", checker.online_list, name="checker_online"),
    path("checker/online/<int:session_id>", checker.online_open, name="checker_online_open"),
    # HR Admin session-level attendance surface (HR-01/02/03) -- read-only, cross-dept
    path("hr/attendance", hr.attendance, name="hr_attendance"),
    path("hr/attendance.csv", hr.attendance_csv, name="hr_attendance_csv"),
    # IFO Admin surfaces
    path("ifo/rooms", ifo.rooms_list, name="ifo_rooms"),
    path("ifo/rooms/board", ifo.rooms_board, name="ifo_rooms_board"),
    # IFO-01b room CRUD. `new` MUST precede the <str:code> pattern below or the
    # code converter swallows the literal and "new" resolves as a room code.
    path("ifo/rooms/new", ifo.room_new, name="ifo_room_new"),
    path("ifo/rooms/<str:code>", ifo.room_detail, name="ifo_room_detail"),
    path("ifo/rooms/<str:code>/edit", ifo.room_edit, name="ifo_room_edit"),
    path("ifo/rooms/<str:code>/delete", ifo.room_delete, name="ifo_room_delete"),
    path("ifo/rooms/<str:code>/panel", ifo.room_panel, name="ifo_room_panel"),
    path("ifo/rooms/<str:code>/poster", ifo.room_poster, name="ifo_room_poster"),
    # IFO-02 credential rotation: a GET confirm page, a POST-only action.
    path("ifo/rooms/<str:code>/rotate", ifo.room_rotate_confirm,
         name="ifo_room_rotate_confirm"),
    path("ifo/rooms/<str:code>/rotate/apply", ifo.room_rotate,
         name="ifo_room_rotate"),
    path("ifo/rooms/<str:code>/qr.png", ifo.room_qr, name="ifo_room_qr"),
    # Merged into the room board; kept so bookmarks and the cached PWA shell work.
    path("ifo/live", ifo.live, name="ifo_live"),
    # IFO-03b schedule import by upload: page (GET) + POST-only
    # preview/commit/discard. Multipart entry point is `preview`.
    path("ifo/import", ifo.import_page, name="ifo_import"),
    path("ifo/import/preview", ifo.import_preview, name="ifo_import_preview"),
    path("ifo/import/commit", ifo.import_commit, name="ifo_import_commit"),
    path("ifo/import/discard", ifo.import_discard, name="ifo_import_discard"),
    # IFO-05 ad-hoc bookings: list (GET) + POST-only create/cancel.
    path("ifo/bookings", ifo.bookings_list, name="ifo_bookings"),
    path("ifo/bookings/create", ifo.booking_create, name="ifo_booking_create"),
    path("ifo/bookings/<int:pk>/cancel", ifo.booking_cancel,
         name="ifo_booking_cancel"),
    # IFO-08 manual room release: open conflicts (GET) + the POST-only action.
    path("ifo/conflicts", ifo.conflicts, name="ifo_conflicts"),
    path("ifo/sessions/<int:pk>/release", ifo.session_release,
         name="ifo_session_release"),
    path("ifo/assignments", ifo.assignments_list, name="ifo_assignments"),
    path("ifo/assignments/create", ifo.assignment_create, name="ifo_assignment_create"),
    # Phase 9 (A1/A5) campus calendar: class suspensions + holidays/breaks.
    path("ifo/suspensions", ifo.suspensions_list, name="ifo_suspensions"),
    path("ifo/suspensions/create", ifo.suspension_create,
         name="ifo_suspension_create"),
    path("ifo/suspensions/<int:pk>/lift", ifo.suspension_lift,
         name="ifo_suspension_lift"),
    path("ifo/breaks", ifo.breaks_list, name="ifo_breaks"),
    path("ifo/breaks/create", ifo.break_create, name="ifo_break_create"),
    path("ifo/breaks/<int:pk>/delete", ifo.break_delete, name="ifo_break_delete"),
    # Phase 9 (A2, D3 IFO-only) reinstate a wrongly-Absent record.
    path("ifo/corrections", ifo.corrections_list, name="ifo_corrections"),
    path("ifo/sessions/<int:pk>/reinstate", ifo.session_reinstate,
         name="ifo_session_reinstate"),
    # IFO-09 reporting dashboard + scorecard drill-down (RPT-04/RPT-05)
    path("ifo/dashboard", ifo.dashboard, name="ifo_dashboard"),
    # IFO-09 tier T2: where and when capacity is idle (heat grid + rollups)
    path("ifo/utilization", ifo.utilization, name="ifo_utilization"),
    path("ifo/scorecard/<int:faculty_id>", ifo.scorecard, name="ifo_scorecard"),
    path("ifo/scorecard/<int:faculty_id>/export.csv", ifo.scorecard_csv,
         name="ifo_scorecard_csv"),
    # IFO Weekly Consolidated Report surface (RPT-01/03) -- unscoped, read-only
    path("ifo/reports", ifo.weekly_reports, name="ifo_weekly_reports"),
    path("ifo/reports/weekly/<int:pk>/<str:fmt>", ifo.weekly_download,
         name="ifo_weekly_download"),
    # Guard surfaces -- GRD-01 floor monitor + GRD-03 faculty locator.
    # GET-only by contract (GRD-05).
    path("guard/monitor", guard.monitor, name="guard_monitor"),
    path("guard/monitor/rows", guard.monitor_rows, name="guard_monitor_rows"),
    path("guard/locate", guard.locate, name="guard_locate"),
    # --- Guard room detail (GRD-02) ---
    # Keyed by room code like every other room route. Floor authorization is
    # re-derived server-side per request; an off-floor code 404s.
    path("guard/rooms/<str:code>", guard.room_detail, name="guard_room"),
    # --- end Guard room detail (GRD-02) ---
    # System Admin operational monitoring (SYS-04) -- read-only
    path("sys/jobs", sys.jobs, name="sys_jobs"),
    # Notifications read surface (NOTIF-01) + mute settings (NOTIF-03)
    path("notifications/bell", notifications.bell, name="notif_bell"),
    path("notifications/dropdown", notifications.dropdown, name="notif_dropdown"),
    path("notifications/settings", notifications.settings_page, name="notif_settings"),
    path("notifications/mute", notifications.mute_toggle, name="notif_mute"),
    path("notifications", notifications.list_page, name="notifications"),
    # Web-push subscription endpoints (NOTIF-02)
    path("notifications/push/subscribe", push.subscribe, name="push_subscribe"),
    path("notifications/push/unsubscribe", push.unsubscribe, name="push_unsubscribe"),
    path("notifications/push/key", push.vapid_public_key, name="push_key"),
    # PWA shell
    path("manifest.webmanifest", views.manifest),
    path("sw.js", views.service_worker),
    path("icon-<int:size>.png", views.icon),
]

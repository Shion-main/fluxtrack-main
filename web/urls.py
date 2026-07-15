from django.urls import path

from . import checker, dean, faculty, hr, ifo, notifications, push, scan, views

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
    path("faculty/modality/mine", faculty.modality_mine, name="faculty_modality_mine"),
    path("faculty/modality/<int:pk>/withdraw", faculty.modality_withdraw,
         name="faculty_modality_withdraw"),
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
    path("ifo/rooms/<str:code>", ifo.room_detail, name="ifo_room_detail"),
    path("ifo/rooms/<str:code>/poster", ifo.room_poster, name="ifo_room_poster"),
    path("ifo/rooms/<str:code>/qr.png", ifo.room_qr, name="ifo_room_qr"),
    path("ifo/live", ifo.live, name="ifo_live"),
    path("ifo/live/rows", ifo.live_rows, name="ifo_live_rows"),
    path("ifo/assignments", ifo.assignments_list, name="ifo_assignments"),
    path("ifo/assignments/create", ifo.assignment_create, name="ifo_assignment_create"),
    # IFO-09 reporting dashboard + scorecard drill-down (RPT-04/RPT-05)
    path("ifo/dashboard", ifo.dashboard, name="ifo_dashboard"),
    path("ifo/scorecard/<int:faculty_id>", ifo.scorecard, name="ifo_scorecard"),
    # IFO Weekly Consolidated Report surface (RPT-01/03) -- unscoped, read-only
    path("ifo/reports", ifo.weekly_reports, name="ifo_weekly_reports"),
    path("ifo/reports/weekly/<int:pk>/<str:fmt>", ifo.weekly_download,
         name="ifo_weekly_download"),
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

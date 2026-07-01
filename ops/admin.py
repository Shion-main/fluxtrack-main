from django.contrib import admin

from .models import (AuditLog, Booking, Notification, PushSubscription,
                     SystemSetting, WeeklyReport)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("room", "occupant_name", "start_datetime", "end_datetime", "status")
    list_filter = ("status",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "type", "read_at", "created_at")
    list_filter = ("type",)


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description")
    search_fields = ("key",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "actor", "target_type", "target_id", "created_at")
    list_filter = ("event_type",)
    readonly_fields = ("actor", "event_type", "target_type", "target_id",
                       "payload", "ip_address", "created_at")


@admin.register(WeeklyReport)
class WeeklyReportAdmin(admin.ModelAdmin):
    list_display = ("week_start", "department", "generated_at")


admin.site.register(PushSubscription)
admin.site.site_header = "FluxTrack Administration"
admin.site.site_title = "FluxTrack"

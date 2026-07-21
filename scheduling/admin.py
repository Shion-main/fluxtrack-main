from django.contrib import admin
from django.core.exceptions import PermissionDenied

from .admin_guards import TermOwnedAdminGuardMixin
from .models import AcademicBreak, AcademicTerm, Schedule, Session


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "status")
    list_filter = ("status",)

    def has_delete_permission(self, request, obj=None):
        return False

    def delete_model(self, request, obj):
        raise PermissionDenied("Academic terms cannot be deleted; use the lifecycle controls.")

    def delete_queryset(self, request, queryset):
        raise PermissionDenied("Academic terms cannot be deleted; use the lifecycle controls.")


@admin.register(AcademicBreak)
class AcademicBreakAdmin(TermOwnedAdminGuardMixin, admin.ModelAdmin):
    list_display = ("reason", "term", "start_date", "end_date")


@admin.register(Schedule)
class ScheduleAdmin(TermOwnedAdminGuardMixin, admin.ModelAdmin):
    list_display = ("course_code", "section", "faculty", "room", "day_of_week",
                    "start_time", "end_time", "modality", "status")
    list_filter = ("term", "modality", "status", "day_of_week")
    search_fields = ("course_code", "section")


@admin.register(Session)
class SessionAdmin(TermOwnedAdminGuardMixin, admin.ModelAdmin):
    list_display = ("schedule", "faculty", "room", "date", "status",
                    "checkin_method", "verified_by_checker")
    list_filter = ("status", "date", "checkin_method")
    date_hierarchy = "date"

from django.contrib import admin

from .models import AcademicBreak, AcademicTerm, Schedule, Session


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)


@admin.register(AcademicBreak)
class AcademicBreakAdmin(admin.ModelAdmin):
    list_display = ("reason", "term", "start_date", "end_date")


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ("course_code", "section", "faculty", "room", "day_of_week",
                    "start_time", "end_time", "modality", "status")
    list_filter = ("term", "modality", "status", "day_of_week")
    search_fields = ("course_code", "section")


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("schedule", "faculty", "room", "date", "status",
                    "checkin_method", "verified_by_checker")
    list_filter = ("status", "date", "checkin_method")
    date_hierarchy = "date"

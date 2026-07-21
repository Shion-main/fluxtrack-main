from django.contrib import admin

from scheduling.admin_guards import TermOwnedAdminGuardMixin

from .models import Assignment, CheckerValidation


@admin.register(Assignment)
class AssignmentAdmin(TermOwnedAdminGuardMixin, admin.ModelAdmin):
    list_display = ("user", "role", "type", "date", "start_time", "end_time", "status")
    list_filter = ("role", "type", "status")
    filter_horizontal = ("floors",)


@admin.register(CheckerValidation)
class CheckerValidationAdmin(TermOwnedAdminGuardMixin, admin.ModelAdmin):
    list_display = ("action", "room", "checker", "session", "validated_at", "offline_queued")
    list_filter = ("action", "offline_queued")

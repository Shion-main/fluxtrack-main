from django.contrib import admin

from .models import Building, Floor, Room


@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ("code", "name")


@admin.register(Floor)
class FloorAdmin(admin.ModelAdmin):
    list_display = ("building", "number")
    list_filter = ("building",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "floor", "capacity")
    list_filter = ("floor__building",)
    search_fields = ("code", "name")
    readonly_fields = ("qr_token", "manual_code", "code_rotated_at", "code_rotated_by")

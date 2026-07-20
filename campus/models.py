"""Spaces: buildings, floors, rooms (SRS §5)."""
from django.conf import settings
from django.db import models


class Building(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.code


class Floor(models.Model):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name="floors")
    number = models.IntegerField()

    class Meta:
        unique_together = [("building", "number")]
        ordering = ["building", "number"]

    def __str__(self):
        return f"{self.building.code} F{self.number}"


class Room(models.Model):
    floor = models.ForeignKey(Floor, on_delete=models.PROTECT, related_name="rooms")
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120, blank=True)
    capacity = models.PositiveIntegerField(default=0)

    # Resolver-only credentials — never rendered client-side (SCAN-07, §6.2)
    # Case-SENSITIVE collation on the two opaque token columns ONLY: case-variant
    # tokens must never collide (a real security bug). Rest of the DB stays CI so
    # faculty emails dedupe. See campus/migrations/0002_cs_collation_tokens.py.
    qr_token = models.CharField(max_length=64, unique=True, db_collation="Latin1_General_100_CS_AS")
    manual_code = models.CharField(max_length=6, unique=True, db_collation="Latin1_General_100_CS_AS")
    code_rotated_at = models.DateTimeField(null=True, blank=True)
    code_rotated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="rotated_room_codes",
    )
    # Phase 10 (A7): a room closed for renovation/repair. Distinct from deletion
    # (which is refused while the room carries history): an out-of-service room
    # keeps its record and schedules but refuses new scans and bookings and drops
    # out of the utilization denominator, so a closed room does not read as
    # "wasted" capacity. Honored by web/scan.py, ifo.booking_create, and
    # scheduling.reporting._physical_rooms.
    out_of_service = models.BooleanField(default=False)
    out_of_service_reason = models.CharField(max_length=200, blank=True)

    @property
    def is_virtual(self):
        """True for a virtual (online-only) room.

        MMCM's own convention, printed as a footnote on the paper schedule form:
        "Rooms that start with V are virtual rooms and are meant for online
        sessions." The importer honours it -- every V-prefixed room lands in the
        ONLINE building and holds only online classes -- so the code IS the flag
        and no second column has to be kept in sync with it.
        """
        return self.code.upper().startswith("V")

    def __str__(self):
        return self.code

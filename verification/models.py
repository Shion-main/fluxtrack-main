"""Verification and duty: assignments, checker validations (SRS §5)."""
from django.conf import settings
from django.db import models


class DutyRole(models.TextChoices):
    CHECKER = "checker", "Checker"
    GUARD = "guard", "Guard"


class AssignmentType(models.TextChoices):
    SHIFT = "shift", "Shift"
    STANDING = "standing", "Standing posting"


class AssignmentScope(models.TextChoices):
    FLOOR = "floor", "Floor"      # gates room scans on the assigned floor(s)
    ONLINE = "online", "Online"   # gates online (Teams) verification, floor-agnostic


class Assignment(models.Model):
    """On-duty grant for a Checker/Guard on assigned floors (CHK-01, IFO-06)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assignments"
    )
    role = models.CharField(max_length=10, choices=DutyRole.choices)
    floors = models.ManyToManyField("campus.Floor", related_name="assignments")
    type = models.CharField(max_length=10, choices=AssignmentType.choices)
    # IFO-06 online-duty extension: FLOOR gates room scans, ONLINE gates online
    # verification. Orthogonal to `type` (shift vs standing).
    scope = models.CharField(
        max_length=10, choices=AssignmentScope.choices, default=AssignmentScope.FLOOR
    )
    date = models.DateField(null=True, blank=True)  # null for standing postings
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    term = models.ForeignKey(
        "scheduling.AcademicTerm", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="assignments",
    )
    status = models.CharField(max_length=20, default="active")

    def __str__(self):
        return f"{self.user} — {self.get_role_display()} ({self.get_type_display()})"


class ValidationAction(models.TextChoices):
    # CONFIRMED_ABSENT and CONFIRMED_EMPTY were retired in 03-01: "Confirm absent"
    # went with CHK-06 (Absent is final via the sweep), and VERIFIED_EMPTY is the
    # single canonical empty action (research Open Q1). See migration 0003.
    VERIFIED = "verified", "Verified"
    FLAG_IDENTITY_MISMATCH = "flag_identity_mismatch", "Flag: identity mismatch"
    FLAG_NOT_PRESENT = "flag_not_present", "Flag: not present"
    VERIFIED_EMPTY = "verified_empty", "Verified empty"


class CheckerValidation(models.Model):
    """A Checker's recorded confirmation/contradiction — the source of truth (§1.2, CHK)."""
    session = models.ForeignKey(
        "scheduling.Session", null=True, blank=True,
        on_delete=models.CASCADE, related_name="validations",
    )
    room = models.ForeignKey("campus.Room", on_delete=models.PROTECT, related_name="validations")
    checker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="validations"
    )
    action = models.CharField(max_length=25, choices=ValidationAction.choices)
    identity_match = models.BooleanField(null=True, blank=True)
    note = models.TextField(blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    validated_at = models.DateTimeField(auto_now_add=True)
    offline_queued = models.BooleanField(default=False)

    class Meta:
        ordering = ["-validated_at"]

    def __str__(self):
        return f"{self.get_action_display()} · {self.room} · {self.checker}"

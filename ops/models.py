"""Operations: bookings, notifications, push, audit, settings, reports (SRS §5)."""
from django.conf import settings
from django.db import models


class Booking(models.Model):
    """Ad-hoc room booking, conflict-checked against sessions (IFO-05)."""
    room = models.ForeignKey("campus.Room", on_delete=models.CASCADE, related_name="bookings")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="bookings"
    )
    occupant_name = models.CharField(max_length=120)
    purpose = models.CharField(max_length=255, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    status = models.CharField(max_length=20, default="active")

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.room} · {self.occupant_name} ({self.start_datetime:%Y-%m-%d %H:%M})"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} → {self.user}"


class PushSubscription(models.Model):
    """Web-push (VAPID) subscription endpoint (NOTIF-02)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    endpoint = models.URLField(max_length=500)
    keys = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"push · {self.user}"


class AuditLog(models.Model):
    """Written on every write event (§6.2, SYS-03)."""
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="audit_events"
    )
    event_type = models.CharField(max_length=60)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["event_type", "created_at"])]

    def __str__(self):
        return f"{self.event_type} by {self.actor} @ {self.created_at:%Y-%m-%d %H:%M}"


class SystemSetting(models.Model):
    """Configurable policy values (SRS §8). Seeded from FLUXTRACK_POLICY."""
    key = models.CharField(max_length=60, unique=True)
    value = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.key} = {self.value}"


class WeeklyReport(models.Model):
    """Weekly per-department consolidated report; files in S3 (RPT-01/02)."""
    week_start = models.DateField()
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="weekly_reports",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    csv_path = models.CharField(max_length=500, blank=True)
    pdf_path = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["-week_start"]
        unique_together = [("week_start", "department")]

    def __str__(self):
        dep = self.department.code if self.department else "ALL"
        return f"WeeklyReport {self.week_start} · {dep}"

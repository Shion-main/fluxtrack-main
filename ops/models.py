"""Operations: bookings, notifications, push, audit, settings, reports (SRS §5)."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class Booking(models.Model):
    """Ad-hoc room booking, conflict-checked against sessions (IFO-05)."""
    # PROTECT, not CASCADE (D-19). Every other FK targeting campus.Room is
    # already PROTECT — scheduling.Schedule.room, scheduling.Session.room and
    # verification.CheckerValidation.room — and D-17 requires a room delete to
    # be REFUSED when anything references it. While this column was CASCADE,
    # D-17's Booking blocker was unenforceable: a room whose only references
    # were bookings deleted cleanly and took its booking history with it, so
    # the refusal was a view-level courtesy that anything bypassing the view
    # (admin, shell, a future caller) silently destroyed. Under PROTECT the
    # database itself is the guarantee.
    #
    # This deliberately changes behaviour for the existing Django-admin Booking
    # surface too: deleting a room from admin now raises ProtectedError instead
    # of cascading. That is the intended effect of D-19, not a regression.
    room = models.ForeignKey("campus.Room", on_delete=models.PROTECT, related_name="bookings")
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


class ImportStaging(models.Model):
    """A .xlsx/.csv held between the IFO-03b dry-run preview and the commit (D-12).

    DESIGN CONTRACT — three stores, three distinct jobs:
      - the BYTES live on disk under MEDIA_ROOT, at a path built server-side
        from `token` and the extension alone;
      - the SESSION carries only the opaque `token`;
      - THIS ROW is the ownership plus lifecycle record (who uploaded it, how
        big, when, and whether it has been consumed).

    Why the bytes are not in the SESSION. This project sets no SESSION_ENGINE,
    so Django's default database backend applies and the session lives in the
    MSSQL `django_session.session_data` text column. That column is re-read on
    every authenticated request for the life of the session, so parking a
    multi-MB spreadsheet in it would tax every unrelated page load until the
    session expires.

    Why the bytes are not in the CACHE. This project sets no CACHES either, so
    the default LocMemCache applies. It is per-process: the worker that handled
    the preview request and the worker that handles the commit request are not
    guaranteed to be the same one, so the file would be silently missing on
    commit under any multi-worker deployment — intermittently, and only in
    production.

    `original_name` is DISPLAY TEXT ONLY and is never used to build a path
    (T-07-04) — see ops.import_staging.stage_upload, which composes
    `stored_path` from STAGING_PREFIX + token + extension.
    """
    # Opaque, server-generated: secrets.token_urlsafe(32). Never user-supplied.
    token = models.CharField(max_length=64, unique=True, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="import_stagings",
    )
    # The client's filename, kept verbatim so the preview page can show the
    # operator which file they picked. NEVER joined into a filesystem path.
    original_name = models.CharField(max_length=255)
    # Storage-relative and entirely server-built.
    stored_path = models.CharField(max_length=255)
    size_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    # NULL until the commit step consumes this upload; a consumed row can never
    # be resolved again (single-use), which is what makes the commit idempotent
    # against a double-submit.
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "consumed" if self.consumed_at else "staged"
        return f"import {self.original_name} ({state}) · {self.uploaded_by}"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    # Outbox stamp (NOTIF-02): the 05-03 scheduler push pass sets this after
    # delivering a push for this row. NULL means not yet processed.
    pushed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        # Supports the unread-badge query (unread_count): rows for one user
        # ordered/filtered by read_at (NOTIF-01).
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"{self.title} → {self.user}"


class NotificationMute(models.Model):
    """Per-user mute of a notification category group (NOTIF-01/03, D-04/D-05).

    Presence-as-mute: the PRESENCE of a row means that `category` is muted for
    `user`; ABSENCE means unmuted. Default is therefore everything-unmuted (D-05)
    with no seed rows and no `is_muted` boolean — a user with zero rows sees all
    notifications. `category` holds a `NotificationCategory` value (defined in
    ops/notifications.py, the single source of truth D-06).
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="notification_mutes",
    )
    category = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "category")]

    def __str__(self):
        return f"mute {self.category} · {self.user}"


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


class RoomConflictFlag(models.Model):
    """One OPEN flag per contradictory room occupancy (JOB-02c).

    Raised by the status sweep's `detect_room_conflicts` when 2+ ACTIVE sessions
    hold one room (room_released_at NULL). The filtered UniqueConstraint below
    guarantees at most ONE open (resolved_at IS NULL) flag per `conflict_key`
    (the dedup key `f"room:{room_id}"`), so a persistent conflict notifies IFO
    exactly once instead of every sweep tick. The sweep stamps `resolved_at` when
    the conflict clears; IFO-08 (Phase 7) resolves the flag manually otherwise.
    Filtered unique on MSSQL is proven (Phase-1 azure_oid landed the same way).
    """
    room = models.ForeignKey(
        "campus.Room", on_delete=models.CASCADE, related_name="conflict_flags"
    )
    conflict_key = models.CharField(max_length=120)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conflict_key"], condition=Q(resolved_at__isnull=True),
                name="uniq_open_conflict_per_key")
        ]

    def __str__(self):
        state = "open" if self.resolved_at is None else "resolved"
        return f"conflict {self.conflict_key} ({state})"


class JobRun(models.Model):
    """One row per scheduled-job execution (ENV-04; SYS-04 reads it in Phase 7).

    The dedicated `runscheduler` process wraps every job in `ops.jobrun.run_job`,
    which records exactly one JobRun per run: `status` moves running -> ok|failed,
    `rows_affected` captures the job's return count, and started/finished_at bound
    the run. ENV-04's "last-run status recordable" is satisfied by this table
    (prefer a row over a log line, Conventions §Logging). SYS-04 (Phase 7) reads
    the latest row per `job_name` — hence the (job_name, -started_at) index.
    """
    job_name = models.CharField(max_length=60)   # "materialize" | "sweep" | "weekly_report"
    status = models.CharField(max_length=10)     # "running" | "ok" | "failed"
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    rows_affected = models.IntegerField(default=0)
    detail = models.TextField(blank=True)        # error repr or run summary

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["job_name", "-started_at"])]

    def __str__(self):
        return f"{self.job_name} {self.status} @ {self.started_at:%Y-%m-%d %H:%M}"


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

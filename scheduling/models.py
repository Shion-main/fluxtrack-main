"""Academics: terms, breaks, schedules, sessions (SRS §5)."""
from django.conf import settings
from django.db import models


class Modality(models.TextChoices):
    F2F = "f2f", "Face-to-face"
    BLENDED = "blended", "Blended"
    ONLINE = "online", "Online"


class DayOfWeek(models.IntegerChoices):
    MON = 0, "Monday"
    TUE = 1, "Tuesday"
    WED = 2, "Wednesday"
    THU = 3, "Thursday"
    FRI = 4, "Friday"
    SAT = 5, "Saturday"
    SUN = 6, "Sunday"


class AcademicTerm(models.Model):
    name = models.CharField(max_length=60)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)  # exactly one active at a time

    def __str__(self):
        return self.name


class AcademicBreak(models.Model):
    """Breaks suppress session materialization (JOB-01)."""
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="breaks")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return f"{self.reason} ({self.start_date}–{self.end_date})"


class ScheduleStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class Schedule(models.Model):
    """A recurring class slot for a term. Sections are fields (no separate entity)."""
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="schedules")
    course_code = models.CharField(max_length=30)
    section = models.CharField(max_length=30)
    enrolled_count = models.PositiveIntegerField(default=0)
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="schedules"
    )
    room = models.ForeignKey("campus.Room", on_delete=models.PROTECT, related_name="schedules")
    day_of_week = models.IntegerField(choices=DayOfWeek.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    modality = models.CharField(max_length=10, choices=Modality.choices, default=Modality.F2F)
    status = models.CharField(
        max_length=10, choices=ScheduleStatus.choices, default=ScheduleStatus.ACTIVE
    )

    def __str__(self):
        return f"{self.course_code}-{self.section} ({self.get_day_of_week_display()})"


class SessionStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    ACTIVE = "active", "Active"
    COMPLETED = "completed", "Completed"
    ABSENT = "absent", "Absent"


class CheckinMethod(models.TextChoices):
    QR_SCAN = "qr_scan", "QR scan"
    MANUAL_CODE = "manual_code", "Manual code"
    ONLINE_MANUAL = "online_manual", "Online (manual)"
    # FAC-08/D-01: the faculty member started their OWN online session by pasting
    # the Teams link. Deliberately NOT ONLINE_MANUAL, which means "a Checker
    # activated this session" (03-05). If both acts wrote one value the data could
    # no longer answer "who started this class", and D-02 depends on exactly that
    # distinction when it says a never-verified self-start must report as
    # held-but-unverified rather than being hidden.
    ONLINE_SELF = "online_self", "Online (self-start)"
    FORCE_HANDOVER = "force_handover", "Force handover"
    MERGED = "merged", "Merged (sibling fill)"


class Session(models.Model):
    """A single dated occurrence of a scheduled class (§5)."""
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE, related_name="sessions")
    faculty = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sessions"
    )
    room = models.ForeignKey("campus.Room", on_delete=models.PROTECT, related_name="sessions")
    date = models.DateField()
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=SessionStatus.choices, default=SessionStatus.SCHEDULED
    )
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    checkin_method = models.CharField(max_length=15, choices=CheckinMethod.choices, blank=True)
    declared_modality = models.CharField(max_length=10, choices=Modality.choices, blank=True)
    modality_changed_at = models.DateTimeField(null=True, blank=True)
    modality_changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="modality_changes",
    )
    handover_from_session = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="handover_to"
    )
    teams_link = models.URLField(blank=True)
    # CHK-02/IFO-06: the one online-duty owner for an online session. Round-robin
    # assigned in 03-03; Phase-4 modality-shift (to Online) also sets it. Nullable
    # until a roster exists for the session's date.
    online_checker = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="online_verifications",
    )
    ended_early = models.BooleanField(default=False)
    early_end_reason = models.CharField(max_length=255, blank=True)
    room_released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "scheduled_start"]
        indexes = [models.Index(fields=["date", "status"]), models.Index(fields=["room", "date"])]

    @property
    def verified_by_checker(self):
        """Derived: true if any 'verified' validation exists (§5)."""
        return self.validations.filter(action="verified").exists()

    def __str__(self):
        return f"{self.schedule.course_code} {self.date} ({self.get_status_display()})"


class ModalityShiftStatus(models.TextChoices):
    """Lifecycle of a modality-shift ticket (MOD-01, D-10, D-07 REVISED).

    DENIED is the terminal no-room-available system outcome (D-07 REVISED);
    REJECTED is the Dean's explicit no (MOD-02). WITHDRAWN is faculty pulling
    a still-PENDING request (D-10).
    """
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    DENIED = "denied", "Denied"


class ModalityShiftRequest(models.Model):
    """One atomic modality-shift ticket spanning a date-range window (D-19, D-01).

    A single request may cover multiple affected schedules over its window; each
    affected schedule is a ModalityShiftItem (request.items). Routes to the
    faculty's department Dean at submit (D-09).
    """
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="modality_requests",
    )
    dean = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modality_requests_routed",  # routed department Dean, stamped at submit (D-09)
    )
    department = models.ForeignKey(
        "accounts.Department", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modality_requests",  # routing snapshot
    )
    target_modality = models.CharField(max_length=10, choices=Modality.choices)
    window_start = models.DateField()  # single-session request => same date both (D-01)
    window_end = models.DateField()
    is_time_move = models.BooleanField(default=False)  # bundled reschedule (D-16)
    status = models.CharField(
        max_length=10, choices=ModalityShiftStatus.choices,
        default=ModalityShiftStatus.PENDING,
    )
    decision_reason = models.CharField(max_length=255, blank=True)  # Dean reject / system deny reason
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modality_requests_decided",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ModalityShift #{self.pk} -> {self.target_modality} ({self.get_status_display()})"


class ModalityShiftItem(models.Model):
    """One affected schedule within a ModalityShiftRequest ticket (D-19).

    assigned_room is the server-written reservation finalized at Dean approval
    and reserved for every in-window session including future ones (D-18);
    preferred_room is only the faculty preference (D-05/D-06).
    """
    request = models.ForeignKey(
        ModalityShiftRequest, on_delete=models.CASCADE, related_name="items"
    )
    schedule = models.ForeignKey(
        Schedule, on_delete=models.PROTECT, related_name="modality_items"
    )
    preferred_room = models.ForeignKey(
        "campus.Room", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modality_preferred_items",  # faculty preference only (D-05/D-06)
    )
    assigned_room = models.ForeignKey(
        "campus.Room", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="modality_assigned_items",  # reserved at Dean approval (D-18)
    )
    new_start_time = models.TimeField(null=True, blank=True)  # time-move slot (D-16); null when not a move
    new_end_time = models.TimeField(null=True, blank=True)

    def __str__(self):
        return f"ShiftItem req={self.request_id} sched={self.schedule_id}"

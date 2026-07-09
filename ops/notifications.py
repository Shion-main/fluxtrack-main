"""Notification categories, the single category->type map, and mute/visibility
helpers (NOTIF-01/NOTIF-03).

D-06: CATEGORY_TYPES is the ONE place the three mute groups are defined. Both the
in-app list filter (05-04) and the web-push filter (05-03) import it, so the two
surfaces can never disagree about what a category covers -- mirroring notify()'s
single-write-path discipline (NOTIF-00).

Mute semantics (D-04/D-05): a user mutes whole category GROUPS, not individual
types. Presence of a NotificationMute row means that group is muted; a user with
no rows is fully unmuted (the default). Types outside CATEGORY_TYPES are always
shown and never mutable this phase (owner default #1) -- granular per-type mute is
a deferred idea.
"""
from django.db import models
from django.utils import timezone


class NotificationCategory(models.TextChoices):
    """The three mute groups (D-04). Values are stored in NotificationMute.category.

    Convention #Types: use TextChoices, never hand-rolled status strings.
    """
    ROOM = "room", "Room events"
    REPORTS = "reports", "Reports"
    SYSTEM = "system", "System"


# Phase 5<->6 contract (owner default #2): defined now so the map + push filter
# are complete. Phase 6's weekly-report job imports this constant and emits rows
# of this type; its push simply won't fire until Phase 6 emits them.
WEEKLY_REPORT_READY = "weekly_report_ready"


# The single source of truth (D-06). Each notify() type string below was verified
# to exist in-repo:
#   room_event                     -> web/scan.py, web/tests.py (wrong-room + force-handover both use it)
#   room_conflict                  -> scheduling/jobs.py detect_room_conflicts
#   job_failed                     -> ops/jobrun.py run_job failure alert
#   modality_materialize_no_room   -> scheduling/.../materialize_sessions.py
# WEEKLY_REPORT_READY lands with Phase 6 (contract defined here).
#
# Types intentionally NOT in any group (owner default #1: always-shown /
# never-mutable this phase): checker_flag, checker_replay_conflict, online_no_link,
# online_unassigned, online_assigned, and the five modality_shift_* types. Do not
# add them to a group -- granular mute is a deferred idea.
CATEGORY_TYPES = {
    NotificationCategory.ROOM: {"room_event", "room_conflict"},
    NotificationCategory.REPORTS: {WEEKLY_REPORT_READY},
    NotificationCategory.SYSTEM: {"job_failed", "modality_materialize_no_room"},
}

# Reverse map DERIVED from the forward map so it can never drift (D-06). Never
# hand-maintain this.
TYPE_CATEGORY = {t: c for c, ts in CATEGORY_TYPES.items() for t in ts}

# The events that also fire a web push (D-08 key events). wrong-room and
# force-handover both notify with type room_event, so a single entry covers them.
PUSH_TYPES = {"room_event", "room_conflict", WEEKLY_REPORT_READY}


def muted_types(user):
    """Return the set of notify() type strings this user has muted (NOTIF-03).

    Reads the user's muted category values and unions the types each group covers.
    `.get(cat, set())` means an unknown/legacy stored category contributes nothing
    (T-05-02), and a type outside CATEGORY_TYPES can never enter the muted set
    (owner default #1). A user with no NotificationMute rows returns an empty set
    -- default-unmuted (D-05).
    """
    cats = user.notification_mutes.values_list("category", flat=True)
    muted = set()
    for cat in cats:
        muted |= CATEGORY_TYPES.get(cat, set())
    return muted


def visible_qs(user):
    """The user's notifications minus their muted types, newest first (NOTIF-01).

    Scoped to `user.notifications` only -- no PK-addressed cross-user access
    (T-05-01).
    """
    return user.notifications.exclude(
        type__in=muted_types(user)).order_by("-created_at")


def unread_count(user):
    """Count of unread (read_at IS NULL) notifications among the visible ones.

    Backs the unread badge (NOTIF-01); muted categories drop out of the count
    because they are excluded by visible_qs. Uses the (user, read_at) index.
    """
    return visible_qs(user).filter(read_at__isnull=True).count()


def _mark_read(qs):
    """Bulk-mark the still-unread rows in `qs` as read, returning the row count.

    Writes NO AuditLog: the notification read surface is audit-silent, mirroring
    notify()'s own deliberate no-audit rule (NOTIF-00). This is a sanctioned
    exception to Convention rule #2 (AuditLog on every write), not an oversight --
    a read receipt is not a domain state change worth auditing.
    """
    return qs.filter(read_at__isnull=True).update(read_at=timezone.now())

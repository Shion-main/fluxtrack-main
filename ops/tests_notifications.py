"""Tests for the notification map + mute/visibility helpers (NOTIF-01/03, D-06).

Locks the single-source guarantees of ops/notifications.py:
- The category->type map is a partition (no type in two groups) and TYPE_CATEGORY
  is derived-from-forward (never drifts).
- WEEKLY_REPORT_READY is the Phase 5<->6 contract constant (owner default #2).
- Default is everything-unmuted (D-05); unmapped types are always shown and never
  mutable this phase (owner default #1).
- visible_qs / unread_count filter muted types and count only read_at IS NULL.

Run via the Django test runner: py -3.12 manage.py test ops.tests_notifications.
ASCII-only assertions (Windows cp1252).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from ops.models import Notification, NotificationMute
from ops.notifications import (
    CATEGORY_TYPES,
    GUARD_FLOOR_ALERT,
    PUSH_TYPES,
    TYPE_CATEGORY,
    WEEKLY_REPORT_READY,
    NotificationCategory,
    muted_types,
    unread_count,
    visible_qs,
)


class MapInvariantTests(TestCase):
    """(a) Partition invariant + (b) contract constants — pure, no DB rows."""

    def test_partition_no_type_in_two_groups(self):
        # Every mapped type belongs to exactly one category group (D-06).
        seen = []
        for types in CATEGORY_TYPES.values():
            seen += list(types)
        self.assertEqual(
            len(seen), len(set(seen)),
            "a notify() type appears in more than one CATEGORY_TYPES group")

    def test_type_category_derived_one_entry_per_type(self):
        # TYPE_CATEGORY is the reverse map: one entry per mapped type, and each
        # points back at the group that contains it.
        total_mapped = sum(len(t) for t in CATEGORY_TYPES.values())
        self.assertEqual(len(TYPE_CATEGORY), total_mapped)
        for cat, types in CATEGORY_TYPES.items():
            for t in types:
                self.assertEqual(TYPE_CATEGORY[t], cat)

    def test_three_groups_exactly(self):
        self.assertEqual(
            set(CATEGORY_TYPES.keys()),
            {NotificationCategory.ROOM, NotificationCategory.REPORTS,
             NotificationCategory.SYSTEM})

    def test_weekly_report_ready_contract(self):
        # owner default #2: define the Phase 5<->6 contract string now.
        self.assertEqual(WEEKLY_REPORT_READY, "weekly_report_ready")
        self.assertIn(
            WEEKLY_REPORT_READY, CATEGORY_TYPES[NotificationCategory.REPORTS])
        self.assertIn(WEEKLY_REPORT_READY, PUSH_TYPES)

    def test_push_types_are_the_key_events(self):
        # D-08 key push events; wrong-room and force-handover both use room_event.
        # guard_floor_alert joined the set in 07-12 (GRD-04 / D-21).
        self.assertEqual(
            PUSH_TYPES,
            {"room_event", "room_conflict", "weekly_report_ready",
             "guard_floor_alert"})


class GuardAlertTypeRegistrationTests(TestCase):
    """GRD-04 / D-21: the guard floor alert must BOTH push AND be mutable.

    This class exists to fail loudly if a future plan adds a notify() type
    without registering it in both maps. The two half-registered states are
    genuinely confusing to debug:

      - in PUSH_TYPES but in no CATEGORY_TYPES group -> `muted_types` does
        `CATEGORY_TYPES.get(cat, set())`, so the type can never enter the muted
        set: it is structurally UNMUTABLE and a guard cannot turn it off.
      - in neither -> `send_push_outbox` filters `type__in=PUSH_TYPES`, so the
        rows render in the bell, never push, and leave `pushed_at` NULL until
        they age out of the send window. The symptom reads as a VAPID
        misconfiguration and is not.

    Any new type added by a later plan should join this assertion set.
    """

    def test_constant_value(self):
        self.assertEqual(GUARD_FLOOR_ALERT, "guard_floor_alert")

    def test_registered_in_push_types(self):
        # Without this the alert writes bell rows that never push (D-21).
        self.assertIn(GUARD_FLOOR_ALERT, PUSH_TYPES)

    def test_belongs_to_exactly_one_category_group(self):
        # ROOM: both GRD-04 triggers are room events, and they sit beside the
        # room_event / room_conflict types a guard already sees.
        holders = [cat for cat, types in CATEGORY_TYPES.items()
                   if GUARD_FLOOR_ALERT in types]
        self.assertEqual(holders, [NotificationCategory.ROOM])

    def test_type_category_resolves_the_new_type(self):
        # TYPE_CATEGORY is DERIVED from CATEGORY_TYPES -- never hand-edited.
        self.assertEqual(
            TYPE_CATEGORY[GUARD_FLOOR_ALERT], NotificationCategory.ROOM)

    def test_muting_room_mutes_the_guard_alert(self):
        User = get_user_model()
        guard = User.objects.create(username="grd_mute")
        NotificationMute.objects.create(
            user=guard, category=NotificationCategory.ROOM)
        self.assertIn(GUARD_FLOOR_ALERT, muted_types(guard))

    def test_unmuted_user_does_not_have_it_muted(self):
        User = get_user_model()
        guard = User.objects.create(username="grd_unmuted")
        self.assertNotIn(GUARD_FLOOR_ALERT, muted_types(guard))


class MutedTypesTests(TestCase):
    """(c) default-unmuted + (d) mute suppresses + (e) unmapped-always-shown."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="fac1")

    def test_default_unmuted_empty_set(self):
        # (c) D-05: a fresh user with no NotificationMute rows mutes nothing.
        self.assertEqual(muted_types(self.user), set())

    def test_mute_room_hides_room_types(self):
        # (d) muting ROOM covers room_event, room_conflict and (since 07-12)
        # the GRD-04 guard floor alert.
        NotificationMute.objects.create(
            user=self.user, category=NotificationCategory.ROOM)
        self.assertEqual(
            muted_types(self.user),
            {"room_event", "room_conflict", "guard_floor_alert"})

    def test_unmapped_type_never_muted(self):
        # (e) owner #1: unmapped types stay always-shown even when every
        # category is muted.
        for cat in NotificationCategory:
            NotificationMute.objects.create(user=self.user, category=cat)
        muted = muted_types(self.user)
        self.assertNotIn("checker_flag", muted)
        self.assertNotIn("modality_shift_approved", muted)

    def test_unknown_stored_category_mutes_nothing(self):
        # T-05-02: a stored category outside the map contributes nothing.
        NotificationMute.objects.create(user=self.user, category="bogus")
        self.assertEqual(muted_types(self.user), set())


class VisibleQsTests(TestCase):
    """(c)/(d)/(e) at the queryset level + (f) unread_count."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="fac2")

    def _mk(self, type, read=False):
        n = Notification.objects.create(
            user=self.user, type=type, title=type)
        if read:
            from django.utils import timezone
            n.read_at = timezone.now()
            n.save(update_fields=["read_at"])
        return n

    def test_default_shows_all(self):
        # (c) with no mutes, visible_qs returns every notification.
        self._mk("room_event")
        self._mk("job_failed")
        self.assertEqual(visible_qs(self.user).count(), 2)

    def test_mute_room_excludes_room_event_keeps_system(self):
        # (d) room_event hidden, job_failed still visible.
        self._mk("room_event")
        self._mk("job_failed")
        NotificationMute.objects.create(
            user=self.user, category=NotificationCategory.ROOM)
        visible = list(visible_qs(self.user).values_list("type", flat=True))
        self.assertNotIn("room_event", visible)
        self.assertIn("job_failed", visible)

    def test_unmapped_always_in_visible_qs(self):
        # (e) owner #1: unmapped types survive muting all categories.
        self._mk("checker_flag")
        self._mk("modality_shift_approved")
        for cat in NotificationCategory:
            NotificationMute.objects.create(user=self.user, category=cat)
        visible = set(visible_qs(self.user).values_list("type", flat=True))
        self.assertIn("checker_flag", visible)
        self.assertIn("modality_shift_approved", visible)

    def test_visible_qs_ordered_desc(self):
        self._mk("room_event")
        self._mk("job_failed")
        qs = list(visible_qs(self.user))
        self.assertGreaterEqual(qs[0].created_at, qs[-1].created_at)

    def test_unread_count_counts_only_unread_visible(self):
        # (f) counts read_at IS NULL among visible rows.
        self._mk("room_event", read=False)
        self._mk("room_event", read=True)
        self._mk("job_failed", read=False)
        self.assertEqual(unread_count(self.user), 2)

    def test_unread_count_drops_when_category_muted(self):
        # (f) muting a category removes its unread rows from the badge count.
        self._mk("room_event", read=False)
        self._mk("job_failed", read=False)
        self.assertEqual(unread_count(self.user), 2)
        NotificationMute.objects.create(
            user=self.user, category=NotificationCategory.ROOM)
        self.assertEqual(unread_count(self.user), 1)

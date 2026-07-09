"""Read-surface tests for the notification bell, dropdown, list, and mute
settings (NOTIF-01/NOTIF-03).

Locks the D-02/D-03 read semantics (poll never marks read; open does), the
audit-silent contract (no AuditLog rows on a read), the D-05 mute suppression
(muted categories drop out, unmapped types stay), and per-user scoping
(T-05-09: a user never sees another user's notifications). ASCII-only.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from ops.models import AuditLog, Notification, NotificationMute
from ops.notifications import NotificationCategory, unread_count


def _notify(user, type_, title):
    return Notification.objects.create(user=user, type=type_, title=title)


class BadgeVisibilityTests(TestCase):
    """The badge counts unread VISIBLE rows and excludes muted categories (D-02/D-05)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="bell_user", role=Role.IFO_ADMIN)
        self.client.force_login(self.user)

    def test_badge_counts_unread_visible(self):
        _notify(self.user, "room_event", "R1")
        _notify(self.user, "checker_flag", "C1")  # unmapped, always shown
        resp = self.client.get(reverse("notif_bell"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["unread"], 2)

    def test_badge_excludes_muted_category(self):
        _notify(self.user, "room_event", "R1")   # ROOM group
        _notify(self.user, "checker_flag", "C1")  # unmapped
        NotificationMute.objects.create(
            user=self.user, category=NotificationCategory.ROOM)
        resp = self.client.get(reverse("notif_bell"))
        # room_event muted out; only the unmapped row remains counted.
        self.assertEqual(resp.context["unread"], 1)


class PollNeverMarksReadTests(TestCase):
    """GET /notifications/bell is READ-ONLY: it must not clear the badge (D-02)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="poll_user", role=Role.IFO_ADMIN)
        self.client.force_login(self.user)

    def test_bell_does_not_mark_read(self):
        _notify(self.user, "room_event", "R1")
        _notify(self.user, "checker_flag", "C1")
        self.assertEqual(unread_count(self.user), 2)
        self.client.get(reverse("notif_bell"))
        self.client.get(reverse("notif_bell"))
        # Poll twice: read_at stays NULL, badge unchanged.
        self.assertEqual(unread_count(self.user), 2)
        self.assertFalse(
            Notification.objects.filter(user=self.user,
                                        read_at__isnull=False).exists())


class AutoReadOnOpenTests(TestCase):
    """Opening the dropdown or the full page marks shown rows read (D-03)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="open_user", role=Role.IFO_ADMIN)
        self.client.force_login(self.user)

    def test_dropdown_open_clears_badge(self):
        _notify(self.user, "room_event", "R1")
        _notify(self.user, "checker_flag", "C1")
        self.assertEqual(unread_count(self.user), 2)
        self.client.get(reverse("notif_dropdown"))
        self.assertEqual(unread_count(self.user), 0)

    def test_list_open_clears_badge(self):
        _notify(self.user, "room_event", "R1")
        _notify(self.user, "job_failed", "J1")
        self.assertEqual(unread_count(self.user), 2)
        self.client.get(reverse("notifications"))
        self.assertEqual(unread_count(self.user), 0)


class ReadSurfaceIsAuditSilentTests(TestCase):
    """Mark-read on open writes NO AuditLog (deliberate, mirrors notify())."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="audit_user", role=Role.IFO_ADMIN)
        self.client.force_login(self.user)

    def test_open_writes_no_auditlog(self):
        _notify(self.user, "room_event", "R1")
        _notify(self.user, "checker_flag", "C1")
        before = AuditLog.objects.count()
        self.client.get(reverse("notif_dropdown"))
        self.client.get(reverse("notifications"))
        self.assertEqual(AuditLog.objects.count(), before)


class MuteSuppressesListTests(TestCase):
    """Muting ROOM via POST removes room_event rows; unmapped types stay (D-05, owner #1)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="mute_user", role=Role.IFO_ADMIN)
        self.client.force_login(self.user)

    def test_mute_room_removes_room_rows_keeps_unmapped(self):
        _notify(self.user, "room_event", "ROOM ROW")
        _notify(self.user, "checker_flag", "CHECKER ROW")
        # Toggle ROOM on (presence = muted).
        resp = self.client.post(reverse("notif_mute"),
                                {"category": NotificationCategory.ROOM.value})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(NotificationMute.objects.filter(
            user=self.user, category=NotificationCategory.ROOM).exists())
        page = self.client.get(reverse("notifications"))
        self.assertNotContains(page, "ROOM ROW")
        self.assertContains(page, "CHECKER ROW")

    def test_mute_toggle_is_presence_based(self):
        # Second toggle removes the row (unmutes).
        self.client.post(reverse("notif_mute"),
                         {"category": NotificationCategory.ROOM.value})
        self.client.post(reverse("notif_mute"),
                         {"category": NotificationCategory.ROOM.value})
        self.assertFalse(NotificationMute.objects.filter(
            user=self.user, category=NotificationCategory.ROOM).exists())

    def test_mute_toggle_rejects_unknown_category(self):
        resp = self.client.post(reverse("notif_mute"), {"category": "bogus"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(NotificationMute.objects.filter(user=self.user).count(), 0)

    def test_mute_toggle_requires_post(self):
        resp = self.client.get(reverse("notif_mute"))
        self.assertEqual(resp.status_code, 405)


class AccessControlTests(TestCase):
    """Every endpoint requires login and is strictly per-user (T-05-09)."""

    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create(username="owner", role=Role.IFO_ADMIN)
        self.other = User.objects.create(username="other", role=Role.IFO_ADMIN)

    def test_endpoints_require_login(self):
        for name in ["notif_bell", "notif_dropdown", "notifications",
                     "notif_settings"]:
            resp = self.client.get(reverse(name))
            self.assertEqual(resp.status_code, 302, name)
            self.assertIn("/login", resp["Location"], name)

    def test_never_returns_another_users_rows(self):
        _notify(self.other, "room_event", "SECRET OTHER ROW")
        self.client.force_login(self.owner)
        self.assertEqual(unread_count(self.owner), 0)
        page = self.client.get(reverse("notifications"))
        self.assertNotContains(page, "SECRET OTHER ROW")
        drop = self.client.get(reverse("notif_dropdown"))
        self.assertNotContains(drop, "SECRET OTHER ROW")
        # Opening the owner's surface must not mark the OTHER user's row read.
        self.assertEqual(unread_count(self.other), 1)

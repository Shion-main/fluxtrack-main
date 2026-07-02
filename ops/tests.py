"""Tests for ops services (SRS §5).

NOTIF-00 — the single Notification write path `ops.notify.notify`:
- NotifyTests: role fan-out reaches ACTIVE users of a role only, explicit-user
  targeting, empty-target no-op, and that notify() writes no AuditLog.
- SingleWritePathTests: a source guard proving the ad-hoc IFO notifier helper is
  gone from web/scan.py and that no notifier module constructs Notification rows
  inline outside ops/notify.py.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Role
from ops.models import AuditLog, Notification


class NotifyTests(TestCase):
    """notify(role=...) fans out to ACTIVE users of that role only; notify(users=...)
    targets an explicit iterable; neither target creates nothing (NOTIF-00).

    Guards T-02-03: the recipient query must reproduce the old _notify_ifo filter
    (role match + is_active=True) so inactive/other-role accounts never receive rows.
    """

    def setUp(self):
        User = get_user_model()
        self.ifo1 = User.objects.create(username="ifo1", role=Role.IFO_ADMIN)
        self.ifo2 = User.objects.create(username="ifo2", role=Role.IFO_ADMIN)
        self.ifo_inactive = User.objects.create(
            username="ifo3", role=Role.IFO_ADMIN, is_active=False)
        self.faculty = User.objects.create(username="fac1", role=Role.FACULTY)

    def test_role_fanout_targets_active_users_only(self):
        from ops.notify import notify
        rows = notify(role=Role.IFO_ADMIN, type="room_event", title="t", body="b")
        self.assertEqual(len(rows), 2)
        recipients = {n.user_id for n in Notification.objects.all()}
        self.assertEqual(recipients, {self.ifo1.pk, self.ifo2.pk})
        self.assertNotIn(self.ifo_inactive.pk, recipients)
        self.assertNotIn(self.faculty.pk, recipients)

    def test_role_fanout_sets_fields(self):
        from ops.notify import notify
        notify(role=Role.IFO_ADMIN, type="room_event", title="Room change",
               body="body text", link="/x")
        n = Notification.objects.filter(user=self.ifo1).first()
        self.assertIsNotNone(n)
        self.assertEqual(n.type, "room_event")
        self.assertEqual(n.title, "Room change")
        self.assertEqual(n.body, "body text")
        self.assertEqual(n.link, "/x")

    def test_explicit_users_target_creates_one_row_each(self):
        from ops.notify import notify
        rows = notify(users=[self.faculty], type="x", title="t")
        self.assertEqual(len(rows), 1)
        self.assertEqual(Notification.objects.filter(user=self.faculty).count(), 1)

    def test_no_target_creates_nothing(self):
        from ops.notify import notify
        rows = notify(type="x", title="t")
        self.assertEqual(rows, [])
        self.assertEqual(Notification.objects.count(), 0)

    def test_notify_emits_no_auditlog(self):
        from ops.notify import notify
        before = AuditLog.objects.count()
        notify(role=Role.IFO_ADMIN, type="room_event", title="t")
        self.assertEqual(AuditLog.objects.count(), before)


class SingleWritePathTests(TestCase):
    """Source guard (T-02-04): every Notification row is created in exactly one
    place — ops/notify.py. The ad-hoc IFO notifier helper must be gone from
    web/scan.py, and no notifier module may construct Notification rows inline.

    The forbidden tokens are assembled from parts so this guard can never match
    its own source; only named notifier modules (never this test file) are read.
    """

    # Assembled from parts on purpose — keeps the guard from matching itself.
    _CREATE_TOKEN = "Notification.objects" + ".create"
    _HELPER_TOKEN = "_notify" + "_ifo"

    # Modules permitted to be scanned as notifier call sites (never the test file).
    NOTIFIER_MODULES = ["web/scan.py", "scheduling/jobs.py"]

    def _read(self, rel):
        return (Path(settings.BASE_DIR) / rel).read_text(encoding="utf-8")

    def test_adhoc_ifo_notifier_helper_removed_from_scan(self):
        src = self._read("web/scan.py")
        self.assertNotIn("def " + self._HELPER_TOKEN, src,
                         "web/scan.py still defines the ad-hoc IFO notifier helper")

    def test_no_inline_notification_create_outside_notify_module(self):
        for rel in self.NOTIFIER_MODULES:
            path = Path(settings.BASE_DIR) / rel
            if not path.exists():
                continue
            src = path.read_text(encoding="utf-8")
            self.assertNotIn(
                self._CREATE_TOKEN, src,
                f"{rel} constructs Notification rows inline; route through "
                "ops.notify.notify (NOTIF-00 single write path)")

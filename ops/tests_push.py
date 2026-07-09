"""Mocked-webpush tests for the push outbox sender (NOTIF-02/03, criterion #4).

Locks the D-08/D-09 push guarantees of ops/push.py with ZERO real network I/O
(ops.push.webpush is patched in every case):
- (a) A key-event row (PUSH_TYPES) + one subscription is sent once and stamped;
      a second pass sends nothing (pushed_at set -> never re-sent).
- (b) A dead endpoint (WebPushException 404/410) is pruned and the pass never
      raises; pushed_at is still stamped (D-09).
- (c) A transient failure (5xx) keeps the subscription for a later pass (T-05-08).
- (d) A muted category suppresses the send but still stamps pushed_at (D-05).
- (e) A non-key type (checker_flag) is never selected (D-08).
- (f) run_job wraps a raising sender: status=failed, no re-raise (criterion #4).

VAPID is enabled via override_settings so the sender is not short-circuited.
Run via the Django test runner: py -3.12 manage.py test ops.tests_push.
ASCII-only assertions (Windows cp1252).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from pywebpush import WebPushException

from ops.jobrun import run_job
from ops.models import Notification, NotificationMute, PushSubscription
from ops.notifications import NotificationCategory
from ops.push import send_push_outbox


def _resp(status):
    """Minimal stand-in for a requests.Response carrying just a status_code."""
    r = mock.Mock()
    r.status_code = status
    return r


@override_settings(
    VAPID_PRIVATE_KEY_PATH="keys/private_key.pem",
    VAPID_SUB="mailto:admin@example.com",
)
class PushOutboxTests(TestCase):
    """send + prune + mute + key-type filtering, all with webpush mocked."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="fac_push")
        self.sub = PushSubscription.objects.create(
            user=self.user,
            endpoint="https://push.example.com/ep-1",
            keys={"p256dh": "k", "auth": "a"},
        )

    def _mk(self, type="room_event"):
        return Notification.objects.create(
            user=self.user, type=type, title="t", body="b", link="/x")

    def test_success_sends_once_and_stamps(self):
        # (a) one key-event row + one subscription -> one webpush call, stamped.
        n = self._mk()
        with mock.patch("ops.push.webpush") as wp:
            sent = send_push_outbox()
        self.assertEqual(sent, 1, "one key-event row should be counted as sent")
        self.assertEqual(wp.call_count, 1, "webpush should be called exactly once")
        n.refresh_from_db()
        self.assertIsNotNone(n.pushed_at, "pushed_at must be stamped after send")
        # Second pass: pushed_at is set, so nothing is left to send.
        with mock.patch("ops.push.webpush") as wp2:
            self.assertEqual(send_push_outbox(), 0, "stamped row must not re-send")
            wp2.assert_not_called()

    def test_prune_on_410(self):
        # (b) D-09: a 410 dead endpoint is deleted; the pass never raises.
        n = self._mk()
        exc = WebPushException("gone", response=_resp(410))
        with mock.patch("ops.push.webpush", side_effect=exc):
            sent = send_push_outbox()
        self.assertEqual(sent, 1)
        self.assertFalse(
            PushSubscription.objects.filter(pk=self.sub.pk).exists(),
            "dead endpoint (410) must be pruned")
        n.refresh_from_db()
        self.assertIsNotNone(n.pushed_at, "row is stamped even when endpoint died")

    def test_prune_on_404(self):
        # (b) D-09: 404 is also a dead endpoint -> prune.
        self._mk()
        exc = WebPushException("not found", response=_resp(404))
        with mock.patch("ops.push.webpush", side_effect=exc):
            send_push_outbox()
        self.assertFalse(
            PushSubscription.objects.filter(pk=self.sub.pk).exists(),
            "dead endpoint (404) must be pruned")

    def test_transient_500_keeps_subscription(self):
        # (c) T-05-08: a transient 5xx must NOT drop a live subscription.
        n = self._mk()
        exc = WebPushException("boom", response=_resp(500))
        with mock.patch("ops.push.webpush", side_effect=exc):
            sent = send_push_outbox()
        self.assertEqual(sent, 1)
        self.assertTrue(
            PushSubscription.objects.filter(pk=self.sub.pk).exists(),
            "transient 500 must keep the subscription for a later pass")
        n.refresh_from_db()
        self.assertIsNotNone(n.pushed_at)

    def test_transient_no_response_keeps_subscription(self):
        # (c) A transport failure with response=None (timeout-like) must not prune.
        self._mk()
        exc = WebPushException("network", response=None)
        with mock.patch("ops.push.webpush", side_effect=exc):
            send_push_outbox()
        self.assertTrue(
            PushSubscription.objects.filter(pk=self.sub.pk).exists(),
            "a status-less failure must not prune the subscription")

    def test_mute_suppresses_send_but_stamps(self):
        # (d) D-05: recipient muted ROOM -> room_event is NOT pushed, but stamped.
        NotificationMute.objects.create(
            user=self.user, category=NotificationCategory.ROOM)
        n = self._mk("room_event")
        with mock.patch("ops.push.webpush") as wp:
            sent = send_push_outbox()
        wp.assert_not_called()
        self.assertEqual(sent, 0, "a muted row is stamped, not counted as sent")
        n.refresh_from_db()
        self.assertIsNotNone(n.pushed_at, "muted row must still be stamped (D-05)")

    def test_non_key_type_ignored(self):
        # (e) D-08: checker_flag is not in PUSH_TYPES -> never selected or sent.
        n = self._mk("checker_flag")
        with mock.patch("ops.push.webpush") as wp:
            sent = send_push_outbox()
        wp.assert_not_called()
        self.assertEqual(sent, 0)
        n.refresh_from_db()
        self.assertIsNone(
            n.pushed_at, "a non-key type must not be selected or stamped")

    @override_settings(VAPID_PRIVATE_KEY_PATH="")
    def test_disabled_when_vapid_unconfigured(self):
        # Empty key path means push is disabled -> short-circuit, no send.
        self._mk()
        with mock.patch("ops.push.webpush") as wp:
            self.assertEqual(send_push_outbox(), 0)
            wp.assert_not_called()


class RunJobNoRaiseTests(TestCase):
    """(f) Criterion #4: run_job records failed and never re-raises."""

    def test_raising_sender_records_failed_without_propagating(self):
        def boom():
            raise RuntimeError("push exploded")

        # Must NOT propagate -- the BlockingScheduler has to survive a bad pass.
        run = run_job("push_outbox", boom)
        self.assertEqual(
            run.status, "failed", "a raising job must record status=failed")
        self.assertIsNotNone(run.finished_at, "failed run must still be finalized")

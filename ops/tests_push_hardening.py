"""Push destination and retry regressions; never perform network requests."""
import base64
from datetime import timedelta
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from pywebpush import WebPushException

from ops.models import Notification, PushSubscription
from ops.push import send_push_outbox


def subscription_keys():
    public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return {"p256dh": encode(public), "auth": encode(b"a" * 16)}


class PushDestinationTests(SimpleTestCase):
    def test_only_supported_provider_endpoints_are_accepted(self):
        from ops.push_validation import valid_subscription
        keys = subscription_keys()
        self.assertTrue(valid_subscription("https://fcm.googleapis.com/fcm/send/token", keys))
        for endpoint in ("https://127.0.0.1/x", "https://localhost/x",
                         "https://10.0.0.1/x", "https://push.example.com/x",
                         "https://fcm.googleapis.com.evil.test/x",
                         "https://fcm.googleapis.com:8443/x",
                         "https://user@fcm.googleapis.com/x"):
            self.assertFalse(valid_subscription(endpoint, keys), endpoint)

    def test_malformed_keys_are_rejected(self):
        from ops.push_validation import valid_subscription
        self.assertFalse(valid_subscription("https://fcm.googleapis.com/fcm/send/x",
                                            {"p256dh": "k", "auth": "a"}))


@override_settings(VAPID_PRIVATE_KEY_PATH="keys/test.pem", VAPID_SUB="mailto:test@example.com")
class PushRetryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="retry-push")
        self.sub = PushSubscription.objects.create(user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/retry", keys=subscription_keys())
        self.n = Notification.objects.create(user=self.user, type="room_event", title="Retry")

    def test_transport_failure_remains_pending_and_retries(self):
        with patch("ops.push.webpush", side_effect=WebPushException("timeout")):
            self.assertEqual(send_push_outbox(), 0)
        self.n.refresh_from_db()
        self.assertIsNone(self.n.pushed_at)
        self.assertEqual(self.n.push_attempts, 1)
        self.assertIsNotNone(self.n.next_push_at)
        Notification.objects.filter(pk=self.n.pk).update(next_push_at=timezone.now()-timedelta(seconds=1))
        with patch("ops.push.webpush") as sender:
            self.assertEqual(send_push_outbox(), 1)
        sender.assert_called_once()
        self.n.refresh_from_db()
        self.assertIsNotNone(self.n.pushed_at)

    def test_pending_notifications_older_than_fifteen_minutes_are_sent(self):
        Notification.objects.filter(pk=self.n.pk).update(created_at=timezone.now()-timedelta(hours=1))
        with patch("ops.push.webpush") as sender:
            self.assertEqual(send_push_outbox(), 1)
        sender.assert_called_once()

    def test_invalid_legacy_destination_never_reaches_transport(self):
        self.sub.endpoint = "https://127.0.0.1/private"
        self.sub.save()
        with patch("ops.push.webpush") as sender:
            send_push_outbox()
        sender.assert_not_called()

    def test_successful_endpoint_is_not_repeated_when_another_retries(self):
        second = PushSubscription.objects.create(user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/second", keys=subscription_keys())
        def send(**kwargs):
            if kwargs["subscription_info"]["endpoint"] == second.endpoint:
                raise WebPushException("temporary")
        with patch("ops.push.webpush", side_effect=send):
            send_push_outbox()
        Notification.objects.filter(pk=self.n.pk).update(next_push_at=timezone.now()-timedelta(seconds=1))
        with patch("ops.push.webpush") as sender:
            send_push_outbox()
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(sender.call_args.kwargs["subscription_info"]["endpoint"], second.endpoint)

    def test_sender_disables_redirects(self):
        from ops.push import ProviderSession
        session = ProviderSession()
        response = Mock(status_code=302)
        with patch("requests.Session.request", return_value=response) as request:
            session.post(self.sub.endpoint, data=b"test")
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    def test_permanent_failure_remains_visible_after_other_device_retry(self):
        PushSubscription.objects.create(user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/second", keys=subscription_keys())
        with patch("ops.push._send_one", side_effect=["permanent", "retry"]):
            send_push_outbox()
        Notification.objects.filter(pk=self.n.pk).update(next_push_at=timezone.now()-timedelta(seconds=1))
        with patch("ops.push._send_one", return_value="delivered"):
            send_push_outbox()
        self.n.refresh_from_db()
        self.assertEqual(self.n.push_error, "permanent failure")

    def test_attempt_limit_and_expiry_are_terminal(self):
        Notification.objects.filter(pk=self.n.pk).update(push_attempts=5)
        with patch("ops.push._send_one", return_value="retry"):
            send_push_outbox()
        self.n.refresh_from_db()
        self.assertIsNotNone(self.n.pushed_at)
        self.assertEqual(self.n.push_error, "attempt limit")
        Notification.objects.filter(pk=self.n.pk).update(pushed_at=None,
            created_at=timezone.now()-timedelta(days=2))
        with patch("ops.push._send_one") as sender:
            send_push_outbox()
        sender.assert_not_called()
        self.n.refresh_from_db()
        self.assertEqual(self.n.push_error, "expired")

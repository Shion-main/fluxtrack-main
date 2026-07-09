"""Web-layer push tests (NOTIF-02): the subscribe/unsubscribe endpoints and the
bell mount in both shells (D-01).

Locks the subscribe persistence + endpoint dedup (Pitfall 6), payload validation
(T-05-14: https endpoint + p256dh/auth keys required), login-required scoping
(T-05-09), and that an authenticated page in EACH shell renders the bell mount
markup (D-01). ASCII-only.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from ops.models import PushSubscription

_VALID = {
    "endpoint": "https://push.example.com/ep/abc123",
    "keys": {"p256dh": "BPk_key_material", "auth": "auth_secret"},
}


class SubscribePersistTests(TestCase):
    """POST subscribe persists exactly one row and dedups on endpoint (Pitfall 6)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="push_sub", role=Role.FACULTY)
        self.client.force_login(self.user)

    def _post(self, payload):
        return self.client.post(
            reverse("push_subscribe"), data=json.dumps(payload),
            content_type="application/json")

    def test_valid_payload_creates_one_subscription(self):
        resp = self._post(_VALID)
        self.assertEqual(resp.status_code, 200)
        rows = PushSubscription.objects.filter(user=self.user)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().endpoint, _VALID["endpoint"])
        self.assertEqual(rows.first().keys, _VALID["keys"])

    def test_second_post_same_endpoint_updates_not_duplicates(self):
        self._post(_VALID)
        # Re-subscribe the SAME endpoint with refreshed keys -> update, not insert.
        refreshed = {"endpoint": _VALID["endpoint"],
                     "keys": {"p256dh": "NEW_key", "auth": "NEW_auth"}}
        resp = self._post(refreshed)
        self.assertEqual(resp.status_code, 200)
        rows = PushSubscription.objects.filter(endpoint=_VALID["endpoint"])
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().keys, refreshed["keys"])


class SubscribeValidationTests(TestCase):
    """Invalid payloads are rejected 400 and persist nothing (T-05-14)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="push_val", role=Role.FACULTY)
        self.client.force_login(self.user)

    def _post(self, payload):
        return self.client.post(
            reverse("push_subscribe"), data=json.dumps(payload),
            content_type="application/json")

    def test_non_https_endpoint_rejected(self):
        bad = {"endpoint": "http://push.example.com/ep/1", "keys": _VALID["keys"]}
        resp = self._post(bad)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_missing_keys_rejected(self):
        bad = {"endpoint": _VALID["endpoint"], "keys": {"p256dh": "only_one"}}
        resp = self._post(bad)
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())

    def test_empty_body_rejected(self):
        resp = self._post({})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushSubscription.objects.exists())


class UnsubscribeScopingTests(TestCase):
    """unsubscribe removes only the caller's row for the posted endpoint (T-05-09)."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="push_unsub", role=Role.FACULTY)
        self.other = User.objects.create(username="push_other", role=Role.FACULTY)
        self.client.force_login(self.user)

    def test_unsubscribe_deletes_own_row(self):
        PushSubscription.objects.create(
            user=self.user, endpoint=_VALID["endpoint"], keys=_VALID["keys"])
        resp = self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": _VALID["endpoint"]}),
            content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(
            PushSubscription.objects.filter(endpoint=_VALID["endpoint"]).exists())

    def test_unsubscribe_never_deletes_another_users_row(self):
        # Another user owns a row with the same endpoint string.
        PushSubscription.objects.create(
            user=self.other, endpoint=_VALID["endpoint"], keys=_VALID["keys"])
        resp = self.client.post(
            reverse("push_unsubscribe"),
            data=json.dumps({"endpoint": _VALID["endpoint"]}),
            content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        # The other user's row survives -- no cross-user deletion.
        self.assertTrue(
            PushSubscription.objects.filter(user=self.other).exists())


class LoginRequiredTests(TestCase):
    """All push endpoints require an authenticated session."""

    def test_endpoints_redirect_when_anonymous(self):
        for name in ("push_subscribe", "push_unsubscribe"):
            resp = self.client.post(reverse(name), data="{}",
                                    content_type="application/json")
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/login", resp["Location"])
        resp = self.client.get(reverse("push_key"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_key_endpoint_returns_public_key_when_authenticated(self):
        User = get_user_model()
        user = User.objects.create(username="push_key_u", role=Role.FACULTY)
        self.client.force_login(user)
        resp = self.client.get(reverse("push_key"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("key", resp.json())


class BellMountTests(TestCase):
    """The bell partial renders in BOTH shells (D-01)."""

    def test_franken_shell_home_mounts_bell(self):
        User = get_user_model()
        user = User.objects.create(username="ifo_bell", role=Role.IFO_ADMIN)
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="notif-bell"')

    def test_faculty_shell_schedule_mounts_bell(self):
        User = get_user_model()
        user = User.objects.create(username="fac_bell", role=Role.FACULTY)
        self.client.force_login(user)
        resp = self.client.get(reverse("faculty_schedule"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="notif-bell"')

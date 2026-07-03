"""Automated proof for the Entra ID local-dev wiring (Plans 01/02/03).

These tests are the automated half of the D-09 proof and the mitigation
verification for the phase threat register (T-03.1-10/11). They exercise the
security-critical code paths — the PKCE backend, the settings wiring, the
deny/oid pipeline steps, and the link_entra command — with adversarial inputs
(None user, inactive user, clashing UPN) using fake response/details dicts. NO
live Entra call, no network, no browser (D-09 manual round-trip is Plan 05).

Requirement / decision anchors are cited per-test in each docstring
(Conventions §module-docstring): AUTH-01 (PKCE), AUTH-03/AUTH-05
(provisioned-only + inactive refusal), D-05 (azure_oid), D-06/D-09#2 (refusal
path), D-07 (link_entra), D-10 (DRF unchanged).
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from social_core.backends.azuread_tenant import AzureADTenantOAuth2
from social_core.backends.oauth import BaseOAuth2PKCE
from social_core.exceptions import AuthForbidden

from accounts.backends import AzureADTenantOAuth2PKCE
from accounts.models import Role
from accounts.pipeline import deny_unprovisioned, write_azure_oid
from ops.models import AuditLog

User = get_user_model()


class PkceBackendTests(TestCase):
    """The registered Entra backend actually honors PKCE (D-02/AUTH-01, Pitfall 1).

    The stock AzureADTenantOAuth2 does not inherit BaseOAuth2PKCE, so USE_PKCE is
    silently ignored. AzureADTenantOAuth2PKCE mixes BaseOAuth2PKCE in first and
    turns PKCE on by default — closing the silent-no-PKCE landmine.
    """

    def test_is_pkce_and_azure_subclass(self):
        """Subclass identity: BaseOAuth2PKCE (first in MRO) AND AzureADTenantOAuth2."""
        self.assertTrue(issubclass(AzureADTenantOAuth2PKCE, BaseOAuth2PKCE))
        self.assertTrue(issubclass(AzureADTenantOAuth2PKCE, AzureADTenantOAuth2))

    def test_name_unchanged(self):
        """.name stays 'azuread-tenant-oauth2' so the callback URL + setting prefix hold."""
        self.assertEqual(AzureADTenantOAuth2PKCE.name, "azuread-tenant-oauth2")

    def test_pkce_on_by_default(self):
        """DEFAULT_USE_PKCE is True — PKCE is actually emitted (AUTH-01)."""
        self.assertIs(AzureADTenantOAuth2PKCE.DEFAULT_USE_PKCE, True)


class AuthWiringTests(TestCase):
    """The settings wiring that makes the provisioned-only + refusal policy real.

    Guards the Plan 01 blocker fix (refusal path) and the D-10 negative guard
    (DRF auth untouched). All assertions read django.conf.settings directly.
    """

    def test_social_django_installed(self):
        """social_django is an installed app (D-01)."""
        self.assertIn("social_django", settings.INSTALLED_APPS)

    def test_backends_order(self):
        """PKCE backend first (real Entra path), ModelBackend second (break-glass)."""
        self.assertEqual(
            list(settings.AUTHENTICATION_BACKENDS),
            [
                "accounts.backends.AzureADTenantOAuth2PKCE",
                "django.contrib.auth.backends.ModelBackend",
            ],
        )

    def test_pipeline_membership(self):
        """Custom steps present; create_user REMOVED (no auto-provision — AUTH-03)."""
        pipeline = tuple(settings.SOCIAL_AUTH_PIPELINE)
        self.assertIn("accounts.pipeline.deny_unprovisioned", pipeline)
        self.assertIn("accounts.pipeline.write_azure_oid", pipeline)
        self.assertIn("social_core.pipeline.social_auth.associate_by_email", pipeline)
        self.assertNotIn("social_core.pipeline.user.create_user", pipeline)

    def test_refusal_path_middleware_positioned(self):
        """SocialAuthExceptionMiddleware sits after Authentication, before Message (D-06/D-09#2)."""
        mw = list(settings.MIDDLEWARE)
        self.assertIn("social_django.middleware.SocialAuthExceptionMiddleware", mw)
        self.assertLess(
            mw.index("django.contrib.auth.middleware.AuthenticationMiddleware"),
            mw.index("social_django.middleware.SocialAuthExceptionMiddleware"),
        )
        self.assertLess(
            mw.index("social_django.middleware.SocialAuthExceptionMiddleware"),
            mw.index("django.contrib.messages.middleware.MessageMiddleware"),
        )

    def test_raise_exceptions_false(self):
        """A refused login redirects (SOCIAL_AUTH_RAISE_EXCEPTIONS False) rather than 500 (D-06/D-09#2)."""
        self.assertIs(settings.SOCIAL_AUTH_RAISE_EXCEPTIONS, False)

    def test_drf_still_session_auth(self):
        """D-10 negative guard: DRF auth is unchanged — SessionAuthentication only."""
        self.assertIn(
            "rest_framework.authentication.SessionAuthentication",
            settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"],
        )


class DenyUnprovisionedTests(TestCase):
    """deny_unprovisioned refuses unprovisioned/inactive identities (D-06/AUTH-03/AUTH-05).

    Runs after associate_by_email with create_user removed, so user=None means the
    tenant identity matched no seeded slot; an inactive user is a reactivation
    bypass. Both refusals raise AuthForbidden and write an auth.entra_refused
    AuditLog; an active provisioned user passes silently.
    """

    def test_none_user_refused(self):
        """No matching seeded user -> AuthForbidden + auth.entra_refused row (AUTH-03)."""
        with self.assertRaises(AuthForbidden):
            deny_unprovisioned(None, "backend", {"email": "ghost@mcm.edu.ph"}, user=None)
        self.assertTrue(
            AuditLog.objects.filter(event_type="auth.entra_refused").exists()
        )

    def test_inactive_user_refused(self):
        """Deactivated account -> AuthForbidden (AUTH-05 reactivation bypass)."""
        u = User.objects.create(username="gone", email="gone@mcm.edu.ph",
                                role=Role.FACULTY, is_active=False)
        with self.assertRaises(AuthForbidden):
            deny_unprovisioned(None, "backend", {"email": u.email}, user=u)
        self.assertTrue(
            AuditLog.objects.filter(event_type="auth.entra_refused").exists()
        )

    def test_active_user_passes(self):
        """Active provisioned user returns None (pipeline continues) — no refusal row."""
        u = User.objects.create(username="ok", email="ok@mcm.edu.ph",
                                role=Role.FACULTY, is_active=True)
        result = deny_unprovisioned(None, "backend", {"email": u.email}, user=u)
        self.assertIsNone(result)
        self.assertFalse(
            AuditLog.objects.filter(event_type="auth.entra_refused").exists()
        )


class WriteAzureOidTests(TestCase):
    """write_azure_oid persists the durable Entra object id + audits success (D-05).

    Reads response['oid'] explicitly (the social uid is the pairwise sub claim, not
    the oid). Idempotent, no-op on user=None, and writes an auth.entra_login row on
    every non-None-user call.
    """

    OID = "11111111-2222-3333-4444-555555555555"

    def test_sets_azure_oid(self):
        """response['oid'] is persisted to User.azure_oid + an auth.entra_login row (D-05)."""
        u = User.objects.create(username="oiduser", email="oid@mcm.edu.ph",
                                role=Role.FACULTY)
        write_azure_oid(None, "backend", {}, {"oid": self.OID}, user=u)
        u.refresh_from_db()
        self.assertEqual(u.azure_oid, self.OID)
        self.assertTrue(
            AuditLog.objects.filter(event_type="auth.entra_login", actor=u).exists()
        )

    def test_idempotent(self):
        """A second call with the same oid does not error and keeps a single value."""
        u = User.objects.create(username="oiduser2", email="oid2@mcm.edu.ph",
                                role=Role.FACULTY)
        write_azure_oid(None, "backend", {}, {"oid": self.OID}, user=u)
        write_azure_oid(None, "backend", {}, {"oid": self.OID}, user=u)
        u.refresh_from_db()
        self.assertEqual(u.azure_oid, self.OID)

    def test_none_user_noop(self):
        """user=None is a safe no-op (no AuditLog, no crash)."""
        write_azure_oid(None, "backend", {}, {"oid": self.OID}, user=None)
        self.assertFalse(AuditLog.objects.filter(event_type="auth.entra_login").exists())


class LinkEntraCommandTests(TestCase):
    """link_entra binds a seeded slot to a real UPN, idempotently (D-07).

    Repoints email so the first Entra login's associate_by_email matches. Reversible
    and idempotent; rejects an invalid UPN and a UPN already held by another user.
    """

    def setUp(self):
        self.mayo = User.objects.create(username="mayo", email="mayo@mcm.edu.ph",
                                        role=Role.FACULTY)

    def test_updates_email(self):
        """link_entra repoints the seeded user's email to the real UPN (D-07)."""
        call_command("link_entra", "mayo", "jane.mayo@mcm.edu.ph")
        self.mayo.refresh_from_db()
        self.assertEqual(self.mayo.email, "jane.mayo@mcm.edu.ph")

    def test_idempotent(self):
        """Re-running with the same UPN is a no-op that exits cleanly (D-07)."""
        call_command("link_entra", "mayo", "jane.mayo@mcm.edu.ph")
        call_command("link_entra", "mayo", "jane.mayo@mcm.edu.ph")
        self.mayo.refresh_from_db()
        self.assertEqual(self.mayo.email, "jane.mayo@mcm.edu.ph")

    def test_invalid_upn_rejected(self):
        """A malformed UPN raises CommandError (no silent bad-email write)."""
        with self.assertRaises(CommandError):
            call_command("link_entra", "mayo", "not-an-email")

    def test_cross_user_clash_rejected(self):
        """A UPN already held by another user raises CommandError (no hijack)."""
        User.objects.create(username="cruz", email="taken@mcm.edu.ph", role=Role.CHECKER)
        with self.assertRaises(CommandError):
            call_command("link_entra", "mayo", "taken@mcm.edu.ph")

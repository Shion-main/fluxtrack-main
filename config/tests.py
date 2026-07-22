"""Deployment-boundary tests for FluxTrack's production runtime."""
import json
import os
import subprocess
import sys

from django.test import SimpleTestCase


class ProductionSettingsTests(SimpleTestCase):
    def _probe(self, **overrides):
        environment = os.environ.copy()
        environment.update({
            "FLUXTRACK_ENV": "production",
            "SECRET_KEY": "production-test-secret-" + ("x" * 40),
            "DEBUG": "False",
            "ALLOWED_HOSTS": "fluxtrack.example.edu",
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_KEY": "client-id",
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_SECRET": "client-secret",
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_TENANT_ID": "tenant-id",
            "SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI": (
                "https://fluxtrack.example.edu/auth/complete/"
                "azuread-tenant-oauth2/"
            ),
            "DB_NAME": "fluxtrack",
            "DB_USER": "fluxtrack_app",
            "DB_PASSWORD": "database-secret",
            "DB_HOST": "fluxtrack.example.rds.amazonaws.com",
            "DB_ODBC_EXTRA": "Encrypt=yes;TrustServerCertificate=no",
        })
        environment.update(overrides)
        script = (
            "import json; import config.settings as s; "
            "print(json.dumps({"
            "'production': s.IS_PRODUCTION, "
            "'debug': s.DEBUG, "
            "'ssl_redirect': s.SECURE_SSL_REDIRECT, "
            "'session_secure': s.SESSION_COOKIE_SECURE, "
            "'csrf_secure': s.CSRF_COOKIE_SECURE, "
            "'redirect_uri': s.SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI"
            "}))"
        )
        return subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(os.path.dirname(os.path.dirname(__file__))),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_production_enables_https_boundary_and_env_sso_redirect(self):
        result = self._probe()
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout.strip())
        self.assertEqual(values, {
            "production": True,
            "debug": False,
            "ssl_redirect": True,
            "session_secure": True,
            "csrf_secure": True,
            "redirect_uri": (
                "https://fluxtrack.example.edu/auth/complete/"
                "azuread-tenant-oauth2/"
            ),
        })

    def test_production_rejects_placeholder_secret_key(self):
        result = self._probe(SECRET_KEY="dev-insecure-change-me")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_rejects_debug_or_wildcard_hosts(self):
        debug = self._probe(DEBUG="True")
        wildcard = self._probe(ALLOWED_HOSTS="*")
        self.assertNotEqual(debug.returncode, 0)
        self.assertIn("DEBUG", debug.stderr)
        self.assertNotEqual(wildcard.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", wildcard.stderr)

    def test_production_rejects_insecure_entra_redirect(self):
        result = self._probe(
            SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI=(
                "http://fluxtrack.example.edu/auth/complete/"
                "azuread-tenant-oauth2/"
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("REDIRECT_URI", result.stderr)

    def test_production_rejects_entra_redirect_for_an_unserved_host(self):
        result = self._probe(
            SOCIAL_AUTH_AZUREAD_TENANT_OAUTH2_REDIRECT_URI=(
                "https://wrong.example.edu/auth/complete/azuread-tenant-oauth2/"
            )
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", result.stderr)


class HealthEndpointTests(SimpleTestCase):
    def test_health_endpoint_is_anonymous_and_cache_disabled(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.assertEqual(response.headers["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")

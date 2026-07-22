"""Deployment-boundary tests for FluxTrack's production runtime."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
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


class DeploymentArtifactTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent

    def _read(self, relative):
        return (self.root / relative).read_text(encoding="utf-8")

    def test_gunicorn_and_systemd_define_multi_worker_single_scheduler_runtime(self):
        self.assertIn("gunicorn", self._read("requirements.txt").lower())
        gunicorn = self._read("deploy/gunicorn.conf.py")
        web = self._read("deploy/systemd/fluxtrack-web.service")
        scheduler = self._read("deploy/systemd/fluxtrack-scheduler.service")
        self.assertIn("workers", gunicorn)
        self.assertIn("config.wsgi", web)
        self.assertIn("gunicorn", web)
        self.assertIn("/usr/bin/flock", scheduler)
        self.assertIn("scheduler.lock", scheduler)
        self.assertIn("manage.py runscheduler", scheduler)

    def test_watchdog_and_deploy_script_cover_cutover_checks(self):
        watchdog = self._read(
            "deploy/systemd/fluxtrack-scheduler-watch.service")
        timer = self._read("deploy/systemd/fluxtrack-scheduler-watch.timer")
        script = self._read("deploy/deploy.sh")
        self.assertIn("manage.py checkscheduler", watchdog)
        self.assertIn("OnUnitActiveSec=5min", timer)
        for token in ("check --deploy", "migrate", "collectstatic", "nginx -t"):
            self.assertIn(token, script)

    def test_nginx_terminates_tls_and_exposes_only_public_profile_media(self):
        nginx = self._read("deploy/nginx/fluxtrack.conf")
        for token in ("listen 443 ssl", "X-Forwarded-Proto", "proxy_pass",
                      "location /media/profile_photos/"):
            self.assertIn(token, nginx)
        self.assertNotIn("location /media/ {", nginx)

    def test_production_logging_emits_request_errors_to_process_stderr(self):
        request_logger = settings.LOGGING["loggers"]["django.request"]
        self.assertIn("console", request_logger["handlers"])
        self.assertEqual(request_logger["level"], "ERROR")

    def test_runbook_has_backup_restore_and_media_recovery_procedures(self):
        runbook = self._read("deploy/README.md").lower()
        for token in ("automated backups", "point-in-time", "media",
                      "restore drill", "break-glass"):
            self.assertIn(token, runbook)


class VendoredFrontendTests(SimpleTestCase):
    root = Path(__file__).resolve().parent.parent
    expected_sha256 = {
        "static/vendor/htmx/2.0.6/htmx.min.js": (
            "b6768eed4f3af85b73a75054701bd60e17cac718aef2b7f6b254e5e0e2045616"),
        "static/vendor/html5-qrcode/2.3.8/html5-qrcode.min.js": (
            "660b12437b1d747e3e68b8be0685c08cb728140110ad213f167b14b66f8b1d8e"),
        "static/vendor/franken-ui/2.1.2/core.min.css": (
            "9577607f8fc992f1346cae12cce05c5214f5b2ea3828a8d7f29b9bac420909fe"),
        "static/vendor/franken-ui/2.1.2/utilities.min.css": (
            "afbcb1eae0928cc0a75baab551885179337b5d21f89dcfc26e861ce69d2e04bb"),
        "static/vendor/franken-ui/2.1.2/core.iife.js": (
            "d2c3cae2e4b2b9d8116112124a8e8ef0a492efd3dd3afff13fa585050be07ba4"),
        "static/vendor/franken-ui/2.1.2/icon.iife.js": (
            "a91efff599704b6b27ca2d664b87b813b41804de5b5def646f0a0934200ea636"),
    }

    def test_vendored_runtime_files_match_reviewed_package_hashes(self):
        for relative, expected in self.expected_sha256.items():
            content = (self.root / relative).read_bytes()
            self.assertEqual(hashlib.sha256(content).hexdigest(), expected, relative)

    def test_templates_do_not_load_frontend_runtime_from_a_cdn(self):
        for relative in (
            "templates/base.html",
            "templates/faculty/scan.html",
            "templates/checker/scan.html",
        ):
            source = (self.root / relative).read_text(encoding="utf-8")
            self.assertNotIn("cdn.jsdelivr.net", source, relative)
            self.assertNotIn("src=\"https://htmx.org", source, relative)

    def test_scanners_expose_manual_fallback_if_camera_library_cannot_load(self):
        for relative in (
            "templates/faculty/scan.html",
            "templates/checker/scan.html",
        ):
            source = (self.root / relative).read_text(encoding="utf-8")
            self.assertIn("if (!window.Html5Qrcode)", source, relative)
            self.assertIn("Scanner library unavailable", source, relative)

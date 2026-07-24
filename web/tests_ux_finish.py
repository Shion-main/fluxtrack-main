"""Phase 13 finish-line UX contracts (audit findings B1-B6).

These tests intentionally cover behavior at the shared shell boundary: production
error handlers, role-appropriate notification chrome, brand identity, and global
htmx failure feedback.  They keep the fixes from drifting independently later.
"""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import get_resolver, reverse

from accounts.models import Role


class ProductionErrorPageTests(TestCase):
    """Production errors stay inside FluxTrack and always offer a safe route home."""

    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(DEBUG=False)
    def test_404_is_branded_and_routes_anonymous_users_to_login(self):
        response = self.client.get("/definitely-not-a-fluxtrack-route")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "FluxTrack", status_code=404)
        self.assertContains(response, 'class="ft-error', status_code=404)
        self.assertContains(response, 'href="/login"', status_code=404)

    @override_settings(DEBUG=False)
    def test_403_is_branded_and_routes_authenticated_users_home(self):
        user = get_user_model().objects.create(
            username="phase13_faculty_denied", role=Role.FACULTY
        )
        self.client.force_login(user)

        response = self.client.get(reverse("ifo_rooms"))

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "FluxTrack", status_code=403)
        self.assertContains(response, 'class="ft-error', status_code=403)
        self.assertContains(response, 'href="/"', status_code=403)

    @override_settings(DEBUG=False)
    def test_500_handler_is_branded_and_has_a_recovery_route(self):
        request = self.factory.get("/broken")
        handler = get_resolver().resolve_error_handler("500")

        response = handler(request)

        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertIn("FluxTrack", body)
        self.assertIn('class="ft-error', body)
        self.assertIn('href="/"', body)

    def test_all_custom_handlers_are_wired(self):
        handlers = {
            code: get_resolver().resolve_error_handler(code).__module__
            for code in ("403", "404", "500")
        }
        self.assertEqual(handlers, {code: "web.views" for code in handlers})


class FloorNotificationShellTests(TestCase):
    """The shared notification pages preserve the phone-first floor shell."""

    FLOOR_ROLES = (
        (Role.FACULTY, "/faculty/home"),
        (Role.CHECKER, "/checker/floor"),
        (Role.GUARD, "/guard/monitor"),
    )

    def test_list_and_settings_use_floor_chrome_for_floor_roles(self):
        User = get_user_model()
        for role, home_url in self.FLOOR_ROLES:
            with self.subTest(role=role):
                user = User.objects.create(username=f"phase13_{role}", role=role)
                self.client.force_login(user)
                for route_name in ("notifications", "notif_settings"):
                    response = self.client.get(reverse(route_name))
                    body = response.content.decode()
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('class="ft-app', body)
                    self.assertIn(f'href="{home_url}"', body)
                    self.assertNotIn("uk-label uk-label-secondary", body)
                    self.assertEqual(body.count("<header"), 1)
                self.client.logout()

    def test_admin_notification_page_keeps_the_desktop_shell(self):
        user = get_user_model().objects.create(
            username="phase13_ifo", role=Role.IFO_ADMIN
        )
        self.client.force_login(user)

        body = self.client.get(reverse("notifications")).content.decode()

        self.assertIn("uk-label uk-label-secondary", body)
        self.assertNotIn('class="ft-app', body)


class FacultyProfileReachabilityTests(TestCase):
    """Every persistent faculty surface exposes Profile in its account menu."""

    def test_primary_faculty_screens_link_to_profile(self):
        user = get_user_model().objects.create(
            username="phase13_profile", role=Role.FACULTY
        )
        self.client.force_login(user)

        for route_name in (
            "faculty_home",
            "faculty_schedule",
            "faculty_online",
            "faculty_history",
            "faculty_modality_mine",
        ):
            with self.subTest(route=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'href="/profile"')


class SharedBrandAndFailureFeedbackTests(TestCase):
    def test_login_consumes_the_shared_brand_navy_token(self):
        body = self.client.get(reverse("login")).content.decode()
        self.assertIn("--mmcm-navy: var(--brand-navy);", body)
        self.assertNotIn("#0f2554", body)

    def test_manifest_theme_matches_the_shell(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["theme_color"], "#001c43")

    def test_procedural_icon_fallback_uses_the_brand_navy(self):
        with TemporaryDirectory() as temp_dir:
            with override_settings(STATIC_ROOT=Path(temp_dir)):
                with patch("django.contrib.staticfiles.finders.find", return_value=None):
                    response = self.client.get("/icon-32.png")

        image = Image.open(BytesIO(response.content)).convert("RGB")
        self.assertEqual(image.getpixel((0, 0)), (0, 28, 67))

    def test_base_shell_has_accessible_global_htmx_failure_feedback(self):
        body = self.client.get(reverse("login")).content.decode()

        self.assertIn('id="htmx-failure"', body)
        self.assertIn('role="alert"', body)
        for event_name in (
            "htmx:responseError",
            "htmx:sendError",
            "htmx:timeout",
        ):
            self.assertIn(event_name, body)

    def test_service_worker_refreshes_static_assets_instead_of_freezing_old_css(self):
        response = self.client.get("/sw.js")
        body = response.content.decode()

        self.assertEqual(response["Cache-Control"], "no-cache, no-store, must-revalidate")
        self.assertIn("fluxtrack-shell-v6", body)
        self.assertIn("fetch(req)", body)
        self.assertIn("caches.match(req)", body)
        self.assertLess(body.index("fetch(req)"), body.index("caches.match(req)"))

    @override_settings(IS_PRODUCTION=True)
    def test_production_base_requests_fresh_service_worker_updates(self):
        body = self.client.get(reverse("login")).content.decode()

        self.assertIn("updateViaCache: 'none'", body)
        self.assertIn("controllerchange", body)
        self.assertIn("window.location.reload()", body)

    @override_settings(DEBUG=False, IS_PRODUCTION=False)
    def test_nonproduction_shell_removes_the_production_asset_worker(self):
        body = self.client.get(reverse("login")).content.decode()

        self.assertNotIn("serviceWorker.register('/sw.js'", body)
        self.assertIn("serviceWorker.getRegistrations()", body)
        self.assertIn("caches.keys()", body)
        self.assertIn("window.location.reload()", body)

    @override_settings(DEBUG=False, IS_PRODUCTION=False)
    def test_nonproduction_shell_fingerprints_live_static_assets(self):
        """Local DEBUG=False must not reuse a browser's prior source asset URL."""
        body = self.client.get(reverse("login")).content.decode()

        self.assertRegex(
            body,
            r'href="/static/faculty/faculty\.css\?v=[0-9a-f]+"',
        )

    def test_html_pages_are_never_reused_from_the_browser_http_cache(self):
        response = self.client.get(reverse("login"))

        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("no-store", cache_control)
        self.assertIn("no-cache", cache_control)
        self.assertIn("must-revalidate", cache_control)


class ResponsiveRoleShellTests(TestCase):
    root = Path(__file__).resolve().parent.parent

    def test_role_navigation_has_desktop_labels_without_replacing_mobile_icons(self):
        source = (self.root / "templates/base.html").read_text(encoding="utf-8")

        for role in ("Faculty", "Checker", "Guard"):
            self.assertIn(
                f'<span class="ft-tabbar__role">{role}</span>',
                source,
            )
        for label in (
            "Home",
            "Schedule",
            "Online classes",
            "My attendance",
            "Requests",
            "Floor board",
            "Scan",
            "Online",
            "Floor monitor",
            "Locate",
        ):
            self.assertIn(f'<span class="ft-tab__label">{label}</span>', source)

    def test_shared_role_css_is_mobile_first_with_tablet_and_desktop_layouts(self):
        source = (
            self.root / "static/faculty/faculty.css"
        ).read_text(encoding="utf-8")

        self.assertIn(".ft-tab__label { display: none; }", source)
        self.assertIn("@media (min-width: 48rem)", source)
        self.assertIn("@media (min-width: 64rem)", source)
        self.assertIn("body:has(.ft-tabbar) .ft-page", source)
        self.assertIn("max-width: 72rem", source)

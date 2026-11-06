from unittest.mock import patch
from django.test import SimpleTestCase
from web.views import icon, SW_JS

class BrowserBoundaryTests(SimpleTestCase):
    def test_arbitrary_icon_size_rejected_before_pillow(self):
        with patch("PIL.Image.new") as allocation:
            self.assertEqual(icon(None, 100000).status_code, 404)
            allocation.assert_not_called()

    def test_offline_shell_contains_capture_without_private_state(self):
        response = self.client.get("/checker/offline")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "public, max-age=300")
        self.assertContains(response, 'id="capture"')
        self.assertContains(response, 'data-offline-shell')
        self.assertNotContains(response, 'data-account-id')

    def test_worker_excludes_private_responses_and_routes(self):
        self.assertIn("private|no-store", SW_JS)
        self.assertIn("if (!isPublic(url)) return", SW_JS)
        self.assertNotIn("caches.match('/login')", SW_JS)

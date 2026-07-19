"""FAC-12 faculty profile photo upload (07-08, D-16).

Three tests here earn their keep beyond "the view works":

* `test_second_upload_leaves_no_orphaned_file` catches a SILENT storage leak.
  FileSystemStorage.get_available_name appends a random suffix on collision, so
  a view that saves without deleting the previous name accumulates a new file
  per upload forever while every page still looks correct.

* `test_posted_user_id_is_ignored` is the IDOR guard (T-07-43). It posts another
  user's pk as an extra field and asserts that user's photo is untouched.

* `test_stored_bytes_are_pillow_output_not_the_upload` is the whole point of
  D-16: the re-encode is the security control, so the stored bytes must not be
  the uploaded bytes even when the upload was already a valid JPEG.

MEDIA_ROOT is overridden to a temp dir on every class -- without it these tests
write real files into the repo's media/ and leave them there.

ASCII-only by convention (Windows cp1252).
"""
import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.test import TestCase, override_settings
from PIL import Image

from accounts import photos
from ops.models import AuditLog

PROFILE_URL = "/faculty/profile"
UPLOAD_URL = "/faculty/profile/photo"


def _user(username, role="faculty"):
    return get_user_model().objects.create(
        username=username, email=f"{username}@mcm.edu.ph", role=role)


def _image_upload(name="me.png", fmt="PNG", size=(80, 60), colour="red"):
    """A real, decodable image as a file object the test client can post."""
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, fmt)
    buf.seek(0)
    buf.name = name
    return buf


def _corrupt_upload(name="broken.jpg"):
    buf = io.BytesIO()
    Image.new("RGB", (200, 200), "blue").save(buf, "JPEG")
    raw = buf.getvalue()
    out = io.BytesIO(raw[:len(raw) // 3])   # truncated mid-scan
    out.name = name
    return out


def _oversized_upload(name="huge.jpg"):
    """Past the byte cap without being a valid image -- the cap must fire first."""
    out = io.BytesIO(b"\xff\xd8\xff\xe0" + b"\x00" * (photos.MAX_UPLOAD_BYTES + 1024))
    out.name = name
    return out


class _MediaTempMixin:
    """Point MEDIA_ROOT at a temp dir for the whole class and clean it up."""

    @classmethod
    def setUpClass(cls):
        cls._media_dir = tempfile.mkdtemp(prefix="fac12-media-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media_dir)
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._media_override.disable()
        shutil.rmtree(cls._media_dir, ignore_errors=True)


class ProfilePhotoUploadTests(_MediaTempMixin, TestCase):

    def setUp(self):
        self.me = _user("fac12_me")
        self.client.force_login(self.me)

    # --- the happy path and what it stores ---------------------------------

    def test_upload_sets_profile_photo_and_stores_jpeg(self):
        resp = self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        self.assertEqual(resp.status_code, 200)
        self.me.refresh_from_db()
        self.assertTrue(self.me.profile_photo.name)

        with self.me.profile_photo.open("rb") as fh:
            stored = fh.read()
        self.assertEqual(Image.open(io.BytesIO(stored)).format, "JPEG")

    def test_stored_bytes_are_pillow_output_not_the_upload(self):
        """T-07-39: the re-encode IS the control, so the bytes must differ."""
        upload = _image_upload(name="already.jpg", fmt="JPEG")
        sent = upload.getvalue()
        upload.seek(0)
        self.client.post(UPLOAD_URL, {"photo": upload})

        self.me.refresh_from_db()
        with self.me.profile_photo.open("rb") as fh:
            stored = fh.read()
        self.assertNotEqual(stored, sent)

    def test_upload_writes_exactly_one_audit_log_without_image_data(self):
        self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        logs = list(AuditLog.objects.filter(event_type="user.photo_updated"))
        self.assertEqual(len(logs), 1)
        entry = logs[0]
        self.assertEqual(entry.actor_id, self.me.pk)
        self.assertEqual(entry.payload.get("user"), self.me.pk)
        self.assertGreater(entry.payload.get("bytes"), 0)
        # No image data of any shape smuggled into the payload.
        for value in entry.payload.values():
            self.assertNotIsInstance(value, (bytes, bytearray))
        self.assertLess(len(str(entry.payload)), 200)

    # --- replacement and the orphan leak -----------------------------------

    def test_second_upload_replaces_the_first(self):
        self.client.post(UPLOAD_URL, {"photo": _image_upload(size=(80, 60))})
        self.me.refresh_from_db()
        first = self.me.profile_photo.name

        self.client.post(UPLOAD_URL, {"photo": _image_upload(size=(40, 40),
                                                             colour="green")})
        self.me.refresh_from_db()
        self.assertTrue(self.me.profile_photo.name)
        with self.me.profile_photo.open("rb") as fh:
            self.assertEqual(Image.open(io.BytesIO(fh.read())).size, (40, 40))
        self.assertNotEqual(first, "")

    def test_second_upload_leaves_no_orphaned_file(self):
        self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        self.me.refresh_from_db()
        first = self.me.profile_photo.name
        self.assertTrue(default_storage.exists(first))

        self.client.post(UPLOAD_URL, {"photo": _image_upload(colour="green")})
        self.me.refresh_from_db()
        current = self.me.profile_photo.name

        if current != first:
            self.assertFalse(
                default_storage.exists(first),
                "the previous photo was left behind as an orphan")
        # Whatever the naming, exactly one file exists for this user.
        _dirs, files = default_storage.listdir("profile_photos")
        mine = [f for f in files if f.startswith(str(self.me.pk))]
        self.assertEqual(len(mine), 1, f"expected one stored photo, found {mine}")

    # --- refusals -----------------------------------------------------------

    def test_corrupt_image_is_refused_with_a_readable_message(self):
        resp = self.client.post(UPLOAD_URL, {"photo": _corrupt_upload()})
        self.assertEqual(resp.status_code, 400)
        body = resp.content.decode()
        self.assertIn("Photo not accepted", body)
        self.assertNotIn("Traceback", body)

    def test_corrupt_image_leaves_an_existing_photo_unchanged(self):
        self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        self.me.refresh_from_db()
        before = self.me.profile_photo.name

        resp = self.client.post(UPLOAD_URL, {"photo": _corrupt_upload()})
        self.assertEqual(resp.status_code, 400)
        self.me.refresh_from_db()
        self.assertEqual(self.me.profile_photo.name, before)
        self.assertTrue(default_storage.exists(before))

    def test_oversized_file_is_refused_and_stores_nothing(self):
        resp = self.client.post(UPLOAD_URL, {"photo": _oversized_upload()})
        self.assertEqual(resp.status_code, 400)
        self.me.refresh_from_db()
        self.assertFalse(self.me.profile_photo.name)
        self.assertFalse(AuditLog.objects.filter(
            event_type="user.photo_updated").exists())

    def test_no_file_at_all_is_a_message_not_a_crash(self):
        """Also the symptom of a form missing hx-encoding."""
        resp = self.client.post(UPLOAD_URL, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Photo not accepted", resp.content.decode())

    def test_a_refusal_does_not_re_render_the_file_input(self):
        """Swapping a file input back in would silently clear the selection."""
        resp = self.client.post(UPLOAD_URL, {"photo": _corrupt_upload()})
        self.assertNotIn('type="file"', resp.content.decode())

    # --- IDOR ---------------------------------------------------------------

    def test_posted_user_id_is_ignored(self):
        """T-07-43: the target is request.user, never a supplied id."""
        victim = _user("fac12_victim")
        self.client.force_login(victim)
        self.client.post(UPLOAD_URL, {"photo": _image_upload(colour="blue")})
        victim.refresh_from_db()
        victim_photo = victim.profile_photo.name
        self.assertTrue(victim_photo)

        self.client.force_login(self.me)
        resp = self.client.post(UPLOAD_URL, {
            "photo": _image_upload(colour="green"),
            "user": str(victim.pk), "user_id": str(victim.pk),
            "pk": str(victim.pk),
        })
        self.assertEqual(resp.status_code, 200)

        victim.refresh_from_db()
        self.me.refresh_from_db()
        self.assertEqual(victim.profile_photo.name, victim_photo)
        self.assertNotEqual(self.me.profile_photo.name, victim_photo)
        self.assertTrue(self.me.profile_photo.name)


class ProfilePageTests(_MediaTempMixin, TestCase):

    def setUp(self):
        self.me = _user("fac12_page")
        self.client.force_login(self.me)

    def test_page_renders_with_the_upload_form(self):
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('hx-encoding="multipart/form-data"', body)
        self.assertIn('type="file"', body)

    def test_page_links_the_existing_notification_settings_surface(self):
        resp = self.client.get(PROFILE_URL)
        body = resp.content.decode()
        self.assertIn("/notifications/settings", body)

    def test_page_does_not_duplicate_the_mute_controls(self):
        """FAC-12's notification half already ships; a second copy would drift."""
        body = self.client.get(PROFILE_URL).content.decode()
        self.assertNotIn("/notifications/mute", body)
        self.assertNotIn('name="category"', body)

    def test_page_shows_a_placeholder_when_there_is_no_photo(self):
        body = self.client.get(PROFILE_URL).content.decode()
        self.assertIn("No photo yet", body)

    def test_page_shows_the_photo_once_uploaded(self):
        self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        body = self.client.get(PROFILE_URL).content.decode()
        self.assertIn("Current photo", body)
        self.assertIn("profile_photos/", body)


class ProfileAuthzTests(_MediaTempMixin, TestCase):
    """Three-way authz plus the method contract on both routes."""

    def setUp(self):
        self.me = _user("fac12_authz")

    def test_faculty_allowed(self):
        self.client.force_login(self.me)
        self.assertEqual(self.client.get(PROFILE_URL).status_code, 200)

    def test_non_faculty_authenticated_denied(self):
        self.client.force_login(_user("fac12_dean", role="dean"))
        self.assertEqual(self.client.get(PROFILE_URL).status_code, 403)

    def test_non_faculty_cannot_upload(self):
        self.client.force_login(_user("fac12_guard", role="guard"))
        resp = self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(PROFILE_URL)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_anonymous_cannot_upload(self):
        resp = self.client.post(UPLOAD_URL, {"photo": _image_upload()})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_post_on_the_profile_page_is_405(self):
        self.client.force_login(self.me)
        self.assertEqual(self.client.post(PROFILE_URL).status_code, 405)

    def test_get_on_the_upload_url_is_405(self):
        self.client.force_login(self.me)
        self.assertEqual(self.client.get(UPLOAD_URL).status_code, 405)

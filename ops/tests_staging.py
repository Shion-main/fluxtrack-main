"""Behaviour proofs for the IFO-03b upload staging service (D-12).

Every test runs under an `override_settings(MEDIA_ROOT=<tmp>)` so nothing here
ever writes into the repo's `media/` directory.

Both upload shapes are exercised deliberately. Django holds an upload under
2.5 MB in memory as an `InMemoryUploadedFile` (which never had a filesystem
path at all) and spills anything larger to a `TemporaryUploadedFile` backed by
a NamedTemporaryFile that is UNLINKED when the request ends. Those two handlers
differ enough that testing only the small synthetic `.csv` fixture proves
nothing about the real multi-MB `.xlsx` — which is exactly why the staging
service copies the bytes itself instead of stashing `temporary_file_path()`.
"""
import shutil
import tempfile
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import (SimpleUploadedFile,
                                            TemporaryUploadedFile)
from django.test import TestCase, override_settings
from django.utils import timezone

from ops.import_staging import (ImportStagingError, consume_staged,
                                discard_staged, resolve_staged, staged_path,
                                stage_upload, sweep_abandoned)
from ops.models import ImportStaging

_TMP_MEDIA = tempfile.mkdtemp(prefix="fluxtrack-staging-tests-")


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class ImportStagingTests(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_stg", email="ifo_stg@mcm.edu.ph", role="ifo_admin")
        self.other = User.objects.create(
            username="ifo_other", email="ifo_other@mcm.edu.ph", role="ifo_admin")

    def _small(self, name="offerings.csv", content=b"code,section\nX,A\n"):
        return SimpleUploadedFile(name, content)

    def _large(self, name="offerings.xlsx", size=3 * 1024 * 1024):
        """A genuine TemporaryUploadedFile — the disk-backed handler path."""
        f = TemporaryUploadedFile(name, "application/vnd.ms-excel", size, None)
        f.write(b"x" * size)
        f.seek(0)
        f.size = size
        return f

    # --- stage_upload -----------------------------------------------------

    def test_stage_upload_writes_file_and_row_with_token(self):
        staging = stage_upload(self._small(), self.ifo)
        self.assertTrue(staging.token)
        self.assertEqual(staging.uploaded_by, self.ifo)
        self.assertEqual(staging.size_bytes, len(b"code,section\nX,A\n"))
        self.assertIsNone(staging.consumed_at)
        self.assertTrue(default_storage.exists(staging.stored_path))

    def test_large_upload_uses_the_temporary_file_handler_path(self):
        """The real .xlsx case: disk-backed, and its temp path is NOT reused."""
        upload = self._large()
        staging = stage_upload(upload, self.ifo)
        self.assertEqual(staging.size_bytes, 3 * 1024 * 1024)
        self.assertTrue(default_storage.exists(staging.stored_path))
        # Our own copy, not Django's soon-to-be-unlinked temp file.
        self.assertNotEqual(staged_path(staging), upload.temporary_file_path())

    def test_hostile_upload_name_cannot_influence_the_stored_path(self):
        """T-07-04: the client controls the filename; it must not reach the path.

        Note what this does NOT prove. Django's `UploadedFile.name` setter
        already reduces a traversal string to its basename, so by the time
        `stage_upload` sees it the teeth are gone — `original_name` records
        "evil.csv", not the "../.." string the client sent. That is welcome
        defense in depth, but it is DJANGO's control, not ours;
        `test_raw_hostile_name_bypassing_django_sanitization_is_still_inert`
        below is the one that proves ours.
        """
        hostile = self._small(name="../../../../etc/passwd/evil.csv")
        staging = stage_upload(hostile, self.ifo)
        self.assertNotIn("..", staging.stored_path)
        self.assertNotIn("passwd", staging.stored_path)
        self.assertIn(staging.token, staging.stored_path)
        self.assertEqual(staging.original_name, "evil.csv")
        self.assertTrue(default_storage.exists(staging.stored_path))

    def test_raw_hostile_name_bypassing_django_sanitization_is_still_inert(self):
        """The path is built from the token alone — independently of any upstream
        sanitization, so a future caller handing us an unsanitized name (a custom
        upload handler, a direct service call) cannot escape the staging prefix."""

        class _RawUpload:
            """Minimal UploadedFile stand-in whose .name is NOT sanitized."""
            name = "../../../../etc/passwd/evil.csv"
            size = 8

            def chunks(self, chunk_size=None):
                yield b"raw-evil"

        staging = stage_upload(_RawUpload(), self.ifo)
        self.assertEqual(staging.stored_path, f"imports/staging/{staging.token}.csv")
        self.assertNotIn("..", staging.stored_path)
        # The unsanitized name is kept verbatim as DISPLAY TEXT only — it is
        # never joined into a path, which is the whole point.
        self.assertEqual(staging.original_name, "../../../../etc/passwd/evil.csv")
        self.assertTrue(default_storage.exists(staging.stored_path))

    def test_disallowed_extension_is_refused_with_a_user_safe_error(self):
        with self.assertRaises(ImportStagingError) as ctx:
            stage_upload(self._small(name="payload.exe"), self.ifo)
        self.assertIn(".xlsx", str(ctx.exception))
        self.assertFalse(ImportStaging.objects.exists())

    def test_oversize_upload_is_refused(self):
        with mock.patch("ops.import_staging.MAX_UPLOAD_BYTES", 4):
            with self.assertRaises(ImportStagingError):
                stage_upload(self._small(), self.ifo)
        self.assertFalse(ImportStaging.objects.exists())

    # --- resolve / consume ------------------------------------------------

    def test_resolve_staged_returns_the_row_for_its_owner(self):
        staging = stage_upload(self._small(), self.ifo)
        self.assertEqual(resolve_staged(staging.token, self.ifo), staging)

    def test_resolve_staged_refuses_a_foreign_owner_unknown_and_consumed(self):
        """T-07-05: holding the token is not enough — ownership is re-checked."""
        staging = stage_upload(self._small(), self.ifo)
        self.assertIsNone(resolve_staged(staging.token, self.other))
        self.assertIsNone(resolve_staged("no-such-token", self.ifo))
        consume_staged(staging)
        self.assertIsNone(resolve_staged(staging.token, self.ifo))

    def test_consume_staged_stamps_and_is_single_use(self):
        staging = stage_upload(self._small(), self.ifo)
        consume_staged(staging)
        staging.refresh_from_db()
        self.assertIsNotNone(staging.consumed_at)
        self.assertIsNone(resolve_staged(staging.token, self.ifo))

    def test_discard_staged_removes_file_and_row(self):
        staging = stage_upload(self._small(), self.ifo)
        path = staging.stored_path
        discard_staged(staging)
        self.assertFalse(default_storage.exists(path))
        self.assertFalse(ImportStaging.objects.filter(pk=staging.pk).exists())

    # --- sweep ------------------------------------------------------------

    def _age(self, staging, hours):
        ImportStaging.objects.filter(pk=staging.pk).update(
            created_at=timezone.now() - timedelta(hours=hours))

    def test_sweep_removes_abandoned_rows_and_their_files_only(self):
        abandoned = stage_upload(self._small(), self.ifo)
        consumed = stage_upload(self._small(), self.ifo)
        fresh = stage_upload(self._small(), self.ifo)
        self._age(abandoned, 5)
        self._age(consumed, 5)
        consume_staged(consumed)
        abandoned_path = abandoned.stored_path

        self.assertEqual(sweep_abandoned(), 1)

        self.assertFalse(ImportStaging.objects.filter(pk=abandoned.pk).exists())
        self.assertFalse(default_storage.exists(abandoned_path))
        # A consumed row is history, not abandonment; a fresh row is in flight.
        self.assertTrue(ImportStaging.objects.filter(pk=consumed.pk).exists())
        self.assertTrue(ImportStaging.objects.filter(pk=fresh.pk).exists())
        self.assertTrue(default_storage.exists(fresh.stored_path))

    def test_sweep_tolerates_a_row_whose_file_is_already_gone(self):
        staging = stage_upload(self._small(), self.ifo)
        self._age(staging, 5)
        default_storage.delete(staging.stored_path)
        self.assertEqual(sweep_abandoned(), 1)
        self.assertFalse(ImportStaging.objects.filter(pk=staging.pk).exists())

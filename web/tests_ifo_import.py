"""IFO-03b schedule-import-by-upload tests (plan 07-07).

THE TWO TESTS THAT MATTER MOST HERE are the large-file lifecycle and the
cross-user commit refusal, and both are easy to omit.

Django holds an upload under 2.5 MB in memory as an `InMemoryUploadedFile`,
which never had a filesystem path at all, and spills anything larger to a
`TemporaryUploadedFile` whose backing file is UNLINKED when the request ends.
Those handlers differ enough that passing against the small synthetic `.csv`
fixture proves nothing about the real multi-MB `.xlsx` an IFO officer will
actually upload -- an implementation that stashed `temporary_file_path()` would
be green on every small-file test in this module and dead on the real file.
So `StagingLifecycleTests` exercises BOTH paths across two real requests.

The two-request tests use two separate `post()` calls on the same client with
the session carried between them, never a single call with an injected token.
The point under test is that the file survives the request boundary; injecting
the token would test everything except that.

Every test runs under `override_settings(MEDIA_ROOT=<tmp>)` so nothing writes
into the repo's `media/`. The valid input is the committed synthetic CSV
fixture; no real registrar file is ever committed.

The three known pre-existing dev-login / home-redirect failures in web/tests.py
are unrelated to this module and are not chased here.

ASCII-only.
"""
import shutil
import tempfile
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role
from ops.import_staging import MAX_UPLOAD_BYTES
from ops.models import AuditLog, ImportStaging
from scheduling.models import AcademicTerm, Schedule, Session
from web.ifo import IMPORT_SESSION_KEY

_TMP_MEDIA = tempfile.mkdtemp(prefix="fluxtrack-import-web-tests-")
_FIXTURE = Path(settings.BASE_DIR) / "data" / "fixtures" / "r3_synthetic.csv"


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class _ImportBase(TestCase):

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_import", email="ifo_import@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.other_ifo = User.objects.create(
            username="ifo_import2", email="ifo_import2@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.faculty = User.objects.create(
            username="fac_import", email="fac_import@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)
        self.active_term = AcademicTerm.objects.create(
            name="Current Active Term",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ACTIVE,
        )
        self.draft_term = AcademicTerm.objects.create(
            name="Future Draft Term",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 10, 31),
            status=AcademicTerm.Status.DRAFT,
        )
        self.archived_term = AcademicTerm.objects.create(
            name="Archived Old Term",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.client.force_login(self.ifo)

    def _fixture_bytes(self):
        return _FIXTURE.read_bytes()

    def _small_upload(self, name="offerings.csv", data=None):
        return SimpleUploadedFile(
            name, data if data is not None else self._fixture_bytes(),
            content_type="text/csv")

    def _large_upload(self, name="offerings-big.csv"):
        """A file over FILE_UPLOAD_MAX_MEMORY_SIZE, so Django's TEMPORARY-file
        handler takes it -- the path the real multi-MB .xlsx uses.

        Padded with WIDE empty CSV rows, not with bare newlines. The width
        matters: bare newlines would make a 2.5 MB file out of ~2.6 million
        one-byte rows and trip the MAX_PARSED_ROWS zip-bomb cap, so the test
        would fail for the wrong reason and prove nothing about the upload
        handler. Wide rows reach the byte threshold in a few thousand rows,
        which is the shape of a real offerings export.
        """
        base = self._fixture_bytes()
        limit = settings.FILE_UPLOAD_MAX_MEMORY_SIZE
        row = b"," * 400 + b"\n"
        rows = (limit // len(row)) + 500
        return SimpleUploadedFile(name, base + row * rows,
                                  content_type="text/csv")

    def _preview(self, upload=None, *, term=None):
        return self.client.post(reverse("ifo_import_preview"),
                                {"file": upload or self._small_upload(),
                                 "term": term if term is not None
                                 else str(self.draft_term.pk)})

    def _commit(self):
        return self.client.post(reverse("ifo_import_commit"))


class ImportPreviewTests(_ImportBase):
    """Preview stages and reports, and writes NOTHING to the domain tables."""

    def test_preview_stages_the_file_and_writes_no_domain_rows(self):
        resp = self._preview()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ImportStaging.objects.count(), 1)
        self.assertEqual(Schedule.objects.count(), 0)
        self.assertEqual(Session.objects.count(), 0)

    def test_preview_stores_only_the_token_in_the_session(self):
        """Never the path, never the bytes."""
        self._preview()
        staging = ImportStaging.objects.get()
        self.assertEqual(self.client.session[IMPORT_SESSION_KEY],
                         staging.token)
        self.assertNotIn(staging.stored_path,
                         str(dict(self.client.session)))

    def test_the_preview_shows_the_four_bucket_counts(self):
        resp = self._preview()
        for bucket in ("intact", "roomless_tba", "online_no_room",
                       "no_schedule", "total"):
            with self.subTest(bucket=bucket):
                self.assertContains(resp, f'data-bucket="{bucket}"')
        self.assertContains(resp, 'data-identity="1"')

    def test_the_import_page_re_renders_a_staged_preview_after_a_reload(self):
        self._preview()
        resp = self.client.get(reverse("ifo_import"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-preview="1"')

    def test_the_import_page_empty_state_when_nothing_is_staged(self):
        resp = self.client.get(reverse("ifo_import"))
        self.assertContains(resp, 'data-empty="1"')

    def test_a_second_preview_replaces_the_first_staged_file(self):
        """Otherwise the first upload is orphaned until the TTL sweep."""
        self._preview()
        first = ImportStaging.objects.get()
        self._preview()
        self.assertEqual(ImportStaging.objects.count(), 1)
        self.assertFalse(ImportStaging.objects.filter(pk=first.pk).exists())


class DraftTermImportTests(_ImportBase):
    """Plan 12-04: browser import targets exactly one selected Draft term."""

    def test_import_page_offers_only_draft_terms(self):
        resp = self.client.get(reverse("ifo_import"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.draft_term.name)
        self.assertContains(resp, f'value="{self.draft_term.pk}"')
        self.assertNotContains(resp, self.active_term.name)
        self.assertNotContains(resp, self.archived_term.name)

    def test_preview_requires_a_draft_term_selection(self):
        resp = self._preview(term="")
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Select a Draft term", status_code=400)
        self.assertEqual(ImportStaging.objects.count(), 0)

    def test_preview_refuses_active_and_archived_targets(self):
        for term in (self.active_term, self.archived_term):
            with self.subTest(term=term.status):
                resp = self._preview(term=str(term.pk))
                self.assertEqual(resp.status_code, 400)
                self.assertContains(resp, "Select a Draft term", status_code=400)
                self.assertEqual(ImportStaging.objects.count(), 0)

    def test_preview_stores_selected_draft_on_staging_row(self):
        resp = self._preview()
        self.assertEqual(resp.status_code, 200)
        staging = ImportStaging.objects.get()
        self.assertEqual(staging.term_id, self.draft_term.pk)
        self.assertContains(resp, self.draft_term.name)
        self.assertContains(resp, f"data-term-id=\"{self.draft_term.pk}\"")

    def test_reload_uses_staging_bound_term(self):
        self._preview()
        self.draft_term.name = "Renamed Draft Target"
        self.draft_term.save(update_fields=["name"])

        resp = self.client.get(reverse("ifo_import"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Renamed Draft Target")
        self.assertContains(resp, f"data-term-id=\"{self.draft_term.pk}\"")


class StagingLifecycleTests(_ImportBase):
    """The file survives the request boundary -- for BOTH upload handlers."""

    def test_commit_in_a_separate_request_creates_schedules(self):
        self._preview()
        self.assertEqual(Schedule.objects.count(), 0)

        resp = self._commit()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-committed="1"')
        self.assertGreater(Schedule.objects.count(), 0)

    def test_a_large_upload_also_survives_preview_to_commit(self):
        """The TemporaryUploadedFile path. An implementation that stashed
        `temporary_file_path()` passes every small-file test in this module and
        fails HERE -- and would fail on the real multi-MB .xlsx in production
        while the whole suite stayed green."""
        upload = self._large_upload()
        self.assertGreater(upload.size, settings.FILE_UPLOAD_MAX_MEMORY_SIZE)

        self.assertEqual(self._preview(upload).status_code, 200)
        resp = self._commit()
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(Schedule.objects.count(), 0)

    def test_commit_consumes_the_staging_row_and_deletes_the_file(self):
        self._preview()
        staging = ImportStaging.objects.get()
        stored = staging.stored_path

        self._commit()

        staging.refresh_from_db()
        self.assertIsNotNone(staging.consumed_at)
        self.assertFalse(
            (Path(_TMP_MEDIA) / stored.replace("/", "\\")).exists()
            or (Path(_TMP_MEDIA) / stored).exists())
        self.assertNotIn(IMPORT_SESSION_KEY, self.client.session)

    def test_commit_is_audited_with_the_original_name_and_size(self):
        self._preview()
        staging = ImportStaging.objects.get()
        self._commit()

        log = AuditLog.objects.get(event_type="schedule.imported")
        self.assertEqual(log.actor_id, self.ifo.pk)
        self.assertEqual(log.payload["original_name"], "offerings.csv")
        self.assertEqual(log.payload["size_bytes"], staging.size_bytes)

    def test_a_second_commit_with_the_same_token_is_refused(self):
        self._preview()
        self._commit()

        resp = self._commit()
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "no longer available", status_code=400)

    def test_committing_the_same_file_twice_creates_no_duplicate_schedules(self):
        """D-13 additive idempotence: every write is get_or_create and nothing
        is deleted, so a re-upload of the same file is a no-op."""
        self._preview()
        self._commit()
        after_first = Schedule.objects.count()
        self.assertGreater(after_first, 0)

        self._preview()
        self._commit()

        self.assertEqual(Schedule.objects.count(), after_first)

    def test_discard_removes_the_row_and_the_file(self):
        self._preview()
        staging = ImportStaging.objects.get()
        stored = staging.stored_path

        resp = self.client.post(reverse("ifo_import_discard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-discarded="1"')

        self.assertFalse(ImportStaging.objects.filter(pk=staging.pk).exists())
        self.assertFalse((Path(_TMP_MEDIA) / stored).exists())
        self.assertNotIn(IMPORT_SESSION_KEY, self.client.session)


class StagingOwnershipTests(_ImportBase):
    """Holding a token is not authority to commit the file behind it."""

    def test_another_ifo_user_cannot_commit_someone_elses_staged_file(self):
        self._preview()
        staging = ImportStaging.objects.get()

        other = self.client_class()
        other.force_login(self.other_ifo)
        # The token is planted directly in the second user's session, which is
        # the STRONGEST form of the attack: even with the secret in hand, the
        # `uploaded_by` filter in resolve_staged must refuse.
        session = other.session
        session[IMPORT_SESSION_KEY] = staging.token
        session.save()

        resp = other.post(reverse("ifo_import_commit"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Schedule.objects.count(), 0)

        staging.refresh_from_db()
        self.assertIsNone(staging.consumed_at)

    def test_the_owner_can_still_commit_after_the_refused_attempt(self):
        self._preview()
        staging = ImportStaging.objects.get()

        other = self.client_class()
        other.force_login(self.other_ifo)
        session = other.session
        session[IMPORT_SESSION_KEY] = staging.token
        session.save()
        other.post(reverse("ifo_import_commit"))

        self.assertEqual(self._commit().status_code, 200)
        self.assertGreater(Schedule.objects.count(), 0)


class ImportValidationTests(_ImportBase):
    """Every bad upload is a message, never a 500."""

    def test_a_txt_upload_is_refused_and_stages_nothing(self):
        upload = SimpleUploadedFile("notes.txt", b"hello",
                                    content_type="text/plain")
        resp = self._preview(upload)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Unsupported file type", status_code=400)
        self.assertEqual(ImportStaging.objects.count(), 0)

    def test_an_oversize_upload_is_refused(self):
        upload = SimpleUploadedFile(
            "huge.csv", b"x" * (MAX_UPLOAD_BYTES + 1),
            content_type="text/csv")
        resp = self._preview(upload)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "too large", status_code=400)
        self.assertEqual(ImportStaging.objects.count(), 0)

    def test_an_unreadable_xlsx_is_a_message_not_a_500(self):
        """A valid extension proves nothing about the content. An .xlsx is a
        zip archive, so a renamed non-zip raises out of the parser."""
        upload = SimpleUploadedFile(
            "offerings.xlsx", b"this is definitely not a zip archive",
            content_type="application/vnd.ms-excel")
        resp = self._preview(upload)
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "could not be read", status_code=400)

    def test_an_unreadable_file_leaves_no_orphan_staging_row(self):
        upload = SimpleUploadedFile("offerings.xlsx", b"not a zip",
                                    content_type="application/vnd.ms-excel")
        self._preview(upload)
        self.assertEqual(ImportStaging.objects.count(), 0)
        self.assertNotIn(IMPORT_SESSION_KEY, self.client.session)

    def test_an_empty_file_is_a_message(self):
        upload = SimpleUploadedFile("offerings.csv", b"",
                                    content_type="text/csv")
        resp = self._preview(upload)
        self.assertEqual(resp.status_code, 400)

    def test_a_preview_with_no_file_at_all_is_a_message(self):
        """The urlencoded-instead-of-multipart failure mode: the file silently
        never arrives and request.FILES is empty."""
        resp = self.client.post(reverse("ifo_import_preview"), {})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Choose a file", status_code=400)

    def test_a_commit_with_nothing_staged_is_a_message(self):
        resp = self._commit()
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "no longer available", status_code=400)

    def test_a_discard_with_nothing_staged_is_harmless(self):
        self.assertEqual(
            self.client.post(reverse("ifo_import_discard")).status_code, 200)


class ImportSourceGuardTests(TestCase):
    """D-13: the destructive term reset stays unreachable from the browser.

    A source guard rather than a comment, because `reset_term` clears 2000+
    Schedule/Session rows behind a CLI `--yes`, and RDS Express has no
    point-in-time restore configured. An accidental web-reachable path to it
    would be unrecoverable, so "nobody would do that" is not a control.
    """

    # Assembled from parts so this guard can never match its own source. The
    # tokens are the two REACHABLE forms -- a module import and a call_command
    # invocation -- not the bare name, because `web/ifo.py` legitimately
    # explains in prose WHY the destructive path is excluded, and a guard that
    # forbade naming the hazard would push that explanation out of the code.
    _NAME = "reset_" + "term"
    _TOKENS = (f"commands.{_NAME}",           # from ...commands.reset_term
               f"import {_NAME}",             # import reset_term
               f'"{_NAME}"', f"'{_NAME}'")    # call_command("reset_term")

    def test_no_web_module_can_invoke_reset_term(self):
        web = Path(settings.BASE_DIR) / "web"
        for path in web.rglob("*.py"):
            if "tests" in path.stem:
                continue
            src = path.read_text(encoding="utf-8")
            for token in self._TOKENS:
                with self.subTest(module=path.name, token=token):
                    self.assertNotIn(
                        token, src,
                        f"{path.name} can reach reset_term; the destructive "
                        "term reset must stay unreachable from the browser "
                        "(D-13).")


class ImportAuthzTests(_ImportBase):
    """Three-way authz on all four URLs, plus 405 on the POST-only three."""

    def _write_urls(self):
        return [reverse("ifo_import_preview"), reverse("ifo_import_commit"),
                reverse("ifo_import_discard")]

    def _all_urls(self):
        return [reverse("ifo_import")] + self._write_urls()

    def test_ifo_reaches_the_import_page(self):
        self.assertEqual(
            self.client.get(reverse("ifo_import")).status_code, 200)

    def test_a_get_on_each_write_url_is_405(self):
        for url in self._write_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_a_post_on_the_import_page_is_405(self):
        self.assertEqual(
            self.client.post(reverse("ifo_import")).status_code, 405)

    def test_a_non_ifo_authenticated_user_gets_403_everywhere(self):
        self.client.force_login(self.faculty)
        for url in self._all_urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.assertEqual(ImportStaging.objects.count(), 0)

    def test_an_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        for url in self._all_urls():
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login", resp["Location"])

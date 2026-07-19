"""Hold an IFO-03b import file between the dry-run preview and the commit (D-12).

A PURE service layer: no HTTP, no `request`. It takes an uploaded-file object
and a user, so it unit-tests without a client and the view layer stays a thin
validate-then-delegate shell (the `scheduling.services` seam).

**Why the bytes are copied here rather than referenced.** This is the single
most likely bug in a naive D-12 implementation. Django unlinks the upload's
temp file when the request finishes, so `uploaded.temporary_file_path()` is
dead by the time the commit request arrives. Worse, it fails ASYMMETRICALLY:
an upload under 2.5 MB arrives as an `InMemoryUploadedFile` that never had a
path at all (`temporary_file_path()` raises AttributeError), while the real
multi-MB `.xlsx` arrives as a `TemporaryUploadedFile` whose path exists during
the preview request and is gone by the commit. So a naive implementation can
pass against the small synthetic `.csv` fixture and fail on the real file, or
vice versa. Writing our own copy during the preview request is what makes the
two-request flow work at all — and it is why the tests exercise BOTH handlers.

**Why `MAX_UPLOAD_BYTES` exists.** Neither Django setting people reach for
imposes a maximum upload size: `DATA_UPLOAD_MAX_MEMORY_SIZE` governs the
NON-FILE request body, and `FILE_UPLOAD_MAX_MEMORY_SIZE` governs only WHERE the
file lands (memory vs. temp file), not whether it is accepted. Checking
`uploaded.size` against our own cap is the only ceiling that exists.

Storage layout: `MEDIA_ROOT/imports/staging/<token><ext>`. The path is composed
entirely server-side from the token — never from the client's filename (T-07-04).
"""
import os
import secrets
from datetime import timedelta

from django.core.files.storage import default_storage
from django.utils import timezone

from ops.models import ImportStaging

# `import_offerings` already dispatches by extension; .xlsx is what IFO
# actually has, .csv is now only the synthetic test fixture (D-12).
ALLOWED_EXTENSIONS = {".xlsx", ".csv"}

# The only upload ceiling that exists — see the module docstring.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

STAGING_PREFIX = "imports/staging/"

# A module constant, deliberately NOT a FLUXTRACK_POLICY knob: how long an
# abandoned upload lingers is an implementation detail of this mechanism, not an
# operator-tunable business rule. Mirrors `_WINDOW_MINUTES` in ops/push.py and
# `_MATERIALIZE_INTERVAL_HOURS` in runscheduler.
STAGING_TTL_HOURS = 2


class ImportStagingError(Exception):
    """A refusal carrying a user-safe message.

    Mirrors the `ModalityShiftError` seam (scheduling/services.py:61) that
    `web/faculty.py:452` renders as a friendly 400 — a refused upload must never
    surface as a 500.
    """


def _extension(client_name):
    """Lowercased extension, used ONLY for the allow-list decision and suffix."""
    return os.path.splitext(client_name or "")[1].lower()


def stage_upload(uploaded, user):
    """Validate, copy to storage, and record an upload. Returns the ImportStaging.

    Raises ImportStagingError on a disallowed extension or an oversize file,
    before anything is written.
    """
    ext = _extension(uploaded.name)
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise ImportStagingError(
            f"Unsupported file type. Upload one of: {allowed}.")
    if uploaded.size > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        raise ImportStagingError(
            f"That file is too large. The limit is {limit_mb:.0f} MB.")

    token = secrets.token_urlsafe(32)
    # Composed from the TOKEN and the extension only. The client's name is
    # never joined into a path, so directory separators or parent-directory
    # segments in it are inert (T-07-04).
    name = f"{STAGING_PREFIX}{token}{ext}"
    # Streamed in chunks, never `uploaded.read()` — a multi-MB .xlsx must not be
    # pulled into memory just to be copied back out.
    stored_path = default_storage.save(name, _ChunkedCopy(uploaded))

    return ImportStaging.objects.create(
        token=token,
        uploaded_by=user,
        original_name=uploaded.name or "",   # display text only
        stored_path=stored_path,
        size_bytes=uploaded.size,
    )


class _ChunkedCopy:
    """Adapts an UploadedFile to the chunked-write contract of Storage.save.

    Written against the `UploadedFile`/`chunks()` API ONLY, so it behaves
    identically for the in-memory and temporary-file handlers.
    """

    def __init__(self, uploaded):
        self._uploaded = uploaded
        self.name = uploaded.name
        self.size = uploaded.size

    def chunks(self, chunk_size=None):
        return self._uploaded.chunks(chunk_size) if chunk_size else self._uploaded.chunks()

    def read(self, *args):
        return self._uploaded.read(*args)

    def __iter__(self):
        return iter(self._uploaded)


def resolve_staged(token, user):
    """Return the live staged row for `token` owned by `user`, else None.

    The `uploaded_by` filter is the IDOR control (T-07-05): holding a token is
    not sufficient authority to address the file behind it. The
    `consumed_at__isnull=True` filter makes a staged upload SINGLE-USE, so a
    double-submitted commit cannot apply the same import twice.

    Callers MUST pass the token read from `request.session` — never from a form
    field or a query parameter, which the client controls.
    """
    return (ImportStaging.objects
            .filter(token=token, uploaded_by=user, consumed_at__isnull=True)
            .first())


def consume_staged(staging):
    """Mark a staged upload as used. It can never be resolved again."""
    staging.consumed_at = timezone.now()
    staging.save(update_fields=["consumed_at"])
    return staging


def _delete_file(path):
    """Best-effort file removal — an already-missing file is not an error.

    Storage.delete does not raise for a missing name on FileSystemStorage, but
    a partially-written or externally-cleaned file must never turn cleanup into
    a 500, so the guard is explicit.
    """
    if not path:
        return
    try:
        if default_storage.exists(path):
            default_storage.delete(path)
    except OSError:
        pass


def discard_staged(staging):
    """Drop a staged upload the operator walked away from: file, then row."""
    _delete_file(staging.stored_path)
    staging.delete()


def staged_path(staging):
    """Absolute filesystem path of the staged file.

    The commit step needs a REAL path because `import_offerings` reads
    `--file <path>` from the filesystem rather than accepting a file object.
    """
    return default_storage.path(staging.stored_path)


def sweep_abandoned(now=None):
    """Delete unconsumed staged uploads past the TTL. Returns the count.

    A CONSUMED row is deliberately left alone — it is history (who imported
    what, when), not abandonment, and its file is already spent.
    """
    cutoff = (now or timezone.now()) - timedelta(hours=STAGING_TTL_HOURS)
    # Materialized with list() before the per-row deletes: MSSQL raises HY010
    # ("function sequence error") when follow-up queries are issued while a
    # cursor is still streaming. Same guard both sweeps in scheduling/jobs.py
    # carry.
    rows = list(ImportStaging.objects.filter(
        consumed_at__isnull=True, created_at__lt=cutoff))
    for staging in rows:
        _delete_file(staging.stored_path)
        staging.delete()
    return len(rows)

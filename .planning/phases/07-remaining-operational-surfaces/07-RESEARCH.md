# Phase 07: Remaining Operational Surfaces - Research

**Researched:** 2026-07-18
**Domain:** Django 6 secure file upload (two-request staging + image re-encode), htmx 2 multipart, scheduled-job push fan-out, referential-integrity introspection on MSSQL
**Confidence:** HIGH on the four asked questions; the recommendations are grounded in this codebase's actual settings, not in generic Django advice.

## Summary

This research answers only the four open technical questions the orchestrator scoped. Everything else in Phase 07 is surface-and-URL work over services that already exist and are tested, and needs no research.

The single most consequential finding is that **this project has no `CACHES` setting and no `SESSION_ENGINE` setting.** That means Django's defaults apply: `LocMemCache` (per-process, not shared across workers, silently lossy) and the database session backend (`django_session` on MSSQL, a text column). Both of those defaults *individually eliminate* the two obvious ways to hold a multi-MB `.xlsx` between the IFO-03b preview request and the commit request. The recommendation is a **temp file on disk under `MEDIA_ROOT`, addressed by an opaque token stored in the session, with a DB staging row carrying the metadata and a sweeper for abandonment.** The session holds the token only — never the bytes.

The second most consequential finding is that **`ops.Booking.room` is `on_delete=CASCADE` while `Schedule.room`, `Session.room`, and `CheckerValidation.room` are all `PROTECT`.** For D-17 this means Django gives you the refusal for free on three of the four relations and *silently destroys data* on the fourth. Room delete must therefore not rely on `PROTECT` alone; it must run explicit `exists()` probes per relation before calling `.delete()`, and must include `CheckerValidation` — which D-17's wording ("Schedule, Session, or Booking") omits.

Third: **`ops/notifications.py` defines `PUSH_TYPES = {"room_event", "room_conflict", WEEKLY_REPORT_READY}` as a hard allow-list.** A new GRD-04 notification type that is not added to that set will write `Notification` rows that render in the bell and never push. This is a one-line change that is very easy to forget and produces a symptom ("alerts appear in-app but no push arrives") that looks like a VAPID problem.

**Primary recommendation:** Stage the import upload as a temp file + DB staging row + session token; validate the profile photo with an open→verify→**reopen**→re-encode→`ContentFile` pipeline; set `hx-encoding="multipart/form-data"` on the `<form>` and accept that a 400 re-render clears the file input (a real consequence of this project's existing `responseHandling` contract); coalesce GRD-04 into one `notify()` per on-duty guard per sweep run and add its type to `PUSH_TYPES`; and answer room-delete with four explicit `exists()` probes, not `NestedObjects`.

## User Constraints (from CONTEXT.md)

### Locked Decisions

Verbatim, the decisions that bear on this research (D-01..D-18 in full are in 07-CONTEXT.md; these four govern the researched questions):

- **D-12:** The upload accepts BOTH `.xlsx` and `.csv` — `import_offerings` already dispatches by extension, and `.xlsx` is what IFO actually has (`.csv` is now only the synthetic test fixture). Flow is preview-then-commit: run `--dry-run` first, show the `reconcile()` report (four-bucket counts, typo rooms, email-less instructors), IFO reviews and clicks Commit to apply (or walks away). The file is held between the two steps.
- **D-16:** Profile photo upload does BASIC validation: file type (jpg/png), max size, real decodable image (Pillow already a dependency), and a server-side re-encode/resize to a standard dimension (consistent Checker view; strips a hostile payload). NO face detection, NO admin approval queue. Enough to keep the photo usable as identity evidence without inventing moderation.
- **D-06:** "Debounced" = coalesce per sweep run: ONE push per job run per on-duty Guard, summarizing the batch (e.g. "3 rooms now free on Floor 3"). Both triggers fire from the same 5-minute sweep job (`sweep_no_shows` + `detect_room_conflicts` run together), so the debounce window falls out of the job cadence — NO new policy knob, NO per-room last-alerted state to persist.
- **D-17:** Room delete REFUSES if the room is referenced by any Schedule, Session, or Booking — the UI blocks it and names what references it. Only a genuinely unused room (e.g. an import typo room with nothing on it) can be removed. Mirrors how `reset_term` treats PROTECTed schedules (report and skip, never half-delete). NOT soft-deactivate (would need an `is_active` field taught to every room query including the scan path we're leaving alone) and NOT cascade (destroys attendance history — catastrophic for an attendance-integrity app). Create/edit are straightforward.
- **D-13:** The web import is ADDITIVE ONLY — every write is `get_or_create`, no deletes; re-running the same file is idempotent. The destructive `reset_term` (clears 2000+ Schedule/Session rows, gated behind CLI `--yes`) is NOT reachable from the browser.
- **D-05:** GRD-04 alert triggers are EXACTLY TWO, both already-emitted events, scoped to the Guard's active floor(s): (1) a `RoomConflictFlag` opens — `detect_room_conflicts` already calls `notify()`; add floor-scoped Guards to that fan-out; and (2) a session is swept to ABSENT past grace (ghost booking → room now free).

### Claude's Discretion

- Audit-log wording/payloads for the new domain actions (link overwrite, QR rotation, manual release, room delete-refusal) follow the existing AuditLog convention.
- Exact template/URL layout of the new surfaces — reuse the navy app-shell and existing polled-monitor pattern (`ifo.live`/`live_rows`).
- Whether Guard duty keeps the `CheckerAssignment` name or gets a neutral rename (cosmetic).

### Deferred Ideas (OUT OF SCOPE)

- Faculty flag dispute/contest workflow.
- Profile-photo moderation/approval queue.
- Web-reachable term reset / replace-term import.
- Unscheduled-room-occupied Guard alert.

### Additionally out of scope for this research (orchestrator-scoped)

The scan resolver, `scheduling/resolver.py`, the shared no-show predicate, anything Entra/AWS (Phase 8), and the room-utilization/IFO-09 thread. Nothing below touches them.

## Project Constraints (from CLAUDE.md and established convention)

There is no repo-level `CLAUDE.md`; the binding constraints come from CONTEXT.md `<code_context>` and STATE.md. Restated for the planner:

1. **`collectstatic` after any CSS/JS edit.** `STORAGES["staticfiles"]` is `CompressedManifestStaticFilesStorage` whenever `DEBUG` is false — and **the test runner forces `DEBUG=False`**, so tests resolve through `staticfiles.json` too. Adding a *new* static file without running `collectstatic` raises `ValueError` in tests, not just in prod. Any new template that references a new `.css`/`.js` asset must be accompanied by a `collectstatic` run. `[VERIFIED: config/settings.py STORAGES block + its own inline comment]`
2. **MSSQL HY010.** pyodbc has MARS off, so one active result set per connection. Materialize with `list()` before issuing follow-up queries or writes inside a loop over a queryset. Precedent in `scheduling/jobs.py` (both functions), `ops/availability.py`, and the 06-07 HR export. `[VERIFIED: scheduling/jobs.py lines 52-58 and 96-98]`
3. **MSSQL 2100-parameter limit.** This project has been bitten (04.1-04: `reset_term --yes` failed at 2113 rows with pyodbc `07002 COUNT field incorrect`). Never build a large `pk__in=[...]`. `[VERIFIED: .planning/STATE.md Blockers, 04.1-04 entry]`
4. **Every domain state-change writes an `AuditLog`** (Conventions §2).
5. **Read-only role surfaces use `@require_http_methods(['GET'])`** so POST is 405.
6. **`notify()` is the single Notification write path.** Nothing else may create a `Notification`.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Import file receipt + staging (IFO-03b) | Django view (`web/ifo.py`) | Filesystem (`MEDIA_ROOT/imports/staging/`) | Bytes belong on disk; the request tier only holds a token |
| Import staging metadata + ownership | Database (`ops` app) | Session (token only) | Multi-worker safety demands shared state; DB is the only shared store configured |
| Import dry-run + apply | Existing management command | — | D-13: wrap `import_offerings`, do not rewrite |
| Abandoned-upload cleanup | Scheduler (`runscheduler` job) | — | Same process that already owns sweep/materialize/push_outbox |
| Photo type/size/decode validation | Django form (`web/forms.py`, net-new) | — | Validation belongs in `clean_<field>`, before any model write |
| Photo re-encode/resize | Service function (`accounts/photos.py`, net-new) | Pillow | Pure bytes-in/bytes-out; unit-testable without HTTP |
| Photo persistence | `ImageField` + `default_storage` | — | `FileSystemStorage` under `MEDIA_ROOT` |
| Multipart encoding switch | Browser/htmx (`hx-encoding`) | — | Purely a client-side XHR concern |
| GRD-04 recipient resolution | Scheduler job (`scheduling/jobs.py`) | `verification.Assignment` + `verification.resolver` | D-06 puts coalescing at job scope; duty predicate is already shared |
| GRD-04 delivery | Existing push outbox (`ops/push.py`) | Scheduler `push_outbox` job | Structural fault isolation already established in 05-03 |
| Room-delete blocker introspection | Django ORM `exists()` per relation | — | Cheapest correct answer; no admin internals |

---

## Question 1a — Holding the import file between preview and commit (IFO-03b / D-12)

### The constraint that decides this

`config/settings.py` defines **no `CACHES` key and no `SESSION_ENGINE` key.** `[VERIFIED: grep of config/settings.py — neither string appears]` Therefore:

- Cache backend = `django.core.cache.backends.locmem.LocMemCache`, **per-process**, unshared, evicted at will, lost on restart. `[CITED: docs.djangoproject.com/en/6.0/topics/cache/ — locmem is the default and is per-process]`
- Session backend = `django.contrib.sessions.backends.db`, i.e. `django_session` on MSSQL, whose `session_data` is a text column holding a base64-encoded, signed, serialized dict. `[CITED: docs.djangoproject.com/en/6.0/topics/http/sessions/]`

And a second constraint: **`import_offerings` takes `--file <path>` and reads from the filesystem.** `[VERIFIED: scheduling/management/commands/import_offerings.py add_arguments line 73, handle line 103 `self._read_rows(o["file"], ...)`]` D-13 says wrap the command, do not rewrite it. So whatever holding mechanism you choose, the commit step must be able to hand the command a **real filesystem path**. That alone rules out anything that keeps the file only as bytes in a column or a cache value, unless you write it back out to disk first — which is the disk approach with extra steps.

Third constraint, and the one that catches people: **Django deletes the upload temp file when the request ends.** With `FILE_UPLOAD_MAX_MEMORY_SIZE` at its 2.5 MB default `[CITED: docs.djangoproject.com/en/6.0/topics/http/file-uploads/ — "if an uploaded file is smaller than 2.5 megabytes, Django will hold the entire contents of the upload in memory"]`, a several-MB `.xlsx` arrives as a `TemporaryUploadedFile` backed by a `NamedTemporaryFile` in the system temp dir. That handle is closed and the file unlinked once the response is finished. **You cannot stash `uploaded.temporary_file_path()` in the session and expect it to exist on the next request.** This is the single most likely bug in a naive implementation of D-12, and it will *work in dev on a small `.csv` fixture* (which stays in memory as `InMemoryUploadedFile` and never had a path at all — `temporary_file_path()` raises `AttributeError`) and *fail on the real multi-MB `.xlsx`*, or vice versa. The two upload handlers behave differently enough that testing with the synthetic `.csv` proves nothing about the real file.

### The three alternatives, and how each fails

| Approach | Failure mode in *this* project |
|---|---|
| **Bytes in the session** | `django_session.session_data` is a text column. A 3 MB `.xlsx` base64-encodes to ~4 MB of text written and re-read on **every single request** for the rest of that session, through pyodbc, on SQL Server Express (10 GB cap, already flagged in STATE.md Blockers). Also: the session cookie's data is server-side here so it is not a cookie-size failure, but `SessionStore` deserializes the whole blob on every authenticated request — you would tax every page load in the app for the duration of one import review. **Reject.** |
| **File in the cache** | `LocMemCache` is per-process. Worker A serves the preview and caches the bytes; worker B serves the commit and finds nothing → "your upload expired, start over," intermittently, and only under multi-worker deployment (i.e. only in production, never on `runserver`). Also memory-bounded and silently evicting. Configuring a shared cache is a Phase 8 infra decision, not a Phase 7 one. **Reject.** |
| **`FileField` staging row (bytes in DB via storage) alone** | Closest to correct, and this is the recommended shape — but note that a `FileField` on `FileSystemStorage` *is* "a file on disk plus a DB row." The failure mode of the *pure* version (no explicit lifecycle) is that `.delete()`-less abandonment leaves orphaned files forever: `FileField` does not delete the underlying file when the row is deleted (Django removed that behavior in 1.3). `[CITED: docs.djangoproject.com/en/6.0/ref/models/fields/#filefield]` So you must delete the file explicitly in the cleanup job. |
| **Temp file on disk + token in session + DB staging row** | **Recommended.** Failure modes are all bounded and cheap to close: orphan files (closed by the sweeper), token theft (closed by binding the row to `created_by` and re-checking on commit), path traversal (closed by never letting the client supply the filename — see below). |

### Recommendation

Add a small staging model to the `ops` app:

```python
# ops/models.py  (sketch — planner owns the final field set)
class ImportStaging(models.Model):
    """A .xlsx/.csv held between the IFO-03b dry-run preview and the commit (D-12).

    The bytes live on disk under MEDIA_ROOT/imports/staging/ addressed by an
    opaque server-generated token; the session carries ONLY that token. The row
    is the ownership + lifecycle record: who uploaded, when, and whether it has
    been consumed. Abandoned rows (and their files) are swept by the scheduler.
    """
    token = models.CharField(max_length=64, unique=True, db_index=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.CASCADE,
                                    related_name="import_stagings")
    original_name = models.CharField(max_length=255)   # display only, never a path
    stored_path = models.CharField(max_length=255)     # storage-relative, server-built
    size_bytes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
```

Flow:

1. **Preview POST.** Validate extension against `{".xlsx", ".csv"}` and size against an explicit cap. Generate `token = secrets.token_urlsafe(32)`. Build the on-disk name **entirely server-side**: `imports/staging/{token}{ext}` — the client's filename is stored in `original_name` for display and is *never* used to construct a path. Write with `default_storage.save(...)` streaming via `for chunk in f.chunks():` (never `.read()`, per the Django docs' explicit advice). Create the `ImportStaging` row. Put **only the token** in `request.session`.
2. **Run the dry run** against `default_storage.path(stored_path)` and render `reconcile()`.
3. **Commit POST.** Re-read the token from the session (not from the form — a form-supplied token is an IDOR handle), fetch the row with `uploaded_by=request.user, consumed_at__isnull=True`, run the real import, stamp `consumed_at`, delete the file, clear the session key.
4. **Walk-away / cancel.** Delete file + row.

**Session stores a token, not a path.** This matters: a path in the session is a path the code will later `open()`, and any bug that lets a client influence it becomes arbitrary file read. A token is an opaque key into a server-owned row that holds the server-built path.

**Calling the command.** `call_command("import_offerings", file=path, dry_run=True, ...)` with `stdout=io.StringIO()` captures the human report. Note the command currently *prints* its reconciliation rather than returning it; the preview surface will want structured numbers. `scheduling/importing.reconcile()` is the pure function that produces the four-bucket partition `[VERIFIED: CONTEXT.md canonical_refs + 04.1-01 STATE entry: "reconcile() four-bucket partition reproduces the real file exactly (1211 = 1042 + 44 + 14 + 111)"]` — call `reconcile()` directly for the structured preview and treat the command's stdout as a detail/log pane, rather than screen-scraping the command output.

**Multi-worker safety.** The disk is shared within a single EC2 host; `MEDIA_ROOT` on the local filesystem is fine for the current single-host deployment. If Phase 8 introduces more than one app host, this becomes an S3-backed-storage change (swap `STORAGES["default"]`), and the token+row design survives that swap unchanged — which is a further argument for it over anything process-local. `[ASSUMED — deployment topology for Phase 8 is not settled; flagged, not relied upon]`

**Cleanup.** Add a fifth scheduler job (or fold into an existing one) that deletes `ImportStaging` rows older than a TTL where `consumed_at IS NULL`, removing the file first then the row. Note the existing invariant: `NoImplicitSchedulerTests` guards the job count and the "built only in `build_scheduler()`" rule `[VERIFIED: STATE.md Phase 02 ENV-04 entry: "4-job scheduler invariant + NoImplicitScheduler intact"]` — adding a job means **updating that test's expected count**, expected, not a regression. If you would rather not touch the scheduler invariant, sweeping opportunistically at the top of the upload view is an acceptable cheaper alternative for a surface used a handful of times per term.

### Pitfalls specific to 1a

- **`temporary_file_path()` across requests.** Covered above. The path is gone when the response finishes.
- **`.csv` and `.xlsx` take different upload handlers at realistic sizes.** The small synthetic `.csv` fixture is `InMemoryUploadedFile`; the real `.xlsx` is `TemporaryUploadedFile`. Write the staging code against the `UploadedFile`/`chunks()` API only, and test with a file forced over the 2.5 MB threshold.
- **Extension check is not a content check.** Checking `.xlsx` proves nothing about content. The real validation is that `import_offerings` parses it; a garbage file should surface as a friendly preview error, not a 500. The stdlib `zipfile` reader used by `scheduling/xlsx.py` `[VERIFIED: 04.1-01 STATE entry — "stdlib zipfile+xml.etree .xlsx reader (no openpyxl/pandas, D1)"]` will raise `BadZipFile` on a non-zip; catch it.
- **Zip bombs.** `.xlsx` is a zip archive. A deliberately crafted one can expand enormously. A size cap on the *uploaded* file does not cap the *expanded* XML. Bounding the number of parsed rows (or checking `ZipInfo.file_size` before extracting) is a cheap mitigation. This is a low-likelihood threat here — the surface is IFO-admin-only, not public — but it is the one input-validation gap worth naming.
- **`DATA_UPLOAD_MAX_MEMORY_SIZE`** (default 2.5 MB) governs the *non-file* part of the request body and does **not** cap file uploads; `FILE_UPLOAD_MAX_MEMORY_SIZE` governs where the file lands, not its maximum size. **Neither setting imposes a maximum upload size.** If you want a cap, you must enforce it yourself in `clean()` from `uploaded.size`. `[CITED: docs.djangoproject.com/en/6.0/ref/settings/]`

---

## Question 1b — Profile photo validation and re-encode (FAC-12 / D-16)

`accounts.User.profile_photo` is already `models.ImageField(upload_to="profile_photos/", null=True, blank=True)` `[VERIFIED: accounts/models.py:36]`. Pillow is already a dependency (`Pillow>=10.0`) `[VERIFIED: requirements.txt]`. No new packages.

### The `verify()`-then-reopen gotcha

Pillow's documentation is explicit: `verify()` checks file integrity *without decoding image data*, and **"if you need to load the image after using this method, you must reopen the image file."** After `verify()` the `Image` object is unusable — Pillow closes it. `[CITED: pillow.readthedocs.io — Image.verify(); corroborated by Django ticket #30252 where `ImageField.to_python()` storing a reference to a post-`verify()` closed `Image` was itself a bug]`

The failure this produces is nasty because it is *silent in the happy path of a naive test*: code that does `img = Image.open(f); img.verify(); img.thumbnail(...)` raises on the `thumbnail` line for real files, so you notice — but code that does `img.verify()` and then only reads `img.format`/`img.size` appears to work while actually having done no decode at all, so a truncated or malformed file sails through validation and blows up later at render time.

The correct shape is **open → verify → seek(0) → reopen → convert → resize → save**:

```python
# accounts/photos.py  (net-new; pure bytes-in/bytes-out so it unit-tests without HTTP)
import io
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG"}
TARGET = (512, 512)


def normalize_profile_photo(fileobj) -> bytes:
    """Validate an uploaded profile photo and return re-encoded JPEG bytes (D-16).

    Raises ValueError with a user-safe message on anything it refuses. The
    re-encode is the security control: the bytes written to storage are bytes
    Pillow produced, so any payload smuggled in the original container (EXIF
    comment, appended archive, polyglot) does not survive. EXIF is dropped for
    the same reason and because a phone photo carries GPS coordinates.
    """
    fileobj.seek(0)
    try:
        probe = Image.open(fileobj)
        probe.verify()                      # integrity check; CLOSES the image
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("That file is not a readable JPEG or PNG image.")
    if probe.format not in ALLOWED_FORMATS:
        raise ValueError("Only JPEG and PNG photos are accepted.")

    fileobj.seek(0)                         # MANDATORY: verify() consumed it
    img = Image.open(fileobj)               # reopen — the verified handle is dead
    img = img.convert("RGB")                # forces a full decode; drops alpha + palette
    img.thumbnail(TARGET, Image.LANCZOS)    # aspect-preserving downscale

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)  # no exif= kwarg -> EXIF dropped
    return out.getvalue()
```

Notes on each line that carries weight:

- **`probe.format` must be read before `verify()` or from the probe object after** — reading it from the *reopened* image is also fine and arguably clearer. Do not trust the uploaded filename's extension or the browser-supplied `content_type`; both are attacker-controlled.
- **`convert("RGB")` is what actually forces a decode.** `Image.open()` is lazy — it reads the header only. Without a decode-forcing operation, a file with a valid header and corrupt body passes. `convert()` (or `load()`) is the real "is this decodable" test, and `verify()` is a cheap pre-filter that catches structural damage first.
- **EXIF is dropped by omission.** Pillow only writes EXIF to the JPEG output if you pass `exif=...`. Not passing it strips orientation, timestamps, camera model, and GPS. The one real cost: dropping the EXIF orientation tag makes a phone photo taken sideways *stay* sideways. If that matters for identity photos, call `ImageOps.exif_transpose(img)` **before** stripping — that applies the rotation to the pixels and then discards the tag, which is exactly the behavior you want.
- **`thumbnail()` not `resize()`.** `thumbnail` preserves aspect ratio and never upscales; `resize` to a fixed tuple distorts a non-square photo. For a consistent square Checker view you would center-crop then resize — a discretionary UI call for the planner.

### Decompression-bomb limits

Pillow raises `DecompressionBombWarning` above `Image.MAX_IMAGE_PIXELS` and escalates to `DecompressionBombError` above twice that limit; the threshold is settable via `Image.MAX_IMAGE_PIXELS` and disablable with `None`. `[CITED: pillow.readthedocs.io/en/stable/reference/Image.html]` The default is ~89.5 megapixels `[ASSUMED — the exact default constant was not re-verified this session; treat the number as indicative and the mechanism as verified]`.

Two things to do:

1. **Lower `MAX_IMAGE_PIXELS` for this path.** A profile photo has no business being above ~40 MP. Setting it low turns a bomb into an *error* rather than a warning, at a threshold you chose.
2. **Turn the warning into an exception**, because a `DecompressionBombWarning` between the limit and 2× the limit is *only a warning* — the decode proceeds and eats the memory. `warnings.simplefilter("error", Image.DecompressionBombWarning)` inside a `catch_warnings()` block scoped to the decode is the surgical form. Catch `Image.DecompressionBombError` alongside `OSError` (it subclasses `Exception`, and `DecompressionBombWarning` subclasses `RuntimeWarning`).

A size cap on the uploaded bytes does **not** protect you here: the whole point of a decompression bomb is that a small file decodes to an enormous bitmap. Both controls are needed.

### Writing back to the `ImageField`

```python
from django.core.files.base import ContentFile

data = normalize_profile_photo(form.cleaned_data["photo"])
user.profile_photo.save(f"{user.pk}.jpg", ContentFile(data), save=True)
```

Gotchas:

- **`FileField.save(name, content, save=True)` writes the file *and* the model field.** Do not also call `user.save()` with `update_fields` that omits `profile_photo`, or you will write the file and drop the pointer.
- **Storage renames on collision.** `FileSystemStorage.get_available_name()` appends a random suffix if `profile_photos/7.jpg` exists, so re-uploading accumulates `7_a8Kd2.jpg`, `7_pQ91x.jpg`… forever. Capture the **old name before saving** and delete it after (`old = user.profile_photo.name; ...; default_storage.delete(old)`), guarded so a missing old file is not an error.
- **`ImageField` requires Pillow and runs its own `to_python()` validation** which itself calls `Image.open().verify()`. That is a floor, not a ceiling — it does not check format allow-lists, size, or bomb limits, and (per ticket #30252) has had its own post-`verify()` bugs. Do your own validation; do not treat `ImageField` as the control.
- **Media files are user-uploaded content served from `MEDIA_URL`.** WhiteNoise serves `STATIC_ROOT`, not `MEDIA_ROOT`; media serving in production is a Phase 8 concern. Within Phase 7, note only that a re-encoded JPEG served from `/media/` should carry `X-Content-Type-Options: nosniff` — `SecurityMiddleware` is already installed but `SECURE_CONTENT_TYPE_NOSNIFF` is not set in settings `[VERIFIED: grep of config/settings.py]`, and its default is `True` in modern Django `[ASSUMED]`. Worth a one-line explicit setting rather than relying on a default.

### Form placement

There is **no `forms.py` anywhere in this project and no `request.FILES` handler** `[VERIFIED: grep across all non-migration Python — `request.FILES`, `forms.py`, and `FileField` return zero hits outside `accounts/models.py`]`. Both uploads in this phase are net-new. Recommend a single `web/forms.py` holding `ProfilePhotoForm` and `ScheduleImportForm`, each doing extension/size/decode checks in `clean_<field>()` and raising `ValidationError` — which lands naturally in the project's existing **400-renders-the-form-back** contract (see Question 2).

---

## Question 2 — htmx 2 multipart upload and the `responseHandling` override

### The mechanism

htmx serializes by default as `application/x-www-form-urlencoded`, which **cannot carry file content** — the file input contributes only its filename, so the file silently never arrives and the server sees an empty `request.FILES`. Setting `hx-encoding="multipart/form-data"` switches htmx to `FormData` + multipart. `[CITED: htmx.org/attributes/hx-encoding/]`

Placement and inheritance: `hx-encoding` is **inherited and can be placed on a parent element** `[CITED: htmx.org/attributes/hx-encoding/]`. Put it on the `<form>` that owns the file input:

```html
<form hx-post="{% url 'ifo_import_preview' %}"
      hx-encoding="multipart/form-data"
      hx-target="#import-panel"
      hx-swap="outerHTML">
  {% csrf_token %}
  <input type="file" name="file" accept=".xlsx,.csv" class="ft-input" required>
  <button type="submit" class="ft-btn">Preview</button>
</form>
```

Requirements that bite if missed:

- The `<input type="file">` must have a **`name`** and must be **inside the form htmx serializes**. htmx includes the enclosing form's values for a `hx-post` on a form or on an element within it.
- `{% csrf_token %}` must be in the form. With multipart, Django reads the CSRF token from the parsed POST data; it works, but only because the token field is part of the multipart body. If you instead trigger the request from a button *outside* the form via `hx-include`, verify the token is included.
- Progress: htmx fires `htmx:xhr:progress` on the requesting element for upload progress. The hx-encoding page does not document this `[VERIFIED: fetched page contains no xhr/progress content]`; it is documented under htmx events `[ASSUMED — not verified this session]`. Progress UI is optional for a file of this size; a disabled button plus a spinner via `hx-indicator` is sufficient and definitely supported.

### Interaction with this project's `responseHandling`

The override in `templates/base.html:36` is:

```
{"responseHandling":[
  {"code":"204","swap":false},
  {"code":"[23]..","swap":true},
  {"code":"400","swap":true,"error":false},
  {"code":"[45]..","swap":false,"error":true}]}
```

`[VERIFIED: templates/base.html:36 read directly]`

**`responseHandling` is purely a response-side config. It does not interact with request encoding at all.** There is no conflict, no ordering problem, and nothing to change in the meta tag for multipart to work. `[VERIFIED: the config governs which status codes swap and which are treated as errors; `hx-encoding` governs XHR request body construction — disjoint concerns]`

But there is a real *behavioral* interaction that will show up in UAT, and it is the answer the planner actually needs:

**A 400 re-render swaps the form back into the page, and the browser will not — cannot — repopulate a file input.** File inputs are read-only from script for security reasons; a swapped-in `<input type="file">` is always empty. So the project's deliberate "here is your form back with the error in it" contract, which works perfectly for text fields, **loses the user's file selection on every validation failure.** The user sees "File too large" and an empty file picker, and must browse for the file again.

Three ways to handle it, in order of preference:

1. **Return 400 for the *file* form but scope the swap to a small region** — swap only the error/status region (`hx-target="#import-status"`, `hx-swap="innerHTML"`) rather than the whole form. The form element with the user's file selection is never replaced, so the selection survives. This is the cleanest fix and requires no change to the global config.
2. **Do client-side pre-validation** of extension and size on `change` so the common refusals never reach the server. Defense in depth only — the server checks stay authoritative (project convention: never trust client state).
3. **Accept the reset** and make the error copy say so explicitly ("Choose the file again"). Acceptable for a rare admin surface; poor for the photo upload.

For the **profile photo** (FAC-12) the same applies, and option 1 is again right: target a `#photo-result` region, not the form.

One more, less obvious: because the 400 rule sets `"error":false`, a 400 does **not** fire `htmx:responseError`. Any JS you write that hangs off `htmx:responseError` to re-enable a submit button will not run on a 400 — use `htmx:afterRequest` (which fires for all outcomes) instead. `[VERIFIED: the config's `"error":false` on the 400 rule, read from base.html]`

Finally: **CSS/template additions for these forms require `collectstatic`** if they introduce a new static asset — and remember the test runner runs with `DEBUG=False` through the manifest.

---

## Question 3 — GRD-04 push fan-out and debounce (D-05 / D-06)

### Verdict on D-06

**D-06 is sound, and it is the right design for this system.** Three independent reasons it fits the existing machinery:

1. **The coalescing window is free.** Both triggers already fire inside the same 5-minute sweep run (`sweep_no_shows` + `detect_room_conflicts` run together under `sweep_interval_minutes: 5` `[VERIFIED: config/settings.py FLUXTRACK_POLICY]`). One `notify()` per guard per run needs no timer, no `last_alerted_at` column, and no new policy knob — exactly as D-06 states.
2. **`notify()` already supports it.** `notify(*, type, title, body, link, role=None, users=None)` takes an explicit `users` iterable and creates one `Notification` per recipient `[VERIFIED: ops/notify.py:18-36]`. A resolved list of on-duty guards drops straight in. No signature change.
3. **Delivery is already fault-isolated.** `send_push_outbox()` runs only in the scheduler's `push_outbox` job, never in a web worker `[VERIFIED: ops/push.py module docstring + 05-03 STATE entry]`. Since GRD-04 also originates in the scheduler, the whole GRD-04 path never touches a web request — no new isolation work.

### The one-line thing that will be forgotten

```python
# ops/notifications.py:59
PUSH_TYPES = {"room_event", "room_conflict", WEEKLY_REPORT_READY}
```

`[VERIFIED: ops/notifications.py:59 read directly]`

This is a **hard allow-list**. `send_push_outbox()` filters `type__in=PUSH_TYPES` `[VERIFIED: ops/push.py:82]`. A new `"guard_floor_alert"` type not added here writes `Notification` rows that appear in the bell and the list and **never push** — and `pushed_at` stays NULL forever, so the rows are re-scanned until they fall out of the 15-minute window. The symptom looks like a VAPID misconfiguration and is not.

Additionally, `CATEGORY_TYPES` maps types to mute categories, and `muted_types()` does `CATEGORY_TYPES.get(cat, set())` `[VERIFIED: ops/notifications.py:62-75]`. A type that belongs to no category **can never be muted** — it is structurally unmutable. Decide deliberately whether guard alerts should be mutable (they probably should, given FAC-12's prefs surface is all-roles) and add the type to a category if so.

### Recipient resolution — the recommended shape

The scoping question is "which on-duty guards cover the floors affected by this batch." The existing duty predicate is already shared and pure: `verification.resolver.assignment_covers_now(assignment, today, now_t)` `[VERIFIED: verification/resolver.py:63-83]`, used by `web/checker._active_floor_ids`, `_is_online_on_duty`, and `web/guard._guard_floor_ids`. **Reuse it; do not write a fourth copy** — the docstring explicitly says it exists so "the three copies can never drift again."

Resolve **guards → floors**, not floors → guards. The guard population is tiny; the affected-room population is not:

```python
# sketch inside the sweep job, after both triggers have run
def _notify_floor_guards(affected_room_ids, summaries, now):
    """One coalesced GRD-04 notification per on-duty guard per sweep run (D-06)."""
    if not affected_room_ids:
        return 0
    # Rooms -> floors. Small, bounded result: MMCM has ~5 active-term buildings.
    affected_floor_ids = set(
        Room.objects.filter(pk__in=affected_room_ids)   # see 2100-param note below
        .values_list("floor_id", flat=True))
    if not affected_floor_ids:
        return 0

    local = timezone.localtime(now)
    today, now_t = local.date(), local.time()

    # ONE query for every active guard assignment, with floors prefetched.
    assignments = list(
        Assignment.objects
        .filter(role=DutyRole.GUARD, scope=AssignmentScope.FLOOR, status="active")
        .select_related("user")
        .prefetch_related("floors"))

    per_user = {}
    for a in assignments:
        if not a.user.is_active or not assignment_covers_now(a, today, now_t):
            continue
        hit = affected_floor_ids & set(a.floors.values_list("pk", flat=True))
        if hit:
            per_user.setdefault(a.user, set()).update(hit)

    for user, floor_ids in per_user.items():
        notify(users=[user], type="guard_floor_alert",
               title=_summarize(summaries, floor_ids),   # "3 rooms now free on Floor 3"
               link="/guard/monitor")
    return len(per_user)
```

Why this shape:

- **`prefetch_related("floors")` collapses the M2M N+1.** Without it, `a.floors.values_list(...)` inside the loop is one query per assignment. With `prefetch_related`, `.values_list()` on the prefetched manager **re-queries anyway** — `values_list` does not use the prefetch cache. Use `[f.pk for f in a.floors.all()]` instead, which *does*. This is a subtle and very common mistake, and `web/guard._guard_floor_ids` currently makes it `[VERIFIED: web/guard.py:47-49 — `prefetch_related("floors")` followed by `a.floors.values_list("pk", flat=True)`]`. That is harmless there (a single user's assignments, per poll) but would matter at fan-out scale. Fixing it in `_guard_floor_ids` too is a cheap, safe improvement.
- **`is_active` is checked explicitly.** `notify(role=...)` filters `is_active=True`; `notify(users=[...])` does **not** — it trusts the caller `[VERIFIED: ops/notify.py:28-31]`. Passing a deactivated guard would create a notification for a disabled account.

### The 2100-parameter risk — where it actually is

This project's prior incident was `reset_term` at 2113 rows `[VERIFIED: STATE.md]`, and 06-07 explicitly avoided it: "key on FK id and `date__range` only (never `pk__in`, the 2100-param trap, T-06-16)" `[VERIFIED: STATE.md 06-07 entry]`.

Assessment for GRD-04:

- **`Room.objects.filter(pk__in=affected_room_ids)` is the one place a large `IN` list can form.** In practice `affected_room_ids` comes from one sweep run's newly-flagged conflicts (typically 0–2) and newly-absent sessions (typically a handful, but **the sweep backfills all past-date no-shows and self-heals after an outage** `[VERIFIED: scheduling/jobs.py sweep_no_shows docstring]` — after a multi-day scheduler outage across a 2113-schedule term, a single run could mark hundreds or low thousands of sessions absent). **That is a real 2100-param exposure, not a theoretical one.** Two mitigations, either sufficient:
  - Chunk the `pk__in` (batches of ~500) and union the floor ids, or
  - Skip the room lookup entirely: have `sweep_no_shows` return the affected floor ids directly, since it already `select_related("schedule")` and can `select_related("room")` to read `room.floor_id` off each session in the loop it is already running — **zero extra queries and zero `IN` list.** Prefer this.
- **The `Assignment` query has no `IN` list at all** — it filters on scalar equality. No risk.
- **`notify(users=[...])` creates rows in a Python loop** (`Notification.objects.create` per recipient) `[VERIFIED: ops/notify.py:32-36]`. That is an N+1 by construction, but N is the number of on-duty guards — single digits. Not worth changing, and changing it would mean editing the single-write-path function that every other feature depends on.
- **`send_push_outbox()` has a genuine N+1**: `muted_types(n.user)` is one query per row and `n.user.push_subscriptions.all()` is another `[VERIFIED: ops/push.py:88, 96]`. Coalescing per D-06 is exactly what keeps this bounded — one row per guard instead of one per room event. **This is an argument *for* D-06, not a problem with it.** Do not optimize `send_push_outbox` in this phase.

### HY010 in the fan-out

`_notify_floor_guards` writes (`Notification.objects.create`) while iterating. The `assignments` list is materialized with `list()` in the sketch above **on purpose** — iterating a lazy queryset while inserting is the exact HY010 pattern both existing sweep functions guard against `[VERIFIED: scheduling/jobs.py lines 52-58, 96-98]`. Keep the `list()`.

### Ordering within the sweep

`detect_room_conflicts` currently notifies IFO inside its per-conflict loop `[VERIFIED: scheduling/jobs.py:111-116]`. D-05 says add floor-scoped guards to that fan-out — but D-06 says coalesce. These are reconcilable: leave the existing per-conflict IFO `notify()` **exactly as it is** (IFO wants one per conflict; changing it would alter Phase 2 behavior and break its tests), and have `detect_room_conflicts` additionally *return or accumulate* the conflicting room ids so the caller can do one coalesced guard notification after both functions have run. **Do not put the guard notify inside `detect_room_conflicts`'s loop** — that would be one push per conflict, which is exactly what D-06 forbids.

This means the coalescing point is the **caller** — `run_status_sweep` / the scheduler's sweep job — not either service function. Both functions currently return only counts; they will need to return (or the caller will need to re-derive) the affected room/floor ids. Returning richer results changes their signatures, and `run_status_sweep` plus their tests assert on the count returns `[ASSUMED — the exact test assertions were not read; the planner should check `scheduling/tests.py` before changing return types]`. Returning a small dataclass or a `(count, room_ids)` tuple is a contained change; the planner should treat it as a deliberate, test-updating edit.

---

## Question 4 — Room delete refusal (D-17)

### The relations that actually exist

| Model | Field | `on_delete` | `related_name` |
|---|---|---|---|
| `scheduling.Schedule` | `room` | **PROTECT** | `schedules` |
| `scheduling.Session` | `room` | **PROTECT** | `sessions` |
| `verification.CheckerValidation` | `room` | **PROTECT** | `validations` |
| `ops.Booking` | `room` | **CASCADE** | `bookings` |
| `campus.Room` | `floor` | PROTECT | (Room→Floor, not a blocker) |

`[VERIFIED: grep of all non-migration ForeignKey declarations targeting campus.Room — scheduling/models.py:57, scheduling/models.py:91, verification/models.py:63, ops/models.py:9]`

**Two findings the planner must act on:**

1. **`Booking.room` is CASCADE.** `Room.delete()` will delete the room's bookings without complaint. So `PROTECT` alone does *not* implement D-17 — a room with only bookings deletes cleanly and takes them with it. D-17 explicitly lists Booking as a blocker, so the check must be explicit code, not a database constraint.
2. **`CheckerValidation` is a fourth blocker D-17 does not name.** It is `PROTECT`, so it *will* refuse — but as an `IntegrityError`-shaped `ProtectedError` from deep inside `.delete()`, which the UI cannot render as a named blocker. Since the phase's whole point is that the UI **names** what blocks the delete, `CheckerValidation` must be in the probe list. (In practice a room with validations also has sessions, so it will rarely be the *only* blocker — but "rarely" is not "never," and an unnamed blocker produces a 500.)

Consider whether `Booking.room` should be migrated to `PROTECT` as a defense-in-depth change. It is a one-line model change plus a metadata-only migration and it makes the database agree with the policy. Recommended, but flag it as a scope call for the planner: it changes behavior for the existing admin-only Booking surface too.

### Comparing the three approaches

| Approach | Verdict |
|---|---|
| **`django.contrib.admin.utils.NestedObjects`** | **Reject.** It is an *undocumented internal* of the admin app — no stability guarantee across Django versions, and this project is on Django 6.0 where admin internals have been actively churned. It walks the **entire** cascade tree collecting **model instances**, which for a room with ~2000 sessions and their validations means loading thousands of objects to answer a yes/no question. It also produces a nested list shaped for admin's confirmation page, which you would then have to reshape. Worst cost, worst stability, wrong output shape. |
| **`django.db.models.deletion.Collector`** | **Reject for the probe.** Same fundamental cost — `collector.collect([room])` resolves the full deletion graph. It is the right tool if you wanted to *report the full cascade*, which D-17 explicitly does not want (D-17 forbids cascade). It also raises `ProtectedError` during collection when it hits a PROTECT relation, so you would be using exception control flow to detect blockers — and the exception's `protected_objects` is a set of *instances*, again materializing rows. |
| **Per-relation `exists()` / `count()`** | **Recommend.** Four tiny queries, each `SELECT TOP 1 ... WHERE room_id = ?` (for `exists()`) or a `COUNT(*)` with an index-eligible predicate. No parameter lists, no instance loading, no admin internals, and the output shape — a dict of `{relation: count}` — is exactly what the UI needs to name blockers. MSSQL-safe by construction. |

### Recommended implementation

```python
# campus/services.py (or web/ifo.py helper) — D-17
def room_delete_blockers(room):
    """Named reasons this Room cannot be deleted, or {} if it is genuinely unused.

    Four scalar-predicate COUNTs — no pk__in list (2100-param safe), no instance
    loading, no admin internals. Schedule/Session/CheckerValidation are PROTECTed
    at the DB level; Booking is NOT (it is CASCADE), so this check is the ONLY
    thing standing between an IFO click and silently deleted bookings.
    """
    counts = {
        "schedules":  room.schedules.count(),
        "sessions":   room.sessions.count(),
        "bookings":   room.bookings.filter(status="active").count(),
        "validations": room.validations.count(),
    }
    return {k: v for k, v in counts.items() if v}
```

Design notes:

- **`count()` over `exists()`** because D-17 wants the UI to *name* the blockers, and "12 sessions, 3 schedules" is a far better refusal message than "sessions, schedules." Four `COUNT(*)`s on an indexed FK column are cheap. If you only needed a boolean, `exists()` short-circuits and is cheaper.
- **`bookings` filters `status="active"`.** This is a judgment call the planner should confirm: a cancelled booking is arguably not a live reference (D-10 establishes `status != "active"` means the room is free), but it *is* historical data that CASCADE would destroy. **Recommend counting all bookings, not just active ones**, precisely because the CASCADE makes deletion destructive — the safest reading of D-17's "referenced by any Booking." The sketch above shows the narrower filter so the choice is visible; prefer the unfiltered `room.bookings.count()`.
- **TOCTOU.** A room can gain a session between the check and the delete. Wrap check+delete in `transaction.atomic()` and **still** catch `ProtectedError` around `.delete()` as a backstop that renders the same friendly refusal. The probes are for naming; `PROTECT` is for correctness. Belt and braces, matching the project's existing "server-side re-gate on every action" convention.
- **Audit both outcomes.** Per Conventions §2, a successful delete writes `room.deleted`. A *refusal* is arguably not a state change and needs no `AuditLog` — but D-17's "Claude's Discretion" note explicitly mentions "room delete-refusal" among the new audit payloads, so log it. `room.delete_refused` with `payload={"blockers": counts}` gives IFO a trail of attempted destructive actions on rooms that turned out to be live.
- **Indexing.** `room_id` on each of these tables is an FK. SQL Server does **not** automatically index foreign keys (unlike MySQL). `[VERIFIED: well-established SQL Server behavior; Django only creates an index if `db_index=True` or the field is a FK — Django *does* set `db_index=True` on ForeignKey by default]` Django's `ForeignKey` defaults to `db_index=True`, so the indexes exist. No action needed, but worth knowing why these counts are cheap.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Image integrity + decode check | Magic-byte sniffing, header parsing | `PIL.Image.open()` + `verify()` + `convert()` | Pillow already a dep; format edge cases are endless |
| Stripping hostile payloads from an image | Byte scrubbing, EXIF surgery | Full re-encode via `img.save(BytesIO)` | Re-encode means the stored bytes are Pillow's bytes — polyglots, appended archives, and metadata all die at once |
| Decompression-bomb defense | Manual pixel-count math | `Image.MAX_IMAGE_PIXELS` + `simplefilter("error", DecompressionBombWarning)` | Pillow's check runs during header parse, before allocation |
| Multipart request encoding | Manual `FormData` + `fetch()` | `hx-encoding="multipart/form-data"` | One attribute; keeps the surface on the same htmx contract as every other form in the app |
| On-duty determination for guards | A fourth `_active_floor_ids` copy | `verification.resolver.assignment_covers_now` | Its docstring exists specifically to prevent a fourth copy |
| Notification creation | `Notification.objects.create` | `ops.notify.notify()` | NOTIF-00: single write path, enforced by convention |
| Push delivery / VAPID | Anything | `ops.push.send_push_outbox` (scheduler-only) | Crypto + fault isolation already solved in 05-03 |
| Room reference introspection | `NestedObjects` / `Collector` | Four `.count()` probes | Admin internals are unstable and load thousands of instances to answer yes/no |
| Import parsing | A second xlsx reader | `scheduling/xlsx.py` + `importing.reconcile()` + `import_offerings` | D-13: wrap, don't rewrite; parity with the real file is already proven |

**Key insight:** every one of these four questions has an existing, tested seam in this codebase. The research repeatedly lands on "call the thing that exists" — the genuinely net-new surface area in Phase 07 is narrow: two forms, one staging model, one photo-normalizing function, and one coalescing helper in the sweep caller.

---

## Common Pitfalls

### Pitfall 1: `temporary_file_path()` stashed in the session
**What goes wrong:** Commit step gets `FileNotFoundError`, or `AttributeError` on small files.
**Why:** Django unlinks the upload temp file when the request finishes; sub-2.5 MB uploads never had a path.
**How to avoid:** Copy to your own storage location in the preview request. Store a token, not a path.
**Warning signs:** Works for `.csv` in dev, fails for real `.xlsx`; or vice versa.

### Pitfall 2: Using the `Image` after `verify()`
**What goes wrong:** `AttributeError`/`OSError` on the next operation, or (worse) validation that silently never decoded anything.
**Why:** `verify()` closes the image; Pillow's docs say you must reopen. `[CITED: pillow.readthedocs.io]`
**How to avoid:** `seek(0)` then `Image.open()` again before any pixel work.
**Warning signs:** Truncated images passing validation.

### Pitfall 3: New notification type missing from `PUSH_TYPES`
**What goes wrong:** Guard alerts appear in the bell, no push ever arrives, `pushed_at` stays NULL.
**Why:** `send_push_outbox` filters `type__in=PUSH_TYPES`, a hard allow-list.
**How to avoid:** Add `"guard_floor_alert"` to `PUSH_TYPES` and to a `CATEGORY_TYPES` category (else it is unmutable).
**Warning signs:** Looks exactly like a VAPID config failure. Check the set first.

### Pitfall 4: 400-swap clears the file input
**What goes wrong:** Validation error re-renders the form; the user's file selection is gone.
**Why:** Browsers forbid programmatic population of file inputs; the swapped-in element is always empty.
**How to avoid:** Target a small status region rather than the whole form for file-bearing forms.
**Warning signs:** UAT feedback of "it made me pick the file twice."

### Pitfall 5: `prefetch_related("floors")` then `.values_list()`
**What goes wrong:** The prefetch is wasted; one query per assignment anyway.
**Why:** `values_list()` on a related manager bypasses the prefetch cache and re-queries.
**How to avoid:** `[f.pk for f in a.floors.all()]`.
**Warning signs:** Query count grows linearly with guard assignments despite the prefetch. Present today in `web/guard.py:47-49`.

### Pitfall 6: Guard notify inside the conflict loop
**What goes wrong:** One push per conflict — the exact spam D-06 forbids.
**Why:** The natural place to add a recipient is the existing `notify()` call site, which is per-conflict.
**How to avoid:** Coalesce in the *caller* after both sweep functions return; leave the per-conflict IFO notify untouched.
**Warning signs:** Guards get five pushes in one minute.

### Pitfall 7: Relying on `PROTECT` for the Booking blocker
**What goes wrong:** A room whose only references are bookings deletes cleanly and destroys them.
**Why:** `Booking.room` is CASCADE, unlike the other three Room FKs.
**How to avoid:** Explicit `exists()`/`count()` probe on `bookings`; consider migrating to `PROTECT`.
**Warning signs:** A delete that "worked" on a room the operator expected to be blocked.

### Pitfall 8: Sweep backfill producing a huge `pk__in`
**What goes wrong:** pyodbc `07002 COUNT field incorrect` after a scheduler outage.
**Why:** `sweep_no_shows` backfills all past no-shows; a multi-day gap yields thousands of affected sessions.
**How to avoid:** Read `room.floor_id` off the sessions the sweep already iterates; never build a room-id `IN` list.
**Warning signs:** Sweep works daily, explodes after downtime — the same failure class as the 04.1-04 `reset_term` incident.

### Pitfall 9: New static asset without `collectstatic`
**What goes wrong:** `ValueError` in the test suite (which forces `DEBUG=False`), or silently stale CSS in prod.
**Why:** `CompressedManifestStaticFilesStorage` resolves through `staticfiles.json`.
**How to avoid:** Run `collectstatic` after adding any new `.css`/`.js`, and restart (the manifest loads once at process start).

---

## Package Legitimacy Audit

**No external packages are installed by this phase.** Every capability researched is served by something already in `requirements.txt`: `Pillow>=10.0` (photo validation/re-encode), `Django==6.0.6` (uploads, forms, storage, ORM introspection), htmx 2.0.6 via CDN (multipart encoding), `pywebpush>=2.3,<3` + `APScheduler>=3.10,<4` (push fan-out).

**Packages removed due to [SLOP] verdict:** none — no new packages proposed.
**Packages flagged as suspicious [SUS]:** none.

The legitimacy gate is therefore not applicable to this phase. If the planner introduces a dependency (e.g. `openpyxl` for the import path), that is a **deviation from 04.1-01's locked D1 decision** — "stdlib zipfile+xml.etree .xlsx reader (no openpyxl/pandas)" `[VERIFIED: STATE.md 04.1-01]` — and must be re-researched with the gate run.

---

## Validation Architecture

### Test Framework

| Property | Value |
|---|---|
| Framework | Django test runner (`django.test.TestCase`), not pytest |
| Config file | none — tests discovered from `<app>/tests*.py` |
| Quick run command | `py -3.12 manage.py test web.tests_ifo_import -v 2` (full interpreter path required per project memory) |
| Full suite command | `py -3.12 manage.py test` |

Note: the runner forces `DEBUG=False`, so any new static asset needs `collectstatic` before tests pass.

### Phase Requirements → Test Map (research-scoped subset)

| Req | Behavior | Type | Command | Exists? |
|---|---|---|---|---|
| IFO-03b | Preview stages the file; commit finds it in a *separate* request | integration | `manage.py test web.tests_ifo_import.StagingLifecycleTests` | ❌ Wave 0 |
| IFO-03b | A >2.5 MB upload (TemporaryUploadedFile path) survives preview→commit | integration | `...ImportLargeFileTests` | ❌ Wave 0 |
| IFO-03b | Another IFO user cannot commit someone else's staged file | integration | `...StagingOwnershipTests` | ❌ Wave 0 |
| IFO-03b | Non-.xlsx/.csv refused at 400 with a friendly message, never 500 | integration | `...ImportValidationTests` | ❌ Wave 0 |
| FAC-12 | Truncated/corrupt image refused | unit | `accounts.tests_photos.PhotoValidationTests` | ❌ Wave 0 |
| FAC-12 | Stored bytes are re-encoded JPEG, EXIF absent | unit | `...PhotoReencodeTests` | ❌ Wave 0 |
| FAC-12 | Oversized-pixel image raises, does not decode | unit | `...DecompressionBombTests` | ❌ Wave 0 |
| GRD-04 | One notification per on-duty guard per sweep run, not per event | integration | `scheduling.tests_guard_alerts.CoalescingTests` | ❌ Wave 0 |
| GRD-04 | Off-duty / wrong-floor guard receives nothing | integration | `...ScopingTests` | ❌ Wave 0 |
| GRD-04 | The new type is in `PUSH_TYPES` | unit | `ops.tests_push.PushTypeRegistrationTests` | ❌ Wave 0 |
| IFO-01b | Delete refused and blockers named, per relation incl. Booking | integration | `web.tests_ifo_rooms.DeleteRefusalTests` | ❌ Wave 0 |
| IFO-01b | Genuinely unused room deletes | integration | `...DeleteAllowedTests` | ❌ Wave 0 |
| GRD-05 | Every guard view returns 405 on POST | integration | `web.tests.GuardReadOnlyTests` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the touched app's test module.
- **Per wave merge:** `manage.py test web ops scheduling accounts`.
- **Phase gate:** full suite green before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `web/forms.py` — net-new; no forms module exists anywhere in the project
- [ ] `web/tests_ifo_import.py`
- [ ] `web/tests_ifo_rooms.py`
- [ ] `accounts/tests_photos.py`
- [ ] `scheduling/tests_guard_alerts.py`
- [ ] A shared test helper producing a >2.5 MB upload (forces `TemporaryUploadedFile`) and a small one (`InMemoryUploadedFile`) — both paths must be exercised
- [ ] Update `NoImplicitSchedulerTests` job-count expectation **if** a staging-cleanup job is added
- [ ] Update the Phase-2 `release_room` grep-guard test for the IFO-08 second caller (already called out in D-11)

---

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---|---|---|
| V2 Authentication | no (Phase 8) | — |
| V3 Session Management | **yes** | Staging token in `request.session`; opaque, server-generated, `secrets.token_urlsafe(32)` |
| V4 Access Control | **yes** | `ifo_required` / `guard_required` per view; staging row bound to `uploaded_by` and re-checked on commit (IDOR); GRD-05 `@require_http_methods(['GET'])` |
| V5 Input Validation | **yes** | Extension + size + Pillow decode; server-built storage paths only |
| V6 Cryptography | no | Nothing new; VAPID owned by pywebpush |
| V12 File Upload | **yes** | Both upload paths — see below |

### Known Threat Patterns

| Pattern | STRIDE | Mitigation |
|---|---|---|
| Path traversal via uploaded filename | Tampering | Never use the client filename to build a path; name the file `{token}{ext}` server-side |
| Polyglot / payload-in-image | Tampering | Full Pillow re-encode; stored bytes are Pillow's output |
| Decompression bomb (image) | DoS | `MAX_IMAGE_PIXELS` lowered + `DecompressionBombWarning` escalated to error |
| Zip bomb (`.xlsx` is a zip) | DoS | Upload size cap + bounded row parse; IFO-admin-only surface limits exposure |
| Staged-file IDOR | Info disclosure | Token read from session (never the form); row filtered by `uploaded_by` |
| Orphaned upload accumulation | DoS (disk) | TTL sweeper deleting file then row |
| EXIF GPS leakage from a phone photo | Info disclosure | EXIF dropped by re-encode (`exif=` not passed) |
| Unauthorized guard write | Elevation | `@require_http_methods(['GET'])` on all three guard views — **currently absent** (GRD-05 open) |
| Cross-user notification leakage | Info disclosure | `notify(users=...)` list built server-side from `Assignment`, never from request data |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Pillow | FAC-12 photo pipeline | ✓ | `>=10.0` pinned, installed | — |
| Django | everything | ✓ | 6.0.6 | — |
| htmx | multipart forms | ✓ | 2.0.6 (CDN) | — |
| pywebpush | GRD-04 delivery | ✓ | `>=2.3,<3` | push silently disabled when `VAPID_PRIVATE_KEY_PATH` empty |
| APScheduler | sweep + cleanup jobs | ✓ | `>=3.10,<4` | — |
| SQL Server (LocalDB) | all persistence | ✓ | 2025 LocalDB, Windows auth | — |
| Writable `MEDIA_ROOT` | both uploads | ✓ | `BASE_DIR/media` exists in the repo | — |
| Shared cache backend | *(not required by the recommendation)* | ✗ | — | Not needed — the recommendation deliberately avoids the cache |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none material.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Pillow's default `MAX_IMAGE_PIXELS` is ~89.5 MP | Q1b | Cosmetic — the recommendation is to set it explicitly anyway |
| A2 | `htmx:xhr:progress` is the event for upload progress | Q2 | Low — progress UI is optional; `hx-indicator` is the recommended path |
| A3 | `SECURE_CONTENT_TYPE_NOSNIFF` defaults to `True` in Django 6 | Q1b | Low — the recommendation is to set it explicitly |
| A4 | `scheduling/tests.py` asserts on the integer return of `sweep_no_shows`/`detect_room_conflicts` | Q3 | Medium — if true, changing return types requires test updates; planner must read the tests before deciding the return shape |
| A5 | Phase 8 keeps a single application host (local `MEDIA_ROOT` remains valid) | Q1a | Low — the token+row design survives a swap to S3-backed storage unchanged |
| A6 | Guard population is single-digit, so per-recipient `notify()` loops are fine | Q3 | Low — would only matter at an implausible guard headcount |

---

## Open Questions

1. **Should `Booking.room` be migrated from CASCADE to PROTECT?**
   - Known: it is the only non-PROTECT Room FK, and it makes D-17's Booking blocker unenforceable at the DB level.
   - Unclear: whether changing it affects the existing admin-only Booking surface in a way the operator would notice.
   - Recommendation: do it — it is a one-line model change plus a metadata migration, and it makes the schema agree with the stated policy. Treat the explicit `count()` probe as the primary control regardless, since the UI must *name* blockers.

2. **Should cancelled bookings block a room delete?**
   - Known: D-10 treats non-active bookings as not occupying the room; CASCADE means deletion destroys them.
   - Recommendation: count **all** bookings, not just active. "Referenced by any Booking" reads plainly and the destructive CASCADE argues for the conservative reading. Worth one line of confirmation from the operator.

3. **Should guard alerts be mutable via the FAC-12 notification-prefs surface?**
   - Known: `muted_types()` only mutes types that appear in a `CATEGORY_TYPES` group; a type in no group is structurally unmutable.
   - Recommendation: add the new type to a category so guards can mute it, consistent with the all-roles prefs surface already shipped. Flag as a deliberate choice either way — silently unmutable is the worst outcome.

4. **Staging TTL value.**
   - Known: needs to outlive a realistic review of a 1211-section reconciliation report.
   - Recommendation: 2 hours, as a module constant (mirroring `ops/push.py`'s `_WINDOW_MINUTES` precedent for a discretionary constant), **not** a `FLUXTRACK_POLICY` knob — it is not an operator-tunable business rule.

---

## Sources

### Primary (HIGH confidence)
- This codebase, read directly: `config/settings.py`, `templates/base.html`, `ops/notify.py`, `ops/push.py`, `ops/notifications.py`, `ops/models.py`, `scheduling/jobs.py`, `web/guard.py`, `verification/models.py`, `verification/resolver.py`, `campus/models.py`, `accounts/models.py`, `requirements.txt`, `scheduling/management/commands/import_offerings.py`
- `.planning/STATE.md` — 2100-param incident, HY010 precedent, scheduler invariants, 06-07 export design
- `.planning/phases/07-remaining-operational-surfaces/07-CONTEXT.md` — D-01..D-18

### Secondary (MEDIUM confidence)
- docs.djangoproject.com/en/6.0/topics/http/file-uploads/ — 2.5 MB threshold, `chunks()` advice, temp-file behavior
- docs.djangoproject.com/en/6.0/releases/6.0/ — confirmed no material upload/storage/forms changes in 6.0
- htmx.org/attributes/hx-encoding/ — values, placement, inheritance
- pillow.readthedocs.io/en/stable/reference/Image.html — `MAX_IMAGE_PIXELS`, `DecompressionBombWarning`/`Error`
- Pillow `verify()` reopen requirement (search-confirmed against Pillow docs and Django ticket #30252)

### Tertiary (LOW confidence)
- Items in the Assumptions Log, all flagged inline.

---

## Metadata

**Confidence breakdown:**
- Q1a staging mechanism: **HIGH** — the decision follows deterministically from verified absent `CACHES`/`SESSION_ENGINE` settings and the command's path-based interface.
- Q1b photo pipeline: **HIGH** — `verify()` reopen and bomb limits are documented; the field already exists.
- Q2 htmx multipart: **HIGH** on the mechanism (documented) and on the non-interaction with `responseHandling` (both configs read directly); **MEDIUM** on the progress-event detail (A2).
- Q3 fan-out: **HIGH** — every seam read in source; the `PUSH_TYPES` and prefetch findings are verified defects-in-waiting. **MEDIUM** on the sweep return-signature impact (A4).
- Q4 room delete: **HIGH** — every FK and `on_delete` read directly; the Booking CASCADE finding contradicts a naive reading of D-17 and is the highest-value item in this document.

**Research date:** 2026-07-18
**Valid until:** 2026-08-17 (30 days — stable stack, no fast-moving dependencies)

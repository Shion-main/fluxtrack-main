---
phase: 07-remaining-operational-surfaces
plan: 08
subsystem: accounts/web-faculty
tags: [faculty, profile, file-upload, multipart, pillow, exif, audit, authz]
requires:
  - web.ifo import upload (07-07) - the multipart house pattern
  - accounts.User.profile_photo (ImageField, already existed, zero writers)
  - web.notifications.settings_page / mute_toggle (the other half of FAC-12)
provides:
  - accounts.photos.normalize_profile_photo / PhotoError / MAX_UPLOAD_BYTES / TARGET
  - web.faculty.profile / profile_photo_upload
  - faculty_profile / faculty_profile_photo
  - AuditLog event user.photo_updated
  - SECURE_CONTENT_TYPE_NOSNIFF
affects:
  - templates/base.html (navy-shell URL-name exclusion list)
  - templates/faculty/{history,home,modality_mine,online,schedule}.html (account menu)
tech-stack:
  added: []
  patterns:
    - pure bytes-in/bytes-out image normalizer, unit-tested without HTTP
    - verify() -> REOPEN -> convert() decode-forcing pipeline
    - full re-encode as the security control rather than byte scrubbing
    - order-asserting tests that patch the decoder to explode if reached
key-files:
  created:
    - accounts/photos.py
    - accounts/tests_photos.py
    - templates/faculty/profile.html
    - templates/faculty/_photo_status.html
    - web/tests_faculty_profile.py
  modified:
    - web/faculty.py
    - web/urls.py
    - config/settings.py
    - static/faculty/faculty.css
    - templates/base.html
    - templates/faculty/history.html
    - templates/faculty/home.html
    - templates/faculty/modality_mine.html
    - templates/faculty/online.html
    - templates/faculty/schedule.html
decisions:
  - No centre-crop; thumbnail() only. The square Checker view is achieved in CSS
    (.ft-idrow__photo is already object-fit cover), so no pixels are destroyed on
    the way in and a face cannot be cropped out of an identity photo.
  - Notification preferences are LINKED, not embedded. The existing surface is
    Franken uk-*; embedding it inside the navy shell would have meant restyling
    someone else's all-roles page.
  - The decompression-bomb defence is doubled: the process-global
    Image.MAX_IMAGE_PIXELS (scoped and restored) plus an explicit check on the
    header-declared dimensions, which does not depend on a global another thread
    could be mutating.
  - A cache-buster on the <img> src, because re-upload can land on the SAME
    stored name and the browser would otherwise show the previous photo.
metrics:
  duration: ~50 min
  tasks: 3
  files: 15
  tests_added: 44
status: complete
---

# Phase 7 Plan 08: FAC-12 Profile Photo Summary

A faculty member can upload a JPEG or PNG identity photo from their own profile page and see it immediately; the bytes that reach storage are always Pillow's re-encoded JPEG output, never the uploaded bytes, so EXIF (including GPS) and anything smuggled in the original container do not survive. This closes the remaining half of FAC-12 — the notification-preferences half already shipped and is linked, not rebuilt.

## What was built

**`accounts/photos.py`** — `normalize_profile_photo(fileobj) -> bytes`, pure bytes-in/bytes-out: no ORM, no storage, no HTTP. A test asserts that purity by grepping the module source, so the next person cannot quietly reach for `request` or `default_storage` in it.

The pipeline, in the order that matters:

1. **Byte cap before any Pillow call.** Two gates: the declared `.size` (cheap) and reading `cap + 1` bytes from the stream (honest, because `.size` is metadata that can disagree with the stream). The docstring records that neither `DATA_UPLOAD_MAX_MEMORY_SIZE` nor `FILE_UPLOAD_MAX_MEMORY_SIZE` is a size limit — the first governs the non-file body and explicitly excludes uploaded files, the second only decides memory-vs-tempfile — so this check is the only size limit that exists on the path.
2. `Image.open` → `verify()` as a structural pre-filter.
3. **Reopen.** `verify()` closes the image; the handle is dead.
4. Allow-list on the **decoded** `format`, never the filename or the browser-supplied content type.
5. `ImageOps.exif_transpose` *before* stripping, so a sideways phone photo does not stay sideways once the tag it depended on is discarded.
6. `convert("RGB")` — the line that actually forces a decode, and therefore the real "is this decodable" test.
7. `thumbnail(TARGET, LANCZOS)` — aspect-preserving, never upscaling.
8. Save as JPEG with **no `exif=` keyword**, so EXIF is dropped by omission.

**`web/faculty.py`** gained a `Profile: identity photo (FAC-12, D-16)` section: `profile` (GET-only) and `profile_photo_upload` (POST-only), both behind the existing `faculty_required`. No new module, no new decorator.

**Templates.** `faculty/profile.html` (navy `.ft-*` shell) plus `faculty/_photo_status.html`, the small swapped region.

**Tests.** 20 in `accounts/tests_photos.py`, 24 in `web/tests_faculty_profile.py`.

## The three security properties, and how each is actually asserted

**The re-encode is the control (T-07-39).** `test_stored_bytes_are_pillow_output_not_the_upload` posts an *already valid* JPEG and asserts the stored bytes differ from the sent bytes. Asserting only "the stored file is a JPEG" would pass in a world where the upload was written through untouched.

**EXIF including GPS is dropped (T-07-40).** The fixture guards itself: the test first asserts the camera-make string *is* present in the raw upload and that the EXIF block is non-empty, then asserts both are gone from the output. Without the fixture guard, a silently-failing EXIF writer would make the test pass for the wrong reason. A companion test proves orientation-6 pixels come back as a 20x40 portrait from a 40x20 landscape frame — the rotation survives losing the tag it rode in on.

**The bomb defence runs before the decode (T-07-41).** `test_pixel_bomb_raises_before_any_decode` patches `Image.Image.convert` to raise `AssertionError` if it is ever reached. The same trick guards the byte cap. These two are the tests that would fail if someone later "simplified" the pipeline by moving the cheap gates after the expensive one — a refactor that leaves every message-asserting test green while the DoS defence is gone.

The pixel test deliberately uses the band between the limit and 2x the limit (10,000 px against a 6,000 px limit), because that is the band where Pillow only **warns** and decodes anyway. Testing only the 2x band would prove `DecompressionBombError` fires on its own and prove nothing about the escalation.

## Key decisions

**No centre-crop.** `thumbnail()` only. A centre-crop on an identity photo can cut off the face it exists to show, and the display side already constrains the shape — `.ft-idrow__photo` is a fixed circle with `object-fit: cover`, so the square Checker view is achieved in CSS without destroying pixels on the way in.

**The bomb defence is doubled.** Setting the process-global `Image.MAX_IMAGE_PIXELS` is what the research called for, but it is a global: another thread's decode can observe a value this one set. So there is also an explicit check on the header-declared dimensions after the probe open, which is deterministic. The global is set in the narrowest possible window and restored in a `finally`; a test asserts it is restored on both the success and the failure path.

**A cache-buster on the `<img>` src.** Re-uploading can land on the same stored name — the old file is deleted *after* the new one is written, so the sequence is `7.jpg` → `7_a8Kd2.jpg` → `7.jpg`. On that third upload the URL is unchanged and the browser shows the previous photo, which reads to a user as "the upload silently did nothing". One `get_modified_time` stat call fixes it.

**Notification preferences are linked, not embedded.** The existing surface is an all-roles Franken `uk-*` page. Embedding its partial inside the navy shell would have meant restyling a page three other roles depend on, to avoid one link. A test asserts the profile page contains no `name="category"` and no `/notifications/mute`, so a second copy of the mute controls cannot creep in later.

**The status region carries the photo, not just the message.** Otherwise a successful upload swaps in "Photo updated" while the preview above it still shows the old photo.

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] The profile page was not registered for the navy shell**

- **Found during:** Task 2 (independently confirmed mid-plan by the concurrent 07-11 agent, which hit the identical trap on `guard_room`)
- **Issue:** `templates/base.html` gates the navy `.ft-*` shell by **URL name**, not by template — it renders the Franken admin header for any url_name *not* in an exclusion list. A new `.ft-*` page whose name is missing ships with two stacked headers and Franken chrome over a navy surface. Nothing in the template hints at this; the plan did not mention it.
- **Fix:** Added `or un == "faculty_profile"` to the exclusion list, and added `test_page_renders_the_navy_shell_without_the_franken_header` so the registration is asserted rather than trusted. Mutation-verified: removing the token fails the test.
- **Files modified:** `templates/base.html`, `web/tests_faculty_profile.py`
- **Commits:** 482685e, 6053dd6

**2. [Rule 2 - Missing critical functionality] The status region needed its own partial**

- **Found during:** Task 2
- **Issue:** The plan listed `templates/faculty/profile.html` as the only new template, but the small status region is rendered from two places — server-side on first load, and swapped in on every upload — so it cannot live inline in the page.
- **Fix:** Created `templates/faculty/_photo_status.html`, mirroring how 07-07 split `import.html` / `_import_panel.html`.
- **Files modified:** `templates/faculty/_photo_status.html` (new)
- **Commit:** 482685e

**3. [Rule 2] A file input needed CSS `.ft-control` did not provide**

- **Found during:** Task 2
- **Issue:** `.ft-control` is sized for text inputs; a file input needs vertical padding for the browser's own "Choose file" button and a styled `::file-selector-button`, or it renders cramped and unstyled inside the navy form.
- **Fix:** One delimited block appended to `static/faculty/faculty.css`, drawing only from `tokens.css`. `collectstatic` run.
- **Commit:** 482685e

## Files touched outside `files_modified`

- **`templates/faculty/_photo_status.html`** — new; see deviation 2.
- **`templates/base.html`** — one token added to the navy-shell exclusion list; see deviation 1.
- **`templates/faculty/{history,home,modality_mine,online,schedule}.html`** — one line each adding the Profile entry to the faculty account menu. The plan's Task 2 asked to "link the profile page from the faculty account menu"; the frontmatter list omitted the files that actually contain that menu. The `.ft-acct__menu` markup is duplicated per template in this codebase, so the link has to be added five times. Guard/Checker templates share the class and were deliberately left alone — the link is faculty-only.

## Merge-coordination note for the orchestrator

Per instruction, both shared files were touched as single contiguous delimited blocks:

**`web/urls.py`** — inserted in the Faculty block, far from the Guard block 07-11 edits:

```python
    # --- Faculty profile photo (FAC-12) ---
    # GET-only page + POST-only multipart upload. The notification-preferences
    # half of FAC-12 is NOT re-routed here -- it already ships all-roles at
    # notif_settings / notif_mute below, and the profile page links to it.
    path("faculty/profile", faculty.profile, name="faculty_profile"),
    path("faculty/profile/photo", faculty.profile_photo_upload,
         name="faculty_profile_photo"),
    # --- end Faculty profile photo (FAC-12) ---
```

**`static/faculty/faculty.css`** — appended at EOF, after the existing `prefers-reduced-motion` block, delimited by `/* --- Faculty profile photo (FAC-12) --- */` and `/* --- end Faculty profile photo (FAC-12) --- */`. Selectors added: `.ft-photo`, `.ft-photo__img`, `.ft-photo__ph`, `.ft-photo__meta`, and `input[type="file"].ft-control` with its `::file-selector-button`. No existing line touched.

**`templates/base.html` WILL CONFLICT and needs a human eye.** Both this plan and 07-11 edited the *same physical line* — the navy-shell exclusion list is one very long line, so git's line-based merge cannot combine `or un == "faculty_profile"` (inserted after `faculty_history`) with 07-11's `or un == "guard_room"`. The resolution is trivial and additive: **keep both tokens on the merged line.** Dropping either one ships that page double-headed, and each side has a test that will catch it.

## Plan assumptions that turned out wrong

- **"Show the current photo reusing `.ft-idrow__photo` / `.ft-idrow__ph`."** Those are 56px — correct for the Checker's identity row where the photo is an ornament, too small for a profile page where the photo is the subject. New 96px `.ft-photo__*` rules were added instead; `.ft-idrow__*` is left untouched for its existing caller.
- **"Embed its existing partial"** was offered as an option for notification prefs. Not viable: that surface is Franken `uk-*` and has no extractable partial — the mute controls are inline in `notifications/settings.html`. Linked instead, which the plan permitted.
- **The research's suggested `web/forms.py` holding a `ProfilePhotoForm`** was not built. PATTERNS.md §0 is right that this project has no `Form`/`ModelForm` usage anywhere in `web/` and hand-validates in the view; 07-07 followed that idiom, and introducing a forms.py for one field would have made this the odd surface out.

## Plan assumptions that held

- Pillow needed no version bump and no new package (12.3.0 installed).
- The `verify()`-then-reopen gotcha is real and the research's shape was correct.
- `FileSystemStorage.get_available_name` does append a collision suffix — the orphan leak is real, and the test for it fails when the delete is removed.
- `SECURE_CONTENT_TYPE_NOSNIFF` was genuinely absent from `config/settings.py`; now explicit.

## Verification

`DB_TEST_NAME=test_fluxtrack_fac2 python manage.py test` — **Ran 780 tests, FAILED (failures=3, skipped=2), 0 errors.**

The 3 failures are exactly the documented pre-existing set, unchanged by this plan:
`DevLoginCoexistTests.test_dev_login_post_authenticates_under_two_backends`,
`DevLoginCuratedDemoTests.test_garay_dev_login_authenticates_and_redirects_home`,
`HomeSurfaceNavTests.test_faculty_home_links_modality_request`.

Targeted: `accounts.tests_photos` 20 tests OK; `web.tests_faculty_profile` 24 tests OK.

`manage.py check` clean. `collectstatic --noinput` run (3 files copied) — required, this plan touched `static/faculty/faculty.css`.

`FluxTrack_SRS.docx` was regenerated by the suite (pandoc) and reverted before committing, as instructed.

**Two guards were mutation-verified rather than assumed:**
- removing `default_storage.delete(old_name)` → `test_second_upload_leaves_no_orphaned_file` fails with "the previous photo was left behind as an orphan";
- removing `faculty_profile` from the base.html exclusion list → `test_page_renders_the_navy_shell_without_the_franken_header` fails.

**Still manual (unverified by this plan):** items 3-7 of the plan's verification list — a real sideways phone photo end-to-end, an EXIF viewer on the stored file, and the Checker-side view of the new photo. The automated tests cover the same properties with generated fixtures, but not a real camera's EXIF.

## Self-Check: PASSED

- `accounts/photos.py` — FOUND
- `accounts/tests_photos.py` — FOUND
- `templates/faculty/profile.html` — FOUND
- `templates/faculty/_photo_status.html` — FOUND
- `web/tests_faculty_profile.py` — FOUND
- commit aa73479 — FOUND
- commit 5dfed22 — FOUND
- commit 482685e — FOUND
- commit 93891d8 — FOUND
- commit 6053dd6 — FOUND

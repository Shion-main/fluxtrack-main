---
phase: 07-remaining-operational-surfaces
plan: 07
subsystem: web/ifo
tags: [ifo, import, file-upload, multipart, staging, audit, authz]
requires:
  - ops.import_staging (07-02) - stage/resolve/consume/discard/sweep
  - scheduling.importing.reconcile
  - scheduling.management.commands.import_offerings (extension dispatch)
provides:
  - web.ifo.import_page / import_preview / import_commit / import_discard
  - web.ifo.IMPORT_SESSION_KEY / MAX_PARSED_ROWS
  - ifo_import / ifo_import_preview / ifo_import_commit / ifo_import_discard
  - AuditLog event schedule.imported
  - THE MULTIPART UPLOAD HOUSE PATTERN (plan 07-08 copies this)
affects:
  - templates/ifo/_console.html
tech-stack:
  added: []
  patterns:
    - multipart upload: hx-encoding + small status target + htmx:afterRequest
    - preview-then-commit across a request boundary via a session token
    - source guard pinning a destructive command out of a package
key-files:
  created:
    - templates/ifo/import.html
    - templates/ifo/_import_panel.html
    - web/tests_ifo_import.py
  modified:
    - web/ifo.py
    - web/urls.py
    - templates/ifo/_console.html
decisions:
  - static/css/console.css was NOT touched - uk-input styles the file control adequately
  - The parse try/except is deliberately broad; enumerating failure modes leaves the next one a 500
  - The reset_term source guard forbids the reachable forms, not the bare name, so the code can still explain the hazard
metrics:
  duration: ~45 min
  tasks: 3
  files: 6
  tests_added: 29
status: complete
---

# Phase 7 Plan 07: IFO-03b Import Upload Summary

Schedules can be imported from the browser: upload a `.xlsx` or `.csv`, review the four-bucket reconciliation report with nothing written to the database, then commit. This is also the first `request.FILES` handling in the codebase and establishes the multipart house pattern.

## What was built

**`web/ifo.py`** gained a `Schedule import by upload (IFO-03b)` section with four views and three helpers:

- `import_page` — GET-only. Calls `sweep_abandoned()` opportunistically (07-02 deliberately did not add a fifth scheduler job, because the 4-job count is an asserted invariant), and re-renders a staged-but-uncommitted preview so a reload does not lose a review in progress.
- `import_preview` — POST-only, the multipart entry point. Reads `request.FILES`, discards any previous staged file for this user, calls `stage_upload`, parses, reconciles, and stores **only the token** in `request.session`.
- `import_commit` — POST-only. Resolves the token from the session, runs `call_command("import_offerings", file=path, dry_run=False)`, computes `schedules_created` as a `Schedule.objects.count()` delta, consumes the row, deletes the file, clears the session key, audits.
- `import_discard` — POST-only cleanup.

`_import_report` calls `scheduling.importing.reconcile` **directly** for the structured numbers and separately captures the command's `--dry-run` stdout as a secondary detail pane — the command prints its reconciliation rather than returning it, so screen-scraping stdout for the primary display would be brittle. Rows are read through `Command()._read_rows`, the command's own extension dispatch, so `.xlsx` and `.csv` are parsed by exactly the code the CLI uses and no second parser exists.

**Templates.** `templates/ifo/import.html` carries `hx-encoding="multipart/form-data"` and targets `#import-status`; `templates/ifo/_import_panel.html` is the swapped report. Nav entry added.

**`web/tests_ifo_import.py`** — 29 tests across `ImportPreviewTests`, `StagingLifecycleTests`, `StagingOwnershipTests`, `ImportValidationTests`, `ImportSourceGuardTests`, `ImportAuthzTests`.

## The multipart house pattern (for plan 07-08 to copy)

1. **`hx-encoding="multipart/form-data"` on the `<form>` is mandatory.** htmx serializes as urlencoded by default, which cannot carry file content — without it the file silently never arrives and `request.FILES` is empty, with no error anywhere to explain why. `test_a_preview_with_no_file_at_all_is_a_message` covers the server side of this.
2. **Target a small status region, never the form.** `templates/base.html` sets `{"code":"400","swap":true,"error":false}`, so a 400 swaps — right for text fields, wrong for file fields. Browsers forbid programmatic population of a file input, so a swapped-in `<input type="file">` is always empty; targeting the form would silently destroy the operator's selection on every refusal. The refusal message says explicitly that the selection is unchanged.
3. **`htmx:responseError` does NOT fire for 400 here** because that same rule sets `"error": false`. Any re-enable handler must hang off `htmx:afterRequest`. No JS was needed in this plan; the note is in the template header for the next one.
4. **Three stores, three jobs:** bytes on disk at a server-composed path, the opaque token in the session, ownership and lifecycle in the `ImportStaging` row. The client filename is display text and is never joined into a path.
5. **Validate content, not extension** — and cap the parsed size, because a byte cap on a zip does not bound its expansion.

## Key decisions

**The parse `try/except` is deliberately broad.** Extension proves nothing about content; the real validation is that the parser accepts the bytes. The failure modes of a hostile or merely corrupt file are open-ended — `BadZipFile` for a renamed non-zip, `KeyError` for a missing sheet, `UnicodeDecodeError`, `IndexError` on a truncated grid. Enumerating them would leave the next unlisted one as a 500, which is exactly what T-07-34 forbids on an operator-facing upload. Documented in the code with that reasoning.

**`MAX_PARSED_ROWS = 20000`.** An `.xlsx` is a zip, so the 10 MB byte cap in `ops/import_staging.py` does not bound the expanded XML (T-07-33). Sized well above a real term load (~2,000 offering rows) so it can only fire on something pathological.

**An unreadable file leaves no staging row.** The bytes are unusable, so `import_preview` discards the row rather than leaving an orphan the operator cannot act on and the sweeper has to collect later.

**`static/css/console.css` was not touched.** The plan said to add CSS only if the file control genuinely needed more than `uk-input`. It did not, so nothing under `static/` changed and no `collectstatic` was required.

## Deviations from Plan

**1. [Rule 1 - Bug] The large-file test fixture tripped the row cap instead of the handler boundary**

- **Found during:** Task 3
- **Issue:** The first `_large_upload` padded the fixture with bare newlines to exceed `FILE_UPLOAD_MAX_MEMORY_SIZE`. That produces a 2.5 MB file made of ~2.6 million one-byte rows, which trips `MAX_PARSED_ROWS` — so the test failed at 400 and would have "passed" only once the cap was weakened. It would have proved nothing about the upload handler, which is its entire purpose.
- **Fix:** Padded with 400-byte-wide empty CSV rows instead, reaching the byte threshold in a few thousand rows — the shape of a real offerings export. The test now genuinely exercises the `TemporaryUploadedFile` path.
- **Files modified:** `web/tests_ifo_import.py`
- **Commit:** 038df69

**2. [Rule 3 - Blocking] The `reset_term` source guard matched its own explanation**

- **Found during:** Task 3
- **Issue:** The first guard forbade the bare string `reset_term` anywhere under `web/`. `web/ifo.py import_commit` legitimately explains *in prose* why the destructive path is excluded, so the guard failed on the very comment that documents the decision — pressuring the explanation out of the code.
- **Fix:** The guard now forbids the four *reachable* forms (`commands.reset_term`, `import reset_term`, and the quoted name as a `call_command` argument) rather than the bare name. The hazard can be named and explained; it cannot be invoked.
- **Files modified:** `web/tests_ifo_import.py`
- **Commit:** 038df69

## Files touched outside `files_modified`

- `templates/ifo/_console.html` — the Import nav entry. The plan's Task 2 text asked for this; the frontmatter list omitted it.
- `static/css/console.css` was listed in `files_modified` but deliberately **not** touched — see Key decisions.

## Plan assumptions that held

- `ops/import_staging.py` needed no changes; the web layer is a thin shell over it, as designed.
- `reconcile(data_rows, col)` returns the structured `Reconciliation` including `flagged_typo`, `flagged_unassigned` and `emailless_instructor_keys` — all rendered.
- `resolve_staged`'s `uploaded_by` + `consumed_at__isnull` filters carry both the cross-user refusal and the double-commit refusal with no extra view logic.

## Verification

`DB_TEST_NAME=test_fluxtrack_ifo python manage.py test` — **Ran 663 tests, FAILED (failures=3, skipped=2), 0 errors.** The 3 are the documented pre-existing ones.

`web.tests_ifo_import` alone: Ran 29 tests, OK.

No files under `static/` were touched, so no `collectstatic` was required.

## Self-Check: PASSED

- `templates/ifo/import.html` — FOUND
- `templates/ifo/_import_panel.html` — FOUND
- `web/tests_ifo_import.py` — FOUND
- commit 038df69 — FOUND

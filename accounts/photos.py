"""Profile-photo validation and re-encode (FAC-12, D-16).

Pure bytes-in / bytes-out: no ORM, no storage, no HTTP. That is deliberate --
this is the security control for an identity photo, and a control that can only
be exercised through a view is a control that is only ever tested through a view.

WHY A FULL RE-ENCODE IS THE CONTROL
-----------------------------------
The bytes written to storage are always bytes Pillow produced, never the bytes
that were uploaded. That single property kills a whole family of attacks at
once rather than one at a time: a polyglot (a file that is a valid JPEG *and* a
valid archive/script depending on who parses it), an archive appended after the
image's end-of-image marker, a payload smuggled in an EXIF comment, and a
malformed-but-renderable structure aimed at a downstream decoder all cease to
exist, because none of them are reproduced by the encoder. Scrubbing known-bad
constructs out of the original bytes would be an allow-list of the attacks we
happened to think of; re-encoding is an allow-list of what an image IS.

EXIF is dropped for two independent reasons: it is a payload channel, and a
phone photo carries GPS coordinates that a faculty member did not intend to
publish to every Checker who looks them up.

`ImageField.to_python()` runs its own `Image.open().verify()`. That is a FLOOR,
not a ceiling -- it does not enforce a format allow-list, a byte cap, or
decompression-bomb limits, and (Django ticket #30252) has had its own bugs
around reusing a post-`verify()` image. Do not treat it as the control.

THE VERIFY-THEN-REOPEN RULE
---------------------------
`verify()` checks structural integrity WITHOUT decoding pixels, and closes the
image; Pillow's docs are explicit that the file must be reopened before any
further use. Skipping the reopen is silent in a naive test: code that verifies
and then only reads `.format` and `.size` appears to work while never decoding
anything, so a truncated file passes validation and fails later at render time
in front of a user. `convert("RGB")` on the REOPENED image is what actually
forces the decode -- `Image.open` is lazy and reads the header only.

CROP POLICY
-----------
`thumbnail()` only: aspect-preserving, never upscaling, and the whole frame is
kept. No centre-crop. A centre-crop on an identity photo can cut off the face it
exists to show, and the display side already constrains the shape -- the
`.ft-idrow__photo` rule in static/faculty/faculty.css is a fixed circle with
`object-fit: cover`, so the square Checker view is achieved in CSS without
destroying pixels on the way in. A fixed-tuple `resize()` would distort any
non-square photo and is never correct here.
"""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

# The uploaded-byte cap. NOTE: neither of Django's upload settings is a size
# limit. DATA_UPLOAD_MAX_MEMORY_SIZE governs the NON-FILE part of the body and
# explicitly excludes uploaded files; FILE_UPLOAD_MAX_MEMORY_SIZE only decides
# whether the file lands in memory or in a temp file. This check is therefore
# the ONLY size limit that exists on this path.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# Checked against the DECODED format. The filename extension and the
# browser-supplied content type are both attacker-controlled and prove nothing.
ALLOWED_FORMATS = frozenset({"JPEG", "PNG"})

# Longest edge of the stored photo. Aspect ratio is preserved, so this is a
# bounding box, not an output size.
TARGET = (512, 512)

# Decompression-bomb ceiling. A byte cap does NOT help here -- the whole point
# of a bomb is that a few kilobytes expand into an enormous bitmap. A profile
# photo has no business above this.
MAX_IMAGE_PIXELS = 40_000_000

JPEG_QUALITY = 85


class PhotoError(ValueError):
    """A refusal carrying a message that is safe to show a faculty member.

    Subclasses ValueError so a caller that forgets to catch it still lands on
    the project's friendly-400 seam rather than in a 500.
    """


_BAD_IMAGE = "That file is not a readable JPEG or PNG photo. Please choose another."
_BAD_FORMAT = "Only JPEG and PNG photos are accepted."
_TOO_BIG = "That photo is too large. Please choose one under {mb} MB."
_TOO_MANY_PIXELS = "That photo has too many pixels to process. Please choose a smaller one."


def _capped_bytes(fileobj):
    """Return the upload's bytes, refusing anything over the cap.

    Runs BEFORE any Pillow call. Two gates, because they catch different things:
    the declared `.size` is the cheap one, and reading cap+1 bytes is the honest
    one -- `.size` is metadata and a stream whose length disagrees with it must
    not slip through.
    """
    declared = getattr(fileobj, "size", None)
    if isinstance(declared, int) and declared > MAX_UPLOAD_BYTES:
        raise PhotoError(_TOO_BIG.format(mb=MAX_UPLOAD_BYTES // (1024 * 1024)))

    fileobj.seek(0)
    data = fileobj.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise PhotoError(_TOO_BIG.format(mb=MAX_UPLOAD_BYTES // (1024 * 1024)))
    if not data:
        raise PhotoError(_BAD_IMAGE)
    return data


def normalize_profile_photo(fileobj):
    """Validate an uploaded profile photo and return re-encoded JPEG bytes.

    Raises PhotoError with a user-safe message on every refusal path, so the
    caller never has to turn a decoder exception into a 500.
    """
    data = _capped_bytes(fileobj)

    # The Pillow pixel ceiling is a process-global, so it is set for the
    # narrowest possible window and always restored. Lowering it is only half
    # the defence: between the limit and 2x the limit Pillow merely WARNS and
    # decodes anyway, so the warning is escalated to an exception for the same
    # window. Without the escalation the bomb still detonates, having politely
    # announced itself.
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            return _decode_and_reencode(data)
    except PhotoError:
        raise
    except Image.DecompressionBombWarning:
        raise PhotoError(_TOO_MANY_PIXELS)
    except Image.DecompressionBombError:
        raise PhotoError(_TOO_MANY_PIXELS)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        # Deliberately broad on the decoder's failure modes. A hostile or merely
        # corrupt file fails in open-ended ways (OSError on a truncated scan,
        # SyntaxError from a plugin's header parser, ValueError on a bad mode);
        # enumerating today's set leaves tomorrow's as a 500 on a surface a
        # faculty member touches from a phone.
        raise PhotoError(_BAD_IMAGE)
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


def _decode_and_reencode(data):
    """The pipeline. Order is load-bearing; see the module docstring."""
    probe = Image.open(io.BytesIO(data))
    declared_pixels = probe.size[0] * probe.size[1]
    probe.verify()                       # structural pre-filter; CLOSES the image

    # Belt-and-braces alongside Image.MAX_IMAGE_PIXELS above: an explicit check
    # on the header-declared dimensions, which is deterministic and does not
    # depend on a process-global that another thread could be changing. Still
    # before any decode -- opening read the header only.
    if declared_pixels > MAX_IMAGE_PIXELS:
        raise PhotoError(_TOO_MANY_PIXELS)

    # MANDATORY reopen: the verified handle is dead (see module docstring).
    img = Image.open(io.BytesIO(data))
    if img.format not in ALLOWED_FORMATS:
        raise PhotoError(_BAD_FORMAT)

    # BEFORE stripping metadata: bakes the rotation into the pixels, so a phone
    # photo taken sideways does not stay sideways once the tag it depended on is
    # discarded.
    img = ImageOps.exif_transpose(img)

    # This is the line that forces a full decode, and therefore the real "is
    # this decodable" test. It also drops alpha and palette modes, which a JPEG
    # save cannot represent.
    img = img.convert("RGB")

    img.thumbnail(TARGET, Image.LANCZOS)

    out = io.BytesIO()
    # No `exif=` keyword: Pillow only writes EXIF when asked, so omitting it
    # drops orientation, timestamps, camera make and GPS coordinates.
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()

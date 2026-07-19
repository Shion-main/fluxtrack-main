"""FAC-12 / D-16: profile photo validation and re-encode (accounts/photos.py).

Every fixture is generated in memory with Pillow rather than committed as a
binary blob -- a checked-in .jpg is unreviewable in a diff, and the corrupt case
has to be built by truncation anyway.

The tests that carry the most value are the ones asserting an ORDER rather than
a result: `test_oversized_file_raises_before_any_decode` and
`test_pixel_bomb_raises_before_any_decode` both patch the decoder to explode if
it is ever reached, so they fail if someone later "simplifies" the pipeline by
moving the cheap gates after the expensive one. A test that only asserted the
error message would still pass in that world while the DoS defence was gone.

ASCII-only by convention (Windows cp1252).
"""
import io
from unittest import mock

from django.test import TestCase
from PIL import Image, ImageOps  # noqa: F401  (ImageOps documents the intent)

from accounts import photos


# --- fixture builders -------------------------------------------------------

def _img_bytes(fmt, size=(64, 64), colour="red", mode="RGB", **save_kwargs):
    """A real, decodable image of `fmt` as bytes."""
    buf = io.BytesIO()
    Image.new(mode, size, colour).save(buf, fmt, **save_kwargs)
    return buf.getvalue()


def _jpeg(size=(64, 64)):
    return _img_bytes("JPEG", size)


def _png(size=(64, 64), mode="RGB"):
    return _img_bytes("PNG", size, mode=mode)


def _png_with_alpha(size=(64, 64)):
    buf = io.BytesIO()
    Image.new("RGBA", size, (255, 0, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


def _jpeg_with_exif(size=(40, 20), orientation=1):
    """A JPEG carrying a camera make, an orientation tag and GPS coordinates.

    The GPS values must be floats: Pillow's rational writer calls abs() on each
    value, so the (numerator, denominator) tuple form raises TypeError at save.
    """
    exif = Image.Exif()
    exif[271] = photos_test_camera_mark          # Make
    exif[274] = orientation                      # Orientation
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (14.0, 35.0, 0.0)                   # GPSLatitude
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


photos_test_camera_mark = "TESTCAMMARK"


def _upload(data, size=None):
    """A minimal stand-in for an UploadedFile: a stream plus a `.size`."""
    f = io.BytesIO(data)
    f.size = len(data) if size is None else size
    return f


def _reopen(data):
    return Image.open(io.BytesIO(data))


# --- tests ------------------------------------------------------------------

class PhotoReencodeTests(TestCase):
    """The happy paths, and the properties the re-encode is supposed to create."""

    def test_valid_jpeg_returns_reopenable_jpeg_bytes(self):
        out = photos.normalize_profile_photo(_upload(_jpeg()))
        self.assertTrue(out)
        img = _reopen(out)
        self.assertEqual(img.format, "JPEG")

    def test_png_is_accepted_and_converted_to_jpeg_without_alpha(self):
        out = photos.normalize_profile_photo(_upload(_png_with_alpha()))
        img = _reopen(out)
        self.assertEqual(img.format, "JPEG")
        self.assertEqual(img.mode, "RGB")

    def test_large_image_is_downscaled_preserving_aspect_ratio(self):
        out = photos.normalize_profile_photo(_upload(_jpeg(size=(1200, 600))))
        w, h = _reopen(out).size
        self.assertLessEqual(w, photos.TARGET[0])
        self.assertLessEqual(h, photos.TARGET[1])
        # 2:1 in, 2:1 out. thumbnail() rounds, so allow a one-pixel drift.
        self.assertAlmostEqual(w / h, 2.0, delta=0.02)

    def test_small_image_is_not_upscaled(self):
        out = photos.normalize_profile_photo(_upload(_jpeg(size=(100, 50))))
        self.assertEqual(_reopen(out).size, (100, 50))

    def test_exif_including_gps_is_stripped(self):
        raw = _jpeg_with_exif()
        # Guard the fixture itself: if the EXIF never got written, the assertion
        # below would pass for the wrong reason.
        self.assertIn(photos_test_camera_mark.encode(), raw)
        self.assertTrue(dict(_reopen(raw).getexif()))

        out = photos.normalize_profile_photo(_upload(raw))
        self.assertEqual(dict(_reopen(out).getexif()), {})
        self.assertNotIn(photos_test_camera_mark.encode(), out)

    def test_exif_rotation_is_applied_to_the_pixels(self):
        # Orientation 6 means "rotate 90 CW to display". A 40x20 landscape frame
        # must therefore come back as a 20x40 portrait, with the tag gone: the
        # rotation has to survive the stripping that removes the tag it rode in on.
        out = photos.normalize_profile_photo(
            _upload(_jpeg_with_exif(size=(40, 20), orientation=6)))
        img = _reopen(out)
        self.assertEqual(img.size, (20, 40))
        self.assertEqual(dict(img.getexif()), {})


class PhotoValidationTests(TestCase):
    """Everything the function refuses, and the reason it refuses it."""

    def test_truncated_image_is_refused(self):
        raw = _jpeg(size=(200, 200))
        with self.assertRaises(photos.PhotoError):
            photos.normalize_profile_photo(_upload(raw[:len(raw) // 3]))

    def test_non_image_named_as_jpg_is_refused(self):
        f = _upload(b"this is plain text, not an image at all" * 10)
        f.name = "portrait.jpg"       # the attacker-controlled part
        with self.assertRaises(photos.PhotoError):
            photos.normalize_profile_photo(f)

    def test_gif_is_refused_on_decoded_format_not_filename(self):
        f = _upload(_img_bytes("GIF", (10, 10), "green"))
        f.name = "portrait.jpg"       # a truthful extension would prove nothing
        with self.assertRaises(photos.PhotoError):
            photos.normalize_profile_photo(f)

    def test_bmp_is_refused_on_decoded_format(self):
        with self.assertRaises(photos.PhotoError):
            photos.normalize_profile_photo(_upload(_img_bytes("BMP", (10, 10))))

    def test_refusal_message_is_user_safe(self):
        with self.assertRaises(photos.PhotoError) as ctx:
            photos.normalize_profile_photo(_upload(b"nope"))
        msg = str(ctx.exception)
        self.assertTrue(msg and msg[0].isupper() and msg.endswith("."))
        # No stack-trace vocabulary leaking to a faculty member on a phone.
        for leak in ("Traceback", "Error:", "PIL", "cannot identify"):
            self.assertNotIn(leak, msg)

    def test_oversized_file_is_refused(self):
        with mock.patch.object(photos, "MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(_jpeg()))

    def test_oversized_file_raises_before_any_decode(self):
        """The byte cap is a cheap gate and must run before Pillow is touched."""
        with mock.patch.object(photos, "MAX_UPLOAD_BYTES", 10), \
                mock.patch.object(photos.Image, "open",
                                  side_effect=AssertionError("decoder reached")):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(_jpeg()))

    def test_size_is_measured_from_the_stream_when_there_is_no_size_attribute(self):
        """A bare file object has no `.size`; the cap must still apply."""
        bare = io.BytesIO(_jpeg())
        with mock.patch.object(photos, "MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(bare)

    def test_a_lying_size_attribute_cannot_bypass_the_cap(self):
        """`.size` is client-adjacent metadata; the real byte length decides."""
        data = _jpeg()
        with mock.patch.object(photos, "MAX_UPLOAD_BYTES", 10):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(data, size=1))


class DecompressionBombTests(TestCase):
    """A byte cap does not help here -- that is the entire point of a bomb."""

    def test_image_over_the_pixel_limit_is_refused(self):
        # 100x100 = 10,000 px against a 6,000 px limit. That band is where Pillow
        # only WARNS and decodes anyway, so this is the case the escalation exists
        # for; the 2x band raising DecompressionBombError on its own proves less.
        with mock.patch.object(photos, "MAX_IMAGE_PIXELS", 6000):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(_png(size=(100, 100))))

    def test_image_far_over_the_pixel_limit_is_refused(self):
        with mock.patch.object(photos, "MAX_IMAGE_PIXELS", 1000):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(_png(size=(100, 100))))

    def test_pixel_bomb_raises_before_any_decode(self):
        """Header parsing is cheap; convert() is where the memory is spent."""
        with mock.patch.object(photos, "MAX_IMAGE_PIXELS", 6000), \
                mock.patch.object(photos.Image.Image, "convert",
                                  side_effect=AssertionError("decoder reached")):
            with self.assertRaises(photos.PhotoError):
                photos.normalize_profile_photo(_upload(_png(size=(100, 100))))

    def test_the_global_pixel_limit_is_restored_afterwards(self):
        """The Pillow limit is process-global; leaking it would affect every thread."""
        before = Image.MAX_IMAGE_PIXELS
        photos.normalize_profile_photo(_upload(_jpeg()))
        self.assertEqual(Image.MAX_IMAGE_PIXELS, before)

        with self.assertRaises(photos.PhotoError):
            photos.normalize_profile_photo(_upload(b"nope"))
        self.assertEqual(Image.MAX_IMAGE_PIXELS, before)


class PhotoPurityTests(TestCase):
    """D-16 puts this function below the HTTP layer; keep it there."""

    def test_module_imports_no_django_request_or_storage_machinery(self):
        source = (photos.__file__)
        with open(source, "r", encoding="utf-8") as fh:
            text = fh.read()
        for forbidden in ("from django", "import django", "request",
                          "default_storage", "models"):
            self.assertNotIn(forbidden, text,
                             f"accounts/photos.py must stay pure; found {forbidden!r}")

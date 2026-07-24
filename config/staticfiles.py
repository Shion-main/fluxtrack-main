"""Static-file storage for non-production environments."""
from pathlib import Path

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage


class LiveStaticFilesStorage(StaticFilesStorage):
    """Give each source asset a URL that changes when the file changes."""

    def url(self, name):
        url = super().url(name)
        source = finders.find(name)
        if isinstance(source, (list, tuple)):
            source = source[0] if source else None
        if not source:
            return url
        try:
            stamp = Path(source).stat().st_mtime_ns
        except OSError:
            return url
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}v={stamp:x}"

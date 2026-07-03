"""Regenerate FluxTrack_SRS.docx from FluxTrack_SRS.md (DOC-01, D-14).

The .docx is a generated artifact: it is produced ONLY by this command from the
Markdown source so the two never drift. Conversion uses the bundled pandoc engine
shipped by ``pypandoc_binary`` (no system pandoc, no PATH dependency).

Never hand-edit FluxTrack_SRS.docx -- edit the .md and re-run this command.

Usage:
    py -3.12 manage.py regenerate_srs_docx
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

import pypandoc


class Command(BaseCommand):
    help = "Regenerate FluxTrack_SRS.docx from FluxTrack_SRS.md via bundled pandoc (DOC-01)."

    def handle(self, *args, **o):
        base = Path(settings.BASE_DIR)
        md_path = base / "FluxTrack_SRS.md"
        docx_path = base / "FluxTrack_SRS.docx"

        if not md_path.exists():
            self.stderr.write(self.style.ERROR(
                f"SRS source not found: {md_path} (nothing to regenerate)."))
            return

        pypandoc.convert_file(str(md_path), "docx", outputfile=str(docx_path))

        self.stdout.write(self.style.SUCCESS(
            f"Regenerated {docx_path} from {md_path} (pandoc {pypandoc.get_pandoc_version()})."))

"""Retired legacy term reset command.

Academic rollover is now close/create/activate. Historical term records are
preserved until an archived term is explicitly reopened through lifecycle tools.
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Retired. Use the academic-term lifecycle workflow instead."

    def add_arguments(self, parser):
        # Keep a minimal compatibility surface so old runbooks fail loudly with
        # the same command name instead of becoming an unknown command.
        parser.add_argument("--yes", action="store_true", help="Ignored.")

    def handle(self, *args, **options):
        raise CommandError(
            "reset_term is retired. Use the lifecycle workflow: close/archive "
            "the finished term, create or prepare the next Draft term, then "
            "activate it. Archived terms preserve official history; reopen an "
            "archive first when a correction is required."
        )

"""
Reversibly clear a term's ``Schedule`` + ``Session`` rows (Phase 04.1, D10).

The clean-load precondition for Plan 04: before a fresh ``import_offerings``
run, the term's prior schedules/sessions must be cleared so a re-import never
double-counts and the real term never mixes with the ``seed_demo`` CCIS/IT-30x
demo data. Only the term's ``Schedule`` (and its cascading ``Session``) rows are
removed — reusable ``User`` / ``Room`` / ``Floor`` / ``Building`` rows are never
touched, so the delete is fully reversible by re-running:

    py -3.12 manage.py load_room_master
    py -3.12 manage.py import_offerings
    py -3.12 manage.py materialize_sessions --days 14

Safety (T-04.1-03): deletion is gated behind an explicit ``--yes`` flag. A run
WITHOUT ``--yes`` only PREVIEWS the counts and deletes nothing.

PROTECT handling (T-04.1-04): a ``Schedule`` referenced by a
``ModalityShiftItem`` is PROTECTed. Rather than crash the whole reset, those
schedule ids are reported and skipped, so an approved-shift ticket can never be
half-deleted into an inconsistent state.

Usage:
    py -3.12 manage.py reset_term                                  # preview only
    py -3.12 manage.py reset_term --yes                            # delete
    py -3.12 manage.py reset_term --term-name "2nd Term SY 2025-2026" --yes
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from scheduling.models import (AcademicTerm, ModalityShiftItem, Schedule,
                               Session)

DEFAULT_TERM = "2nd Term SY 2025-2026"

# SQL Server caps a single statement at 2100 parameters. At full-term scale a
# term holds ~2,100+ schedules/sessions, so a single `id__in=[...]` delete — and
# the deletion collector's SET_NULL update on Session.handover_from_session —
# overflows that cap (pyodbc 07002 "COUNT field incorrect or syntax error").
# Batch every id list well under the limit. (mssql-django too-many-params wall.)
PARAM_CHUNK = 900


def _chunks(seq, n=PARAM_CHUNK):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


class Command(BaseCommand):
    help = ("Reversibly clear a term's Schedule + Session rows behind a --yes "
            "guard (D10). Keeps reusable User/Room/Building rows.")

    def add_arguments(self, p):
        p.add_argument("--term-name", default=DEFAULT_TERM,
                       help="Term to reset (default the 2T 2025-2026 term).")
        p.add_argument("--yes", action="store_true",
                       help="Actually delete. Without it, only preview counts.")

    def handle(self, *args, **o):
        w = self.stdout.write
        term_name = o["term_name"]

        term = AcademicTerm.objects.filter(name=term_name).first()
        if term is None:
            w(self.style.WARNING(
                f"No term named {term_name!r} — nothing to reset."))
            return

        # Full-term counts for the preview (materialize before any write:
        # pyodbc single-active-result-set / HY010).
        schedule_ids = list(
            Schedule.objects.filter(term=term).values_list("id", flat=True))
        session_count = Session.objects.filter(schedule__term=term).count()

        if not o["yes"]:
            w(self.style.WARNING(
                f"\nDRY RUN — nothing deleted (pass --yes to delete)"))
            w(f"  Term    : {term_name}")
            w(f"  Sessions: {session_count}")
            w(f"  Schedules: {len(schedule_ids)}")
            return

        # PROTECT guard: schedules referenced by a ModalityShiftItem cannot be
        # deleted. Report + skip them rather than raising ProtectedError.
        blocked_ids = list(
            ModalityShiftItem.objects
            .filter(schedule__term=term)
            .values_list("schedule_id", flat=True)
            .distinct())
        deletable_ids = [sid for sid in schedule_ids if sid not in blocked_ids]

        deleted_sessions = deleted_schedules = 0
        with transaction.atomic():
            # Delete Sessions first (explicit), then the Schedules. Deleting a
            # Session touches neither its PROTECTed room nor faculty rows. Batch
            # the id lists (PARAM_CHUNK) so no single DELETE / cascade SET_NULL
            # UPDATE exceeds SQL Server's 2100-parameter limit at full scale.
            for batch in _chunks(deletable_ids):
                n, _ = Session.objects.filter(schedule_id__in=batch).delete()
                deleted_sessions += n
            for batch in _chunks(deletable_ids):
                n, _ = Schedule.objects.filter(id__in=batch).delete()
                deleted_schedules += n

        w(self.style.SUCCESS(f"\nReset complete for {term_name!r}"))
        w(f"  Sessions deleted : {deleted_sessions}")
        w(f"  Schedules deleted: {deleted_schedules}")
        if blocked_ids:
            w(self.style.WARNING(
                f"  Skipped (ModalityShiftItem PROTECT): "
                f"{', '.join(str(i) for i in sorted(blocked_ids))}"))
        w("  Reusable User/Room/Building rows preserved. Re-run load_room_master"
          " + import_offerings to restore the term cleanly.")

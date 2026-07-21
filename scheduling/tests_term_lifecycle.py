"""Phase 12 (A4) - academic-term lifecycle foundations.

These tests are the Wave 0 guard for the non-destructive term lifecycle. The
checked-in SQLite file is not migration evidence; the constraint tests must run
against the configured Django test database, and production-shaped data still
needs the migration rehearsal described in the plan before production use.
"""
from datetime import date
from pathlib import Path

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TransactionTestCase

from scheduling.models import AcademicTerm


class TermConstraintTests(TransactionTestCase):
    """The database is the final backstop for lifecycle invariants."""

    reset_sequences = True

    def test_second_active_term_is_rejected_by_database(self):
        AcademicTerm.objects.create(
            name="Lifecycle Active A",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ACTIVE,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicTerm.objects.create(
                    name="Lifecycle Active B",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 12, 31),
                    status=AcademicTerm.Status.ACTIVE,
                )

    def test_inverted_date_order_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicTerm.objects.create(
                    name="Lifecycle Inverted",
                    start_date=date(2026, 8, 1),
                    end_date=date(2026, 7, 31),
                    status=AcademicTerm.Status.DRAFT,
                )

    def test_duplicate_term_name_is_rejected_by_database(self):
        AcademicTerm.objects.create(
            name="Lifecycle Unique",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AcademicTerm.objects.create(
                    name="Lifecycle Unique",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 12, 31),
                    status=AcademicTerm.Status.DRAFT,
                )


class TermMigrationContractTests(SimpleTestCase):
    """Source contract for the staged legacy-state migration."""

    def test_0008_maps_legacy_state_before_removing_boolean(self):
        path = Path("scheduling/migrations/0008_term_lifecycle.py")
        source = path.read_text(encoding="utf-8")

        self.assertIn("def forwards", source)
        self.assertIn("is_active", source)
        self.assertIn("status", source)
        self.assertIn("more than one active", source.lower())
        self.assertIn("duplicate", source.lower())
        self.assertIn("overlap", source.lower())

        runpython_at = source.index("migrations.RunPython")
        remove_field_at = source.index("migrations.RemoveField")
        self.assertLess(runpython_at, remove_field_at)

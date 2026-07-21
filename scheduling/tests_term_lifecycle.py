"""Phase 12 (A4) - academic-term lifecycle foundations.

These tests are the Wave 0 guard for the non-destructive term lifecycle. The
checked-in SQLite file is not migration evidence; the constraint tests must run
against the configured Django test database, and production-shaped data still
needs the migration rehearsal described in the plan before production use.
"""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from accounts.models import Role
from ops.models import AuditLog
from scheduling.models import AcademicTerm
from scheduling.term_lifecycle import (
    TermLifecycleError,
    create_term,
    preflight_term_creation,
)
from scheduling.term_scope import (
    ArchivedTermError,
    NoActiveTermError,
    get_active_term,
    require_active_term,
    require_writable_term,
)


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


def _user(username, role=Role.IFO_ADMIN, **kwargs):
    return get_user_model().objects.create(
        username=username,
        email=f"{username}@mcm.edu.ph",
        role=role,
        is_active=True,
        **kwargs,
    )


class TermScopeTests(TestCase):
    def test_get_active_term_uses_status_only(self):
        draft = AcademicTerm.objects.create(
            name="Scope Draft",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.DRAFT,
        )
        active = AcademicTerm.objects.create(
            name="Scope Active",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ACTIVE,
        )

        self.assertEqual(get_active_term(), active)
        self.assertNotEqual(get_active_term(), draft)

    def test_require_active_term_raises_explicit_domain_error(self):
        with self.assertRaises(NoActiveTermError):
            require_active_term()

    def test_archived_term_is_not_writable(self):
        term = AcademicTerm.objects.create(
            name="Scope Archived",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )

        with self.assertRaises(ArchivedTermError):
            require_writable_term(term)


class TermCreateTests(TestCase):
    def setUp(self):
        self.ifo = _user("term_create_ifo")
        self.dean = _user("term_create_dean", role=Role.DEAN)

    def test_non_ifo_actor_is_denied_by_service_preflight(self):
        with self.assertRaises(TermLifecycleError) as ctx:
            preflight_term_creation(
                actor=self.dean,
                name="Next Term",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 12, 31),
            )
        self.assertIn("unauthorized", ctx.exception.blockers)

    def test_preflight_reports_duplicate_overlap_and_date_blockers(self):
        AcademicTerm.objects.create(
            name="Existing Term",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
            status=AcademicTerm.Status.ARCHIVED,
        )

        duplicate = preflight_term_creation(
            actor=self.ifo,
            name="existing term",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 12, 31),
        )
        self.assertIn("duplicate_name", duplicate.blockers)

        overlap = preflight_term_creation(
            actor=self.ifo,
            name="Overlap Term",
            start_date=date(2026, 6, 30),
            end_date=date(2026, 12, 31),
        )
        self.assertIn("overlapping_term", overlap.blockers)

        inverted = preflight_term_creation(
            actor=self.ifo,
            name="Inverted Term",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 7, 31),
        )
        self.assertIn("date_order", inverted.blockers)

    def test_confirmed_create_makes_blank_draft_and_audit_in_one_transaction(self):
        term = create_term(
            actor=self.ifo,
            name="  Next   Term  ",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            confirmation_name="Next Term",
        )

        self.assertEqual(term.name, "Next Term")
        self.assertEqual(term.status, AcademicTerm.Status.DRAFT)
        self.assertEqual(term.schedules.count(), 0)

        audit = AuditLog.objects.get(event_type="term.created")
        self.assertEqual(audit.actor, self.ifo)
        self.assertEqual(audit.target_type, "academic_term")
        self.assertEqual(audit.target_id, str(term.pk))
        self.assertIsNone(audit.payload["reason"])
        self.assertEqual(audit.payload["before"], None)
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.DRAFT)
        self.assertEqual(audit.payload["schedule_count"], 0)
        self.assertEqual(audit.payload["session_count"], 0)

    def test_create_requires_distinct_exact_confirmation(self):
        with self.assertRaises(TermLifecycleError) as ctx:
            create_term(
                actor=self.ifo,
                name="Next Term",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 12, 31),
                confirmation_name="next term",
            )
        self.assertIn("confirmation_mismatch", ctx.exception.blockers)
        self.assertFalse(AcademicTerm.objects.filter(name="Next Term").exists())

    def test_create_revalidates_duplicate_inserted_after_display_preflight(self):
        preflight = preflight_term_creation(
            actor=self.ifo,
            name="Race Term",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
        )
        self.assertFalse(preflight.blockers)
        AcademicTerm.objects.create(
            name="Race Term",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.DRAFT,
        )

        with self.assertRaises(TermLifecycleError) as ctx:
            create_term(
                actor=self.ifo,
                name="Race Term",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 12, 31),
                confirmation_name="Race Term",
            )
        self.assertIn("duplicate_name", ctx.exception.blockers)

    def test_audit_failure_rolls_back_created_term(self):
        with patch("scheduling.term_lifecycle.AuditLog.objects.create") as create_audit:
            create_audit.side_effect = RuntimeError("audit insert failed")
            with self.assertRaises(RuntimeError):
                create_term(
                    actor=self.ifo,
                    name="Rollback Term",
                    start_date=date(2026, 6, 1),
                    end_date=date(2026, 12, 31),
                    confirmation_name="Rollback Term",
                )

        self.assertFalse(AcademicTerm.objects.filter(name="Rollback Term").exists())

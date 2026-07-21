"""Phase 12 (A4) - academic-term lifecycle foundations.

These tests are the Wave 0 guard for the non-destructive term lifecycle. The
checked-in SQLite file is not migration evidence; the constraint tests must run
against the configured Django test database, and production-shaped data still
needs the migration rehearsal described in the plan before production use.
"""
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from accounts.models import Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog
from scheduling.models import AcademicTerm, Schedule, Session, SessionStatus
from scheduling.term_lifecycle import (
    TermLifecycleError,
    close_term,
    create_term,
    preflight_term_action,
    preflight_term_creation,
    reopen_term,
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


def _aware(d, t):
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=ZoneInfo("Asia/Manila"))


def _room(prefix):
    building = Building.objects.create(name=f"{prefix} Hall", code=f"{prefix}-BLD")
    floor = Floor.objects.create(building=building, number=1)
    return Room.objects.create(
        floor=floor,
        code=f"{prefix}-101",
        capacity=40,
        qr_token=f"{prefix}-qr",
        manual_code=f"{prefix[:1].upper()}0001"[:6],
    )


def _schedule(term, faculty, prefix="tlc"):
    room = _room(prefix)
    return Schedule.objects.create(
        term=term,
        course_code=f"{prefix.upper()}101",
        section="A",
        faculty=faculty,
        room=room,
        day_of_week=0,
        start_time=time(8, 0),
        end_time=time(9, 30),
    )


def _session(schedule, faculty, status=SessionStatus.SCHEDULED):
    d = date(2026, 5, 1)
    return Session.objects.create(
        schedule=schedule,
        faculty=faculty,
        room=schedule.room,
        date=d,
        scheduled_start=_aware(d, schedule.start_time),
        scheduled_end=_aware(d, schedule.end_time),
        status=status,
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


class TermTransitionTests(TestCase):
    def setUp(self):
        self.ifo = _user("term_transition_ifo")
        self.faculty = _user("term_transition_faculty", role=Role.FACULTY)
        self.today = date(2026, 6, 1)
        self.term = AcademicTerm.objects.create(
            name="Transition Active",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ACTIVE,
        )

    def test_close_refuses_before_end_date(self):
        with self.assertRaises(TermLifecycleError) as ctx:
            close_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name=self.term.name,
                reason="End of term",
                today=date(2026, 5, 30),
            )
        self.assertIn("before_end_date", ctx.exception.blockers)
        self.term.refresh_from_db()
        self.assertEqual(self.term.status, AcademicTerm.Status.ACTIVE)

    def test_close_refuses_active_sessions(self):
        schedule = _schedule(self.term, self.faculty, "act")
        _session(schedule, self.faculty, SessionStatus.ACTIVE)

        with self.assertRaises(TermLifecycleError) as ctx:
            close_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name=self.term.name,
                reason="End of term",
                today=self.today,
            )
        self.assertIn("active_sessions", ctx.exception.blockers)

    def test_close_requires_exact_confirmation_and_reason(self):
        with self.assertRaises(TermLifecycleError) as wrong:
            close_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name="transition active",
                reason="End of term",
                today=self.today,
            )
        self.assertIn("confirmation_mismatch", wrong.exception.blockers)

        with self.assertRaises(TermLifecycleError) as missing_reason:
            close_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name=self.term.name,
                reason=" ",
                today=self.today,
            )
        self.assertIn("reason_required", missing_reason.exception.blockers)

    def test_close_revalidates_warning_acknowledgements_under_lock(self):
        preflight = preflight_term_action(
            self.term.pk, "close", actor=self.ifo, today=self.today
        )
        self.assertEqual(preflight.warnings, ())
        schedule = _schedule(self.term, self.faculty, "warn")
        _session(schedule, self.faculty, SessionStatus.SCHEDULED)

        with self.assertRaises(TermLifecycleError) as ctx:
            close_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name=self.term.name,
                reason="End of term",
                today=self.today,
                acknowledged_warnings=preflight.warnings,
            )
        self.assertIn("warnings_unacknowledged", ctx.exception.blockers)

    def test_successful_close_preserves_schedules_sessions_and_audits(self):
        schedule = _schedule(self.term, self.faculty, "done")
        session = _session(schedule, self.faculty, SessionStatus.COMPLETED)

        closed = close_term(
            self.term.pk,
            actor=self.ifo,
            confirmation_name=self.term.name,
            reason="Registrar close",
            today=self.today,
        )

        self.assertEqual(closed.status, AcademicTerm.Status.ARCHIVED)
        self.assertTrue(Schedule.objects.filter(pk=schedule.pk).exists())
        session.refresh_from_db()
        self.assertEqual(session.status, SessionStatus.COMPLETED)
        audit = AuditLog.objects.get(event_type="term.archived")
        self.assertEqual(audit.actor, self.ifo)
        self.assertEqual(audit.payload["reason"], "Registrar close")
        self.assertEqual(audit.payload["before"], AcademicTerm.Status.ACTIVE)
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.ARCHIVED)
        self.assertEqual(audit.payload["schedule_count"], 1)
        self.assertEqual(audit.payload["session_count"], 1)
        self.assertEqual(audit.payload["active_session_count"], 0)

    def test_reopen_requires_reason_and_returns_archived_to_draft_with_active_untouched(self):
        self.term.status = AcademicTerm.Status.ARCHIVED
        self.term.save(update_fields=["status"])
        current = AcademicTerm.objects.create(
            name="Current Active",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ACTIVE,
        )

        with self.assertRaises(TermLifecycleError) as missing_reason:
            reopen_term(
                self.term.pk,
                actor=self.ifo,
                confirmation_name=self.term.name,
                reason=" ",
            )
        self.assertIn("reason_required", missing_reason.exception.blockers)

        reopened = reopen_term(
            self.term.pk,
            actor=self.ifo,
            confirmation_name=self.term.name,
            reason="Correction window",
            acknowledged_warnings=("active_successor_exists",),
        )

        reopened.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(reopened.status, AcademicTerm.Status.DRAFT)
        self.assertEqual(current.status, AcademicTerm.Status.ACTIVE)
        audit = AuditLog.objects.get(event_type="term.reopened")
        self.assertEqual(audit.payload["before"], AcademicTerm.Status.ARCHIVED)
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.DRAFT)
        self.assertIn("active_successor_exists", audit.payload["acknowledged_warning_keys"])

    def test_injected_audit_failure_rolls_back_close(self):
        with patch("scheduling.term_lifecycle.AuditLog.objects.create") as create_audit:
            create_audit.side_effect = RuntimeError("audit insert failed")
            with self.assertRaises(RuntimeError):
                close_term(
                    self.term.pk,
                    actor=self.ifo,
                    confirmation_name=self.term.name,
                    reason="End of term",
                    today=self.today,
                )

        self.term.refresh_from_db()
        self.assertEqual(self.term.status, AcademicTerm.Status.ACTIVE)
        self.assertFalse(AuditLog.objects.filter(event_type="term.archived").exists())

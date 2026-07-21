"""Phase 12 (A4) - academic-term lifecycle foundations.

These tests are the Wave 0 guard for the non-destructive term lifecycle. The
checked-in SQLite file is not migration evidence; the constraint tests must run
against the configured Django test database, and production-shaped data still
needs the migration rehearsal described in the plan before production use.
"""
from datetime import date, datetime, time, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib import admin
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.admin import WeeklyReportAdmin
from ops.models import AuditLog, Notification, RoomConflictFlag, WeeklyReport
from scheduling.admin import AcademicTermAdmin, ScheduleAdmin
from scheduling.jobs import detect_room_conflicts, sweep_no_shows
from scheduling.materialization import MaterializationError, materialize_term
from scheduling.merge import propagate_merged_present
from scheduling.models import (
    AcademicTerm,
    AcademicBreak,
    ClassSuspension,
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Schedule,
    ScheduleStatus,
    Session,
    SessionStatus,
)
from scheduling.schedule_ops import cancel_schedule, update_schedule
from scheduling.services import (
    ModalityShiftError,
    apply_approval,
    reject_modality_shift,
    submit_modality_shift,
    withdraw_modality_shift,
)
from scheduling.suspensions import lift_suspension, suspend_classes
from scheduling.term_lifecycle import (
    TermLifecycleError,
    activate_term,
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
from verification.admin import AssignmentAdmin, CheckerValidationAdmin
from verification.models import (
    Assignment,
    AssignmentScope,
    CheckerValidation,
    DutyRole,
)
from verification.services import assign_online_sessions


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
    manual_prefix = "".join(ch for ch in prefix.upper() if ch.isalnum())[:3] or "TLC"
    return Room.objects.create(
        floor=floor,
        code=f"{prefix}-101",
        capacity=40,
        qr_token=f"{prefix}-qr",
        manual_code=f"{manual_prefix}001"[:6],
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


class ActivationMaterializationTests(TestCase):
    def setUp(self):
        self.ifo = _user("activation_ifo")
        self.faculty = _user("activation_faculty", role=Role.FACULTY)
        self.active = AcademicTerm.objects.create(
            name="Materialize Active",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.ACTIVE,
        )
        self.draft = AcademicTerm.objects.create(
            name="Materialize Draft",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.DRAFT,
        )
        self.archived = AcademicTerm.objects.create(
            name="Materialize Archived",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.ARCHIVED,
        )

    def test_materialize_term_targets_only_the_explicit_term_and_is_idempotent(self):
        active_schedule = _schedule(self.active, self.faculty, "mat")
        draft_schedule = _schedule(self.draft, self.faculty, "mdr")

        first = materialize_term(
            self.active, start=date(2026, 7, 6), days=7
        )
        second = materialize_term(
            self.active, start=date(2026, 7, 6), days=7
        )

        self.assertEqual(first.created, 1)
        self.assertEqual(first.existing, 0)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.existing, 1)
        self.assertEqual(
            Session.objects.filter(schedule__term=self.active).count(), 1
        )
        self.assertFalse(
            Session.objects.filter(schedule=draft_schedule).exists()
        )
        self.assertTrue(
            Session.objects.filter(schedule=active_schedule).exists()
        )

    def test_materialize_term_clamps_to_term_bounds(self):
        _schedule(self.active, self.faculty, "clp")

        result = materialize_term(
            self.active, start=date(2026, 6, 29), days=14
        )

        self.assertEqual(result.created, 1)
        self.assertEqual(
            list(Session.objects.values_list("date", flat=True)),
            [date(2026, 7, 6)],
        )

    def test_materialize_term_rejects_draft_unless_internal_override(self):
        _schedule(self.draft, self.faculty, "drf")

        with self.assertRaises(MaterializationError):
            materialize_term(self.draft, start=date(2026, 7, 6), days=7)

        result = materialize_term(
            self.draft, start=date(2026, 7, 6), days=7, allow_draft=True
        )

        self.assertEqual(result.created, 1)

    def test_materialize_term_always_rejects_archived_terms(self):
        _schedule(self.archived, self.faculty, "arc")

        with self.assertRaises(MaterializationError):
            materialize_term(
                self.archived, start=date(2026, 7, 6), days=7,
                allow_draft=True,
            )

        self.assertEqual(Session.objects.count(), 0)

    def test_command_without_term_uses_authoritative_active_term(self):
        _schedule(self.active, self.faculty, "cmd")
        _schedule(self.draft, self.faculty, "cmdr")
        out = StringIO()

        call_command(
            "materialize_sessions",
            start="2026-07-06",
            days=7,
            stdout=out,
        )

        self.assertIn("Materialized 2026-07-06", out.getvalue())
        self.assertEqual(
            Session.objects.filter(schedule__term=self.active).count(), 1
        )
        self.assertEqual(
            Session.objects.filter(schedule__term=self.draft).count(), 0
        )

    def test_command_term_option_refuses_draft_and_archived_targets(self):
        _schedule(self.draft, self.faculty, "cdt")
        _schedule(self.archived, self.faculty, "car")

        for target in (str(self.draft.pk), self.archived.name):
            with self.subTest(target=target):
                with self.assertRaisesMessage(Exception, "ACTIVE"):
                    call_command(
                        "materialize_sessions",
                        term=target,
                        start="2026-07-06",
                        days=7,
                    )

        self.assertEqual(Session.objects.count(), 0)

    def test_materialize_command_delegates_to_service_without_recurrence_loop(self):
        source = Path(
            "scheduling/management/commands/materialize_sessions.py"
        ).read_text(encoding="utf-8")

        self.assertIn("materialize_term(", source)
        self.assertNotIn(".filter(is_active=True).first()", source)
        self.assertNotIn("while d < end", source)

    def test_activate_refuses_when_another_term_is_active(self):
        _schedule(self.draft, self.faculty, "actblk")

        with self.assertRaises(TermLifecycleError) as ctx:
            activate_term(
                self.draft.pk,
                actor=self.ifo,
                confirmation_name=self.draft.name,
                today=date(2026, 7, 6),
            )

        self.assertIn("another_active", ctx.exception.blockers)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AcademicTerm.Status.DRAFT)

    def test_activate_materializes_policy_horizon_before_status_and_audit(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])
        _schedule(self.draft, self.faculty, "actok")

        with patch("scheduling.term_lifecycle.get_policy", return_value=14):
            activated = activate_term(
                self.draft.pk,
                actor=self.ifo,
                confirmation_name=self.draft.name,
                today=date(2026, 7, 6),
            )

        self.assertEqual(activated.status, AcademicTerm.Status.ACTIVE)
        self.assertEqual(
            Session.objects.filter(schedule__term=self.draft).count(), 2
        )
        audit = AuditLog.objects.get(event_type="term.activated")
        self.assertEqual(audit.payload["horizon_days"], 14)
        self.assertEqual(audit.payload["materialization"]["created"], 2)
        self.assertEqual(audit.payload["before"], AcademicTerm.Status.DRAFT)
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.ACTIVE)

    def test_activate_rolls_back_materialized_sessions_state_and_audit_on_failure(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])
        schedule = _schedule(self.draft, self.faculty, "actfail")

        def fail_after_create(term, *, start, days, allow_draft=False):
            Session.objects.create(
                schedule=schedule,
                faculty=self.faculty,
                room=schedule.room,
                date=date(2026, 7, 6),
                scheduled_start=_aware(date(2026, 7, 6), schedule.start_time),
                scheduled_end=_aware(date(2026, 7, 6), schedule.end_time),
                status=SessionStatus.SCHEDULED,
            )
            raise RuntimeError("materializer failed after first create")

        with patch(
            "scheduling.term_lifecycle.materialize_term",
            side_effect=fail_after_create,
        ):
            with self.assertRaises(RuntimeError):
                activate_term(
                    self.draft.pk,
                    actor=self.ifo,
                    confirmation_name=self.draft.name,
                    today=date(2026, 7, 6),
                )

        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(Session.objects.filter(schedule__term=self.draft).exists())
        self.assertFalse(AuditLog.objects.filter(event_type="term.activated").exists())

    def test_empty_schedule_warning_must_be_acknowledged_before_activation(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])

        with self.assertRaises(TermLifecycleError) as ctx:
            activate_term(
                self.draft.pk,
                actor=self.ifo,
                confirmation_name=self.draft.name,
                today=date(2026, 7, 6),
            )
        self.assertIn("warnings_unacknowledged", ctx.exception.blockers)
        self.assertIn("empty_schedule_set", ctx.exception.warnings)

        activated = activate_term(
            self.draft.pk,
            actor=self.ifo,
            confirmation_name=self.draft.name,
            acknowledged_warnings=("empty_schedule_set",),
            today=date(2026, 7, 6),
        )

        self.assertEqual(activated.status, AcademicTerm.Status.ACTIVE)
        self.assertEqual(Session.objects.filter(schedule__term=self.draft).count(), 0)


class SingleActiveTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.ifo = _user("single_active_ifo")
        self.faculty = _user("single_active_faculty", role=Role.FACULTY)
        self.first = AcademicTerm.objects.create(
            name="Single Draft A",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.DRAFT,
        )
        self.second = AcademicTerm.objects.create(
            name="Single Draft B",
            start_date=date(2026, 8, 3),
            end_date=date(2026, 8, 17),
            status=AcademicTerm.Status.DRAFT,
        )
        _schedule(self.first, self.faculty, "saa")
        _schedule(self.second, self.faculty, "sab")

    def test_losing_activation_reports_controlled_blocker_and_preserves_single_active(self):
        activate_term(
            self.first.pk,
            actor=self.ifo,
            confirmation_name=self.first.name,
            today=date(2026, 7, 6),
        )

        with self.assertRaises(TermLifecycleError) as ctx:
            activate_term(
                self.second.pk,
                actor=self.ifo,
                confirmation_name=self.second.name,
                today=date(2026, 8, 3),
            )

        self.assertIn("another_active", ctx.exception.blockers)
        self.assertEqual(
            AcademicTerm.objects.filter(status=AcademicTerm.Status.ACTIVE).count(),
            1,
        )


class ActiveTermJobScopeTests(TestCase):
    def setUp(self):
        self.ifo = _user("active_job_ifo")
        self.faculty = _user("active_job_faculty", role=Role.FACULTY)
        self.active = AcademicTerm.objects.create(
            name="Job Active",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.ACTIVE,
        )
        self.draft = AcademicTerm.objects.create(
            name="Job Draft",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.DRAFT,
        )
        self.archived = AcademicTerm.objects.create(
            name="Job Archived",
            start_date=date(2026, 7, 6),
            end_date=date(2026, 7, 20),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.active_schedule = _schedule(self.active, self.faculty, "jba")
        self.draft_schedule = _schedule(self.draft, self.faculty, "jbd")
        self.archived_schedule = _schedule(self.archived, self.faculty, "jbh")

    def _job_session(
        self,
        schedule,
        *,
        status=SessionStatus.SCHEDULED,
        room=None,
        hour=8,
    ):
        d = date(2026, 7, 6)
        start = timezone.make_aware(datetime.combine(d, time(hour, 0)))
        return Session.objects.create(
            schedule=schedule,
            faculty=self.faculty,
            room=room or schedule.room,
            date=d,
            scheduled_start=start,
            scheduled_end=start + timedelta(minutes=90),
            status=status,
        )

    def test_sweep_no_shows_marks_only_active_term_same_date_candidates(self):
        active = self._job_session(self.active_schedule)
        draft = self._job_session(self.draft_schedule)
        archived = self._job_session(self.archived_schedule)
        now = timezone.make_aware(datetime(2026, 7, 6, 10, 0))

        marked = sweep_no_shows(now=now)

        self.assertEqual(marked, 1)
        active.refresh_from_db()
        draft.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(active.status, SessionStatus.ABSENT)
        self.assertEqual(draft.status, SessionStatus.SCHEDULED)
        self.assertEqual(archived.status, SessionStatus.SCHEDULED)
        self.assertEqual(
            list(AuditLog.objects.values_list("target_id", flat=True)),
            [str(active.pk)],
        )

    def test_sweep_no_shows_without_active_term_is_zero_effect(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])
        session = self._job_session(self.active_schedule)
        now = timezone.make_aware(datetime(2026, 7, 6, 10, 0))

        marked = sweep_no_shows(now=now)

        session.refresh_from_db()
        self.assertEqual(marked, 0)
        self.assertEqual(session.status, SessionStatus.SCHEDULED)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_conflict_detection_ignores_non_active_same_room_sessions(self):
        room = self.active_schedule.room
        self._job_session(self.draft_schedule, status=SessionStatus.ACTIVE, room=room)
        self._job_session(
            self.archived_schedule,
            status=SessionStatus.ACTIVE,
            room=room,
        )

        flagged = detect_room_conflicts()

        self.assertEqual(flagged, 0)
        self.assertEqual(RoomConflictFlag.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    def test_conflict_detection_flags_only_active_term_room_pairs(self):
        room = self.active_schedule.room
        self._job_session(self.active_schedule, status=SessionStatus.ACTIVE, room=room)
        self._job_session(
            self.archived_schedule,
            status=SessionStatus.ACTIVE,
            room=room,
        )

        self.assertEqual(detect_room_conflicts(), 0)

        other_active_schedule = _schedule(self.active, self.faculty, "jbc")
        self._job_session(other_active_schedule, status=SessionStatus.ACTIVE, room=room)

        self.assertEqual(detect_room_conflicts(), 1)
        self.assertEqual(RoomConflictFlag.objects.count(), 1)

    def test_online_assignment_uses_only_active_sessions_and_duty(self):
        checker = _user("active_job_checker", role=Role.CHECKER)
        Assignment.objects.create(
            user=checker,
            role=DutyRole.CHECKER,
            type="standing",
            scope=AssignmentScope.ONLINE,
            term=self.active,
            status="active",
        )
        self.active_schedule.modality = Modality.ONLINE
        self.active_schedule.save(update_fields=["modality"])
        self.draft_schedule.modality = Modality.ONLINE
        self.draft_schedule.save(update_fields=["modality"])
        self.archived_schedule.modality = Modality.ONLINE
        self.archived_schedule.save(update_fields=["modality"])
        active = self._job_session(self.active_schedule)
        draft = self._job_session(self.draft_schedule)
        archived = self._job_session(self.archived_schedule)

        result = assign_online_sessions(date(2026, 7, 6))

        self.assertEqual(result, {"assigned": 1, "unassigned": 0})
        active.refresh_from_db()
        draft.refresh_from_db()
        archived.refresh_from_db()
        self.assertEqual(active.online_checker_id, checker.id)
        self.assertIsNone(draft.online_checker_id)
        self.assertIsNone(archived.online_checker_id)

    def test_online_assignment_ignores_non_active_duty_and_no_active_is_noop(self):
        checker = _user("draft_job_checker", role=Role.CHECKER)
        Assignment.objects.create(
            user=checker,
            role=DutyRole.CHECKER,
            type="standing",
            scope=AssignmentScope.ONLINE,
            term=self.draft,
            status="active",
        )
        self.active_schedule.modality = Modality.ONLINE
        self.active_schedule.save(update_fields=["modality"])
        active = self._job_session(self.active_schedule)

        result = assign_online_sessions(date(2026, 7, 6))

        active.refresh_from_db()
        self.assertEqual(result, {"assigned": 0, "unassigned": 1})
        self.assertIsNone(active.online_checker_id)

        Notification.objects.all().delete()
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])

        result = assign_online_sessions(date(2026, 7, 6))

        active.refresh_from_db()
        self.assertEqual(result, {"assigned": 0, "unassigned": 0})
        self.assertIsNone(active.online_checker_id)
        self.assertEqual(Notification.objects.count(), 0)

    def test_job_source_coupling_names_authoritative_active_scope(self):
        jobs_source = Path("scheduling/jobs.py").read_text(encoding="utf-8")
        services_source = Path("verification/services.py").read_text(encoding="utf-8")
        command_source = Path(
            "scheduling/management/commands/assign_online.py"
        ).read_text(encoding="utf-8")

        self.assertIn("get_active_term()", jobs_source)
        self.assertIn("schedule__term=active_term", jobs_source)
        self.assertIn("get_active_term()", services_source)
        self.assertIn("schedule__term=active_term", services_source)
        self.assertIn("term=active_term", services_source)
        self.assertIn("get_active_term()", command_source)

    def test_no_option_command_touches_only_authoritative_active_term(self):
        out = StringIO()

        call_command(
            "materialize_sessions",
            start="2026-07-06",
            days=7,
            stdout=out,
        )

        self.assertEqual(
            Session.objects.filter(schedule=self.active_schedule).count(), 1
        )
        self.assertFalse(Session.objects.filter(schedule=self.draft_schedule).exists())
        self.assertFalse(
            Session.objects.filter(schedule=self.archived_schedule).exists()
        )
        out.getvalue().encode("ascii")

    def test_term_option_selects_only_exact_active_target_and_is_idempotent(self):
        for _ in range(2):
            call_command(
                "materialize_sessions",
                term=self.active.name,
                start="2026-07-06",
                days=7,
            )

        self.assertEqual(
            Session.objects.filter(schedule=self.active_schedule).count(), 1
        )
        self.assertFalse(Session.objects.filter(schedule=self.draft_schedule).exists())
        self.assertFalse(
            Session.objects.filter(schedule=self.archived_schedule).exists()
        )

    def test_public_command_refuses_draft_and_archived_terms_without_writes(self):
        for target in (str(self.draft.pk), self.archived.name):
            with self.subTest(target=target):
                with self.assertRaisesMessage(CommandError, "ACTIVE"):
                    call_command(
                        "materialize_sessions",
                        term=target,
                        start="2026-07-06",
                        days=7,
                    )

        self.assertEqual(Session.objects.count(), 0)

    def test_public_command_without_active_term_fails_friendly_without_writes(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])

        with self.assertRaisesMessage(CommandError, "No ACTIVE academic term"):
            call_command(
                "materialize_sessions",
                start="2026-07-06",
                days=7,
            )

        self.assertEqual(Session.objects.count(), 0)

    def test_scheduler_materialize_job_inherits_command_adapter(self):
        scheduler_source = Path(
            "scheduling/management/commands/runscheduler.py"
        ).read_text(encoding="utf-8")
        command_source = Path(
            "scheduling/management/commands/materialize_sessions.py"
        ).read_text(encoding="utf-8")

        self.assertIn('call_command("materialize_sessions")', scheduler_source)
        self.assertIn("materialize_term(", command_source)
        self.assertNotIn("while d < end", command_source)


class ArchiveFreezeServiceTests(TestCase):
    """D-04: reusable service writers refuse archived term ownership."""

    def setUp(self):
        self.dept = Department.objects.create(name="Freeze Dept", code="FRZ")
        self.ifo = _user("freeze_ifo")
        self.faculty = _user("freeze_faculty", role=Role.FACULTY,
                             department=self.dept)
        self.dean = _user("freeze_dean", role=Role.DEAN, department=self.dept)
        self.archived = AcademicTerm.objects.create(
            name="Freeze Archived",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.active = AcademicTerm.objects.create(
            name="Freeze Active",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            status=AcademicTerm.Status.ACTIVE,
        )

    def _schedule(self, term, prefix):
        return _schedule(term, self.faculty, prefix)

    def _session(self, schedule, status=SessionStatus.SCHEDULED):
        return _session(schedule, self.faculty, status)

    def _pending_request(self, schedule):
        req = ModalityShiftRequest.objects.create(
            requester=self.faculty,
            dean=self.dean,
            department=self.dept,
            target_modality=Modality.ONLINE,
            window_start=date(2026, 5, 1),
            window_end=date(2026, 5, 1),
            status=ModalityShiftStatus.PENDING,
        )
        ModalityShiftItem.objects.create(request=req, schedule=schedule)
        return req

    def _counts(self):
        return {
            "audit": AuditLog.objects.count(),
            "notification": Notification.objects.count(),
            "requests": ModalityShiftRequest.objects.count(),
            "items": ModalityShiftItem.objects.count(),
            "suspensions": ClassSuspension.objects.count(),
        }

    def test_schedule_update_and_cancel_refuse_archived_without_side_effects(self):
        schedule = self._schedule(self.archived, "frzsch")
        session = self._session(schedule)
        before = self._counts()

        with self.assertRaises(ArchivedTermError):
            update_schedule(
                schedule,
                faculty=self.dean,
                room=schedule.room,
                start_time=time(10, 0),
                end_time=time(11, 30),
                enrolled_count=20,
                actor=self.ifo,
                today=date(2026, 5, 1),
            )
        with self.assertRaises(ArchivedTermError):
            cancel_schedule(
                schedule, actor=self.ifo, reason="Archived correction",
                today=date(2026, 5, 1),
            )

        schedule.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(schedule.status, ScheduleStatus.ACTIVE)
        self.assertEqual(session.status, SessionStatus.SCHEDULED)
        self.assertEqual(self._counts(), before)

    def test_suspension_declare_and_lift_refuse_archived_without_side_effects(self):
        schedule = self._schedule(self.archived, "frzsus")
        session = self._session(schedule)
        suspension = ClassSuspension.objects.create(
            term=self.archived,
            start_date=session.date,
            end_date=session.date,
            reason="Archived",
            declared_by=self.ifo,
        )
        before = self._counts()

        with self.assertRaises(ArchivedTermError):
            suspend_classes(
                term=self.archived,
                start_date=session.date,
                end_date=session.date,
                reason="Archived",
                declared_by=self.ifo,
            )
        with self.assertRaises(ArchivedTermError):
            lift_suspension(suspension, lifted_by=self.ifo)

        session.refresh_from_db()
        suspension.refresh_from_db()
        self.assertEqual(session.status, SessionStatus.SCHEDULED)
        self.assertIsNone(suspension.lifted_at)
        self.assertEqual(self._counts(), before)

    def test_modality_submit_refuses_archived_and_mixed_terms_without_writes(self):
        archived_schedule = self._schedule(self.archived, "frzmod")
        active_schedule = self._schedule(self.active, "frzact")
        self._session(archived_schedule)
        before = self._counts()

        with self.assertRaises(ModalityShiftError):
            submit_modality_shift(
                self.faculty,
                [archived_schedule],
                Modality.ONLINE,
                date(2026, 5, 1),
                date(2026, 5, 1),
                now=_aware(date(2026, 4, 20), time(8, 0)),
            )
        with self.assertRaises(ModalityShiftError):
            submit_modality_shift(
                self.faculty,
                [archived_schedule, active_schedule],
                Modality.ONLINE,
                date(2026, 5, 1),
                date(2026, 5, 1),
                now=_aware(date(2026, 4, 20), time(8, 0)),
            )

        self.assertEqual(self._counts(), before)

    def test_modality_decision_writers_refuse_archived_without_side_effects(self):
        schedule = self._schedule(self.archived, "frzdec")
        session = self._session(schedule)
        for writer in ("withdraw", "reject", "apply"):
            req = self._pending_request(schedule)
            before = self._counts()
            with self.subTest(writer=writer):
                with self.assertRaises(ModalityShiftError):
                    if writer == "withdraw":
                        withdraw_modality_shift(req, self.faculty)
                    elif writer == "reject":
                        reject_modality_shift(req, self.dean, "No")
                    else:
                        apply_approval(req, self.dean, now=_aware(session.date, time(9, 0)))

                req.refresh_from_db()
                session.refresh_from_db()
                self.assertEqual(req.status, ModalityShiftStatus.PENDING)
                self.assertEqual(session.status, SessionStatus.SCHEDULED)
                self.assertEqual(session.declared_modality, "")
                self.assertEqual(self._counts(), before)

    def test_merge_propagation_refuses_archived_anchor_without_audit_or_status_write(self):
        anchor_schedule = self._schedule(self.archived, "frzmrg")
        sibling_schedule = self._schedule(self.archived, "frzmrs")
        sibling_schedule.course_code = anchor_schedule.course_code
        sibling_schedule.save(update_fields=["course_code"])
        anchor = self._session(anchor_schedule)
        sibling = self._session(sibling_schedule)
        before = self._counts()

        with self.assertRaises(ArchivedTermError):
            propagate_merged_present(
                anchor,
                now=_aware(anchor.date, time(8, 5)),
                actor=self.faculty,
            )

        anchor.refresh_from_db()
        sibling.refresh_from_db()
        self.assertEqual(anchor.status, SessionStatus.SCHEDULED)
        self.assertEqual(sibling.status, SessionStatus.SCHEDULED)
        self.assertEqual(self._counts(), before)

    def test_merge_propagation_filters_same_start_candidates_to_anchor_term(self):
        anchor_schedule = self._schedule(self.active, "frzma")
        archived_schedule = self._schedule(self.archived, "frzmb")
        archived_schedule.course_code = anchor_schedule.course_code
        archived_schedule.save(update_fields=["course_code"])
        anchor = self._session(anchor_schedule)
        archived = self._session(archived_schedule)

        filled = propagate_merged_present(
            anchor,
            now=_aware(anchor.date, time(8, 5)),
            actor=self.faculty,
        )

        archived.refresh_from_db()
        self.assertEqual(filled, [])
        self.assertEqual(archived.status, SessionStatus.SCHEDULED)


class ArchiveFreezeCommandTests(TestCase):
    """D-04/D-16: management commands do not mutate archived history."""

    def setUp(self):
        self.ifo = _user("freeze_cmd_ifo")
        self.faculty = _user("freeze_cmd_faculty", role=Role.FACULTY)
        self.archived = AcademicTerm.objects.create(
            name="Command Archived",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.schedule = _schedule(self.archived, self.faculty, "cmdarc")
        self.session = _session(self.schedule, self.faculty)

    def _row_counts(self):
        return {
            "terms": AcademicTerm.objects.count(),
            "schedules": Schedule.objects.count(),
            "sessions": Session.objects.count(),
            "audit": AuditLog.objects.count(),
        }

    def test_reset_term_is_retired_and_cannot_write_rows(self):
        before = self._row_counts()

        with self.assertRaisesMessage(CommandError, "reset_term is retired"):
            call_command("reset_term", yes=True)

        self.assertEqual(self._row_counts(), before)
        self.assertTrue(Schedule.objects.filter(pk=self.schedule.pk).exists())
        self.assertTrue(Session.objects.filter(pk=self.session.pk).exists())

    def test_reset_term_source_has_no_legacy_target_or_destructive_orm(self):
        source = Path("scheduling/management/commands/reset_term.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("DEFAULT_TERM", source)
        self.assertNotIn("2nd Term SY 2025-2026", source)
        self.assertNotIn(".delete(", source)
        self.assertNotIn("Session.objects", source)
        self.assertNotIn("Schedule.objects", source)

    def test_seed_term_without_active_term_fails_before_archived_rows_change(self):
        before = self._row_counts()

        with self.assertRaisesMessage(CommandError, "No ACTIVE academic term"):
            call_command("seed_term", force=True)

        self.assertEqual(self._row_counts(), before)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.SCHEDULED)

    def test_retained_commands_use_authoritative_active_resolver_source_guard(self):
        seed_source = Path(
            "scheduling/management/commands/seed_term.py"
        ).read_text(encoding="utf-8")
        audit_source = Path(
            "scheduling/management/commands/audit_merge_coverage.py"
        ).read_text(encoding="utf-8")

        for source in (seed_source, audit_source):
            self.assertIn("require_active_term", source)
            self.assertNotIn("filter(is_active=True)", source)
            self.assertNotIn(".first()", source)

    def test_audit_merge_coverage_without_active_term_is_read_only(self):
        before = self._row_counts()
        out = StringIO()

        call_command("audit_merge_coverage", stdout=out)

        self.assertIn("no active term", out.getvalue())
        self.assertEqual(self._row_counts(), before)


class ArchiveFreezeAdminTests(TestCase):
    """D-04: raw Django Admin mutation seams enforce the archive freeze."""

    def setUp(self):
        self.user = _user("admin_freeze_user")
        self.archived = AcademicTerm.objects.create(
            name="Admin Archived",
            start_date=date(2025, 1, 1),
            end_date=date(2025, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.draft = AcademicTerm.objects.create(
            name="Admin Draft",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.DRAFT,
        )
        self.archived_schedule = _schedule(self.archived, self.user, "adm-arc")
        self.draft_schedule = _schedule(self.draft, self.user, "adm-drf")

    def test_archived_schedule_save_is_refused_and_draft_save_succeeds(self):
        model_admin = ScheduleAdmin(Schedule, admin.site)
        self.archived_schedule.section = "REFUSED"
        with self.assertRaises(PermissionDenied):
            model_admin.save_model(None, self.archived_schedule, None, True)
        self.archived_schedule.refresh_from_db()
        self.assertNotEqual(self.archived_schedule.section, "REFUSED")

        self.draft_schedule.section = "WRITABLE"
        model_admin.save_model(None, self.draft_schedule, None, True)
        self.draft_schedule.refresh_from_db()
        self.assertEqual(self.draft_schedule.section, "WRITABLE")

    def test_mixed_delete_queryset_refuses_before_any_delete(self):
        model_admin = ScheduleAdmin(Schedule, admin.site)
        queryset = Schedule.objects.filter(
            pk__in=[self.archived_schedule.pk, self.draft_schedule.pk]
        )
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(None, queryset)
        self.assertEqual(queryset.count(), 2)

    def test_academic_term_delete_is_always_denied(self):
        model_admin = AcademicTermAdmin(AcademicTerm, admin.site)
        self.assertFalse(model_admin.has_delete_permission(None, self.draft))
        with self.assertRaises(PermissionDenied):
            model_admin.delete_model(None, self.draft)
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(None, AcademicTerm.objects.all())

    def test_verification_and_report_admin_guards_follow_owner_paths(self):
        assignment = Assignment.objects.create(
            user=self.user,
            role=DutyRole.CHECKER,
            type="shift",
            term=self.archived,
        )
        with self.assertRaises(PermissionDenied):
            AssignmentAdmin(Assignment, admin.site).delete_model(None, assignment)

        session = _session(self.archived_schedule, self.user)
        validation = CheckerValidation.objects.create(
            session=session,
            room=session.room,
            checker=self.user,
            action="verified",
        )
        with self.assertRaises(PermissionDenied):
            CheckerValidationAdmin(CheckerValidation, admin.site).delete_model(
                None, validation
            )

        report = WeeklyReport.objects.create(
            term=self.archived,
            week_start=self.archived.start_date,
            csv_path="reports/original.csv",
        )
        report.csv_path = "reports/refused.csv"
        with self.assertRaises(PermissionDenied):
            WeeklyReportAdmin(WeeklyReport, admin.site).save_model(
                None, report, None, True
            )
        report.refresh_from_db()
        self.assertEqual(report.csv_path, "reports/original.csv")


class AdminDeleteQuerysetFreezeTests(SimpleTestCase):
    def test_every_term_owned_admin_uses_shared_bulk_guard(self):
        for path in (
            Path("scheduling/admin.py"),
            Path("verification/admin.py"),
            Path("ops/admin.py"),
        ):
            source = path.read_text(encoding="utf-8")
            self.assertIn("TermOwnedAdminGuardMixin", source)

        guard_source = Path("scheduling/admin_guards.py").read_text(encoding="utf-8")
        self.assertIn("objects = list(queryset)", guard_source)
        self.assertLess(
            guard_source.index("for obj in objects"),
            guard_source.index("super().delete_queryset"),
        )

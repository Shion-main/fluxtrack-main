"""Tests for the weekly report service + JOB-03 fill (RPT-02 / ENV-04 / NOTIF-00).

Exercises ops/reports.py and the filled scheduler slot against the shared
make_reporting_fixture (06-01): a two-department, multi-status object graph inside
the known Mon-Sun week beginning 2026-07-06. Storage assertions run against an
isolated temp MEDIA_ROOT so no real repo files are touched. ASCII-only.
"""
import shutil
import tempfile
from datetime import date
import inspect
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.core.management import call_command, CommandError
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings

from accounts.models import Role
from ops.models import Notification, WeeklyReport
from ops.notifications import WEEKLY_REPORT_READY
from ops.reports import (generate_week_reports, generate_weekly_report,
                         notify_report_ready, report_week_bounds)
from scheduling.models import AcademicTerm, Schedule, Session, SessionStatus
from scheduling.reporting import faculty_attendance
from scheduling.term_scope import ArchivedTermError
from scheduling.test_support import make_reporting_fixture

# One temp MEDIA_ROOT for the whole module; every storage-touching class overrides
# MEDIA_ROOT to it so default_storage writes here and never into the repo media/.
_MEDIA = tempfile.mkdtemp(prefix="fluxtrack-reports-test-")


def tearDownModule():  # noqa: N802 (Django/unittest hook name)
    shutil.rmtree(_MEDIA, ignore_errors=True)


@override_settings(MEDIA_ROOT=_MEDIA)
class IdempotencyTests(TestCase):
    """RPT-02: re-generating the same week+department upserts one row (no dup)."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_generate_twice_upserts_one_row_and_repopulates_paths(self):
        fx = self.fx
        r1 = generate_weekly_report(
            term=fx.term, week_start=fx.week_start, week_end=fx.sun,
            department=fx.dept_a)
        r2 = generate_weekly_report(
            term=fx.term, week_start=fx.week_start, week_end=fx.sun,
            department=fx.dept_a)

        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(
            WeeklyReport.objects.filter(
                term=fx.term, week_start=fx.week_start,
                department=fx.dept_a).count(), 1)
        self.assertTrue(r2.csv_path)
        self.assertTrue(r2.pdf_path)
        self.assertTrue(default_storage.exists(r2.csv_path))
        self.assertTrue(default_storage.exists(r2.pdf_path))

    def test_all_rollup_department_none_is_idempotent(self):
        fx = self.fx
        r1 = generate_weekly_report(
            term=fx.term, week_start=fx.week_start, week_end=fx.sun,
            department=None)
        r2 = generate_weekly_report(
            term=fx.term, week_start=fx.week_start, week_end=fx.sun,
            department=None)

        self.assertEqual(r1.pk, r2.pk)
        self.assertEqual(
            WeeklyReport.objects.filter(
                term=fx.term, week_start=fx.week_start,
                department__isnull=True).count(), 1)

    def test_storage_name_is_server_built_from_dept_code_and_week(self):
        fx = self.fx
        report = generate_weekly_report(
            term=fx.term, week_start=fx.week_start, week_end=fx.sun,
            department=fx.dept_a)
        # Path is derived ONLY from department.code + week_start (T-06-05), never
        # from any request input, so it can never traverse out of the reports tree.
        self.assertTrue(
            report.csv_path.startswith(
                f"reports/term-{fx.term.pk}/{fx.week_start}/"))
        self.assertIn(fx.dept_a.code, report.csv_path)


@override_settings(MEDIA_ROOT=_MEDIA)
class WeeklyReportTermGenerationTests(TestCase):
    """D-12/T-12-03: stored report generation is keyed by one writable term."""

    def setUp(self):
        self.fx = make_reporting_fixture("wterm")
        self.draft = AcademicTerm.objects.create(
            name="wterm Draft", start_date=self.fx.week_start,
            end_date=self.fx.sun, status=AcademicTerm.Status.DRAFT)

    def _same_date_session(self, term, status, course="WTERM101"):
        sched = Schedule.objects.create(
            term=term, course_code=course, section="A",
            faculty=self.fx.faculty_a, room=self.fx.room_a,
            day_of_week=self.fx.week_start.weekday(),
            start_time=self.fx.s_active.schedule.start_time,
            end_time=self.fx.s_active.schedule.end_time,
        )
        return Session.objects.create(
            schedule=sched, faculty=self.fx.faculty_a, room=self.fx.room_a,
            date=self.fx.week_start,
            scheduled_start=self.fx.s_active.scheduled_start,
            scheduled_end=self.fx.s_active.scheduled_end,
            status=status,
        )

    def test_same_week_department_generates_non_colliding_term_paths(self):
        self._same_date_session(self.draft, SessionStatus.ACTIVE, "WTDRAFT1")

        active = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        draft = generate_weekly_report(
            term=self.draft, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)

        self.assertNotEqual(active.pk, draft.pk)
        self.assertIn(f"reports/term-{self.fx.term.pk}/", active.csv_path)
        self.assertIn(f"reports/term-{self.draft.pk}/", draft.csv_path)
        self.assertNotEqual(active.csv_path, draft.csv_path)
        self.assertTrue(default_storage.exists(active.csv_path))
        self.assertTrue(default_storage.exists(draft.csv_path))

    def test_generated_csv_contains_selected_term_rows_only(self):
        self._same_date_session(self.draft, SessionStatus.ACTIVE, "WTDRAFT2")

        report = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        csv_text = default_storage.open(report.csv_path).read().decode("utf-8")

        self.assertIn("Ana Alvarez", csv_text)
        # Active term faculty_a scheduled count remains the fixture's 8, not 9.
        self.assertIn(",8,6,1,", csv_text)

    def test_rerun_is_idempotent_within_same_term_identity(self):
        first = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        second = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            WeeklyReport.objects.filter(
                term=self.fx.term, week_start=self.fx.week_start,
                department=self.fx.dept_a).count(),
            1,
        )

    def test_archived_generation_refuses_before_file_or_metadata_write(self):
        archived = AcademicTerm.objects.create(
            name="wterm Archived", start_date=self.fx.week_start,
            end_date=self.fx.sun, status=AcademicTerm.Status.ARCHIVED)
        existing = WeeklyReport.objects.create(
            term=archived, week_start=self.fx.week_start,
            department=self.fx.dept_a, csv_path="reports/old.csv",
            pdf_path="reports/old.pdf")

        with patch("ops.reports._save_overwrite") as save_overwrite:
            with self.assertRaises(ArchivedTermError):
                generate_weekly_report(
                    term=archived, week_start=self.fx.week_start,
                    week_end=self.fx.sun, department=self.fx.dept_a)

        save_overwrite.assert_not_called()
        existing.refresh_from_db()
        self.assertEqual(existing.csv_path, "reports/old.csv")
        self.assertEqual(existing.pdf_path, "reports/old.pdf")

    def test_generate_week_reports_derives_departments_from_supplied_term(self):
        self._same_date_session(self.draft, SessionStatus.ACTIVE, "WTDRAFT3")

        active_count = generate_week_reports(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun)
        draft_count = generate_week_reports(
            term=self.draft, week_start=self.fx.week_start,
            week_end=self.fx.sun)

        self.assertEqual(active_count, 3)
        self.assertEqual(draft_count, 2)  # dept_a plus ALL roll-up.
        self.assertEqual(
            WeeklyReport.objects.filter(term=self.fx.term).count(), 3)
        self.assertEqual(
            WeeklyReport.objects.filter(term=self.draft).count(), 2)


class WeeklyReportTermIdentityTests(TestCase):
    """D-12: stored reports are identified by term, week and department."""

    def setUp(self):
        self.fx = make_reporting_fixture()
        self.other_term = AcademicTerm.objects.create(
            name="rpt Other Term",
            start_date=date(2027, 1, 1),
            end_date=date(2027, 6, 30),
            status=AcademicTerm.Status.DRAFT,
        )

    def test_same_week_department_can_repeat_across_terms(self):
        WeeklyReport.objects.create(
            term=self.fx.term, week_start=self.fx.week_start,
            department=self.fx.dept_a,
        )
        WeeklyReport.objects.create(
            term=self.other_term, week_start=self.fx.week_start,
            department=self.fx.dept_a,
        )

        self.assertEqual(
            WeeklyReport.objects.filter(
                week_start=self.fx.week_start, department=self.fx.dept_a
            ).count(),
            2,
        )

    def test_term_is_required_for_new_weekly_reports(self):
        with self.assertRaises(IntegrityError):
            WeeklyReport.objects.create(
                week_start=self.fx.week_start, department=self.fx.dept_a
            )

    def test_term_delete_is_protected_by_stored_report_history(self):
        WeeklyReport.objects.create(
            term=self.fx.term, week_start=self.fx.week_start,
            department=self.fx.dept_a,
        )

        with self.assertRaises(ProtectedError):
            self.fx.term.delete()


@override_settings(MEDIA_ROOT=_MEDIA)
class NotifyTargetingTests(TestCase):
    """RPT-02 / T-06-06: IFO + only the report's department Dean are notified."""

    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_admin1", email="ifo1@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.dean_a = User.objects.create(
            username="dean_a1", email="deana@mcm.edu.ph",
            role=Role.DEAN, department=self.fx.dept_a, is_active=True)
        self.dean_b = User.objects.create(
            username="dean_b1", email="deanb@mcm.edu.ph",
            role=Role.DEAN, department=self.fx.dept_b, is_active=True)

    def _count(self, user):
        return Notification.objects.filter(
            user=user, type=WEEKLY_REPORT_READY).count()

    def test_dept_report_notifies_ifo_and_that_dept_dean_only(self):
        fx = self.fx
        notify_report_ready(fx.dept_a, fx.week_start, link="/reports/x/")

        self.assertEqual(self._count(self.ifo), 1)
        self.assertEqual(self._count(self.dean_a), 1)
        self.assertEqual(self._count(self.dean_b), 0)  # other dept Dean untouched

    def test_all_rollup_notifies_ifo_not_any_dean(self):
        notify_report_ready(None, self.fx.week_start, link="")

        self.assertEqual(self._count(self.ifo), 1)
        self.assertEqual(
            Notification.objects.filter(
                type=WEEKLY_REPORT_READY, user__role=Role.DEAN).count(), 0)

    def test_notification_written_only_through_notify_path(self):
        # No Notification row exists before generation; notify() creates them.
        self.assertEqual(Notification.objects.count(), 0)
        notify_report_ready(self.fx.dept_b, self.fx.week_start, link="")
        self.assertEqual(self._count(self.dean_b), 1)
        self.assertEqual(self._count(self.dean_a), 0)


class WeekBoundaryTests(TestCase):
    """RPT-02 / Pitfall 1: Monday..Sunday local bounds; no UTC edge drift."""

    def setUp(self):
        self.fx = make_reporting_fixture()

    def test_bounds_are_monday_to_sunday_local(self):
        # A Wednesday resolves to its own Mon..Sun week.
        start, end = report_week_bounds(date(2026, 7, 8))
        self.assertEqual(start, date(2026, 7, 6))   # Monday
        self.assertEqual(end, date(2026, 7, 12))    # Sunday

    def test_sunday_included_next_monday_excluded(self):
        fx = self.fx
        start, end = report_week_bounds(fx.week_start)

        base = next(r for r in faculty_attendance(
            term=fx.term, start=start, end=end, department=fx.dept_a)
            if r.faculty_id == fx.faculty_a.id)
        base_scheduled = base.scheduled

        # A Sunday-of-week session must be counted; the following Monday must not.
        fx.add_session(fx.faculty_a, fx.sun, SessionStatus.ACTIVE)
        fx.add_session(fx.faculty_a, fx.next_monday, SessionStatus.ACTIVE)

        after = next(r for r in faculty_attendance(
            term=fx.term, start=start, end=end, department=fx.dept_a)
            if r.faculty_id == fx.faculty_a.id)

        self.assertEqual(after.scheduled, base_scheduled + 1)


@override_settings(MEDIA_ROOT=_MEDIA)
class JobFillTests(TestCase):
    """ENV-04 / RPT-02: filled JOB-03 generates a positive count, idempotently,
    without disturbing the 4-job scheduler invariant."""

    def _run_job_for_fixture_week(self, fx):
        # The job reports on localdate()-7 days; pin "now" to the Monday AFTER the
        # fixture week so the prior completed week IS the fixture's 2026-07-06 week.
        from scheduling.management.commands import runscheduler
        with patch.object(runscheduler.timezone, "localdate",
                          return_value=fx.next_monday):
            return runscheduler._job_weekly_report()

    def test_job_generates_positive_count_and_rows(self):
        fx = make_reporting_fixture()
        count = self._run_job_for_fixture_week(fx)
        # dept_a + dept_b (both have sessions that week) + the ALL roll-up.
        self.assertEqual(count, 3)
        self.assertEqual(WeeklyReport.objects.count(), 3)
        self.assertTrue(
            WeeklyReport.objects.filter(department=fx.dept_a).exists())
        self.assertTrue(
            WeeklyReport.objects.filter(department__isnull=True).exists())

    def test_job_rerun_is_idempotent(self):
        fx = make_reporting_fixture()
        self._run_job_for_fixture_week(fx)
        self._run_job_for_fixture_week(fx)
        # Second run overwrites files, never adds rows (unique_together key).
        self.assertEqual(WeeklyReport.objects.count(), 3)

    def test_on_demand_command_generates_same_reports(self):
        fx = make_reporting_fixture()
        call_command("generate_weekly_report", week=str(fx.week_start))
        self.assertEqual(WeeklyReport.objects.count(), 3)

    def test_on_demand_command_accepts_explicit_active_term_pk(self):
        fx = make_reporting_fixture()
        call_command(
            "generate_weekly_report",
            week=str(fx.week_start),
            term=str(fx.term.pk),
        )
        self.assertEqual(
            WeeklyReport.objects.filter(term=fx.term).count(), 3)

    def test_on_demand_command_accepts_explicit_active_term_name(self):
        fx = make_reporting_fixture()
        call_command(
            "generate_weekly_report",
            week=str(fx.week_start),
            term=fx.term.name,
        )
        self.assertEqual(
            WeeklyReport.objects.filter(term=fx.term).count(), 3)

    def test_on_demand_command_refuses_explicit_non_active_term(self):
        fx = make_reporting_fixture()
        draft = AcademicTerm.objects.create(
            name="jobfill Draft", start_date=fx.week_start, end_date=fx.sun,
            status=AcademicTerm.Status.DRAFT)

        with self.assertRaises(CommandError):
            call_command(
                "generate_weekly_report",
                week=str(fx.week_start),
                term=str(draft.pk),
            )

        self.assertFalse(WeeklyReport.objects.filter(term=draft).exists())

    def test_scheduler_no_active_is_safe_noop(self):
        fx = make_reporting_fixture()
        AcademicTerm.objects.filter(pk=fx.term.pk).update(
            status=AcademicTerm.Status.ARCHIVED)

        self.assertEqual(self._run_job_for_fixture_week(fx), 0)
        self.assertFalse(WeeklyReport.objects.exists())

    def test_scheduler_still_registers_exactly_four_jobs(self):
        from scheduling.management.commands.runscheduler import build_scheduler
        sched = build_scheduler()
        try:
            self.assertEqual(
                {j.id for j in sched.get_jobs()},
                {"materialize", "sweep", "weekly_report", "push_outbox"})
        finally:
            if getattr(sched, "running", False):
                sched.shutdown(wait=False)


class WeeklyReportProductionCouplingTests(TestCase):
    """D-12/T-12-07: production adapters pass term; service performs no lookup."""

    def test_report_service_has_no_implicit_active_lookup(self):
        import ops.reports as reports

        src = inspect.getsource(reports)
        self.assertNotIn("get_active_term", src)
        self.assertNotIn("require_active_term", src)

    def test_scheduler_and_command_call_generate_week_reports_with_term(self):
        from scheduling.management.commands import generate_weekly_report
        from scheduling.management.commands import runscheduler

        scheduler_src = inspect.getsource(runscheduler._job_weekly_report)
        command_src = inspect.getsource(generate_weekly_report.Command.handle)
        self.assertIn("term=", scheduler_src)
        self.assertIn("term=", command_src)

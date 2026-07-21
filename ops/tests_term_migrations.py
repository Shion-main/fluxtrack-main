"""Migration contracts for term-owned ops records (Phase 12 Plan 03)."""
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class _OpsTermMigrationTestCase(TransactionTestCase):
    migrate_from = [
        ("scheduling", "0008_term_lifecycle"),
        ("ops", "0005_booking_protect_import_staging"),
    ]
    migrate_to = [
        ("scheduling", "0008_term_lifecycle"),
        ("ops", "0006_term_ownership"),
    ]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self):
        # Leave the database at the project leaf even after fail-loud migration
        # assertions so later tests do not inherit a historical app state.
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _create_department(self, code="CSE"):
        Department = self.old_apps.get_model("accounts", "Department")
        return Department.objects.create(name=f"{code} Department", code=code)

    def _create_user(self):
        User = self.old_apps.get_model("accounts", "User")
        return User.objects.create(username="ifo", email="ifo@example.test")

    def _create_term(self, name, start, end, status="archived"):
        AcademicTerm = self.old_apps.get_model("scheduling", "AcademicTerm")
        return AcademicTerm.objects.create(
            name=name, start_date=start, end_date=end, status=status
        )

    def _create_report(self, week_start, department=None, csv_path="", pdf_path=""):
        WeeklyReport = self.old_apps.get_model("ops", "WeeklyReport")
        return WeeklyReport.objects.create(
            week_start=week_start,
            department=department,
            csv_path=csv_path,
            pdf_path=pdf_path,
        )

    def _migrate_forward(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        return self.executor.loader.project_state(self.migrate_to).apps


class WeeklyReportTermBackfillTests(_OpsTermMigrationTestCase):
    def test_report_week_intersecting_exactly_one_term_maps_to_that_term(self):
        dept = self._create_department()
        expected = self._create_term(
            "Summer 2026", date(2026, 7, 1), date(2026, 7, 31)
        )
        self._create_term(
            "Fall 2026", date(2026, 8, 1), date(2026, 12, 31),
            status="draft",
        )
        legacy = self._create_report(
            date(2026, 7, 6),
            department=dept,
            csv_path="reports/2026-07-06/CSE.csv",
            pdf_path="reports/2026-07-06/CSE.pdf",
        )

        new_apps = self._migrate_forward()

        WeeklyReport = new_apps.get_model("ops", "WeeklyReport")
        migrated = WeeklyReport.objects.get(pk=legacy.pk)
        self.assertEqual(migrated.term_id, expected.pk)
        self.assertEqual(migrated.csv_path, "reports/2026-07-06/CSE.csv")
        self.assertEqual(migrated.pdf_path, "reports/2026-07-06/CSE.pdf")

    def test_two_overlapping_candidate_terms_abort_without_guessing(self):
        dept = self._create_department()
        self._create_term("Term A", date(2026, 7, 1), date(2026, 7, 20))
        self._create_term(
            "Term B", date(2026, 7, 10), date(2026, 7, 31),
            status="draft",
        )
        legacy = self._create_report(date(2026, 7, 13), department=dept)

        with self.assertRaisesMessage(
            RuntimeError,
            f"WeeklyReport {legacy.pk} week 2026-07-13 has 2 candidate terms",
        ):
            self._migrate_forward()

    def test_no_candidate_term_aborts_without_active_fallback(self):
        dept = self._create_department()
        self._create_term(
            "Current Active", date(2026, 1, 1), date(2026, 6, 30),
            status="active",
        )
        legacy = self._create_report(date(2026, 7, 6), department=dept)

        with self.assertRaisesMessage(
            RuntimeError,
            f"WeeklyReport {legacy.pk} week 2026-07-06 has 0 candidate terms",
        ):
            self._migrate_forward()

    def test_same_week_department_can_coexist_for_different_terms(self):
        dept = self._create_department()
        first = self._create_term(
            "First Term", date(2026, 7, 1), date(2026, 7, 12)
        )
        second = self._create_term(
            "Second Term", date(2026, 7, 13), date(2026, 7, 31),
            status="draft",
        )
        first_report = self._create_report(date(2026, 7, 6), department=dept)

        new_apps = self._migrate_forward()

        WeeklyReport = new_apps.get_model("ops", "WeeklyReport")
        migrated = WeeklyReport.objects.get(pk=first_report.pk)
        WeeklyReport.objects.create(
            term_id=second.pk, week_start=migrated.week_start, department_id=dept.pk
        )
        self.assertEqual(
            WeeklyReport.objects.filter(
                week_start=date(2026, 7, 6), department_id=dept.pk
            ).count(),
            2,
        )
        self.assertEqual(migrated.term_id, first.pk)


class ImportStagingTermMigrationTests(_OpsTermMigrationTestCase):
    def test_legacy_import_staging_row_keeps_null_term(self):
        ImportStaging = self.old_apps.get_model("ops", "ImportStaging")
        legacy = ImportStaging.objects.create(
            token="tok_legacy",
            uploaded_by=self._create_user(),
            original_name="offerings.xlsx",
            stored_path="imports/tok_legacy.xlsx",
            size_bytes=128,
        )

        new_apps = self._migrate_forward()

        ImportStaging = new_apps.get_model("ops", "ImportStaging")
        migrated = ImportStaging.objects.get(pk=legacy.pk)
        self.assertIsNone(migrated.term_id)
        self.assertEqual(migrated.stored_path, "imports/tok_legacy.xlsx")

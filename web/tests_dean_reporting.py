"""DEAN-01..04 view-level tests for the Dean reporting surface.

The phase's central access-control requirement lives here: a Dean is READ-ONLY and
strictly scoped to their OWN department. These tests lock:

  - DeanDashboardTests: a DEAN with a department gets a 200 department-scoped
    dashboard (four KPI captions + a latest-report card / empty state); a non-Dean
    is refused 403 (T-06-13).
  - DeanScopeTests (the central security test, T-06-01 IDOR/BOLA): a Dean can NEVER
    reach another department's data. A foreign-department scorecard and
    weekly_download 404 SERVER-SIDE (refused, not merely hidden), and a foreign
    faculty never appears in the Dean's report/export.
  - DeanExportTests: report_export csv/pdf are attachments over the render layer,
    and a formula-triggering faculty name is csv_safe-neutralized (T-06-02).
  - ReadOnlyTests: a POST to any Dean reporting URL is rejected 405 -- the surface
    exposes no write endpoint (DEAN-01 / T-06-07).

Seeds the shared two-department make_reporting_fixture from 06-01. ASCII-only.
"""
import tempfile

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role
from ops.reports import generate_weekly_report
from scheduling.models import SessionStatus
from scheduling.test_support import make_reporting_fixture

# Storage-touching download tests write real CSV/PDF bytes via default_storage;
# isolate them under a throwaway MEDIA_ROOT so the repo tree is never polluted.
_TMP_MEDIA = tempfile.mkdtemp(prefix="dean_reporting_")


class _DeanBase(TestCase):
    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        # The test Dean belongs to dept_a (the "home" department). dept_b is the
        # "foreign" department the Dean must never reach.
        self.dean = User.objects.create(
            username="dn_dean_a", email="dn_dean_a@mcm.edu.ph",
            role=Role.DEAN, department=self.fx.dept_a, is_active=True)
        self.client.force_login(self.dean)

    def _range(self):
        return {"from": self.fx.week_start.isoformat(),
                "to": self.fx.sun.isoformat()}


class DeanDashboardTests(_DeanBase):
    """DEAN-04: a department-scoped dashboard for a Dean; non-Deans refused."""

    def test_dean_gets_dashboard_with_cards_and_report_card(self):
        resp = self.client.get(reverse("dean_dashboard"), self._range())
        self.assertEqual(resp.status_code, 200)
        for caption in ("Faculty", "Sessions", "Absences", "Attendance %"):
            self.assertContains(resp, caption)
        # No WeeklyReport seeded yet -> the calm Pattern F empty state.
        self.assertContains(resp, "No weekly report yet")
        # The dept badge proves the surface knows its scope.
        self.assertContains(resp, self.fx.dept_a.code)

    def test_non_dean_refused(self):
        User = get_user_model()
        other = User.objects.create(
            username="dn_fac_x", email="dn_fac_x@mcm.edu.ph",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self.client.force_login(other)
        resp = self.client.get(reverse("dean_dashboard"))
        self.assertEqual(resp.status_code, 403)


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class DeanScopeTests(_DeanBase):
    """T-06-01 (BOLA/IDOR): cross-department access is refused SERVER-SIDE."""

    def test_foreign_department_scorecard_404s(self):
        # faculty_b is in dept_b; the dept_a Dean must NOT reach the scorecard.
        url = reverse("dean_scorecard", args=[self.fx.faculty_b.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 404)

    def test_own_department_scorecard_renders(self):
        url = reverse("dean_scorecard", args=[self.fx.faculty_a.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Attendance scorecard")
        # The back link points at the Dean report, not the IFO-only dashboard.
        self.assertContains(resp, "/dean/reports")

    def test_report_excludes_foreign_faculty(self):
        resp = self.client.get(reverse("dean_reports"), self._range())
        self.assertEqual(resp.status_code, 200)
        # The Dean's own faculty is present; the foreign department's is NOT.
        self.assertContains(resp, self.fx.faculty_a.last_name)
        self.assertNotContains(resp, self.fx.faculty_b.last_name)

    def test_export_excludes_foreign_faculty(self):
        resp = self.client.get(
            reverse("dean_report_export", args=["csv"]), self._range())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn(self.fx.faculty_a.last_name, body)
        self.assertNotIn(self.fx.faculty_b.last_name, body)

    def test_foreign_department_weekly_download_404s(self):
        # A stored report for the FOREIGN department (dept_b): its pk must 404.
        rep_b = generate_weekly_report(
            self.fx.week_start, self.fx.sun, self.fx.dept_b)
        resp = self.client.get(
            reverse("dean_weekly_download", args=[rep_b.pk, "csv"]))
        self.assertEqual(resp.status_code, 404)

    def test_own_department_weekly_download_streams(self):
        rep_a = generate_weekly_report(
            self.fx.week_start, self.fx.sun, self.fx.dept_a)
        resp = self.client.get(
            reverse("dean_weekly_download", args=[rep_a.pk, "csv"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class DeanExportTests(_DeanBase):
    """DEAN-03/RPT-03: exports reuse the render layer; CSV injection neutralized."""

    def setUp(self):
        super().setUp()
        # A faculty in the Dean's OWN department whose name STARTS with a formula
        # trigger, with a session in range so it lands in the export (T-06-02).
        User = get_user_model()
        self.evil = User.objects.create(
            username="dn_evil", email="dn_evil@mcm.edu.ph",
            first_name="=cmd", last_name="Payload",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self.fx.add_session(self.evil, self.fx.week_start, SessionStatus.ACTIVE)

    def test_csv_export_is_attachment_and_neutralizes_formula(self):
        resp = self.client.get(
            reverse("dean_report_export", args=["csv"]), self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = resp.content.decode("utf-8")
        # csv_safe prefixes a single quote so "=cmd Payload" is not an Excel formula.
        self.assertIn("'=cmd Payload", body)
        self.assertNotIn("\n=cmd Payload", body)

    def test_pdf_export_is_attachment_pdf_bytes(self):
        resp = self.client.get(
            reverse("dean_report_export", args=["pdf"]), self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("attachment", resp["Content-Disposition"])
        self.assertTrue(resp.content.startswith(b"%PDF"))

    def test_unknown_format_404s(self):
        resp = self.client.get(
            reverse("dean_report_export", args=["xlsx"]), self._range())
        self.assertEqual(resp.status_code, 404)


class ReadOnlyTests(_DeanBase):
    """DEAN-01 / T-06-07: the Dean reporting surface exposes NO write endpoint."""

    def test_post_rejected_on_every_reporting_route(self):
        routes = [
            reverse("dean_dashboard"),
            reverse("dean_reports"),
            reverse("dean_report_export", args=["csv"]),
            reverse("dean_scorecard", args=[self.fx.faculty_a.id]),
            reverse("dean_weekly_download", args=[1, "csv"]),
        ]
        for url in routes:
            resp = self.client.post(url)
            self.assertEqual(
                resp.status_code, 405,
                msg=f"POST to {url} should be rejected (read-only)")

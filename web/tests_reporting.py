"""IFO-09 / RPT-04 / RPT-05 view-level tests for the reporting dashboard and the
faculty scorecard drill-down.

Locks the T-06-10 role gate (only IFO_ADMIN/superuser reach the surfaces), the
RPT-05 per-card isolation contract end-to-end (one raising aggregate errors in its
own card while the sibling section still renders, and the raw exception text never
reaches the response -- T-06-04), and the T-06-11 filter validation (bad dates
degrade to the default range with a friendly note, never a 500). Seeds the shared
two-department multi-status make_reporting_fixture from 06-01. ASCII-only.
"""
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role
from ops.reports import generate_weekly_report
from scheduling.test_support import make_reporting_fixture

# Storage-touching download tests write real CSV/PDF bytes via default_storage;
# isolate them under a throwaway MEDIA_ROOT so the repo tree is never polluted.
_TMP_MEDIA = tempfile.mkdtemp(prefix="ifo_reporting_")


class _IfoBase(TestCase):
    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        self.ifo = User.objects.create(
            username="rpt_ifo", email="rpt_ifo@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)

    def _range(self):
        return {"from": self.fx.week_start.isoformat(),
                "to": self.fx.sun.isoformat()}


class IfoDashboardTests(_IfoBase):
    """An IFO gets an unscoped dashboard of KPI cards + a faculty table; a
    non-IFO user is refused (T-06-10)."""

    def test_ifo_gets_dashboard_with_cards_and_rows(self):
        resp = self.client.get(reverse("ifo_dashboard"), self._range())
        self.assertEqual(resp.status_code, 200)
        for caption in ("Faculty", "Sessions", "Absences", "Attendance %"):
            self.assertContains(resp, caption)
        # An unscoped dashboard shows faculty from BOTH departments.
        self.assertContains(resp, self.fx.faculty_a.last_name)
        self.assertContains(resp, self.fx.faculty_b.last_name)

    def test_non_ifo_refused(self):
        User = get_user_model()
        other = User.objects.create(
            username="rpt_fac_x", email="rpt_fac_x@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)
        self.client.force_login(other)
        resp = self.client.get(reverse("ifo_dashboard"))
        self.assertEqual(resp.status_code, 403)


class ScorecardDrilldownTests(_IfoBase):
    """The faculty scorecard opens as a full page, shows the modality breakdown,
    and carries the active from/to range (RPT-04 / A-DRILL)."""

    def test_scorecard_renders_for_ifo(self):
        url = reverse("ifo_scorecard", args=[self.fx.faculty_a.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Attendance scorecard")
        self.assertContains(resp, "Effective modality")
        # faculty_a has a declared-ONLINE-over-F2F held session in the fixture.
        self.assertContains(resp, "Online")
        # The back link carries the active range as query params.
        self.assertContains(resp, "from=" + self.fx.week_start.isoformat())

    def test_non_ifo_refused(self):
        User = get_user_model()
        other = User.objects.create(
            username="rpt_fac_y", email="rpt_fac_y@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)
        self.client.force_login(other)
        resp = self.client.get(
            reverse("ifo_scorecard", args=[self.fx.faculty_a.id]))
        self.assertEqual(resp.status_code, 403)

    def test_scorecard_page_has_export_csv_cta(self):
        url = reverse("ifo_scorecard", args=[self.fx.faculty_a.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Export CSV")
        self.assertContains(
            resp, reverse("ifo_scorecard_csv", args=[self.fx.faculty_a.id]))

    def test_scorecard_csv_exports_this_faculty_only(self):
        resp = self.client.get(
            reverse("ifo_scorecard_csv", args=[self.fx.faculty_a.id]),
            self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = resp.content.decode("utf-8")
        # This faculty's row is present; a different department's faculty is not.
        self.assertIn(self.fx.faculty_a.last_name, body)
        self.assertNotIn(self.fx.faculty_b.last_name, body)

    def test_scorecard_csv_refused_for_non_ifo(self):
        User = get_user_model()
        other = User.objects.create(
            username="rpt_fac_w", email="rpt_fac_w@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)
        self.client.force_login(other)
        resp = self.client.get(
            reverse("ifo_scorecard_csv", args=[self.fx.faculty_a.id]))
        self.assertEqual(resp.status_code, 403)


class CardIsolationViewTests(_IfoBase):
    """RPT-05 end-to-end: when one aggregate raises, the dashboard still returns
    200, the failing section shows the generic error copy, the sibling section
    still renders its value, and the raw exception text never leaks (T-06-04)."""

    def test_one_failing_aggregate_isolated(self):
        boom = "KABOOM_SECRET_TRACE_12345"
        # dept_summary powers the KPI cards; patch it to raise. faculty_attendance
        # (the sibling table section) must still render.
        with mock.patch("web.ifo.dept_summary",
                        side_effect=RuntimeError(boom)):
            resp = self.client.get(reverse("ifo_dashboard"), self._range())
        self.assertEqual(resp.status_code, 200)
        # The failing KPI section shows the shared generic error card.
        self.assertContains(resp, "Couldn't load this section")
        # The sibling faculty table still renders a real value.
        self.assertContains(resp, self.fx.faculty_a.last_name)
        # Information-disclosure guard: the raw exception text is absent.
        self.assertNotContains(resp, boom)


class FilterValidationTests(_IfoBase):
    """T-06-11: an invalid from/to degrades to the default range with a friendly
    note, never a 500."""

    def test_invalid_dates_fall_back_with_note(self):
        resp = self.client.get(
            reverse("ifo_dashboard"),
            {"from": "not-a-date", "to": "also-bad"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "current week")

    def test_reversed_range_falls_back_with_note(self):
        resp = self.client.get(
            reverse("ifo_dashboard"),
            {"from": self.fx.sun.isoformat(),
             "to": self.fx.week_start.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "current week")


@override_settings(MEDIA_ROOT=_TMP_MEDIA)
class IfoWeeklyReportsTests(_IfoBase):
    """RPT-01/03: the IFO-wide Weekly Consolidated Report surface is UNSCOPED --
    IFO can list and download BOTH a per-department report AND the org-wide
    (department=None) roll-up; a non-IFO is refused; bad fmt / missing file 404."""

    def test_index_lists_dept_and_rollup_for_the_week(self):
        generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=None)
        resp = self.client.get(reverse("ifo_weekly_reports"))
        self.assertEqual(resp.status_code, 200)
        # The per-department report and the "All departments" roll-up both appear.
        self.assertContains(resp, self.fx.dept_a.code)
        self.assertContains(resp, "All departments")
        # The primary CTA the UI-SPEC/UI-REVIEW required exists on this surface.
        self.assertContains(resp, "Download PDF")

    def test_index_empty_state_when_no_reports(self):
        resp = self.client.get(reverse("ifo_weekly_reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No weekly reports yet")

    def test_ifo_downloads_per_department_report(self):
        rep = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        resp = self.client.get(
            reverse("ifo_weekly_download", args=[rep.pk, "csv"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_ifo_downloads_the_none_rollup(self):
        # The org-wide roll-up (department=None) is reachable by IFO (unscoped) --
        # this is exactly what the Dean surface must NEVER resolve.
        rollup = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=None)
        resp = self.client.get(
            reverse("ifo_weekly_download", args=[rollup.pk, "pdf"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertIn("attachment", resp["Content-Disposition"])

    def test_unknown_format_404s(self):
        rep = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        resp = self.client.get(
            reverse("ifo_weekly_download", args=[rep.pk, "xlsx"]))
        self.assertEqual(resp.status_code, 404)

    def test_missing_stored_file_404s(self):
        rep = generate_weekly_report(
            term=self.fx.term, week_start=self.fx.week_start,
            week_end=self.fx.sun, department=self.fx.dept_a)
        # A row whose stored path no longer resolves must 404, never 500.
        rep.pdf_path = "reports/nope/missing.pdf"
        rep.save(update_fields=["pdf_path"])
        resp = self.client.get(
            reverse("ifo_weekly_download", args=[rep.pk, "pdf"]))
        self.assertEqual(resp.status_code, 404)

    def test_non_ifo_refused(self):
        User = get_user_model()
        other = User.objects.create(
            username="rpt_fac_z", email="rpt_fac_z@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)
        self.client.force_login(other)
        resp = self.client.get(reverse("ifo_weekly_reports"))
        self.assertEqual(resp.status_code, 403)

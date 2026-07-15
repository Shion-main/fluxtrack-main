"""IFO-09 / RPT-04 / RPT-05 view-level tests for the reporting dashboard and the
faculty scorecard drill-down.

Locks the T-06-10 role gate (only IFO_ADMIN/superuser reach the surfaces), the
RPT-05 per-card isolation contract end-to-end (one raising aggregate errors in its
own card while the sibling section still renders, and the raw exception text never
reaches the response -- T-06-04), and the T-06-11 filter validation (bad dates
degrade to the default range with a friendly note, never a 500). Seeds the shared
two-department multi-status make_reporting_fixture from 06-01. ASCII-only.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role
from scheduling.test_support import make_reporting_fixture


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

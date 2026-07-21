"""Selected-term reporting contracts for management report surfaces.

Phase 12 makes report scope explicit, bounded, and linkable. These tests keep
the shared parser independent from any one role surface, then exercise the HR
consumer against adversarial same-date data in ``HrReportTermTests``.
ASCII-only by convention (Windows cp1252).
"""
from datetime import date, datetime, time
from html import unescape
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from scheduling.models import (AcademicTerm, Modality, Schedule, Session,
                               SessionStatus)
from scheduling.test_support import make_reporting_fixture
from web.reporting_common import selected_report_scope


class ReportScopeTests(TestCase):
    """D-10/D-11: one explicit term plus a bounded, normalized window."""

    today = date(2026, 7, 8)

    def setUp(self):
        self.rf = RequestFactory()
        self.active = AcademicTerm.objects.create(
            name="Active 2026", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE,
        )
        self.archived = AcademicTerm.objects.create(
            name="Archived 2025", start_date=date(2025, 1, 6),
            end_date=date(2025, 5, 31), status=AcademicTerm.Status.ARCHIVED,
        )

    def _active_window(self, term):
        self.assertEqual(term, self.active)
        return date(2026, 7, 6), self.today

    def _scope(self, params=None):
        request = self.rf.get("/reports", params or {})
        request.session = {"sentinel": "unchanged"}
        with patch("web.reporting_common.timezone.localdate", return_value=self.today):
            scope = selected_report_scope(
                request, default_window=self._active_window)
        self.assertEqual(request.session, {"sentinel": "unchanged"})
        return scope

    def test_missing_term_resolves_active_with_controller_default(self):
        scope = self._scope()
        self.assertTrue(scope.is_valid)
        self.assertEqual(scope.term, self.active)
        self.assertEqual((scope.start, scope.end),
                         (date(2026, 7, 6), self.today))
        self.assertEqual(scope.as_of, self.today)
        self.assertEqual(scope.query_params["term"], str(self.active.pk))

    def test_archived_term_defaults_to_full_span(self):
        scope = self._scope({"term": self.archived.pk})
        self.assertEqual(scope.term, self.archived)
        self.assertEqual((scope.start, scope.end),
                         (self.archived.start_date, self.archived.end_date))
        self.assertEqual(scope.as_of, self.archived.end_date)

    def test_explicit_invalid_term_never_falls_back(self):
        for supplied in ("not-a-pk", "999999"):
            with self.subTest(supplied=supplied):
                scope = self._scope({"term": supplied})
                self.assertFalse(scope.is_valid)
                self.assertEqual(scope.error_code, "invalid-term")
                self.assertIsNone(scope.term)
                self.assertEqual(dict(scope.query_params), {})
                self.assertNotIn(str(self.active.pk), scope.scope_query)

    def test_missing_active_returns_named_empty_state(self):
        self.active.status = AcademicTerm.Status.DRAFT
        self.active.save(update_fields=["status"])
        scope = self._scope()
        self.assertFalse(scope.is_valid)
        self.assertEqual(scope.error_code, "no-active-term")
        self.assertIsNone(scope.term)
        self.assertIsNone(scope.start)

    def test_explicit_range_clamps_to_term_bounds(self):
        scope = self._scope({
            "term": self.archived.pk,
            "from": "2024-01-01",
            "to": "2026-01-01",
        })
        self.assertEqual((scope.start, scope.end),
                         (self.archived.start_date, self.archived.end_date))
        self.assertEqual(scope.query_params["from"], "2025-01-06")
        self.assertEqual(scope.query_params["to"], "2025-05-31")

    def test_reversed_range_uses_safe_term_default(self):
        scope = self._scope({
            "term": self.archived.pk,
            "from": "2025-05-01",
            "to": "2025-02-01",
        })
        self.assertEqual((scope.start, scope.end),
                         (self.archived.start_date, self.archived.end_date))
        self.assertIn("start date was after", scope.note.lower())

    def test_as_of_clamps_to_selected_end_and_today(self):
        archived = self._scope({"term": self.archived.pk, "as_of": "2099-01-01"})
        self.assertEqual(archived.as_of, self.archived.end_date)
        active = self._scope({"as_of": "2099-01-01"})
        self.assertEqual(active.as_of, self.today)

    def test_encoded_query_is_normalized_and_choices_are_active_first(self):
        scope = self._scope({
            "term": self.active.pk,
            "from": "2026-07-01",
            "to": "2026-07-07",
            "as_of": "2026-07-06",
        })
        self.assertEqual(
            scope.scope_query,
            f"term={self.active.pk}&from=2026-07-01&to=2026-07-07&as_of=2026-07-06",
        )
        self.assertEqual(scope.term_choices[0], self.active)

    def test_shared_term_filter_renders_scope_and_preservation_hooks(self):
        scope = self._scope()
        html = render_to_string("reports/_term_filter.html", {
            "scope": scope,
            "scope_hidden_fields": (
                {"name": "department", "value": "7"},
                {"name": "q", "value": "A&B"},
            ),
        })
        self.assertIn(f'value="{self.active.pk}" selected', html)
        self.assertIn('name="from"', html)
        self.assertIn('name="to"', html)
        self.assertIn('name="department" value="7"', html)
        self.assertIn('name="q" value="A&amp;B"', html)


def _aware(day, value):
    return timezone.make_aware(datetime.combine(day, value))


class HrReportTermTests(TestCase):
    """D-09/D-12: HR HTML/CSV consume one identical selected term."""

    def setUp(self):
        self.fx = make_reporting_fixture(prefix="hrterm")
        User = get_user_model()
        self.hr = User.objects.create(
            username="hr_term_admin", email="hr_term_admin@mcm.edu.ph",
            role=Role.HR_ADMIN, is_active=True,
        )
        self.client.force_login(self.hr)
        self.archived = AcademicTerm.objects.create(
            name="Archived HR Term", start_date=self.fx.term.start_date,
            end_date=self.fx.term.end_date,
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.archived_schedule = Schedule.objects.create(
            term=self.archived, course_code="ARCHIVEONLY", section="HX",
            faculty=self.fx.faculty_a, room=self.fx.room_a, day_of_week=0,
            start_time=time(8), end_time=time(9), modality=Modality.F2F,
        )
        self.archived_session = Session.objects.create(
            schedule=self.archived_schedule, faculty=self.fx.faculty_a,
            room=self.fx.room_a, date=self.fx.week_start,
            scheduled_start=_aware(self.fx.week_start, time(8)),
            scheduled_end=_aware(self.fx.week_start, time(9)),
            actual_start=_aware(self.fx.week_start, time(8, 5)),
            status=SessionStatus.ACTIVE,
        )

    def _csv_body(self, params=None):
        response = self.client.get(reverse("hr_attendance_csv"), params or {})
        return response, b"".join(response.streaming_content).decode("utf-8")

    def test_fresh_html_and_csv_query_only_active_term(self):
        page = self.client.get(reverse("hr_attendance"))
        self.assertEqual(page.context["scope"].term, self.fx.term)
        self.assertContains(page, self.fx.s_active.schedule.course_code)
        self.assertNotContains(page, "ARCHIVEONLY")

        export, body = self._csv_body()
        self.assertEqual(export.status_code, 200)
        self.assertIn(self.fx.s_active.schedule.course_code, body)
        self.assertNotIn("ARCHIVEONLY", body)

    def test_archived_html_and_csv_default_to_full_archived_span(self):
        params = {"term": self.archived.pk}
        page = self.client.get(reverse("hr_attendance"), params)
        scope = page.context["scope"]
        self.assertEqual((scope.start, scope.end),
                         (self.archived.start_date, self.archived.end_date))
        self.assertContains(page, "ARCHIVEONLY")
        self.assertNotContains(page, self.fx.s_active.schedule.course_code)

        _export, body = self._csv_body(params)
        self.assertIn("ARCHIVEONLY", body)
        self.assertNotIn(self.fx.s_active.schedule.course_code, body)

    def test_explicit_dates_clamp_identically_for_html_and_csv(self):
        params = {
            "term": self.archived.pk,
            "from": "1900-01-01",
            "to": "2099-12-31",
        }
        page = self.client.get(reverse("hr_attendance"), params)
        scope = page.context["scope"]
        self.assertEqual(scope.start, self.archived.start_date)
        self.assertEqual(scope.end, self.archived.end_date)
        export, body = self._csv_body(params)
        self.assertEqual(export["X-Report-From"], self.archived.start_date.isoformat())
        self.assertEqual(export["X-Report-To"], self.archived.end_date.isoformat())
        self.assertIn("ARCHIVEONLY", body)

    def test_invalid_explicit_term_is_friendly_and_never_falls_back(self):
        page = self.client.get(reverse("hr_attendance"), {"term": "missing"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["scope"].error_code, "invalid-term")
        self.assertContains(page, "academic term is not available")
        self.assertNotContains(page, self.fx.s_active.schedule.course_code)

        export = self.client.get(
            reverse("hr_attendance_csv"), {"term": "missing"})
        self.assertEqual(export.status_code, 400)
        self.assertNotIn(self.fx.s_active.schedule.course_code,
                         export.content.decode("utf-8"))

    def test_export_reset_and_pager_links_preserve_normalized_scope(self):
        # Force two archived rows across two pages without changing production's
        # bounded page size.
        Session.objects.create(
            schedule=self.archived_schedule, faculty=self.fx.faculty_a,
            room=self.fx.room_a, date=self.fx.week_start,
            scheduled_start=_aware(self.fx.week_start, time(10)),
            scheduled_end=_aware(self.fx.week_start, time(11)),
            status=SessionStatus.ABSENT,
        )
        params = {
            "term": self.archived.pk,
            "from": "1900-01-01",
            "to": "2099-12-31",
            "faculty": self.fx.faculty_a.pk,
            "q": "ARCHIVE",
        }
        with patch("web.hr.HR_PAGE_SIZE", 1):
            page = self.client.get(reverse("hr_attendance"), params)
        html = unescape(page.content.decode("utf-8"))
        expected_scope = {
            "term": [str(self.archived.pk)],
            "from": [self.archived.start_date.isoformat()],
            "to": [self.archived.end_date.isoformat()],
        }
        for url in (page.context["export_url"], page.context["reset_url"]):
            parsed = parse_qs(urlparse(url).query)
            for key, value in expected_scope.items():
                self.assertEqual(parsed[key], value)
        self.assertIn(f"term={self.archived.pk}&from=", html)
        self.assertIn("page=2", html)

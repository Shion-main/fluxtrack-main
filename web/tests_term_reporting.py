"""Selected-term reporting contracts for management report surfaces.

Phase 12 makes report scope explicit, bounded, and linkable. These tests keep
the shared parser independent from any one role surface, then exercise the HR
consumer against adversarial same-date data in ``HrReportTermTests``.
ASCII-only by convention (Windows cp1252).
"""
from datetime import date
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from scheduling.models import AcademicTerm
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

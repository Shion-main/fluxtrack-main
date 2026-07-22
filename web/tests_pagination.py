"""Tests for the shared list pagination (web/pagination.py + _pager.html).

The two properties that actually matter on these surfaces:

  - **Filters survive paging.** Every dense table sits under a GET filter bar. If
    a page link dropped the filters, page 2 of a filtered payroll query would
    quietly show unfiltered data -- a correctness bug wearing a UI costume.
  - **Bad page values degrade, never 500.** These are read-only surfaces reached
    from bookmarks and stale links; `?page=99` after a filter narrows the set is
    normal, not exceptional.

Plus the HR surface's own guarantee: paging bounds the SCREEN, never the export.
ASCII-only.
"""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from scheduling.models import (AcademicTerm, Modality, Schedule, Session,
                               SessionStatus)
from web.pagination import DEFAULT_PER_PAGE, paginate


class PaginateHelperTests(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.items = list(range(1, 121))  # 120 items -> 3 pages at 50

    def _ctx(self, query=""):
        return paginate(self.rf.get(f"/x?{query}"), self.items)

    def test_defaults_to_first_page(self):
        ctx = self._ctx()
        self.assertEqual(ctx["page"].number, 1)
        self.assertEqual(list(ctx["page"].object_list), self.items[:DEFAULT_PER_PAGE])
        self.assertEqual(ctx["paginator"].num_pages, 3)

    def test_page_param_selects_the_page(self):
        ctx = self._ctx("page=2")
        self.assertEqual(ctx["page"].number, 2)
        self.assertEqual(ctx["page"].start_index(), 51)
        self.assertEqual(ctx["page"].end_index(), 100)

    def test_non_integer_page_falls_back_to_first(self):
        self.assertEqual(self._ctx("page=banana")["page"].number, 1)

    def test_out_of_range_page_clamps_to_last(self):
        """A stale ?page=99 (or a filter that narrowed the set) must land on the
        last real page, not raise."""
        self.assertEqual(self._ctx("page=99")["page"].number, 3)

    def test_zero_and_negative_pages_do_not_raise(self):
        for raw in ("page=0", "page=-4"):
            self.assertIn(self._ctx(raw)["page"].number, (1, 3))

    def test_querystring_carries_other_filters_and_drops_page(self):
        ctx = self._ctx("department=2&q=cruz&page=2")
        self.assertIn("department=2", ctx["querystring"])
        self.assertIn("q=cruz", ctx["querystring"])
        self.assertNotIn("page=", ctx["querystring"])
        # Trailing '&' so the template can append page=N directly.
        self.assertTrue(ctx["querystring"].endswith("&"))

    def test_querystring_is_empty_when_no_other_filters(self):
        self.assertEqual(self._ctx("page=2")["querystring"], "")

    def test_empty_list_is_one_empty_page_not_an_error(self):
        ctx = paginate(self.rf.get("/x"), [])
        self.assertEqual(ctx["paginator"].count, 0)
        self.assertEqual(list(ctx["page"].object_list), [])


class HrPaginationTests(TestCase):
    """The surface that motivated this: HR attendance used to slice to 200 rows
    and say 'showing up to 200', which never told the reader whether they were
    seeing everything."""

    def setUp(self):
        User = get_user_model()
        today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name="T", start_date=today - timedelta(days=60),
            end_date=today + timedelta(days=60),
            status=AcademicTerm.Status.ACTIVE)
        self.dept = Department.objects.create(name="Computing", code="CCS")
        building = Building.objects.create(name="Academic", code="ACAD")
        floor = Floor.objects.create(building=building, number=1)
        self.room = Room.objects.create(
            floor=floor, code="R101", qr_token="tokp", manual_code="MCP001")
        self.faculty = User.objects.create(
            username="fac_pag", email="fac_pag@mcm.edu.ph", role=Role.FACULTY,
            last_name="Cruz", department=self.dept, is_active=True)
        self.other = User.objects.create(
            username="fac_other", email="fac_other@mcm.edu.ph", role=Role.FACULTY,
            last_name="Reyes", is_active=True)
        self.hr = User.objects.create(
            username="hr_pag", email="hr_pag@mcm.edu.ph", role=Role.HR_ADMIN,
            is_active=True)

        # 60 sessions for Cruz (2 pages) + 5 for Reyes, so a faculty filter has
        # something to exclude.
        self._make(self.faculty, 60)
        self._make(self.other, 5)
        self.client.force_login(self.hr)

    def _make(self, faculty, n):
        schedule = Schedule.objects.create(
            term=self.term, course_code="IT301", section="A", faculty=faculty,
            room=self.room, day_of_week=0, start_time="10:00", end_time="11:00",
            modality=Modality.F2F)
        today = timezone.localdate()
        for i in range(n):
            d = today - timedelta(days=i)
            Session.objects.create(
                schedule=schedule, faculty=faculty, room=self.room, date=d,
                scheduled_start=timezone.make_aware(datetime(d.year, d.month, d.day, 10, 0)),
                scheduled_end=timezone.make_aware(datetime(d.year, d.month, d.day, 11, 0)),
                status=SessionStatus.COMPLETED)

    def test_first_page_is_bounded_and_reports_the_true_total(self):
        resp = self.client.get(reverse("hr_attendance"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["sessions"]), 50)
        self.assertEqual(resp.context["paginator"].count, 65)
        self.assertContains(resp, "of <b>65</b>", html=False)

    def test_second_page_holds_the_remainder(self):
        resp = self.client.get(reverse("hr_attendance"), {"page": 2})
        self.assertEqual(len(resp.context["sessions"]), 15)
        self.assertEqual(resp.context["page"].number, 2)

    def test_paging_preserves_an_active_filter(self):
        """Page 2 of a filtered query must stay filtered. Without the querystring
        carry-forward this silently shows unfiltered payroll data."""
        resp = self.client.get(
            reverse("hr_attendance"), {"faculty": self.faculty.id, "page": 2})
        self.assertEqual(resp.context["paginator"].count, 60)
        self.assertTrue(
            all(s.faculty_id == self.faculty.id for s in resp.context["sessions"]))
        self.assertIn(f"faculty={self.faculty.id}", resp.context["querystring"])

    def test_stale_page_beyond_the_end_does_not_error(self):
        resp = self.client.get(reverse("hr_attendance"), {"page": 999})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["page"].number, 2)

    def test_export_is_not_paginated(self):
        """Paging bounds the screen, not the data (HR-03)."""
        resp = self.client.get(reverse("hr_attendance_csv"))
        body = b"".join(resp.streaming_content).decode()
        self.assertEqual(len(body.strip().splitlines()), 66)  # header + 65 rows

    def test_single_page_renders_a_plain_count_not_a_pager(self):
        resp = self.client.get(
            reverse("hr_attendance"), {"faculty": self.other.id})
        self.assertEqual(resp.context["paginator"].num_pages, 1)
        self.assertContains(resp, "5 rows")
        self.assertNotContains(resp, 'aria-label="Pagination"')

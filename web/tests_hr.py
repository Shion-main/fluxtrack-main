"""HR-01/02/03 view-level tests for the HR session-level attendance surface.

The HR surface is the ONE reporting surface that is cross-department by design and
whose export can hit full-term scale. These tests lock:

  - HrGateTests: an HR_ADMIN gets 200 on the list + CSV; a non-HR user (faculty) is
    refused 403 (T-06-14).
  - HrFilterTests: the four independent filters (faculty / department / date range /
    term) each narrow the visible sessions; an invalid date yields a 200 friendly
    notice (never a 500, T-06-16); a no-match filter shows the no-results state.
  - HrExportTests: /hr/attendance.csv streams a text/csv attachment whose decoded
    body has the header + a Present row + an Absent row, honors the active filters,
    and neutralizes a faculty name beginning with '=' (csv_safe reuse, T-06-02).
  - HrReadOnlyTests: a POST to either HR route is rejected 405 -- the surface
    exposes no write endpoint (T-06-07).

Seeds the shared two-department make_reporting_fixture from 06-01. ASCII-only.
"""
import csv
import io
from datetime import datetime, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from scheduling.models import (AcademicTerm, Modality, Schedule, Session,
                               SessionStatus)
from scheduling.test_support import make_reporting_fixture


def _aware(d, t):
    """Local-aware datetime from a date + time (tz-only; date filtering is on `date`)."""
    return timezone.make_aware(datetime(d.year, d.month, d.day, t.hour, t.minute))


class _HrBase(TestCase):
    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        # HR is cross-department: the HR user needs no department scope.
        self.hr = User.objects.create(
            username="hr_admin_x", email="hr_admin_x@mcm.edu.ph",
            role=Role.HR_ADMIN, is_active=True)
        self.client.force_login(self.hr)


class HrGateTests(_HrBase):
    """HR-01 / T-06-14: only HR_ADMIN (or superuser) may reach the surface."""

    def test_hr_admin_gets_attendance_list(self):
        resp = self.client.get(reverse("hr_attendance"))
        self.assertEqual(resp.status_code, 200)
        # The list is unscoped by department -> both faculties are visible.
        self.assertContains(resp, self.fx.faculty_a.last_name)
        self.assertContains(resp, self.fx.faculty_b.last_name)

    def test_hr_admin_gets_csv(self):
        resp = self.client.get(reverse("hr_attendance_csv"))
        self.assertEqual(resp.status_code, 200)

    def test_non_hr_refused_on_list(self):
        User = get_user_model()
        faculty = User.objects.create(
            username="hr_fac_x", email="hr_fac_x@mcm.edu.ph",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self.client.force_login(faculty)
        resp = self.client.get(reverse("hr_attendance"))
        self.assertEqual(resp.status_code, 403)

    def test_non_hr_refused_on_csv(self):
        User = get_user_model()
        faculty = User.objects.create(
            username="hr_fac_y", email="hr_fac_y@mcm.edu.ph",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self.client.force_login(faculty)
        resp = self.client.get(reverse("hr_attendance_csv"))
        self.assertEqual(resp.status_code, 403)


class HrFilterTests(_HrBase):
    """HR-02: four independent filters + validation + no-results state."""

    # Assert on per-session course codes, which appear ONLY in table rows -- the
    # faculty/department/term dropdowns echo every choice, so a faculty name or
    # dept code is present in the page even when its rows are filtered OUT.
    def test_faculty_filter_narrows(self):
        resp = self.client.get(reverse("hr_attendance"),
                               {"faculty": self.fx.faculty_a.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.fx.s_active.schedule.course_code)     # faculty_a
        self.assertNotContains(resp, self.fx.s_b_active.schedule.course_code)  # faculty_b

    def test_department_filter_narrows(self):
        resp = self.client.get(reverse("hr_attendance"),
                               {"department": self.fx.dept_b.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.fx.s_b_active.schedule.course_code)   # dept_b
        self.assertNotContains(resp, self.fx.s_active.schedule.course_code)  # dept_a

    def test_date_range_filter_narrows(self):
        # Wednesday (2026-07-08) carries ONLY faculty_a's SCHEDULED session; the
        # Monday/Tuesday session rows must not survive the range.
        resp = self.client.get(reverse("hr_attendance"),
                               {"from": self.fx.wed.isoformat(),
                                "to": self.fx.wed.isoformat()})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.fx.s_scheduled.schedule.course_code)  # wed row
        self.assertNotContains(resp, self.fx.s_active.schedule.course_code)   # mon row
        self.assertNotContains(resp, self.fx.s_b_active.schedule.course_code)  # mon row

    def test_term_filter_narrows(self):
        # A second (inactive) term with one uniquely-coded session for faculty_a.
        other_term = AcademicTerm.objects.create(
            name="Other Term", start_date=self.fx.term.start_date,
            end_date=self.fx.term.end_date,
            status=AcademicTerm.Status.ARCHIVED)
        sched = Schedule.objects.create(
            term=other_term, course_code="OTHERTERMSESS", section="Z",
            faculty=self.fx.faculty_a, room=self.fx.room_a, day_of_week=0,
            start_time=datetime(2026, 1, 1, 8, 0).time(),
            end_time=datetime(2026, 1, 1, 9, 30).time(), modality=Modality.F2F)
        Session.objects.create(
            schedule=sched, faculty=self.fx.faculty_a, room=self.fx.room_a,
            date=self.fx.week_start,
            scheduled_start=_aware(self.fx.week_start, datetime(2026, 1, 1, 8, 0).time()),
            scheduled_end=_aware(self.fx.week_start, datetime(2026, 1, 1, 9, 30).time()),
            status=SessionStatus.ACTIVE)

        # Filtering by the ORIGINAL active term excludes the other-term session.
        resp = self.client.get(reverse("hr_attendance"),
                               {"term": self.fx.term.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.fx.faculty_a.last_name)
        self.assertNotContains(resp, "OTHERTERMSESS")
        # Filtering by the OTHER term surfaces exactly that session.
        resp2 = self.client.get(reverse("hr_attendance"),
                                {"term": other_term.id})
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "OTHERTERMSESS")

    def test_fresh_request_resolves_active_term_in_context(self):
        resp = self.client.get(reverse("hr_attendance"))
        self.assertEqual(resp.context["scope"].term, self.fx.term)
        self.assertEqual(resp.context["filters"]["term"], str(self.fx.term.pk))
        self.assertIn(f"term={self.fx.term.pk}", resp.context["scope_query"])

    def test_invalid_date_is_friendly_not_500(self):
        resp = self.client.get(reverse("hr_attendance"),
                               {"from": "not-a-date"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "date filter was ignored")

    def test_no_match_shows_no_results_state(self):
        resp = self.client.get(reverse("hr_attendance"),
                               {"q": "zzz-no-such-faculty-or-course"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No sessions match these filters")


class HrExportTests(_HrBase):
    """HR-03 / T-06-02: streaming text/csv attachment; formula injection neutralized."""

    def setUp(self):
        super().setUp()
        # A dept_a faculty whose display name STARTS with a formula trigger, with a
        # session in range so the cell lands in the export.
        User = get_user_model()
        self.evil = User.objects.create(
            username="hr_evil", email="hr_evil@mcm.edu.ph",
            first_name="=cmd", last_name="Payload",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self.fx.add_session(self.evil, self.fx.week_start, SessionStatus.ACTIVE)

    def _body(self, resp):
        return b"".join(resp.streaming_content).decode("utf-8")

    def test_csv_is_streaming_attachment_with_rows(self):
        resp = self.client.get(reverse("hr_attendance_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("attachment", resp["Content-Disposition"])
        body = self._body(resp)
        # Header + a Present (ACTIVE) row + an Absent (ABSENT) row all present.
        self.assertIn("Faculty,Department,Course", body)
        self.assertIn("Present", body)
        self.assertIn("Absent", body)
        self.assertIn(self.fx.faculty_a.last_name, body)

    def test_csv_neutralizes_formula_name(self):
        resp = self.client.get(reverse("hr_attendance_csv"))
        body = self._body(resp)
        # csv_safe prefixes a single quote so "=cmd Payload" is not an Excel formula.
        self.assertIn("'=cmd Payload", body)
        # The raw formula never appears at the start of a cell/line.
        self.assertNotIn("\n=cmd Payload", body)

    def test_csv_honors_faculty_filter(self):
        resp = self.client.get(reverse("hr_attendance_csv"),
                               {"faculty": self.fx.faculty_a.id})
        body = self._body(resp)
        self.assertIn(self.fx.faculty_a.last_name, body)
        self.assertNotIn(self.fx.faculty_b.last_name, body)

    def test_csv_filename_identifies_selected_term(self):
        resp = self.client.get(reverse("hr_attendance_csv"))
        self.assertIn(
            f"term-{self.fx.term.pk}", resp["Content-Disposition"])
        self.assertEqual(resp["X-Report-Term"], str(self.fx.term.pk))


class HrReadOnlyTests(_HrBase):
    """T-06-07: the HR surface exposes NO write endpoint -- POST is rejected 405."""

    def test_post_rejected_on_every_route(self):
        for name in ("hr_attendance", "hr_attendance_csv"):
            resp = self.client.post(reverse(name))
            self.assertEqual(
                resp.status_code, 405,
                msg=f"POST to {name} should be rejected (read-only)")


class HrLatenessCsvTests(_HrBase):
    """A3 / D-03: the payroll CSV ADDS a derived per-session minutes-late column and
    KEEPS the raw actual_start timestamp. The derived cell is computed via the SHARED
    ``scheduling.reporting.session_minutes_late`` helper (imported, not re-derived) so
    the payroll export and the faculty aggregate cannot drift (Pitfall 5)."""

    def _grid(self, resp):
        body = b"".join(resp.streaming_content).decode("utf-8")
        return list(csv.reader(io.StringIO(body)))

    def _seed_late(self, minutes):
        # A held faculty_a session whose actual_start is `minutes` past scheduled
        # (fixture teach_start is 08:00, so 08:00 + minutes).
        start = _aware(self.fx.week_start, time(8, minutes))
        return self.fx.add_session(
            self.fx.faculty_a, self.fx.week_start, SessionStatus.ACTIVE,
            actual_start=start)

    def test_hr_csv_keeps_actual_start_and_adds_lateness(self):
        self._seed_late(12)
        grid = self._grid(self.client.get(reverse("hr_attendance_csv")))
        header = grid[0]
        # Both the raw timestamp column and the new derived column are present.
        self.assertIn("Actual start", header)
        self.assertIn("Minutes late", header)
        a_idx, m_idx = header.index("Actual start"), header.index("Minutes late")
        # The 12-min-late row still carries its raw actual_start timestamp (D-03:
        # add the derived column, do NOT remove the timestamp).
        late_rows = [r for r in grid[1:] if r[m_idx] == "12"]
        self.assertEqual(len(late_rows), 1)
        self.assertTrue(late_rows[0][a_idx], "raw actual_start cell must be retained")

    def test_hr_late_session_shows_minutes(self):
        self._seed_late(12)
        grid = self._grid(self.client.get(reverse("hr_attendance_csv")))
        m_idx = grid[0].index("Minutes late")
        minutes_cells = [r[m_idx] for r in grid[1:]]
        self.assertIn("12", minutes_cells)

    def test_hr_absent_zero_minutes(self):
        # The fixture already carries ABSENT sessions (actual_start NULL). An ABSENT
        # row shows 0 minutes late and an empty raw actual_start cell.
        grid = self._grid(self.client.get(reverse("hr_attendance_csv")))
        header = grid[0]
        s_idx = header.index("Status")
        a_idx = header.index("Actual start")
        m_idx = header.index("Minutes late")
        absent_rows = [r for r in grid[1:] if r[s_idx] == "Absent"]
        self.assertTrue(absent_rows, "fixture must contribute at least one Absent row")
        for r in absent_rows:
            self.assertEqual(r[m_idx], "0")
            self.assertEqual(r[a_idx], "")


class ScorecardLatenessSurfaceTests(TestCase):
    """A3 / D-02 / D-03: the faculty scorecard page renders avg-minutes-late and
    shows the chronic verdict ONLY at the >= 5-held floor. Reads the Plan-01
    Scorecard.minutes_late_avg / chronic_late fields; IFO-gated view."""

    def setUp(self):
        self.fx = make_reporting_fixture()
        User = get_user_model()
        self.ifo = User.objects.create(
            username="score_ifo", email="score_ifo@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.client.force_login(self.ifo)

    def _range(self):
        return {"from": self.fx.week_start.isoformat(),
                "to": self.fx.sun.isoformat()}

    def _seed_late(self, faculty, minutes, count):
        for _ in range(count):
            self.fx.add_session(
                faculty, self.fx.week_start, SessionStatus.ACTIVE,
                actual_start=_aware(self.fx.week_start, time(8, minutes)))

    def test_scorecard_page_shows_lateness(self):
        # faculty_a already has held sessions; add 5 late-by-12 held sessions so the
        # >=5-held floor is met and >=30% frequency trips the chronic verdict.
        self._seed_late(self.fx.faculty_a, 12, 5)
        url = reverse("ifo_scorecard", args=[self.fx.faculty_a.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Avg min late")
        self.assertContains(resp, "12.0")
        # >= 5 held AND chronic -> the paired Chronic verdict renders.
        self.assertContains(resp, "Chronic")

    def test_scorecard_suppresses_chronic_below_floor(self):
        # A fresh faculty with only 2 held-with-start sessions -> below the D-02
        # floor; the average still shows but the chronic verdict must not.
        User = get_user_model()
        thin = User.objects.create(
            username="score_thin", email="score_thin@mcm.edu.ph",
            first_name="Tina", last_name="Thin",
            role=Role.FACULTY, department=self.fx.dept_a, is_active=True)
        self._seed_late(thin, 6, 2)
        url = reverse("ifo_scorecard", args=[thin.id])
        resp = self.client.get(url, self._range())
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "6.0")
        self.assertNotContains(resp, "Chronic")

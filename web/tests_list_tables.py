"""Long lists are tables: a table on desktop, labelled cards on a phone.

Every list that can run past a screen renders through the shared `.tbl--stack`
table (cards below 640px, see static/css/app.css), keeps the row actions it had,
gets the filters a reader needs to narrow it, and pages at 50 rows through the
shared pager (D10). These tests pin that contract per surface. ASCII-only.
"""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from scheduling.models import (
    AcademicTerm,
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.test_support import MANILA, make_shift_fixture
from verification.models import (
    Assignment,
    AssignmentScope,
    AssignmentType,
    CheckerValidation,
    DutyRole,
)
from verification.tests import _CheckerFixtureMixin
from web.pagination import DEFAULT_PER_PAGE as PER

TABLE = 'class="tbl tbl--stack'


def _day(offset):
    return timezone.localdate() + timedelta(days=offset)


def _session_on(schedule, day, *, start=time(8, 0), end=time(9, 30),
                status=SessionStatus.SCHEDULED):
    return Session.objects.create(
        schedule=schedule, faculty=schedule.faculty, room=schedule.room, date=day,
        scheduled_start=datetime.combine(day, start, tzinfo=MANILA),
        scheduled_end=datetime.combine(day, end, tzinfo=MANILA),
        status=status)


def _request(fx, requester=None, status=ModalityShiftStatus.PENDING,
             modality=Modality.ONLINE, reason="Transport strike."):
    req = ModalityShiftRequest.objects.create(
        requester=requester or fx.faculty, department=fx.dept,
        target_modality=modality, window_start=_day(1), window_end=_day(1),
        request_reason=reason, status=status)
    ModalityShiftItem.objects.create(request=req, schedule=fx.f2f_schedule)
    return req


class DeanListTableTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("dlt")
        self.fx.session.delete()
        self.client.force_login(self.fx.dean)

    # --- Faculty roster ---------------------------------------------------
    def test_roster_is_a_table_and_searchable(self):
        get_user_model().objects.create(
            username="dlt_zed", first_name="Zed", last_name="Quill",
            email="zed@mcm.edu.ph", role=Role.FACULTY,
            department=self.fx.dept, is_active=True)

        resp = self.client.get("/dean/faculty")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, 'data-label="Email"')
        self.assertContains(resp, "Zed Quill")

        narrowed = self.client.get("/dean/faculty?q=quill")
        self.assertContains(narrowed, "Zed Quill")
        self.assertNotContains(narrowed, self.fx.faculty.email)

    # --- Faculty detail ---------------------------------------------------
    def test_detail_lists_are_tables(self):
        _session_on(self.fx.f2f_schedule, _day(1))
        resp = self.client.get(f"/dean/faculty/{self.fx.faculty.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(resp.content.decode().count(TABLE), 2)
        self.assertContains(resp, 'data-label="Day"')        # recurring schedule
        self.assertContains(resp, 'data-label="Date"')       # upcoming sessions

    def test_upcoming_sessions_page_with_no_silent_cap(self):
        for i in range(1, 126):
            _session_on(self.fx.f2f_schedule, _day(i))
        url = f"/dean/faculty/{self.fx.faculty.pk}"

        first = self.client.get(url)
        self.assertContains(first, 'name="sessions"', count=PER)
        self.assertContains(first, "<b>125</b>")              # the old [:100] cap is gone

        last = self.client.get(url + "?page=9")
        self.assertContains(last, 'name="sessions"', count=125 - 8 * PER)

    def test_upcoming_sessions_filter_by_class_and_date(self):
        other = Schedule.objects.create(
            term=self.fx.term, course_code="DLTOTHER", section="B",
            faculty=self.fx.faculty, room=self.fx.room_b, day_of_week=2,
            start_time=time(13, 0), end_time=time(14, 0), modality=Modality.F2F)
        _session_on(self.fx.f2f_schedule, _day(2))
        _session_on(other, _day(3), start=time(13, 0), end=time(14, 0))
        _session_on(other, _day(20), start=time(13, 0), end=time(14, 0))
        url = f"/dean/faculty/{self.fx.faculty.pk}"

        by_class = self.client.get(f"{url}?schedule={other.pk}")
        self.assertContains(by_class, 'name="sessions"', count=2)

        by_date = self.client.get(
            f"{url}?from={_day(1).isoformat()}&to={_day(5).isoformat()}")
        self.assertContains(by_date, 'name="sessions"', count=2)

    def test_recurring_schedule_pages_at_the_cap(self):
        for i in range(PER + 3):
            Schedule.objects.create(
                term=self.fx.term, course_code=f"DLTR{i:02d}", section="A",
                faculty=self.fx.faculty, room=self.fx.room_b, day_of_week=i % 6,
                start_time=time(7, 0), end_time=time(8, 0), modality=Modality.F2F)
        url = f"/dean/faculty/{self.fx.faculty.pk}"
        first = self.client.get(url)
        self.assertContains(first, "spage=2")
        self.assertContains(first, f"<b>{PER}</b>")              # page 1 ends at the cap

    # --- Approval queue ---------------------------------------------------
    def test_queue_is_a_table_with_actions_and_filters(self):
        other = get_user_model().objects.create(
            username="dlt_other", first_name="Olive", last_name="Tan",
            role=Role.FACULTY, department=self.fx.dept, is_active=True)
        _request(self.fx)
        _request(self.fx, requester=other, modality=Modality.BLENDED)

        resp = self.client.get("/dean/requests")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, "/approve", count=4)        # hx-post + action, x2
        self.assertContains(resp, 'name="reason"', count=2)   # reject reason per row

        by_name = self.client.get("/dean/requests?q=olive")
        self.assertContains(by_name, "/approve", count=2)
        by_modality = self.client.get("/dean/requests?modality=online")
        self.assertContains(by_modality, "/approve", count=2)

    def test_queue_pages_at_the_cap(self):
        for _ in range(55):
            _request(self.fx)
        resp = self.client.get("/dean/requests")
        self.assertContains(resp, "<b>55</b>")
        self.assertContains(resp, 'name="reason"', count=PER)

    def test_queue_redraw_after_a_decision_is_still_the_table(self):
        keep = _request(self.fx)
        gone = _request(self.fx)
        resp = self.client.post(f"/dean/requests/{gone.pk}/reject",
                                {"reason": "Not needed."})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, TABLE)
        self.assertContains(resp, f"/dean/requests/{keep.pk}/approve")


class IfoAssignmentTableTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="AT", start_date=timezone.localdate() - timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=90),
            status=AcademicTerm.Status.ACTIVE)
        bldg = Building.objects.create(name="Assign Hall", code="AH")
        self.floor = Floor.objects.create(building=bldg, number=1)
        self.ifo = User.objects.create(username="at_ifo", role=Role.IFO_ADMIN,
                                       is_active=True)
        self.client.force_login(self.ifo)
        self._n = 0

    def _post(self, role=DutyRole.CHECKER, scope=AssignmentScope.FLOOR):
        self._n += 1
        user = get_user_model().objects.create(
            username=f"at_u{self._n}", last_name=f"Duty{self._n}",
            role=Role.CHECKER if role == DutyRole.CHECKER else Role.GUARD,
            is_active=True)
        a = Assignment.objects.create(
            user=user, role=role, type=AssignmentType.STANDING, scope=scope,
            term=self.term, status="active")
        if scope == AssignmentScope.FLOOR:
            a.floors.set([self.floor])
        return a

    def test_roster_is_a_table_with_end_actions_and_filters(self):
        self._post()
        self._post(role=DutyRole.GUARD)
        self._post(scope=AssignmentScope.ONLINE)

        resp = self.client.get("/ifo/assignments")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, "/end", count=3)

        guards = self.client.get("/ifo/assignments?role=guard")
        self.assertContains(guards, "/end", count=1)
        online = self.client.get("/ifo/assignments?scope=online")
        self.assertContains(online, "/end", count=1)

    def test_roster_pages_at_the_cap(self):
        for _ in range(55):
            self._post()
        resp = self.client.get("/ifo/assignments")
        self.assertContains(resp, "<b>55</b>")
        self.assertContains(resp, "/end", count=PER)

    def test_ending_a_posting_redraws_the_table(self):
        keep = self._post()
        gone = self._post()
        resp = self.client.post(f"/ifo/assignments/{gone.pk}/end")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, TABLE)
        self.assertContains(resp, f"/ifo/assignments/{keep.pk}/end")


class FacultyListTableTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("flt")
        self.fx.session.delete()
        self.client.force_login(self.fx.faculty)

    def test_requests_are_a_table_withdraw_only_while_pending(self):
        _request(self.fx)
        _request(self.fx, status=ModalityShiftStatus.APPROVED)
        _request(self.fx, status=ModalityShiftStatus.REJECTED)

        resp = self.client.get("/faculty/modality/mine")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, "/withdraw", count=1)
        self.assertContains(resp, "data-request=", count=3)

        approved = self.client.get("/faculty/modality/mine?status=approved")
        self.assertContains(approved, "data-request=", count=1)

    def test_requests_page_at_the_cap(self):
        for _ in range(55):
            _request(self.fx, status=ModalityShiftStatus.WITHDRAWN)
        resp = self.client.get("/faculty/modality/mine")
        self.assertContains(resp, "<b>55</b>")
        self.assertContains(resp, "data-request=", count=PER)

    def test_next_seven_days_is_a_table(self):
        _session_on(self.fx.f2f_schedule, _day(1))
        _session_on(self.fx.f2f_schedule, _day(2))
        resp = self.client.get("/faculty/schedule")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, 'data-label="Day"')



    def test_next_seven_days_pages_at_the_cap(self):
        for d in range(1, 8):
            for h in (7, 9, 11):
                _session_on(self.fx.f2f_schedule, _day(d), start=time(h, 0), end=time(h, 50))
        resp = self.client.get("/faculty/schedule")
        self.assertContains(resp, "Showing")
        self.assertContains(resp, "page=2")

    def test_history_is_a_table(self):
        _session_on(self.fx.f2f_schedule, _day(-1), status=SessionStatus.COMPLETED)
        resp = self.client.get("/faculty/history")
        self.assertContains(resp, TABLE)
        self.assertContains(resp, "data-history-session=")


class GuardMonitorTableTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="GMT", start_date=timezone.localdate() - timedelta(days=30),
            end_date=timezone.localdate() + timedelta(days=90),
            status=AcademicTerm.Status.ACTIVE)
        bldg = Building.objects.create(name="GM", code="GM")
        self.floor = Floor.objects.create(building=bldg, number=1)
        self.room1 = Room.objects.create(floor=self.floor, code="GM101",
                                         qr_token="gmq1", manual_code="910101")
        self.room2 = Room.objects.create(floor=self.floor, code="GM102",
                                         qr_token="gmq2", manual_code="910102")
        self.faculty = User.objects.create(
            username="gm_fac", first_name="Ana", last_name="Reyes", role=Role.FACULTY)
        self.guard = User.objects.create(username="gm_guard", role=Role.GUARD)
        a = Assignment.objects.create(
            user=self.guard, role=DutyRole.GUARD, type=AssignmentType.STANDING,
            scope=AssignmentScope.FLOOR, term=self.term, status="active")
        a.floors.set([self.floor])
        self.client.force_login(self.guard)

    def _session(self, room, status, course):
        now = timezone.now()
        sch = Schedule.objects.create(
            term=self.term, course_code=course, section="A", faculty=self.faculty,
            room=room, day_of_week=0, start_time=time(8, 0), end_time=time(9, 30))
        return Session.objects.create(
            schedule=sch, faculty=self.faculty, room=room, date=timezone.localdate(),
            scheduled_start=now, scheduled_end=now + timedelta(minutes=90),
            status=status)

    def test_both_lists_are_tables_and_rooms_filter_by_status(self):
        self._session(self.room1, SessionStatus.ACTIVE, "GMLIVE")
        self._session(self.room2, SessionStatus.SCHEDULED, "GMSOON")

        resp = self.client.get("/guard/monitor/rows")
        self.assertEqual(resp.content.decode().count(TABLE), 2)
        self.assertContains(resp, "/guard/faculty/", count=1)  # one row per person

        live = self.client.get("/guard/monitor/rows?status=active")
        self.assertContains(live, "GMLIVE")
        self.assertNotContains(live, "GMSOON")

    def test_monitor_shell_has_the_status_filter(self):
        resp = self.client.get("/guard/monitor")
        self.assertContains(resp, 'name="status"')


class CheckerFloorTableTests(_CheckerFixtureMixin, TestCase):
    def test_board_is_a_table_and_filters_without_moving_coverage(self):
        checker = self._checker()
        self._active_floor_assignment(checker, self.floor)
        done = self._session(self._room())
        open_ = self._session(self._room())
        CheckerValidation.objects.create(
            session=done, room=done.room, checker=checker,
            action="verified", identity_match=True)
        self.client.force_login(checker)

        resp = self.client.get("/checker/floor/rows")
        self.assertContains(resp, TABLE)

        narrowed = self.client.get("/checker/floor/rows?state=verified")
        self.assertContains(narrowed, done.room.code)
        self.assertNotContains(narrowed, f'data-room="{open_.room.code}"')
        self.assertEqual(narrowed.context["total"], 2)       # coverage is the floor
        self.assertEqual(narrowed.context["verified"], 1)

    def test_board_shell_has_the_state_filter(self):
        checker = self._checker()
        self.client.force_login(checker)
        resp = self.client.get("/checker/floor")
        self.assertContains(resp, 'name="state"')

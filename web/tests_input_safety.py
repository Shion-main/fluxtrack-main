"""Bad input gets a friendly answer, never a server error (audit M1, M2).

Impossible dates pass Django's shape check and then raise, and ``str.isdigit`` is
true for characters ``int()`` rejects. Both reached the views as 500s.
"""
import json
import uuid
from datetime import date

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase

from accounts.models import Role
from scheduling.test_support import make_shift_fixture
from verification.models import Assignment, AssignmentScope, AssignmentType, DutyRole
from web.parsing import is_id, safe_parse_date, safe_parse_time

User = get_user_model()
BAD_DATE = "2026-02-31"
SUPERSCRIPT = "²"          # str.isdigit() is True, int() raises
TOO_BIG = "9" * 30              # overflows the database driver


class ParsingHelperTests(SimpleTestCase):
    def test_is_id(self):
        cases = [("7", True), (7, True), ("007", True),
                 ("", False), (None, False), ("abc", False), ("-5", False),
                 ("1.5", False), (SUPERSCRIPT, False), (TOO_BIG, False)]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertIs(is_id(raw), expected)

    def test_safe_parse_date(self):
        self.assertEqual(safe_parse_date("2026-02-28"), date(2026, 2, 28))
        self.assertIsNone(safe_parse_date(BAD_DATE))
        self.assertIsNone(safe_parse_date("not a date"))
        self.assertIsNone(safe_parse_date(None))   # an absent GET param

    def test_safe_parse_time(self):
        self.assertEqual(safe_parse_time("08:30").hour, 8)
        self.assertIsNone(safe_parse_time("25:99"))
        self.assertIsNone(safe_parse_time(None))


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("inp")
        make = lambda role, name: User.objects.create(  # noqa: E731
            username=name, email=f"{name}@mcm.edu.ph", role=role, is_active=True)
        self.faculty = self.browser(self.fx.faculty)
        self.dean = self.browser(self.fx.dean)
        self.ifo = self.browser(make(Role.IFO_ADMIN, "inp_ifo"))
        self.hr = self.browser(make(Role.HR_ADMIN, "inp_hr"))
        self.checker_user = make(Role.CHECKER, "inp_chk")
        self.checker = self.browser(self.checker_user)

    def browser(self, user):
        client = Client(raise_request_exception=False)
        client.force_login(user)
        return client


class ImpossibleDateTests(Base):
    def test_report_filters_fall_back_with_a_note(self):
        cases = [
            (self.faculty, f"/faculty/history?from={BAD_DATE}"),
            (self.hr, f"/hr/attendance?from={BAD_DATE}"),
            (self.ifo, f"/ifo/dashboard?from={BAD_DATE}"),
            (self.ifo, f"/ifo/utilization?as_of={BAD_DATE}"),
            (self.ifo, f"/ifo/reports?week={BAD_DATE}"),
            (self.dean, f"/dean/reports?from={BAD_DATE}"),
            (self.dean, f"/dean/dashboard?to={BAD_DATE}"),
        ]
        for client, url in cases:
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)

    def test_history_says_the_date_was_ignored(self):
        response = self.faculty.get(f"/faculty/history?from={BAD_DATE}")
        self.assertContains(response, "date filter was ignored")

    def test_csv_export_still_downloads(self):
        response = self.hr.get(f"/hr/attendance.csv?to={BAD_DATE}")
        self.assertEqual(response.status_code, 200)

    def test_modality_request_with_impossible_date_is_refused_politely(self):
        response = self.faculty.post("/faculty/modality/new", {
            "target_modality": "blended", "schedules": [self.fx.f2f_schedule.pk],
            "request_reason": "x", "window_mode": "single", "on_date": BAD_DATE})
        self.assertEqual(response.status_code, 400)

    def test_modality_request_with_impossible_time_is_refused_politely(self):
        response = self.faculty.post("/faculty/modality/new", {
            "target_modality": "blended", "schedules": [self.fx.f2f_schedule.pk],
            "request_reason": "x", "window_mode": "weeks", "weeks": "1",
            "new_start_time": "25:99", "new_end_time": "26:00"})
        self.assertEqual(response.status_code, 400)

    def test_term_form_reports_the_bad_date_at_both_steps(self):
        fields = {"name": "Z", "start_date": BAD_DATE, "end_date": BAD_DATE,
                  "confirmation_name": "Z"}
        self.assertEqual(
            self.ifo.post("/ifo/terms/create", fields).status_code, 200)
        self.assertEqual(self.ifo.post("/ifo/terms/create", {
            **fields, "step": "confirm"}).status_code, 400)


class CraftedIdTests(Base):
    def test_no_crafted_id_reaches_a_server_error(self):
        fx = self.fx
        modality = {"target_modality": "blended", "request_reason": "x"}
        booking = {"occupant_name": "x", "date": "2026-07-06",
                   "start_time": "08:00", "end_time": "09:00"}
        assignment = {"role": "checker", "type": "shift", "scope": "floor"}
        room = {"code": "INP-Z", "room_type": "CLASSROOM"}
        cases = []
        for bad in (SUPERSCRIPT, TOO_BIG):
            cases += [
                (self.faculty, "post", "/faculty/modality/new",
                 {**modality, "schedules": [bad], "weeks": "1"}),
                (self.faculty, "post", "/faculty/modality/new",
                 {**modality, "schedules": [fx.f2f_schedule.pk], "weeks": bad}),
                (self.faculty, "post", "/faculty/modality/new",
                 {**modality, "schedules": [fx.f2f_schedule.pk], "weeks": "1",
                  f"preferred_room_{fx.f2f_schedule.pk}": bad}),
                (self.faculty, "get", "/faculty/modality/rooms", {"schedules": bad}),
                (self.faculty, "get", "/faculty/modality/new", {"schedule": bad}),
                (self.faculty, "get", "/faculty/history", {"term": bad}),
                (self.hr, "get", "/hr/attendance", {"term": bad}),
                (self.hr, "get", "/hr/attendance", {"faculty": bad}),
                (self.hr, "get", "/hr/attendance", {"department": bad}),
                (self.dean, "post", f"/dean/faculty/{fx.faculty.pk}",
                 {"session": bad, "target_modality": "online", "reason": "x"}),
                (self.dean, "post", f"/dean/faculty/{fx.faculty.pk}",
                 {"action": "bulk_override", "sessions": [bad],
                  "target_modality": "online", "reason": "x"}),
                (self.dean, "post", "/dean/modality/override", {"session": bad}),
                (self.ifo, "post", "/ifo/schedules/new",
                 {"course_code": "A", "section": "B", "faculty": bad, "room": bad}),
                (self.ifo, "post", f"/ifo/schedules/{fx.f2f_schedule.pk}/edit",
                 {"faculty": bad, "room": bad}),
                (self.ifo, "post", "/ifo/bookings/create", {**booking, "room": bad}),
                (self.ifo, "post", "/ifo/assignments/create",
                 {**assignment, "user": bad, "floors": [fx.room_a.floor.pk]}),
                (self.ifo, "post", "/ifo/assignments/create",
                 {**assignment, "user": self.checker_user.pk, "floors": [bad]}),
                (self.ifo, "get", "/ifo/rooms", {"floor": bad}),
                (self.ifo, "post", "/ifo/rooms/new",
                 {**room, "floor": bad, "capacity": "1"}),
                (self.ifo, "post", "/ifo/rooms/new",
                 {**room, "floor": fx.room_a.floor.pk, "capacity": bad}),
                (self.ifo, "post", "/ifo/suspensions/create",
                 {"start_date": "2026-07-06", "reason": "x", "building": bad}),
                (self.ifo, "post", "/ifo/import/preview", {"term": bad}),
                (self.checker, "post", "/checker/action",
                 {"action": "verified", "room_id": bad}),
                (self.checker, "post", "/checker/action",
                 {"action": "verified", "session_id": bad}),
            ]
        for client, method, url, data in cases:
            with self.subTest(url=url, data=str(data)[:60]):
                response = getattr(client, method)(url, data)
                self.assertLess(response.status_code, 500)

    def test_replay_flags_a_crafted_session_id_instead_of_crashing(self):
        assignment = Assignment.objects.create(
            user=self.checker_user, role=DutyRole.CHECKER,
            type=AssignmentType.STANDING, scope=AssignmentScope.FLOOR,
            term=self.fx.term)
        assignment.floors.set([self.fx.room_a.floor])
        item = {"owner_id": self.checker_user.pk, "client_uuid": str(uuid.uuid4()),
                "token": self.fx.room_a.qr_token, "action": "verified_empty",
                "session_id": SUPERSCRIPT}
        response = self.checker.post("/checker/replay",
                                     json.dumps({"items": [item]}),
                                     content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["status"], "flagged")

    def test_room_capacity_beyond_the_column_is_refused(self):
        response = self.ifo.post("/ifo/rooms/new", {
            "code": "INP-Y", "room_type": "CLASSROOM",
            "floor": self.fx.room_a.floor.pk, "capacity": "99999999999"})
        self.assertEqual(response.status_code, 400)

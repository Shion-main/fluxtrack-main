"""Phase 12 Plan 06: active-term live surface and archived-id write guards."""
from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog, Notification
from scheduling.models import (
    AcademicTerm,
    Modality,
    Schedule,
    Session,
    SessionStatus,
)
from verification.models import (
    Assignment,
    AssignmentScope,
    CheckerValidation,
    DutyRole,
    ValidationAction,
)
from web import checker, faculty, guard


class _LiveTermFixture(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.today = timezone.localdate()
        self.dept = Department.objects.create(name="Term Web", code="TWEB")
        self.faculty_user = self.User.objects.create(
            username="term_faculty",
            email="term_faculty@mcm.edu.ph",
            role=Role.FACULTY,
            department=self.dept,
            is_active=True,
        )
        self.checker_user = self.User.objects.create(
            username="term_checker",
            email="term_checker@mcm.edu.ph",
            role=Role.CHECKER,
            is_active=True,
        )
        self.guard_user = self.User.objects.create(
            username="term_guard",
            email="term_guard@mcm.edu.ph",
            role=Role.GUARD,
            is_active=True,
        )
        self.ifo_user = self.User.objects.create(
            username="term_ifo",
            email="term_ifo@mcm.edu.ph",
            role=Role.IFO_ADMIN,
            is_active=True,
        )
        self.active = AcademicTerm.objects.create(
            name="Web Active",
            start_date=self.today - timedelta(days=7),
            end_date=self.today + timedelta(days=30),
            status=AcademicTerm.Status.ACTIVE,
        )
        self.draft = AcademicTerm.objects.create(
            name="Web Draft",
            start_date=self.active.start_date,
            end_date=self.active.end_date,
            status=AcademicTerm.Status.DRAFT,
        )
        self.archived = AcademicTerm.objects.create(
            name="Web Archived",
            start_date=self.active.start_date,
            end_date=self.active.end_date,
            status=AcademicTerm.Status.ARCHIVED,
        )
        building = Building.objects.create(name="Term Hall", code="TWEB")
        self.floor = Floor.objects.create(building=building, number=1)
        self.room = Room.objects.create(
            floor=self.floor,
            code="TW101",
            capacity=40,
            qr_token="tw-active-token",
            manual_code="910101",
        )

    def _schedule(self, term, prefix, *, modality=Modality.F2F):
        return Schedule.objects.create(
            term=term,
            course_code=prefix,
            section="A",
            faculty=self.faculty_user,
            room=self.room,
            day_of_week=self.today.weekday(),
            start_time=time(8, 0),
            end_time=time(9, 30),
            modality=modality,
        )

    def _session(
        self,
        term,
        prefix,
        *,
        modality=Modality.F2F,
        status=SessionStatus.SCHEDULED,
        start_delta=-10,
    ):
        schedule = self._schedule(term, prefix, modality=modality)
        start = timezone.now() + timedelta(minutes=start_delta)
        return Session.objects.create(
            schedule=schedule,
            faculty=self.faculty_user,
            room=self.room,
            date=self.today,
            scheduled_start=start,
            scheduled_end=start + timedelta(minutes=90),
            status=status,
        )

    def _floor_assignment(self, user, term):
        assignment = Assignment.objects.create(
            user=user,
            role=DutyRole.CHECKER if user.role == Role.CHECKER else DutyRole.GUARD,
            type="standing",
            scope=AssignmentScope.FLOOR,
            term=term,
            status="active",
        )
        assignment.floors.add(self.floor)
        return assignment

    def _online_assignment(self, user, term):
        return Assignment.objects.create(
            user=user,
            role=DutyRole.CHECKER,
            type="standing",
            scope=AssignmentScope.ONLINE,
            term=term,
            status="active",
        )


class ActiveTermOperationalScopeTests(_LiveTermFixture):
    def test_faculty_cards_and_online_rows_show_only_active_term(self):
        active = self._session(self.active, "FACACTIVE")
        self._session(self.draft, "FACDRAFT")
        self._session(self.archived, "FACARCH")
        active_online = self._session(
            self.active,
            "ONACTIVE",
            modality=Modality.ONLINE,
        )
        self._session(self.draft, "ONDRAFT", modality=Modality.ONLINE)
        self._session(self.archived, "ONARCH", modality=Modality.ONLINE)

        today_cards, week_cards, _ = faculty._faculty_cards(
            self.faculty_user,
            timezone.localtime(),
        )
        online_rows = faculty._online_rows(self.faculty_user, timezone.localtime())

        card_ids = {card["rep"].pk for card in today_cards + week_cards}
        self.assertIn(active.pk, card_ids)
        self.assertIn(active_online.pk, card_ids)
        self.assertEqual({row["session"].pk for row in online_rows}, {active_online.pk})

    def test_checker_room_online_and_floor_queries_use_active_term(self):
        archived = self._session(self.archived, "CHKARCH", status=SessionStatus.ACTIVE)
        self._floor_assignment(self.checker_user, self.active)
        session, state = checker._room_session_state(self.room, timezone.now())
        self.assertIsNone(session)
        self.assertIsNone(state)

        active = self._session(self.active, "CHKACTIVE", status=SessionStatus.ACTIVE)
        session, state = checker._room_session_state(self.room, timezone.now())
        self.assertEqual(session.pk, active.pk)
        self.assertEqual(state.id, active.pk)

        self._online_assignment(self.checker_user, self.archived)
        archived_online = self._session(
            self.archived,
            "CHKONARCH",
            modality=Modality.ONLINE,
        )
        archived_online.online_checker = self.checker_user
        archived_online.save(update_fields=["online_checker"])
        self.assertIsNone(checker._online_session(archived_online.pk, self.checker_user))

    def test_guard_monitor_room_and_locator_use_active_term(self):
        self._floor_assignment(self.guard_user, self.active)
        self._session(self.archived, "GRDARCH", status=SessionStatus.ACTIVE)
        active = self._session(self.active, "GRDACTIVE", status=SessionStatus.ACTIVE)

        self.client.force_login(self.guard_user)
        rows = self.client.get("/guard/monitor/rows")
        self.assertContains(rows, "GRDACTIVE")
        self.assertNotContains(rows, "GRDARCH")

        room = self.client.get(f"/guard/rooms/{self.room.code}")
        self.assertContains(room, "GRDACTIVE")
        self.assertNotContains(room, "GRDARCH")

        located = self.client.get("/guard/locate", {"q": self.faculty_user.username})
        self.assertContains(located, active.schedule.course_code)
        self.assertNotContains(located, "GRDARCH")


class NoActiveTermSurfaceTests(_LiveTermFixture):
    def test_live_helpers_return_empty_without_active_term(self):
        self.active.status = AcademicTerm.Status.ARCHIVED
        self.active.save(update_fields=["status"])
        self._session(self.archived, "NOACTIVE", status=SessionStatus.ACTIVE)
        self._floor_assignment(self.checker_user, self.archived)
        self._floor_assignment(self.guard_user, self.archived)

        today_cards, week_cards, _ = faculty._faculty_cards(
            self.faculty_user,
            timezone.localtime(),
        )
        self.assertEqual(today_cards, [])
        self.assertEqual(week_cards, [])
        self.assertEqual(faculty._online_rows(self.faculty_user, timezone.localtime()), [])
        self.assertEqual(checker._active_floor_ids(self.checker_user, timezone.now()), set())
        self.assertEqual(guard._guard_floor_ids(self.guard_user, timezone.now()), set())
        self.assertEqual(
            checker._room_session_state(self.room, timezone.now()),
            (None, None),
        )


class ArchivedPostRefusalTests(_LiveTermFixture):
    def test_faculty_online_start_refuses_archived_session_without_writes(self):
        archived = self._session(
            self.archived,
            "POSTARCH",
            modality=Modality.ONLINE,
        )
        self.client.force_login(self.faculty_user)

        response = self.client.post(
            f"/faculty/online/{archived.pk}/start",
            {"teams_link": "https://teams.microsoft.com/l/meetup-join/example"},
        )

        archived.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(archived.status, SessionStatus.SCHEDULED)
        self.assertEqual(archived.teams_link, "")
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_checker_online_action_refuses_archived_session_without_writes(self):
        self._online_assignment(self.checker_user, self.active)
        archived = self._session(
            self.archived,
            "CHKPOSTARCH",
            modality=Modality.ONLINE,
        )
        archived.online_checker = self.checker_user
        archived.save(update_fields=["online_checker"])
        self.client.force_login(self.checker_user)

        response = self.client.post(
            "/checker/action",
            {"session_id": archived.pk, "action": ValidationAction.VERIFIED},
        )

        archived.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(archived.status, SessionStatus.SCHEDULED)
        self.assertFalse(CheckerValidation.objects.exists())
        self.assertFalse(AuditLog.objects.exists())
        self.assertFalse(Notification.objects.exists())

    def test_source_coupling_names_active_term_predicates(self):
        files = [
            "web/scan.py",
            "web/faculty.py",
            "web/checker.py",
            "web/guard.py",
        ]
        for path in files:
            with self.subTest(path=path):
                source = open(path, encoding="utf-8").read()
                self.assertIn("get_active_term()", source)
        self.assertNotIn("filter(is_active=True)", open("web/faculty.py", encoding="utf-8").read())
        self.assertNotIn("filter(is_active=True)", open("web/guard.py", encoding="utf-8").read())

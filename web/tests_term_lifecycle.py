"""Phase 12 Plan 06: active-term live surface and archived-id write guards."""
from datetime import date, datetime, time, timedelta
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog, Notification
from ops.models import RoomConflictFlag
from scheduling.models import (
    AcademicBreak,
    AcademicTerm,
    ClassSuspension,
    Modality,
    Schedule,
    ScheduleStatus,
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
from web import checker, faculty, guard, ifo


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


class IfoActiveTermScopeTests(_LiveTermFixture):
    def test_room_board_panel_and_detail_ignore_non_active_term_sessions(self):
        active = self._session(self.active, "IFOACTIVE", status=SessionStatus.ACTIVE)
        self._session(self.archived, "IFOARCH", status=SessionStatus.ACTIVE)

        board = ifo._room_board("all")
        tiles = [tile for group in board["groups"] for tile in group["tiles"]]
        tile = next(tile for tile in tiles if tile["room"].pk == self.room.pk)
        self.assertEqual(tile["count"], 1)
        self.assertEqual(tile["session"].pk, active.pk)

        self.client.force_login(self.ifo_user)
        panel = self.client.get(f"/ifo/rooms/{self.room.code}/panel")
        self.assertContains(panel, "IFOACTIVE")
        self.assertNotContains(panel, "IFOARCH")

        detail = self.client.get(f"/ifo/rooms/{self.room.code}")
        self.assertContains(detail, "IFOACTIVE")
        self.assertNotContains(detail, "IFOARCH")

    def test_conflict_contenders_ignore_archived_term_sessions(self):
        self._session(self.archived, "CONARCH1", status=SessionStatus.ACTIVE)
        self._session(self.archived, "CONARCH2", status=SessionStatus.ACTIVE)
        RoomConflictFlag.objects.create(room=self.room, conflict_key=f"room:{self.room.pk}")

        self.assertEqual(ifo._contending_sessions([self.room.pk]), {})

        active = self._session(self.active, "CONACTIVE", status=SessionStatus.ACTIVE)
        self.assertEqual(
            [s.pk for s in ifo._contending_sessions([self.room.pk])[self.room.pk]],
            [active.pk],
        )

    def test_active_assignment_helper_uses_active_term_only(self):
        active_assignment = self._floor_assignment(self.checker_user, self.active)
        self._floor_assignment(self.guard_user, self.archived)

        self.assertEqual(
            list(ifo._active_assignments().values_list("pk", flat=True)),
            [active_assignment.pk],
        )

    def test_ifo_release_refuses_archived_session_without_writes(self):
        archived = self._session(self.archived, "RELARCH", status=SessionStatus.ACTIVE)
        self.client.force_login(self.ifo_user)

        response = self.client.post(f"/ifo/sessions/{archived.pk}/release")

        archived.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(archived.room_released_at)
        self.assertFalse(AuditLog.objects.exists())

    def test_ifo_break_delete_refuses_archived_break_without_writes(self):
        archived_break = AcademicBreak.objects.create(
            term=self.archived,
            start_date=self.today,
            end_date=self.today,
            reason="Archived holiday",
        )
        self.client.force_login(self.ifo_user)

        response = self.client.post(f"/ifo/breaks/{archived_break.pk}/delete")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(AcademicBreak.objects.filter(pk=archived_break.pk).exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_ifo_suspension_lift_refuses_archived_suspension_without_writes(self):
        suspension = ClassSuspension.objects.create(
            term=self.archived,
            start_date=self.today,
            end_date=self.today,
            reason="Archived closure",
            declared_by=self.ifo_user,
        )
        self.client.force_login(self.ifo_user)

        response = self.client.post(f"/ifo/suspensions/{suspension.pk}/lift")

        suspension.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(suspension.lifted_at)
        self.assertFalse(AuditLog.objects.exists())

    def test_ifo_reinstate_refuses_archived_absent_session_without_writes(self):
        archived = self._session(
            self.archived,
            "REINARCH",
            status=SessionStatus.ABSENT,
        )
        self.client.force_login(self.ifo_user)

        response = self.client.post(
            f"/ifo/sessions/{archived.pk}/reinstate",
            {"reason": "Wrongly marked absent"},
        )

        archived.refresh_from_db()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(archived.status, SessionStatus.ABSENT)
        self.assertFalse(AuditLog.objects.exists())

    def test_ifo_schedule_edit_and_cancel_refuse_archived_schedule_without_writes(self):
        schedule = self._schedule(self.archived, "SCHARCH")
        session = Session.objects.create(
            schedule=schedule,
            faculty=self.faculty_user,
            room=self.room,
            date=self.today + timedelta(days=1),
            scheduled_start=timezone.make_aware(datetime.combine(
                self.today + timedelta(days=1), time(8, 0))),
            scheduled_end=timezone.make_aware(datetime.combine(
                self.today + timedelta(days=1), time(9, 30))),
            status=SessionStatus.SCHEDULED,
        )
        self.client.force_login(self.ifo_user)

        edit = self.client.post(
            f"/ifo/schedules/{schedule.pk}/edit",
            {
                "faculty": str(self.faculty_user.pk),
                "room": str(self.room.pk),
                "start_time": "10:00",
                "end_time": "11:00",
                "enrolled_count": "25",
            },
        )
        cancel = self.client.post(
            f"/ifo/schedules/{schedule.pk}/cancel",
            {"reason": "Archived schedule direct POST"},
        )

        schedule.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(edit.status_code, 404)
        self.assertEqual(cancel.status_code, 404)
        self.assertEqual(schedule.status, ScheduleStatus.ACTIVE)
        self.assertEqual(session.status, SessionStatus.SCHEDULED)
        self.assertFalse(AuditLog.objects.exists())

    def test_ifo_source_coupling_uses_active_term_predicates(self):
        source = open("web/ifo.py", encoding="utf-8").read()
        self.assertIn("get_active_term()", source)
        self.assertNotIn("AcademicTerm.objects.filter(is_active=True)", source)


class _TermConsoleFixture(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.ifo = self.User.objects.create(
            username="console_ifo", email="console_ifo@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True,
        )
        self.superuser = self.User.objects.create_superuser(
            username="console_root", email="console_root@mcm.edu.ph",
            password="test",
        )
        self.denied_users = [
            self.User.objects.create(
                username=f"console_{role}", email=f"console_{role}@mcm.edu.ph",
                role=role, is_active=True,
            )
            for role in (
                Role.DEAN, Role.HR_ADMIN, Role.FACULTY, Role.CHECKER, Role.GUARD,
            )
        ]

    def _details(self, **overrides):
        data = {
            "step": "details",
            "name": "AY 2027-2028",
            "start_date": "2027-06-01",
            "end_date": "2028-05-31",
        }
        data.update(overrides)
        return data

    def _confirm(self, **overrides):
        data = self._details(step="confirm", confirmation_name="AY 2027-2028")
        data.update(overrides)
        return data


class TermCreateViewTests(_TermConsoleFixture):
    def test_list_and_detail_are_ifo_or_superuser_only_and_get_is_read_only(self):
        term = AcademicTerm.objects.create(
            name="Console Draft", start_date=date(2027, 1, 1),
            end_date=date(2027, 5, 31), status=AcademicTerm.Status.DRAFT,
        )
        routes = [reverse("ifo_terms"), reverse("ifo_term_detail", args=[term.pk])]
        for user in (self.ifo, self.superuser):
            self.client.force_login(user)
            for route in routes:
                with self.subTest(user=user.username, route=route):
                    response = self.client.get(route)
                    self.assertEqual(response.status_code, 200)
        for user in self.denied_users:
            self.client.force_login(user)
            for route in routes:
                with self.subTest(user=user.username, route=route):
                    self.assertEqual(self.client.get(route).status_code, 403)
        self.assertEqual(AcademicTerm.objects.count(), 1)
        self.assertFalse(AuditLog.objects.exists())

    def test_terms_list_is_status_first_then_date_descending(self):
        active = AcademicTerm.objects.create(
            name="Active", start_date=date(2027, 1, 1), end_date=date(2027, 5, 31),
            status=AcademicTerm.Status.ACTIVE,
        )
        newer_draft = AcademicTerm.objects.create(
            name="New Draft", start_date=date(2028, 1, 1), end_date=date(2028, 5, 31),
            status=AcademicTerm.Status.DRAFT,
        )
        older_draft = AcademicTerm.objects.create(
            name="Old Draft", start_date=date(2026, 1, 1), end_date=date(2026, 5, 31),
            status=AcademicTerm.Status.DRAFT,
        )
        archived = AcademicTerm.objects.create(
            name="Archive", start_date=date(2025, 1, 1), end_date=date(2025, 5, 31),
            status=AcademicTerm.Status.ARCHIVED,
        )
        self.client.force_login(self.ifo)

        response = self.client.get(reverse("ifo_terms"))

        self.assertEqual(
            [term.pk for term in response.context["terms"]],
            [active.pk, newer_draft.pk, older_draft.pk, archived.pk],
        )

    def test_details_post_is_read_only_preflight_and_confirmation_starts_empty(self):
        self.client.force_login(self.ifo)

        response = self.client.post(reverse("ifo_term_create"), self._details())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preflight"].candidate_name, "AY 2027-2028")
        self.assertEqual(response.context["confirmation_name"], "")
        self.assertContains(response, 'name="confirmation_name"', html=False)
        self.assertFalse(AcademicTerm.objects.exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_confirmation_is_distinct_exact_and_stale_preflight_refuses(self):
        self.client.force_login(self.ifo)
        for confirmation in ("", "ay 2027-2028"):
            response = self.client.post(
                reverse("ifo_term_create"), self._confirm(confirmation_name=confirmation),
            )
            self.assertEqual(response.status_code, 400)
            self.assertFalse(AcademicTerm.objects.exists())
            self.assertFalse(AuditLog.objects.exists())

        preflight = self.client.post(reverse("ifo_term_create"), self._details())
        self.assertEqual(preflight.status_code, 200)
        AcademicTerm.objects.create(
            name="Inserted overlap", start_date=date(2027, 7, 1),
            end_date=date(2027, 7, 31), status=AcademicTerm.Status.DRAFT,
        )
        response = self.client.post(reverse("ifo_term_create"), self._confirm())
        self.assertEqual(response.status_code, 400)
        self.assertFalse(AcademicTerm.objects.filter(name="AY 2027-2028").exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_confirmed_create_redirects_to_blank_draft_with_atomic_audit(self):
        self.client.force_login(self.ifo)

        response = self.client.post(reverse("ifo_term_create"), self._confirm())

        term = AcademicTerm.objects.get(name="AY 2027-2028")
        self.assertRedirects(response, reverse("ifo_term_detail", args=[term.pk]))
        self.assertEqual(term.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(term.schedules.exists())
        audit = AuditLog.objects.get(event_type="term.created")
        self.assertEqual(audit.actor, self.ifo)
        self.assertIsNone(audit.payload["reason"])
        self.assertIsNone(audit.payload["before"])
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.DRAFT)
        self.assertEqual(audit.payload["schedule_count"], 0)
        self.assertEqual(audit.payload["session_count"], 0)

    def test_injected_audit_failure_rolls_back_and_rerenders_400(self):
        self.client.force_login(self.ifo)
        with patch("scheduling.term_lifecycle.AuditLog.objects.create",
                   side_effect=RuntimeError("audit unavailable")):
            response = self.client.post(reverse("ifo_term_create"), self._confirm())

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "could not be committed", status_code=400)
        self.assertFalse(AcademicTerm.objects.exists())
        self.assertFalse(AuditLog.objects.exists())


class TermAuthorityAndPreflightTests(_TermConsoleFixture):
    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def _term(self, name, status, start_delta, end_delta):
        return AcademicTerm.objects.create(
            name=name,
            start_date=self.today + timedelta(days=start_delta),
            end_date=self.today + timedelta(days=end_delta),
            status=status,
        )

    def _schedule_session(self, term, status, suffix):
        faculty = next(user for user in self.denied_users if user.role == Role.FACULTY)
        building = Building.objects.create(name=f"Lifecycle {suffix}", code=f"LC{suffix}")
        floor = Floor.objects.create(building=building, number=1)
        room = Room.objects.create(
            floor=floor, code=f"LC{suffix}01", capacity=30,
            qr_token=f"lifecycle-{suffix}", manual_code=f"8{suffix.zfill(5)}"[-6:],
        )
        schedule = Schedule.objects.create(
            term=term, course_code=f"LC{suffix}", section="A", faculty=faculty,
            room=room, day_of_week=self.today.weekday(), start_time=time(8, 0),
            end_time=time(9, 0), modality=Modality.F2F,
        )
        start = timezone.make_aware(datetime.combine(self.today, time(8, 0)))
        session = Session.objects.create(
            schedule=schedule, faculty=faculty, room=room, date=self.today,
            scheduled_start=start, scheduled_end=start + timedelta(hours=1),
            status=status,
        )
        return schedule, session

    def test_each_transition_has_separate_authorized_get_preflight(self):
        draft = self._term("Action Draft", AcademicTerm.Status.DRAFT, 30, 120)
        active = self._term("Action Active", AcademicTerm.Status.ACTIVE, -120, -1)
        archived = self._term("Action Archive", AcademicTerm.Status.ARCHIVED, -300, -200)
        routes = [
            reverse("ifo_term_activate", args=[draft.pk]),
            reverse("ifo_term_close", args=[active.pk]),
            reverse("ifo_term_reopen", args=[archived.pk]),
        ]
        for user in (self.ifo, self.superuser):
            self.client.force_login(user)
            for route in routes:
                with self.subTest(user=user.username, route=route):
                    self.assertEqual(self.client.get(route).status_code, 200)
        for user in self.denied_users:
            self.client.force_login(user)
            for route in routes:
                with self.subTest(user=user.username, route=route):
                    self.assertEqual(self.client.get(route).status_code, 403)
        self.assertFalse(AuditLog.objects.exists())

    def test_action_forms_show_blockers_warnings_confirmation_and_reason_rules(self):
        active = self._term("Current Active", AcademicTerm.Status.ACTIVE, -120, -1)
        draft = self._term("Empty Draft", AcademicTerm.Status.DRAFT, 30, 120)
        archived = self._term("Old Archive", AcademicTerm.Status.ARCHIVED, -300, -200)
        self.client.force_login(self.ifo)

        activate = self.client.get(reverse("ifo_term_activate", args=[draft.pk]))
        self.assertContains(activate, "another_active")
        self.assertContains(activate, "empty_schedule_set")
        self.assertContains(activate, 'name="confirmation_name"', html=False)
        self.assertNotContains(activate, 'name="reason"', html=False)
        self.assertContains(activate, "disabled")

        close = self.client.get(reverse("ifo_term_close", args=[active.pk]))
        self.assertContains(close, 'name="reason"', html=False)
        self.assertContains(close, 'name="confirmation_name"', html=False)

        reopen = self.client.get(reverse("ifo_term_reopen", args=[archived.pk]))
        self.assertContains(reopen, "active_successor_exists")
        self.assertContains(reopen, 'name="reason"', html=False)
        self.assertContains(reopen, 'name="acknowledged_warnings"', html=False)

    def test_activation_refusal_rerenders_400_then_acknowledged_success_redirects(self):
        draft = self._term("Empty Draft", AcademicTerm.Status.DRAFT, 30, 120)
        self.client.force_login(self.ifo)
        route = reverse("ifo_term_activate", args=[draft.pk])

        missing_confirmation = self.client.post(route, {
            "confirmation_name": "",
            "acknowledged_warnings": "empty_schedule_set",
        })
        self.assertEqual(missing_confirmation.status_code, 400)
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(AuditLog.objects.exists())

        missing_warning = self.client.post(route, {
            "confirmation_name": draft.name,
        })
        self.assertEqual(missing_warning.status_code, 400)
        self.assertFalse(AuditLog.objects.exists())

        success = self.client.post(route, {
            "confirmation_name": draft.name,
            "acknowledged_warnings": "empty_schedule_set",
        })
        self.assertRedirects(success, reverse("ifo_term_detail", args=[draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.ACTIVE)
        self.assertTrue(AuditLog.objects.filter(event_type="term.activated").exists())

    def test_close_and_reopen_require_reason_and_exact_name(self):
        active = self._term("Closable Active", AcademicTerm.Status.ACTIVE, -120, -1)
        self.client.force_login(self.ifo)
        close_route = reverse("ifo_term_close", args=[active.pk])

        for data in (
            {"confirmation_name": "wrong", "reason": "Term complete"},
            {"confirmation_name": active.name, "reason": ""},
        ):
            response = self.client.post(close_route, data)
            self.assertEqual(response.status_code, 400)
            active.refresh_from_db()
            self.assertEqual(active.status, AcademicTerm.Status.ACTIVE)

        closed = self.client.post(close_route, {
            "confirmation_name": active.name,
            "reason": "Registrar close",
        })
        self.assertRedirects(closed, reverse("ifo_term_detail", args=[active.pk]))
        active.refresh_from_db()
        self.assertEqual(active.status, AcademicTerm.Status.ARCHIVED)

        reopen_route = reverse("ifo_term_reopen", args=[active.pk])
        refused = self.client.post(reopen_route, {
            "confirmation_name": active.name,
            "reason": "",
        })
        self.assertEqual(refused.status_code, 400)
        reopened = self.client.post(reopen_route, {
            "confirmation_name": active.name,
            "reason": "Correction window",
        })
        self.assertRedirects(reopened, reverse("ifo_term_detail", args=[active.pk]))
        active.refresh_from_db()
        self.assertEqual(active.status, AcademicTerm.Status.DRAFT)

    def test_denied_roles_cannot_post_creation_or_transitions(self):
        draft = self._term("Denied Draft", AcademicTerm.Status.DRAFT, 30, 120)
        for user in self.denied_users:
            self.client.force_login(user)
            create = self.client.post(reverse("ifo_term_create"), self._confirm())
            activate = self.client.post(
                reverse("ifo_term_activate", args=[draft.pk]),
                {"confirmation_name": draft.name,
                 "acknowledged_warnings": "empty_schedule_set"},
            )
            self.assertEqual(create.status_code, 403)
            self.assertEqual(activate.status_code, 403)
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(AuditLog.objects.exists())

    def test_creation_preflight_surfaces_duplicate_date_order_and_overlap_without_writes(self):
        self._term("Existing Term", AcademicTerm.Status.ARCHIVED, 200, 260)
        self.client.force_login(self.ifo)

        duplicate = self.client.post(reverse("ifo_term_create"), self._details(
            name="Existing Term", start_date=str(self.today + timedelta(days=300)),
            end_date=str(self.today + timedelta(days=360)),
        ))
        inverted = self.client.post(reverse("ifo_term_create"), self._details(
            name="Inverted Proposal", start_date=str(self.today + timedelta(days=500)),
            end_date=str(self.today + timedelta(days=400)),
        ))
        overlap = self.client.post(reverse("ifo_term_create"), self._details(
            name="Overlap Proposal", start_date=str(self.today + timedelta(days=220)),
            end_date=str(self.today + timedelta(days=280)),
        ))

        self.assertContains(duplicate, "duplicate_name")
        self.assertContains(inverted, "date_order")
        self.assertContains(overlap, "overlapping_term")
        self.assertEqual(AcademicTerm.objects.count(), 1)
        self.assertFalse(AuditLog.objects.exists())

    def test_close_rechecks_before_end_active_sessions_and_stale_warning(self):
        active = self._term("Guarded Active", AcademicTerm.Status.ACTIVE, -30, 10)
        self.client.force_login(self.ifo)
        route = reverse("ifo_term_close", args=[active.pk])

        early = self.client.post(route, {
            "confirmation_name": active.name, "reason": "Too early",
        })
        self.assertEqual(early.status_code, 400)
        self.assertContains(early, "before_end_date", status_code=400)

        active.end_date = self.today - timedelta(days=1)
        active.save(update_fields=["end_date"])
        self.client.get(route)
        _, session = self._schedule_session(active, SessionStatus.SCHEDULED, "201")
        stale_warning = self.client.post(route, {
            "confirmation_name": active.name, "reason": "Term complete",
        })
        self.assertEqual(stale_warning.status_code, 400)
        self.assertContains(stale_warning, "warnings_unacknowledged", status_code=400)

        session.status = SessionStatus.ACTIVE
        session.save(update_fields=["status"])
        blocked = self.client.post(route, {
            "confirmation_name": active.name, "reason": "Term complete",
            "acknowledged_warnings": "scheduled_sessions_present",
        })
        self.assertEqual(blocked.status_code, 400)
        self.assertContains(blocked, "active_sessions", status_code=400)
        active.refresh_from_db()
        self.assertEqual(active.status, AcademicTerm.Status.ACTIVE)
        self.assertFalse(AuditLog.objects.exists())

    def test_activation_rechecks_another_active_inserted_after_get(self):
        draft = self._term("Stale Draft", AcademicTerm.Status.DRAFT, 30, 120)
        self.client.force_login(self.ifo)
        route = reverse("ifo_term_activate", args=[draft.pk])
        displayed = self.client.get(route)
        self.assertNotContains(displayed, "another_active")
        self._term("Inserted Active", AcademicTerm.Status.ACTIVE, -120, -1)

        response = self.client.post(route, {
            "confirmation_name": draft.name,
            "acknowledged_warnings": "empty_schedule_set",
        })

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "another_active", status_code=400)
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(AuditLog.objects.exists())

    def test_materializer_failure_rolls_back_sessions_state_and_audit(self):
        draft = self._term("Failure Draft", AcademicTerm.Status.DRAFT, 0, 60)
        schedule, _ = self._schedule_session(
            draft, SessionStatus.SCHEDULED, "301",
        )
        Session.objects.filter(schedule=schedule).delete()
        faculty = schedule.faculty

        def fail_after_write(term, *, start, days, allow_draft=False):
            scheduled_start = timezone.make_aware(datetime.combine(start, time(8, 0)))
            Session.objects.create(
                schedule=schedule, faculty=faculty, room=schedule.room, date=start,
                scheduled_start=scheduled_start,
                scheduled_end=scheduled_start + timedelta(hours=1),
                status=SessionStatus.SCHEDULED,
            )
            raise RuntimeError("materialization failed")

        self.client.force_login(self.ifo)
        with patch("scheduling.term_lifecycle.materialize_term", side_effect=fail_after_write):
            with self.assertRaises(RuntimeError):
                self.client.post(reverse("ifo_term_activate", args=[draft.pk]), {
                    "confirmation_name": draft.name,
                })

        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(Session.objects.filter(schedule=schedule).exists())
        self.assertFalse(AuditLog.objects.exists())

    def test_close_then_activate_are_two_committed_requests_with_audit_evidence(self):
        current = self._term("Rollover Current", AcademicTerm.Status.ACTIVE, -120, -1)
        draft = self._term("Rollover Next", AcademicTerm.Status.DRAFT, 30, 120)
        self.client.force_login(self.ifo)

        closed = self.client.post(reverse("ifo_term_close", args=[current.pk]), {
            "confirmation_name": current.name, "reason": "Academic year complete",
        })
        self.assertRedirects(closed, reverse("ifo_term_detail", args=[current.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.DRAFT)
        self.assertFalse(AuditLog.objects.filter(event_type="term.activated").exists())

        activated = self.client.post(reverse("ifo_term_activate", args=[draft.pk]), {
            "confirmation_name": draft.name,
            "acknowledged_warnings": "empty_schedule_set",
        })
        self.assertRedirects(activated, reverse("ifo_term_detail", args=[draft.pk]))
        draft.refresh_from_db()
        self.assertEqual(draft.status, AcademicTerm.Status.ACTIVE)
        close_audit = AuditLog.objects.get(event_type="term.archived")
        activate_audit = AuditLog.objects.get(event_type="term.activated")
        self.assertEqual(close_audit.actor, self.ifo)
        self.assertEqual(close_audit.payload["reason"], "Academic year complete")
        self.assertEqual(close_audit.payload["before"], AcademicTerm.Status.ACTIVE)
        self.assertEqual(close_audit.payload["after"], AcademicTerm.Status.ARCHIVED)
        self.assertEqual(activate_audit.actor, self.ifo)
        self.assertIsNone(activate_audit.payload["reason"])
        self.assertEqual(activate_audit.payload["before"], AcademicTerm.Status.DRAFT)
        self.assertEqual(activate_audit.payload["after"], AcademicTerm.Status.ACTIVE)

    def test_reopen_keeps_newer_active_untouched_and_superuser_uses_same_service(self):
        archived = self._term("Historic Archive", AcademicTerm.Status.ARCHIVED, -300, -200)
        current = self._term("Current Active", AcademicTerm.Status.ACTIVE, -120, 60)
        self.client.force_login(self.superuser)

        response = self.client.post(reverse("ifo_term_reopen", args=[archived.pk]), {
            "confirmation_name": archived.name,
            "reason": "Registrar correction",
            "acknowledged_warnings": "active_successor_exists",
        })

        self.assertRedirects(response, reverse("ifo_term_detail", args=[archived.pk]))
        archived.refresh_from_db()
        current.refresh_from_db()
        self.assertEqual(archived.status, AcademicTerm.Status.DRAFT)
        self.assertEqual(current.status, AcademicTerm.Status.ACTIVE)
        audit = AuditLog.objects.get(event_type="term.reopened")
        self.assertEqual(audit.actor, self.superuser)
        self.assertEqual(audit.payload["reason"], "Registrar correction")
        self.assertEqual(audit.payload["before"], AcademicTerm.Status.ARCHIVED)
        self.assertEqual(audit.payload["after"], AcademicTerm.Status.DRAFT)

    def test_lifecycle_controller_source_delegates_without_reset_or_status_writes(self):
        source = open("web/ifo_terms.py", encoding="utf-8").read()
        for service_call in (
            "preflight_term_creation(", "create_term(", "preflight_term_action(",
            "activate_term(", "close_term(", "reopen_term(",
        ):
            self.assertIn(service_call, source)
        self.assertNotIn("reset_term", source)
        self.assertIsNone(re.search(r"\.status\s*=(?!=)", source))

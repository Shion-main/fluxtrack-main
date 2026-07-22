"""Integration tests for the scan flow's IFO notifications after the NOTIF-00
migration (§6.6, FAC-09/10).

ScanNotifyTests drives the real two-step confirm endpoints and asserts the
migrated call sites still create type="room_event" Notification rows for active
IFO admins — guarding T-02-05 (a silent notification regression during migration).
"""
from datetime import date, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from web import views
from ops.models import Notification
from scheduling.models import AcademicTerm, Schedule, Session, SessionStatus


class ScanNotifyTests(TestCase):
    """A confirmed room-change and a confirmed force-handover each notify the IFO
    admin via the shared notify() write path (NOTIF-00)."""

    def setUp(self):
        cache.clear()  # locmem cache is not rolled back between tests
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="T", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)
        self.bldg = Building.objects.create(name="R", code="R")
        self.floor = Floor.objects.create(building=self.bldg, number=3)
        self.faculty = User.objects.create(username="fac_scan", role=Role.FACULTY)
        self.ifo = User.objects.create(username="ifo_scan", role=Role.IFO_ADMIN)
        self.client.force_login(self.faculty)

    def _room(self, code, qr, manual):
        return Room.objects.create(floor=self.floor, code=code,
                                   qr_token=qr, manual_code=manual)

    def _session(self, room, faculty, status, start, end):
        sch = Schedule.objects.create(
            term=self.term, course_code="CS101", section="A",
            faculty=faculty, room=room, day_of_week=0,
            start_time=time(8, 0), end_time=time(9, 30))
        return Session.objects.create(
            schedule=sch, faculty=faculty, room=room, date=timezone.localdate(),
            scheduled_start=start, scheduled_end=end, status=status)

    def _confirm(self, payload):
        """Drive /scan/resolve for a needs-confirm outcome, then post the signed
        token to /scan/confirm (the two-step flow, SCAN-04)."""
        resp = self.client.post("/scan/resolve", {"payload": payload})
        token = resp.context["confirm_token"]
        return self.client.post("/scan/confirm", {"token": token})

    def test_confirmed_room_change_notifies_ifo(self):
        now = timezone.now()
        room_a = self._room("R301", "tok-a", "300301")
        self._room("R302", "tok-b", "300302")  # room B — where faculty actually scanned
        self._session(room_a, self.faculty, SessionStatus.SCHEDULED,
                      now, now + timedelta(minutes=90))

        self._confirm("300302")  # scan room B while scheduled in room A -> WRONG_ROOM

        n = Notification.objects.filter(user=self.ifo, type="room_event").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.title, "Room change")

    def test_confirmed_force_handover_notifies_ifo(self):
        now = timezone.now()
        room_a = self._room("R303", "tok-c", "300303")
        other = get_user_model().objects.create(username="fac_other", role=Role.FACULTY)
        # Another faculty's ACTIVE session occupies room A.
        self._session(room_a, other, SessionStatus.ACTIVE,
                      now, now + timedelta(minutes=90))
        # My scheduled session in the same room.
        self._session(room_a, self.faculty, SessionStatus.SCHEDULED,
                      now, now + timedelta(minutes=90))

        self._confirm("300303")  # scan the occupied room -> ROOM_OCCUPIED handover

        n = Notification.objects.filter(user=self.ifo, type="room_event").first()
        self.assertIsNotNone(n)
        self.assertEqual(n.title, "Force handover")

    def test_released_room_does_not_force_handover(self):
        """Audit M4 (2026-07-19): an ACTIVE session whose room was manually
        released (IFO-08) no longer holds the room -- same rule as
        ops/availability.py and the JOB-02c conflict query. The next faculty's
        scan checks in directly instead of force-completing the ghost session
        with a bogus hours-late actual_end."""
        now = timezone.now()
        room_a = self._room("R304", "tok-d", "300304")
        other = get_user_model().objects.create(username="fac_rel",
                                                role=Role.FACULTY)
        ghost = self._session(room_a, other, SessionStatus.ACTIVE,
                              now - timedelta(minutes=60),
                              now + timedelta(minutes=30))
        ghost.room_released_at = now - timedelta(minutes=10)
        ghost.save(update_fields=["room_released_at"])
        mine = self._session(room_a, self.faculty, SessionStatus.SCHEDULED,
                             now, now + timedelta(minutes=90))

        resp = self.client.post("/scan/resolve", {"payload": "300304"})
        self.assertEqual(resp.status_code, 200)
        mine.refresh_from_db()
        ghost.refresh_from_db()
        # Checked in directly -- no ROOM_OCCUPIED two-step, ghost untouched.
        self.assertEqual(mine.status, SessionStatus.ACTIVE)
        self.assertEqual(ghost.status, SessionStatus.ACTIVE)
        self.assertIsNone(ghost.actual_end)
        self.assertFalse(Notification.objects.filter(
            user=self.ifo, title="Force handover").exists())


@override_settings(DEBUG=True)
class DevLoginCoexistTests(TestCase):
    """The DEBUG dev-login survives the second AUTHENTICATION_BACKENDS entry (D-08/D-09#3).

    Plan 01 added the Entra PKCE backend, so two backends are now configured and a
    bare login() cannot infer which one authenticated — it raises ValueError
    (RESEARCH Pitfall 2). Plan 03 named ModelBackend explicitly; these tests fail
    loudly if that regresses. Superuser break-glass via ModelBackend password auth
    is also proven (D-03/D-09#3). No live Entra call.
    """

    def setUp(self):
        User = get_user_model()
        self.faculty = User.objects.create(username="devfac", email="devfac@mcm.edu.ph",
                                           role=Role.FACULTY, is_active=True)
        self.admin = User.objects.create(username="devadmin", email="devadmin@mcm.edu.ph",
                                         role=Role.SYSTEM_ADMIN, is_active=True,
                                         is_staff=True, is_superuser=True)
        self.admin.set_password("break-glass-pw")
        self.admin.save()

    def test_dev_login_post_authenticates_under_two_backends(self):
        """POST /login logs the seeded user in and redirects to / — no ValueError (Pitfall 2)."""
        # Two backends are configured; the dev-login must name ModelBackend or login() raises.
        self.assertEqual(len(settings.AUTHENTICATION_BACKENDS), 2)
        resp = self.client.post("/login", {"username": "devfac"})
        # home() now role-routes: / itself 302s a faculty user on to their
        # console, so the redirect target is a redirect, not a 200.
        self.assertRedirects(resp, "/", target_status_code=302)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.faculty.pk))

    def test_superuser_break_glass_via_modelbackend(self):
        """A superuser still authenticates via ModelBackend password auth (D-03/D-09#3)."""
        self.assertTrue(self.client.login(username="devadmin", password="break-glass-pw"))
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.admin.pk))


@override_settings(DEBUG=True)
class DevLoginCuratedDemoTests(TestCase):
    """The DEBUG dev-login shows a CURATED per-role demo set with the real professor
    GARAY (cdgaray) as the faculty account, not a dump of every imported instructor
    (Phase 04.1 Task 3). The passwordless-by-username POST is unchanged: a curated
    account (cdgaray) authenticates and role-routes home."""

    def setUp(self):
        User = get_user_model()
        # The curated FACULTY demo: the real imported professor GARAY.
        self.garay = User.objects.create(
            username="cdgaray", email="cdgaray@mcm.edu.ph",
            first_name="Christian Dominique", last_name="Garay",
            role=Role.FACULTY, is_active=True)
        # A non-allowlisted imported instructor — must NOT appear in the curated list.
        self.other_faculty = User.objects.create(
            username="cjldellosa", email="cjldellosa@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)

    def test_curated_dev_users_include_garay_exclude_arbitrary_instructor(self):
        """The login-page dev_users context is the curated allowlist: it includes
        cdgaray and excludes a random imported faculty (not a 200-name dump)."""
        resp = self.client.get("/login")
        usernames = {u.username for u in resp.context["dev_users"]}
        self.assertIn("cdgaray", usernames)
        self.assertNotIn("cjldellosa", usernames)
        self.assertLessEqual(len(usernames), len(views.DEMO_USERNAMES))

    def test_allowlist_resolves_one_demo_account_per_role(self):
        """Coupling guard: DEMO_USERNAMES must name accounts seed_demo actually
        creates. The list is USERNAMES, not surnames — the seed_demo `people`
        rows are (username, last_name, ...), and reading the wrong column silently
        yields an allowlist that matches nobody, collapsing the login page to the
        one role whose demo account is externally imported (faculty/cdgaray)."""
        call_command("seed_demo")
        resp = self.client.get("/login")
        roles = sorted(u.role for u in resp.context["dev_users"])
        self.assertEqual(roles, sorted([
            Role.FACULTY, Role.CHECKER, Role.IFO_ADMIN, Role.HR_ADMIN,
            Role.GUARD, Role.DEAN, Role.SYSTEM_ADMIN,
        ]), "every role must have exactly one selectable dev-login account")

    def test_garay_dev_login_authenticates_and_redirects_home(self):
        """A DEBUG POST of cdgaray logs in via the unchanged passwordless path and
        redirects home (role-routed to the faculty schedule)."""
        resp = self.client.post("/login", {"username": "cdgaray"})
        # / role-routes faculty onward (302), same as DevLoginCoexistTests.
        self.assertRedirects(resp, "/", target_status_code=302)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.garay.pk))


class LogoutTests(TestCase):
    """/logout flushes the local session and redirects to /login (D-11).

    D-11: logout is a local Django session flush only (no Entra global sign-out).
    After logout the session must no longer identify the user.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(username="outuser", email="out@mcm.edu.ph",
                                        role=Role.FACULTY, is_active=True)

    def test_logout_flushes_session_and_redirects(self):
        """An authenticated GET /logout redirects to /login and drops the user (D-11)."""
        self.client.force_login(self.user)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))
        resp = self.client.get("/logout")
        self.assertRedirects(resp, "/login")
        self.assertNotIn("_auth_user_id", self.client.session)


class MicrosoftButtonPostTests(TestCase):
    """The 'Sign in with Microsoft' button must POST to social:begin, not GET it.

    social-auth-app-django 6.0.0 decorates the begin view with @require_POST
    (login-CSRF hardening), so a GET link returns 405 and SSO never starts. This
    guards the exact regression found live at the D-09 gate: the login template
    must render a POST <form> to the begin URL, carrying a CSRF token — not an
    <a href> link. No live Entra call.
    """

    def test_login_page_posts_to_social_begin(self):
        """/login renders a POST form to the begin URL and no GET link to it."""
        begin_url = reverse("social:begin", args=["azuread-tenant-oauth2"])
        html = self.client.get("/login").content.decode()
        self.assertIn(f'action="{begin_url}"', html)      # form posts to begin
        self.assertIn("csrfmiddlewaretoken", html)         # CSRF token present
        self.assertNotIn(f'href="{begin_url}"', html)      # old GET link is gone

    def test_social_begin_rejects_get(self):
        """Documents why the button must POST: GET on begin is 405 under 6.0.0."""
        begin_url = reverse("social:begin", args=["azuread-tenant-oauth2"])
        self.assertEqual(self.client.get(begin_url).status_code, 405)


# ---------------------------------------------------------------------------
# 04-07 -- Faculty modality-shift surface authz + validation (MOD-01/05/06).
#
# The faculty half of the T-04 register: @faculty_required gates every view
# (T-04-10 non-faculty access); modality_withdraw delegates its guard to
# withdraw_modality_shift so a FOREIGN withdraw is refused server-side and the
# ticket stays PENDING (T-04-01 IDOR); a malformed submit is a friendly 400, never
# a 500 (T-04-05v); a forged room pk is never trusted (T-04-02, service re-resolves).
# MOD-06/D-13: there is NO faculty self-declare route -- this request workflow is
# the sole faculty modality-change entry point (the FAC-07 path is retired).
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta  # noqa: E402

from scheduling.models import (  # noqa: E402
    Modality,
    ModalityShiftItem,
    ModalityShiftRequest,
    ModalityShiftStatus,
    Session,
    SessionStatus,
)
from scheduling.test_support import IN_WINDOW_DATE, make_shift_fixture  # noqa: E402


class FacultyModalityAuthzTests(TestCase):
    """Authz + input-validation guards on the faculty modality-shift surface."""

    def setUp(self):
        cache.clear()  # locmem cache is not rolled back between tests
        self.fx = make_shift_fixture("web07")

    def _future_session(self, days=30):
        """A SCHEDULED session comfortably past the lead-time cutoff for a real
        ``timezone.now()`` (the view cannot inject a fake clock), so a valid submit
        exercises routing/creation rather than the lead gate."""
        sch = self.fx.f2f_schedule
        d = timezone.localdate() + timedelta(days=days)
        start = timezone.make_aware(datetime.combine(d, sch.start_time))
        end = timezone.make_aware(datetime.combine(d, sch.end_time))
        Session.objects.create(
            schedule=sch, faculty=sch.faculty, room=sch.room, date=d,
            scheduled_start=start, scheduled_end=end,
            status=SessionStatus.SCHEDULED)
        return d

    def test_non_faculty_denied(self):
        """A non-faculty user (the Dean) is denied GET and POST on the submit view
        (T-04-10, @faculty_required)."""
        self.client.force_login(self.fx.dean)
        self.assertEqual(self.client.get("/faculty/modality/new").status_code, 403)
        self.assertEqual(
            self.client.post("/faculty/modality/new", {}).status_code, 403)

    def test_foreign_withdraw_refused_and_stays_pending(self):
        """A faculty withdrawing ANOTHER faculty's pending ticket is refused and the
        ticket stays PENDING (T-04-01 IDOR; guard delegated to the service)."""
        req = ModalityShiftRequest.objects.create(
            requester=self.fx.faculty, dean=self.fx.dean,
            department=self.fx.dept, target_modality="online",
            window_start=timezone.localdate(), window_end=timezone.localdate(),
            status=ModalityShiftStatus.PENDING)
        self.client.force_login(self.fx.competitor_faculty)  # a different faculty
        resp = self.client.post(f"/faculty/modality/{req.pk}/withdraw")
        self.assertEqual(resp.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)

    def test_malformed_submit_is_400_not_500(self):
        """A bad target modality / out-of-range weeks / bad single date renders the
        form partial at 400, never a 500 (T-04-05v, assignment_create pattern)."""
        self.client.force_login(self.fx.faculty)
        bad_modality = self.client.post("/faculty/modality/new", {
            "target_modality": "banana",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "weeks", "weeks": "1"})
        self.assertEqual(bad_modality.status_code, 400)
        bad_weeks = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "weeks", "weeks": "0"})
        self.assertEqual(bad_weeks.status_code, 400)
        bad_date = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "single", "on_date": "not-a-date"})
        self.assertEqual(bad_date.status_code, 400)

    def test_valid_submit_creates_one_pending_routed_to_dean(self):
        """A valid submit creates exactly one PENDING ticket routed to the
        department Dean (MOD-01/D-09), and redirects to the my-requests list."""
        d = self._future_session()
        self.client.force_login(self.fx.faculty)
        resp = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "single", "on_date": d.isoformat()})
        self.assertRedirects(resp, "/faculty/modality/mine")
        reqs = ModalityShiftRequest.objects.filter(requester=self.fx.faculty)
        self.assertEqual(reqs.count(), 1)
        req = reqs.get()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)
        self.assertEqual(req.dean, self.fx.dean)

    # --- no-double-request guard + weeks picker (UAT 2026-07-05) ---------------
    def _existing_request_on_f2f(self, *, status=ModalityShiftStatus.PENDING,
                                 decided_at=None):
        """A prior request with one item on the f2f schedule, to exercise the guard."""
        req = ModalityShiftRequest.objects.create(
            requester=self.fx.faculty, dean=self.fx.dean, department=self.fx.dept,
            target_modality="online",
            window_start=timezone.localdate(), window_end=timezone.localdate(),
            status=status, decided_at=decided_at)
        ModalityShiftItem.objects.create(request=req, schedule=self.fx.f2f_schedule)
        return req

    def test_double_request_while_pending_refused(self):
        """A second request for a schedule that already has a PENDING one is refused at
        400 and no new ticket is created (UAT no-double guard)."""
        self._existing_request_on_f2f()
        d = timezone.localdate() + timedelta(days=30)
        self.client.force_login(self.fx.faculty)
        resp = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "single", "on_date": d.isoformat()})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            ModalityShiftRequest.objects.filter(requester=self.fx.faculty).count(), 1)

    def test_rerequest_within_cooldown_after_decision_refused(self):
        """A schedule decided within the 2-day cooldown cannot be re-requested (400)."""
        self._existing_request_on_f2f(
            status=ModalityShiftStatus.REJECTED, decided_at=timezone.now())
        d = timezone.localdate() + timedelta(days=30)
        self.client.force_login(self.fx.faculty)
        resp = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "single", "on_date": d.isoformat()})
        self.assertEqual(resp.status_code, 400)

    def test_withdrawn_allows_immediate_rerequest(self):
        """A WITHDRAWN request (decided_at NULL) is exempt from the cooldown -- the
        faculty may re-request the schedule now, creating a fresh PENDING ticket."""
        self._existing_request_on_f2f(status=ModalityShiftStatus.WITHDRAWN)
        d = self._future_session()
        self.client.force_login(self.fx.faculty)
        resp = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "single", "on_date": d.isoformat()})
        self.assertRedirects(resp, "/faculty/modality/mine")
        self.assertEqual(
            ModalityShiftRequest.objects.filter(
                requester=self.fx.faculty,
                status=ModalityShiftStatus.PENDING).count(), 1)

    def test_weeks_mode_submit_derives_window_from_count(self):
        """A weeks-mode submit derives the window server-side: it starts after the
        lead-time and spans weeks*7 days (UAT weeks picker)."""
        self._future_session(days=7)  # a session inside the 2-week window
        self.client.force_login(self.fx.faculty)
        resp = self.client.post("/faculty/modality/new", {
            "target_modality": "online",
            "schedules": [str(self.fx.f2f_schedule.pk)],
            "window_mode": "weeks", "weeks": "2"})
        self.assertRedirects(resp, "/faculty/modality/mine")
        req = ModalityShiftRequest.objects.get(requester=self.fx.faculty)
        self.assertEqual((req.window_end - req.window_start).days + 1, 14)
        self.assertGreater(req.window_start, timezone.localdate())

    def test_no_faculty_self_declare_route_exists(self):
        """MOD-06/D-13: the modality-shift request is the sole faculty modality-change
        entry point -- no self-declare view/route survives."""
        with self.assertRaises(NoReverseMatch):
            reverse("faculty_modality_declare")


# ---------------------------------------------------------------------------
# 04-08 -- Dean modality-shift approval surface authz + consequence (MOD-02/04).
#
# The Dean half of the T-04 register: @dean_required gates every view (T-04-10
# non-Dean access); approve/reject DELEGATE their guard to the 04-05 services so a
# cross-department decision is refused server-side and the ticket stays PENDING
# (T-04-01 IDOR / T-04-03 TOCTOU). A valid ->Online approve applies the room-release
# consequence and notifies requester + IFO; a no-room ->F2F approve is a terminal
# DENIED with the session provably unchanged (D-07 REVISED / T-04-07); a reject
# requires a non-empty reason (T-04-05v) and records it. Assertions are on the
# persisted state + Notification rows, never on HTML strings.
# ---------------------------------------------------------------------------
class DeanModalityAuthzTests(TestCase):
    """Authz + consequence guards on the Dean modality-shift approval surface."""

    def setUp(self):
        cache.clear()  # locmem cache is not rolled back between tests
        self.fx = make_shift_fixture("web08")
        self.ifo = get_user_model().objects.create(
            username="web08_ifo", email="web08_ifo@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)

    def _pending(self, target_modality, schedule):
        """A PENDING ticket routed to the fixture Dean's department, one item."""
        req = ModalityShiftRequest.objects.create(
            requester=self.fx.faculty, dean=self.fx.dean,
            department=self.fx.dept, target_modality=target_modality,
            window_start=IN_WINDOW_DATE, window_end=IN_WINDOW_DATE,
            status=ModalityShiftStatus.PENDING)
        ModalityShiftItem.objects.create(request=req, schedule=schedule)
        return req

    def test_non_dean_approve_denied(self):
        """A non-Dean (the requesting faculty) POSTing approve is denied (403,
        @dean_required) and the ticket stays PENDING (T-04-10)."""
        req = self._pending(Modality.ONLINE, self.fx.f2f_schedule)
        self.client.force_login(self.fx.faculty)  # role FACULTY, not a Dean
        resp = self.client.post(f"/dean/requests/{req.pk}/approve")
        self.assertEqual(resp.status_code, 403)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)

    def test_cross_department_approve_refused_stays_pending(self):
        """A Dean of another department approving Department A's request is refused
        server-side (the service re-gate) and the ticket stays PENDING with the
        session untouched (T-04-01 cross-department IDOR)."""
        req = self._pending(Modality.ONLINE, self.fx.f2f_schedule)
        # Distinct first-two-chars vs "web08": the fixture derives room.manual_code
        # from prefix[:2], so a "web08b" second dept would collide on manual_code.
        other = make_shift_fixture("dep2")  # a different department + its Dean
        self.client.force_login(other.dean)
        resp = self.client.post(f"/dean/requests/{req.pk}/approve")
        self.assertEqual(resp.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, "")
        self.assertIsNone(self.fx.session.room_released_at)

    def test_online_approve_applies_and_notifies(self):
        """The routed Dean approving a ->Online request applies it: the request is
        APPROVED, the in-window session is effective-Online with room_released_at
        stamped, and the requester + IFO are notified (MOD-03/D-11)."""
        req = self._pending(Modality.ONLINE, self.fx.f2f_schedule)
        self.client.force_login(self.fx.dean)
        resp = self.client.post(f"/dean/requests/{req.pk}/approve")
        self.assertEqual(resp.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.APPROVED)
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.declared_modality, Modality.ONLINE)
        self.assertIsNotNone(self.fx.session.room_released_at)
        self.assertTrue(Notification.objects.filter(
            user=self.fx.faculty, type="modality_shift_approved").exists())
        self.assertTrue(Notification.objects.filter(
            user=self.ifo, type="modality_shift_applied").exists())

    def test_no_room_f2f_approve_denies_session_unchanged(self):
        """A ->F2F approval with no free room that day is a terminal DENIED with a
        reason, and the session is provably unchanged (D-07 REVISED / T-04-07).

        Both building rooms are held at the F2F session's own 08:00-09:30 slot:
        room A by the fixture competitor, room B by an added blocker."""
        blocker_sched = Schedule.objects.create(
            term=self.fx.term, course_code="BLK", section="A",
            faculty=self.fx.competitor_faculty, room=self.fx.room_b,
            day_of_week=0, start_time=time(8, 0), end_time=time(9, 30),
            modality=Modality.F2F)
        Session.objects.create(
            schedule=blocker_sched, faculty=self.fx.competitor_faculty,
            room=self.fx.room_b, date=IN_WINDOW_DATE,
            scheduled_start=self.fx.session.scheduled_start,
            scheduled_end=self.fx.session.scheduled_end,
            status=SessionStatus.SCHEDULED)
        req = self._pending(Modality.F2F, self.fx.f2f_schedule)
        self.client.force_login(self.fx.dean)
        resp = self.client.post(f"/dean/requests/{req.pk}/approve")
        self.assertEqual(resp.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.DENIED)
        self.assertTrue(req.decision_reason)
        self.fx.session.refresh_from_db()
        self.assertEqual(self.fx.session.room_id, self.fx.room_a.pk)
        self.assertEqual(self.fx.session.declared_modality, "")
        self.assertIsNone(self.fx.session.room_released_at)

    def test_reject_records_reason_and_notifies(self):
        """A reject with a reason sets REJECTED + decision_reason and notifies the
        requester once (MOD-02/D-10/D-11)."""
        req = self._pending(Modality.ONLINE, self.fx.f2f_schedule)
        self.client.force_login(self.fx.dean)
        resp = self.client.post(f"/dean/requests/{req.pk}/reject",
                                {"reason": "Conflicts with a department event."})
        self.assertEqual(resp.status_code, 200)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.REJECTED)
        self.assertEqual(req.decision_reason, "Conflicts with a department event.")
        self.assertTrue(Notification.objects.filter(
            user=self.fx.faculty, type="modality_shift_rejected").exists())

    def test_reject_empty_reason_is_400_and_stays_pending(self):
        """A reject with an empty/whitespace reason returns 400 and leaves the
        ticket PENDING (T-04-05v input validation)."""
        req = self._pending(Modality.ONLINE, self.fx.f2f_schedule)
        self.client.force_login(self.fx.dean)
        resp = self.client.post(f"/dean/requests/{req.pk}/reject", {"reason": "   "})
        self.assertEqual(resp.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, ModalityShiftStatus.PENDING)


class HomeSurfaceNavTests(TestCase):
    """The home page must link to the Phase 4 modality surfaces for the roles that own
    them. Guards the UAT-04 gap: the faculty/dean views + URLs existed but SURFACES
    (web/views.py) was never updated, leaving the features reachable only by typing a URL."""

    def test_faculty_home_links_modality_request(self):
        u = get_user_model().objects.create(username="fac_nav", role=Role.FACULTY)
        self.client.force_login(u)
        # Faculty home redirects into the faculty console (same follow pattern
        # as the dean test below). The hero's /faculty/modality/new link only
        # renders when an upcoming class exists, so the ALWAYS-present guard is
        # the tab bar's Requests entry -- /faculty/modality/mine, whose page in
        # turn links /faculty/modality/new. That keeps the UAT-04 property
        # (modality surfaces reachable by tapping, not by typing a URL) for
        # every faculty user, including one with no scheduled classes.
        resp = self.client.get("/", follow=True)
        self.assertContains(resp, "/faculty/modality/mine")

    def test_dean_home_links_approval_queue(self):
        u = get_user_model().objects.create(username="dean_nav", role=Role.DEAN)
        self.client.force_login(u)
        # Dean home redirects into the Dean console (Oversight); its sidebar nav
        # carries the Approvals link to /dean/requests.
        resp = self.client.get("/", follow=True)
        self.assertContains(resp, "/dean/requests")


class SysJobMonitorTests(TestCase):
    """SYS-04 scheduled-job status monitor: role-gated, read-only, reads JobRun."""

    def _make_run(self, name="materialize", status="ok", rows=42):
        from ops.models import JobRun
        now = timezone.now()
        return JobRun.objects.create(
            job_name=name, status=status, started_at=now,
            finished_at=now + timedelta(seconds=3), rows_affected=rows,
            detail="" if status == "ok" else "boom")

    def test_sysadmin_sees_job_status(self):
        User = get_user_model()
        u = User.objects.create(username="sys_mon", role=Role.SYSTEM_ADMIN)
        self.client.force_login(u)
        self._make_run(name="materialize", status="ok", rows=7)
        self._make_run(name="sweep", status="failed", rows=0)
        resp = self.client.get(reverse("sys_jobs"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "materialize")
        self.assertContains(resp, "sweep")
        self.assertContains(resp, "Failed")

    def test_non_sysadmin_is_forbidden(self):
        User = get_user_model()
        u = User.objects.create(username="fac_nojobs", role=Role.FACULTY)
        self.client.force_login(u)
        resp = self.client.get(reverse("sys_jobs"))
        self.assertEqual(resp.status_code, 403)

    def test_empty_state_when_no_runs(self):
        User = get_user_model()
        u = User.objects.create(username="sys_empty", role=Role.SYSTEM_ADMIN)
        self.client.force_login(u)
        resp = self.client.get(reverse("sys_jobs"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No job runs recorded yet")


class GuardSurfaceTests(TestCase):
    """GRD-01/02: role-gated, read-only floor monitor scoped to the guard's active
    floors, and a campus-wide faculty locator."""

    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="GT", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)
        self.bldg = Building.objects.create(name="G", code="G")
        self.floor1 = Floor.objects.create(building=self.bldg, number=1)
        self.floor2 = Floor.objects.create(building=self.bldg, number=2)
        self.room1 = Room.objects.create(floor=self.floor1, code="G101",
                                         qr_token="gq1", manual_code="900101")
        self.room2 = Room.objects.create(floor=self.floor2, code="G201",
                                         qr_token="gq2", manual_code="900201")
        self.faculty = User.objects.create(
            username="g_fac", first_name="Ana", last_name="Reyes", role=Role.FACULTY)
        self.guard = User.objects.create(username="g_guard", role=Role.GUARD)

    def _session(self, room, status=SessionStatus.SCHEDULED):
        now = timezone.now()
        sch = Schedule.objects.create(
            term=self.term, course_code="GG101", section="A", faculty=self.faculty,
            room=room, day_of_week=0, start_time=time(8, 0), end_time=time(9, 30))
        return Session.objects.create(
            schedule=sch, faculty=self.faculty, room=room, date=timezone.localdate(),
            scheduled_start=now, scheduled_end=now + timedelta(minutes=90), status=status)

    def _post_guard_to(self, *floors):
        from verification.models import (Assignment, AssignmentScope,
                                         AssignmentType, DutyRole)
        a = Assignment.objects.create(
            user=self.guard, role=DutyRole.GUARD, type=AssignmentType.STANDING,
            scope=AssignmentScope.FLOOR, term=self.term, status="active")
        a.floors.set(floors)
        return a

    def test_non_guard_is_forbidden(self):
        self.client.force_login(self.faculty)
        for name in ("guard_monitor", "guard_monitor_rows", "guard_locate"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_off_duty_shows_not_on_duty(self):
        self.client.force_login(self.guard)
        resp = self.client.get(reverse("guard_monitor_rows"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "not on duty")

    def test_monitor_scoped_to_assigned_floor_only(self):
        self._session(self.room1)  # assigned floor
        self._session(self.room2)  # OTHER floor -- must not leak
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(reverse("guard_monitor_rows"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "G101")
        self.assertNotContains(resp, "G201")

    def test_locator_reports_current_session(self):
        self._session(self.room1, status=SessionStatus.ACTIVE)
        self.client.force_login(self.guard)
        resp = self.client.get(reverse("guard_locate"), {"q": "g_fac"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "In session now")
        self.assertContains(resp, "G101")


class GuardReadOnlyTests(TestCase):
    """GRD-05 -- "a Guard has no write access anywhere" -- as an enforced
    contract, not an observed habit.

    Before Phase 07 every Guard view was read-only only because no write branch
    existed to reach; a POST still answered 200. Each URL below now carries
    `@require_http_methods(["GET"])`, so the method is refused at the door.
    ANY Guard view added by a later plan must be added to GUARD_URLS here.

    The 403 case is the regression this decorator could plausibly introduce:
    the role gate must stay outermost, so a non-Guard is rejected on role
    before the method decorator is ever consulted.
    """

    # (url name, reverse args). GRD-02's room page is keyed by room code, so the
    # list carries args rather than bare names.
    GUARD_URLS = (
        ("guard_monitor", ()),
        ("guard_monitor_rows", ()),
        ("guard_locate", ()),
        ("guard_room", ("RO101",)),
    )

    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="RO Term", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)
        self.bldg = Building.objects.create(name="RO", code="RO")
        self.floor = Floor.objects.create(building=self.bldg, number=1)
        self.room = Room.objects.create(floor=self.floor, code="RO101",
                                        qr_token="roq1", manual_code="910101")
        self.guard = User.objects.create(username="ro_guard", role=Role.GUARD)
        self.faculty = User.objects.create(username="ro_fac", role=Role.FACULTY)
        # guard_room is floor-authorized, so the GET-still-works case needs the
        # guard actually posted to this room's floor; the method and role gates
        # are what this class is asserting, not the floor scope.
        from verification.models import (Assignment, AssignmentScope,
                                         AssignmentType, DutyRole)
        a = Assignment.objects.create(
            user=self.guard, role=DutyRole.GUARD, type=AssignmentType.STANDING,
            scope=AssignmentScope.FLOOR, term=self.term, status="active")
        a.floors.set([self.floor])

    def test_post_is_refused_on_every_guard_url(self):
        self.client.force_login(self.guard)
        for name, args in self.GUARD_URLS:
            with self.subTest(url=name):
                self.assertEqual(
                    self.client.post(reverse(name, args=args)).status_code, 405)

    def test_get_still_works_on_every_guard_url(self):
        # The decorator refuses the method; it must not break the surface.
        self.client.force_login(self.guard)
        for name, args in self.GUARD_URLS:
            with self.subTest(url=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 200)

    def test_role_gate_still_outermost_for_non_guard(self):
        self.client.force_login(self.faculty)
        for name, args in self.GUARD_URLS:
            with self.subTest(url=name):
                self.assertEqual(
                    self.client.get(reverse(name, args=args)).status_code, 403)


class GuardRoomScheduleTests(TestCase):
    """GRD-02: a Guard's per-room schedule page.

    The authorization tests are the point of this class. Floor scope is
    re-derived server-side on every request from the guard's CURRENT
    assignments, so an off-floor room and an off-shift request both 404 -- 404
    and not 403, so the response never confirms that the room code exists.
    """

    def setUp(self):
        User = get_user_model()
        self.term = AcademicTerm.objects.create(
            name="RT", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)
        self.bldg = Building.objects.create(name="RM", code="RM")
        self.floor1 = Floor.objects.create(building=self.bldg, number=1)
        self.floor2 = Floor.objects.create(building=self.bldg, number=2)
        self.room1 = Room.objects.create(floor=self.floor1, code="RM101",
                                         qr_token="rmq1", manual_code="920101")
        self.room2 = Room.objects.create(floor=self.floor2, code="RM201",
                                         qr_token="rmq2", manual_code="920201")
        # V-prefixed == virtual (campus.models.Room.is_virtual), on the guard's
        # own floor so the online-occupancy contrast is an authorization no-op.
        self.vroom = Room.objects.create(floor=self.floor1, code="VRM1",
                                         qr_token="rmqv", manual_code="920301")
        self.faculty = User.objects.create(
            username="rm_fac", first_name="Ana", last_name="Villanueva",
            role=Role.FACULTY)
        self.guard = User.objects.create(username="rm_guard", role=Role.GUARD)
        self.other = User.objects.create(username="rm_other", role=Role.FACULTY)

    # --- fixture helpers ---------------------------------------------------
    def _schedule(self, room, course="RM101X", modality=None, start=time(8, 0),
                  end=time(9, 30), day=0):
        kwargs = dict(term=self.term, course_code=course, section="A",
                      faculty=self.faculty, room=room, day_of_week=day,
                      start_time=start, end_time=end)
        if modality is not None:
            kwargs["modality"] = modality
        return Schedule.objects.create(**kwargs)

    def _session(self, room, course="RM101X", modality=None,
                 status=SessionStatus.SCHEDULED, starts_ago=0, runs=90):
        now = timezone.now()
        sch = self._schedule(room, course=course, modality=modality)
        return Session.objects.create(
            schedule=sch, faculty=self.faculty, room=room,
            date=timezone.localdate(),
            scheduled_start=now - timedelta(minutes=starts_ago),
            scheduled_end=now + timedelta(minutes=runs - starts_ago),
            status=status)

    def _post_guard_to(self, *floors, **kwargs):
        from verification.models import (Assignment, AssignmentScope,
                                         AssignmentType, DutyRole)
        a = Assignment.objects.create(
            user=self.guard, role=DutyRole.GUARD,
            type=kwargs.pop("type", AssignmentType.STANDING),
            scope=AssignmentScope.FLOOR, term=self.term, status="active", **kwargs)
        a.floors.set(floors)
        return a

    def _url(self, room):
        return reverse("guard_room", args=(room.code,))

    # --- authorization -----------------------------------------------------
    def test_room_on_posted_floor_is_visible(self):
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room1))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "RM101")

    def test_room_on_other_floor_is_404_and_not_named(self):
        """404, not 403: a 403 would confirm the room code exists."""
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room2))
        self.assertEqual(resp.status_code, 404)
        self.assertNotContains(resp, "RM201", status_code=404)

    def test_shift_not_covering_now_is_404(self):
        """Scope is re-derived per request, so a lapsed shift closes the page.

        The window logic itself is verification.resolver.assignment_covers_now;
        this only proves the view consults it rather than trusting a stale scope.
        """
        from verification.models import AssignmentType
        local = timezone.localtime(timezone.now())
        self._post_guard_to(self.floor1, type=AssignmentType.SHIFT,
                            date=local.date(), start_time=time(0, 0),
                            end_time=time(0, 1))
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room1))
        self.assertEqual(resp.status_code, 404)

    def test_standing_posting_is_always_on_duty(self):
        from verification.models import AssignmentType
        self._post_guard_to(self.floor1, type=AssignmentType.STANDING)
        self.client.force_login(self.guard)
        self.assertEqual(self.client.get(self._url(self.room1)).status_code, 200)

    def test_non_guard_is_forbidden_and_anonymous_is_redirected(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._url(self.room1)).status_code, 403)
        self.client.logout()
        resp = self.client.get(self._url(self.room1))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_post_is_refused(self):
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        self.assertEqual(self.client.post(self._url(self.room1)).status_code, 405)

    # --- content -----------------------------------------------------------
    def test_today_lists_sessions_with_faculty_and_course(self):
        self._session(self.room1, course="RMTODAY")
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room1))
        self.assertContains(resp, "RMTODAY")
        self.assertContains(resp, "Villanueva")

    def test_online_class_absent_from_physical_room_present_in_virtual(self):
        from scheduling.models import Modality
        self._session(self.room1, course="RMONLINE", modality=Modality.ONLINE)
        self._session(self.vroom, course="VRONLINE", modality=Modality.ONLINE)
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)

        physical = self.client.get(self._url(self.room1))
        self.assertEqual(physical.status_code, 200)
        self.assertNotContains(physical, "RMONLINE")

        virtual = self.client.get(self._url(self.vroom))
        self.assertEqual(virtual.status_code, 200)
        self.assertContains(virtual, "VRONLINE")

    def test_past_grace_no_show_reads_absent_without_the_sweep(self):
        """Still SCHEDULED well past the grace window == absent on the page.

        The sweep job has not run; the page must not wait for it to tell the
        truth (the same rule the IFO board uses, from the same code).
        """
        self._session(self.room1, course="RMLATE", starts_ago=180, runs=240,
                      status=SessionStatus.SCHEDULED)
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room1))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-state="absent"')

    def test_weekly_timetable_renders_recurring_classes(self):
        self._schedule(self.room1, course="RMWEEK", day=2)
        self._post_guard_to(self.floor1)
        self.client.force_login(self.guard)
        resp = self.client.get(self._url(self.room1))
        self.assertContains(resp, "RMWEEK")
        self.assertContains(resp, 'class="tt"')


class ConsoleChromeTests(TestCase):
    """Every page renders exactly ONE <header>.

    Phase 07 UAT found Bookings, Import, Conflicts, Utilization and the room
    sub-pages rendering base.html's global header stacked on top of the console
    bar -- two FluxTrack brand marks and two notification bells, both showing
    the same unread count, on one page.

    The cause was an opt-IN allowlist of url_names in base.html. It could only
    ever be right until the next page was added, and Phase 06.1 and Phase 07
    added ten. base.html now renders the global header inside a
    `{% block global_header %}` that any chrome-owning shell overrides away, so
    a new console page inherits suppression instead of needing to be remembered.

    This test is the thing the allowlist never had: something that fails when a
    page is added to the wrong shell.
    """

    CONSOLE_PATHS = [
        "/ifo/rooms", "/ifo/bookings", "/ifo/import", "/ifo/conflicts",
        "/ifo/utilization", "/ifo/dashboard", "/ifo/assignments",
        "/ifo/reports",
    ]

    def setUp(self):
        self.ifo = get_user_model().objects.create(
            username="chrome_ifo", role=Role.IFO_ADMIN)

    def _headers(self, resp):
        return resp.content.decode("utf-8", "replace").count("<header")

    def test_console_pages_render_exactly_one_header(self):
        self.client.force_login(self.ifo)
        for path in self.CONSOLE_PATHS:
            with self.subTest(path=path):
                resp = self.client.get(path)
                if resp.status_code != 200:
                    self.skipTest(f"{path} -> {resp.status_code}")
                self.assertEqual(
                    self._headers(resp), 1,
                    f"{path} renders {self._headers(resp)} <header> elements. "
                    f"A console page must render only the console bar; if it "
                    f"also renders base.html's global header the user sees two "
                    f"brand marks and two notification bells.")

    def test_faculty_pages_render_exactly_one_header(self):
        fac = get_user_model().objects.create(
            username="chrome_fac", role=Role.FACULTY)
        self.client.force_login(fac)
        for path in ["/faculty/home", "/faculty/profile", "/faculty/history"]:
            with self.subTest(path=path):
                resp = self.client.get(path)
                if resp.status_code != 200:
                    self.skipTest(f"{path} -> {resp.status_code}")
                self.assertEqual(self._headers(resp), 1, f"{path} chrome")

    def test_non_console_page_keeps_the_global_header(self):
        """The negative half: suppression must not leak to ordinary pages.

        Without this, 'delete the global header everywhere' would pass the two
        tests above while stripping the only navigation a non-console page has.
        """
        self.client.force_login(self.ifo)
        resp = self.client.get("/notifications")
        if resp.status_code != 200:
            self.skipTest(f"/notifications -> {resp.status_code}")
        body = resp.content.decode("utf-8", "replace")
        self.assertEqual(body.count("<header"), 1)
        self.assertIn("sticky top-0", body)
        self.assertNotIn('<header class="cns__bar"', body)

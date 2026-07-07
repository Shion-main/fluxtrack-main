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
            end_date=date(2026, 12, 31), is_active=True)
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
        self.assertRedirects(resp, "/")
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

    def test_garay_dev_login_authenticates_and_redirects_home(self):
        """A DEBUG POST of cdgaray logs in via the unchanged passwordless path and
        redirects home (role-routed to the faculty schedule)."""
        resp = self.client.post("/login", {"username": "cdgaray"})
        self.assertRedirects(resp, "/")
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
        resp = self.client.get("/")
        self.assertContains(resp, "/faculty/modality/new")

    def test_dean_home_links_approval_queue(self):
        u = get_user_model().objects.create(username="dean_nav", role=Role.DEAN)
        self.client.force_login(u)
        resp = self.client.get("/")
        self.assertContains(resp, "/dean/requests")

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
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
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

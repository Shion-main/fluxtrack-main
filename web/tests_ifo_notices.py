"""IFO notices lead somewhere and do not repeat themselves (audit M10, M11)."""
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase

from accounts.models import Role
from ops.models import Notification
from scheduling.models import Session
from scheduling.services import apply_approval, submit_modality_shift
from scheduling.test_support import IN_WINDOW_DATE as DAY, make_shift_fixture
from verification.models import Assignment, AssignmentScope, AssignmentType, DutyRole

MANILA = ZoneInfo("Asia/Manila")
User = get_user_model()


def at(hour, minute=0, day=DAY):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MANILA)


def frozen(when):
    return patch("django.utils.timezone.now", return_value=when)


def person(role, name):
    return User.objects.create(username=name, email=f"{name}@mcm.edu.ph", role=role,
                               is_active=True)


def browser(user):
    client = Client()
    client.force_login(user)
    return client


class IfoHomeLinkTests(TestCase):
    def setUp(self):
        self.fx = make_shift_fixture("lnk")
        self.ifo_user = person(Role.IFO_ADMIN, "lnk_ifo")

    def test_link_on_a_real_notification_opens_a_page(self):
        with frozen(at(9, 0, DAY - timedelta(days=7))):
            request = submit_modality_shift(
                self.fx.faculty, [self.fx.f2f_schedule], "online", DAY, DAY,
                request_reason="x")
            apply_approval(request, self.fx.dean)
        note = Notification.objects.get(user=self.ifo_user,
                                        type="modality_shift_applied")
        response = browser(self.ifo_user).get(note.link, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], "/ifo/rooms")

    def test_other_roles_are_refused(self):
        self.assertEqual(browser(self.fx.faculty).get("/ifo").status_code, 403)

    def test_signed_out_visitors_go_to_login(self):
        response = Client().get("/ifo")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login"))


class MissingTeamsLinkNoticeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("ntl")
        self.ifo_a = person(Role.IFO_ADMIN, "ntl_i1")
        self.ifo_b = person(Role.IFO_ADMIN, "ntl_i2")
        self.checker = person(Role.CHECKER, "ntl_chk")
        Assignment.objects.create(
            user=self.checker, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
            scope=AssignmentScope.ONLINE, term=self.fx.term)
        self.session = self.fx.online_session
        Session.objects.filter(pk=self.session.pk).update(online_checker=self.checker)
        self.client = browser(self.checker)

    def open(self, session=None):
        return self.client.get(f"/checker/online/{(session or self.session).pk}")

    def notices(self):
        return Notification.objects.filter(type="online_no_link")

    def test_reopening_the_page_does_not_repeat_the_notice(self):
        for _ in range(3):
            response = self.open()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.notices().filter(user=self.ifo_a).count(), 1)
        self.assertEqual(self.notices().filter(user=self.ifo_b).count(), 1)

    def test_a_second_checker_opening_it_does_not_repeat_the_notice(self):
        self.open()
        other = person(Role.CHECKER, "ntl_ch2")
        Session.objects.filter(pk=self.session.pk).update(online_checker=other)
        browser(other).get(f"/checker/online/{self.session.pk}")
        self.assertEqual(self.notices().filter(user=self.ifo_a).count(), 1)

    def test_next_weeks_class_gets_its_own_notice(self):
        self.open()
        next_week = DAY + timedelta(days=7)
        later = Session.objects.create(
            schedule=self.session.schedule, faculty=self.fx.faculty,
            room=self.session.room, date=next_week, online_checker=self.checker,
            scheduled_start=at(10, 0, next_week),
            scheduled_end=at(11, 30, next_week), declared_modality="online")
        self.open(later)
        self.assertEqual(self.notices().filter(user=self.ifo_a).count(), 2)

    def test_the_page_still_shows_the_missing_link_state(self):
        for _ in range(2):
            response = self.open()
        self.assertTrue(response.context["no_link"])


class TeamsLinkNoticeTimingTests(TestCase):
    """A blank link is normal until the instructor starts the class, so IFO hears
    about it only once the class is past grace, and is told who can act on it."""

    def setUp(self):
        cache.clear()
        self.fx = make_shift_fixture("ntt")
        self.ifo = person(Role.IFO_ADMIN, "ntt_ifo")
        self.checker = person(Role.CHECKER, "ntt_chk")
        Assignment.objects.create(
            user=self.checker, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
            scope=AssignmentScope.ONLINE, term=self.fx.term)
        self.session = self.fx.online_session  # 10:00-11:30
        Session.objects.filter(pk=self.session.pk).update(online_checker=self.checker)
        self.client = browser(self.checker)

    def open_at(self, when):
        with frozen(when):
            return self.client.get(f"/checker/online/{self.session.pk}")

    def notices(self):
        return Notification.objects.filter(user=self.ifo, type="online_no_link")

    def test_before_the_class_starts_nobody_is_told(self):
        self.open_at(at(9))
        self.assertFalse(self.notices().exists())

    def test_during_grace_nobody_is_told(self):
        self.open_at(at(10, 10))
        self.assertFalse(self.notices().exists())

    def test_past_grace_ifo_is_told_to_contact_the_instructor(self):
        self.open_at(at(10, 20))
        self.assertIn("instructor", self.notices().get().body)

    def test_cancelled_class_tells_nobody(self):
        Session.objects.filter(pk=self.session.pk).update(status="cancelled")
        self.open_at(at(10, 20))
        self.assertFalse(self.notices().exists())

    def test_checker_page_does_not_promise_that_ifo_will_add_a_link(self):
        response = self.open_at(at(9))
        self.assertTrue(response.context["no_link"])
        self.assertNotContains(response, "flagged IFO")


"""FAC-11 faculty attendance history (07-10, D-15).

The two scope tests carry the most value: a faculty member must not see another's
sessions, AND adding a `faculty` querystring parameter must not surface them. The
second is the regression guard against someone later "helpfully" adding a faculty
filter by copying HR's parser wholesale.

The no-dispute-control assertion is deliberately BEHAVIOURAL -- it asserts there
is no actionable element against a flag rather than keying on a particular word,
so it stays meaningful if the copy changes (D-15).

ASCII-only by convention (Windows cp1252).
"""
import re
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from campus.models import Building, Floor, Room
from scheduling.models import (
    AcademicTerm,
    Schedule,
    Session,
    SessionStatus,
)
from verification.models import CheckerValidation, ValidationAction
from web.reporting_common import status_label


def _user(username, role="faculty"):
    return get_user_model().objects.create(
        username=username, email=f"{username}@mcm.edu.ph", role=role)


def _term(name="FAC11 Term", active=True):
    return AcademicTerm.objects.get_or_create(
        name=name, defaults={"start_date": date(2026, 1, 1),
                             "end_date": date(2026, 12, 31),
                             "is_active": active})[0]


_SEQ = {"n": 0}


def make_history_session(faculty, *, days_ago=1, status=SessionStatus.COMPLETED,
                         term=None, course=None):
    """One past session for `faculty`. Rooms need unique qr_token/manual_code."""
    _SEQ["n"] += 1
    n = _SEQ["n"]
    bldg = Building.objects.get_or_create(name="H1", code="H1")[0]
    floor = Floor.objects.get_or_create(building=bldg, number=1)[0]
    room = Room.objects.create(floor=floor, code=f"H1{n:03d}",
                               qr_token=f"tok-h1-{n}", manual_code=f"77{n:04d}")
    d = timezone.localdate() - timedelta(days=days_ago)
    start = timezone.make_aware(
        timezone.datetime.combine(d, time(10, 0)))
    sch = Schedule.objects.create(
        term=term or _term(), course_code=course or f"H1{n:03d}", section="A",
        faculty=faculty, room=room, day_of_week=d.weekday(),
        start_time=time(10, 0), end_time=time(11, 30), enrolled_count=25)
    return Session.objects.create(
        schedule=sch, faculty=faculty, room=room, date=d,
        scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
        status=status, actual_start=start if status == SessionStatus.COMPLETED else None)


def _rendered_session_ids(resp):
    return set(re.findall(r'data-session="(\d+)"', resp.content.decode()))


class FacultyHistoryScopeTests(TestCase):
    """T-07-53: the history is hard-scoped and accepts no faculty parameter."""

    def setUp(self):
        self.me = _user("hist_me")
        self.them = _user("hist_them")
        self.mine = make_history_session(self.me)
        self.theirs = make_history_session(self.them)
        self.client.force_login(self.me)

    def test_sees_own_sessions_only(self):
        resp = self.client.get("/faculty/history")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rendered_session_ids(resp), {str(self.mine.pk)})

    def test_faculty_parameter_cannot_surface_another_users_sessions(self):
        """A forged `?faculty=<other pk>` changes NOTHING: the surface does not
        accept the concept of a faculty filter at all."""
        resp = self.client.get(f"/faculty/history?faculty={self.them.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_rendered_session_ids(resp), {str(self.mine.pk)})

    def test_term_filter_applies(self):
        other_term = _term(name="FAC11 Other Term", active=False)
        older = make_history_session(self.me, days_ago=40, term=other_term)
        resp = self.client.get(f"/faculty/history?term={other_term.pk}")
        self.assertEqual(_rendered_session_ids(resp), {str(older.pk)})

    def test_invalid_date_filter_is_a_friendly_200_not_a_500(self):
        """T-07-55: the bound is dropped, a note is rendered, the page still
        shows the unfiltered rows."""
        resp = self.client.get("/faculty/history?from=not-a-date")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-note="filter"', resp.content.decode())
        self.assertEqual(_rendered_session_ids(resp), {str(self.mine.pk)})

    def test_pagination_carries_active_filters_into_page_links(self):
        for i in range(30):
            make_history_session(self.me, days_ago=i + 2)
        resp = self.client.get("/faculty/history?from=2020-01-01")
        body = resp.content.decode()
        self.assertIn("page=2", body)
        # Every page link must still carry the active filter.
        for link in re.findall(r'href="(\?[^"]*page=\d+)"', body):
            self.assertIn("from=2020-01-01", link)


class FacultyHistoryFlagTests(TestCase):
    """D-15: flags are visible with their reason, and nothing is actionable."""

    def setUp(self):
        self.me = _user("hist_flag")
        self.checker = _user("hist_chk", role="checker")
        self.client.force_login(self.me)

    def _validate(self, session, action, note=""):
        return CheckerValidation.objects.create(
            session=session, room=session.room, checker=self.checker,
            action=action, note=note)

    def test_flag_not_present_renders_with_its_reason(self):
        s = make_history_session(self.me)
        self._validate(s, ValidationAction.FLAG_NOT_PRESENT, note="empty room")
        body = self.client.get("/faculty/history").content.decode()
        self.assertIn('data-flag="1"', body)
        self.assertIn(ValidationAction.FLAG_NOT_PRESENT.label, body)

    def test_verified_empty_is_not_a_flag_against_the_faculty(self):
        """VERIFIED_EMPTY is not the claim "this faculty member was not present",
        so it must not put a mark on the record."""
        s = make_history_session(self.me)
        self._validate(s, ValidationAction.VERIFIED_EMPTY)
        body = self.client.get("/faculty/history").content.decode()
        self.assertNotIn('data-flag="1"', body)

    def test_verified_renders_as_checker_verified(self):
        s = make_history_session(self.me)
        self._validate(s, ValidationAction.VERIFIED)
        body = self.client.get("/faculty/history").content.decode()
        self.assertIn("Verified", body)
        self.assertNotIn('data-flag="1"', body)

    def test_labels_agree_with_hr_for_the_same_session(self):
        """The shared helper is actually shared: the label this page renders for a
        session is the SAME string HR renders for it, compared rather than
        hard-coded in two places."""
        hr_admin = _user("hist_hr", role="hr_admin")
        cases = [(SessionStatus.COMPLETED, 3), (SessionStatus.ABSENT, 4),
                 (SessionStatus.SCHEDULED, 5)]
        sessions = [make_history_session(self.me, days_ago=d, status=st)
                    for st, d in cases]

        mine = self.client.get("/faculty/history").content.decode()
        self.client.force_login(hr_admin)
        theirs = self.client.get("/hr/attendance").content.decode()

        for s in sessions:
            label = status_label(s.status)
            self.assertIn(label, mine, f"faculty page missing {label}")
            self.assertIn(label, theirs, f"HR page missing {label}")

    def test_page_offers_no_actionable_control_against_a_flag(self):
        """D-15 / T-07-57: no dispute affordance. Behavioural, not word-keyed --
        the flag chip must carry no link and no button, and the only form on the
        page must be the GET filter bar."""
        s = make_history_session(self.me)
        self._validate(s, ValidationAction.FLAG_NOT_PRESENT, note="not there")
        body = self.client.get("/faculty/history").content.decode()

        # No POST form anywhere: the surface is read-only.
        self.assertNotIn('method="post"', body.lower())
        self.assertNotIn("hx-post", body)
        for form in re.findall(r"<form[^>]*>", body, flags=re.I):
            self.assertIn('method="get"', form.lower())

        # The flag chip itself carries no <a> and no <button>.
        chip = re.search(r'<span class="[^"]*" data-flag="1">(.*?)</span>',
                         body, flags=re.S)
        self.assertIsNotNone(chip, "flag chip not rendered")
        self.assertNotIn("<a", chip.group(1))
        self.assertNotIn("<button", chip.group(1))


class FacultyHistoryAuthzTests(TestCase):
    """Three-way authz plus the read-only method contract (T-07-54)."""

    def setUp(self):
        self.me = _user("hist_authz")
        make_history_session(self.me)

    def test_faculty_allowed(self):
        self.client.force_login(self.me)
        self.assertEqual(self.client.get("/faculty/history").status_code, 200)

    def test_non_faculty_authenticated_denied(self):
        self.client.force_login(_user("hist_dean", role="dean"))
        self.assertEqual(self.client.get("/faculty/history").status_code, 403)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get("/faculty/history")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_post_is_405(self):
        self.client.force_login(self.me)
        self.assertEqual(self.client.post("/faculty/history").status_code, 405)

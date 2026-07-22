"""FAC-08 faculty online "Verify & Start" (07-09, D-01/D-02/D-03).

Two of these classes carry most of the value and must not be dropped:

  * ``OnlineSelfStartTests.test_checker_sees_the_link_the_faculty_pasted`` proves
    D-03 end to end -- the faculty writes ``Session.teams_link`` and the Checker's
    own verify surface reads that very field, so the two roles can never verify
    against different meetings.
  * ``OnlineSweepInteractionTests`` proves D-02's claim that self-start needs NO
    change to the JOB-02 sweep: the sweep only moves SCHEDULED rows, so a
    self-started ACTIVE session is naturally skipped.

ASCII-only by convention (Windows cp1252).
"""
from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from campus.models import Building, Floor, Room
from ops.models import AuditLog
from ops.policy import get_policy
from scheduling.jobs import sweep_no_shows
from scheduling.models import (
    AcademicTerm,
    CheckinMethod,
    Modality,
    Schedule,
    Session,
    SessionStatus,
)
from scheduling.resolver import is_no_show_past_grace
from verification.models import CheckerValidation

GOOD_LINK = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_abc/0"
OTHER_LINK = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_zzz/0"


def _term():
    return AcademicTerm.objects.get_or_create(
        name="FAC08 Term", defaults={"start_date": date(2026, 1, 1),
                                     "end_date": date(2026, 12, 31),
                                     "status": AcademicTerm.Status.ACTIVE})[0]


def _room(code, seq):
    bldg = Building.objects.get_or_create(name="F8", code="F8")[0]
    floor = Floor.objects.get_or_create(building=bldg, number=8)[0]
    return Room.objects.create(floor=floor, code=code,
                               qr_token=f"tok-f8-{seq}",
                               manual_code=f"88{seq:04d}")


def _user(username, role="faculty"):
    return get_user_model().objects.create(
        username=username, email=f"{username}@mcm.edu.ph", role=role)


def make_online_session(username="fac_on", *, seq=1, modality=Modality.ONLINE,
                        minutes_from_now=-5, status=SessionStatus.SCHEDULED,
                        faculty=None, teams_link="", online_checker=None):
    """A session for `faculty` whose scheduled_start is `minutes_from_now`.

    The view reads a real ``timezone.now()`` (no injectable clock), so the clock
    is steered by placing the session relative to now rather than by faking time.
    """
    fac = faculty or _user(username)
    room = _room(f"F8{seq:02d}", seq)
    start = timezone.now() + timedelta(minutes=minutes_from_now)
    local_start = timezone.localtime(start)
    sch = Schedule.objects.create(
        term=_term(), course_code=f"F8{seq:03d}", section="A", faculty=fac,
        room=room, day_of_week=local_start.weekday(),
        start_time=time(8, 0), end_time=time(9, 30),
        modality=modality, enrolled_count=30)
    return Session.objects.create(
        schedule=sch, faculty=fac, room=room, date=local_start.date(),
        scheduled_start=start, scheduled_end=start + timedelta(minutes=90),
        status=status, teams_link=teams_link, online_checker=online_checker)


class OnlineSelfStartTests(TestCase):
    """The happy path and the D-02/D-03 contracts it must NOT overstep."""

    def setUp(self):
        self.session = make_online_session()
        self.faculty = self.session.faculty
        self.url = f"/faculty/online/{self.session.pk}/start"

    def test_start_writes_active_actual_start_method_and_link(self):
        """A valid start sets ACTIVE + actual_start + ONLINE_SELF and stores the
        pasted link on Session.teams_link (D-01/D-03)."""
        self.client.force_login(self.faculty)
        resp = self.client.post(self.url, {"teams_link": GOOD_LINK})
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.ACTIVE)
        self.assertIsNotNone(self.session.actual_start)
        self.assertEqual(self.session.checkin_method, CheckinMethod.ONLINE_SELF)
        self.assertEqual(self.session.teams_link, GOOD_LINK)

    def test_self_start_is_distinguishable_from_checker_activation(self):
        """ONLINE_SELF, never ONLINE_MANUAL: the data must still be able to answer
        'who started this class' (D-01/D-02)."""
        self.client.force_login(self.faculty)
        self.client.post(self.url, {"teams_link": GOOD_LINK})
        self.session.refresh_from_db()
        self.assertNotEqual(self.session.checkin_method,
                            CheckinMethod.ONLINE_MANUAL)

    def test_start_does_not_make_it_checker_verified(self):
        """Starting is not verifying (D-02): verified_by_checker stays false and
        no CheckerValidation row is written, so a never-verified self-start
        reports as held-but-UNVERIFIED rather than being hidden."""
        self.client.force_login(self.faculty)
        self.client.post(self.url, {"teams_link": GOOD_LINK})
        self.session.refresh_from_db()
        self.assertFalse(self.session.verified_by_checker)
        self.assertEqual(
            CheckerValidation.objects.filter(session=self.session).count(), 0)

    def test_checker_sees_the_link_the_faculty_pasted(self):
        """D-03 end to end: the Checker's online verify surface renders the very
        link the faculty pasted, and its no-link branch does NOT fire."""
        checker = _user("chk_on", role="checker")
        self.session.online_checker = checker
        self.session.save(update_fields=["online_checker"])

        self.client.force_login(self.faculty)
        self.client.post(self.url, {"teams_link": GOOD_LINK})

        self.client.force_login(checker)
        resp = self.client.get(f"/checker/online/{self.session.pk}")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(GOOD_LINK, body)
        self.assertNotIn('data-outcome="no-link"', body)

    def test_overwrite_audits_the_previous_link(self):
        """An overwrite is the interesting case: the audit row carries the value
        that was replaced (T-07-51)."""
        self.session.teams_link = OTHER_LINK
        self.session.save(update_fields=["teams_link"])
        self.client.force_login(self.faculty)
        self.client.post(self.url, {"teams_link": GOOD_LINK})
        log = AuditLog.objects.filter(event_type="session.teams_link_set",
                                      target_id=str(self.session.pk)).get()
        self.assertEqual(log.actor, self.faculty)
        self.assertEqual(log.target_type, "session")
        self.assertEqual(log.payload["previous_teams_link"], OTHER_LINK)
        self.assertEqual(log.payload["teams_link"], GOOD_LINK)

    def test_online_list_shows_only_own_online_sessions_today(self):
        """The list is scoped to the requester and today, and only EFFECTIVE-online
        sessions appear -- Blended still checks in by QR."""
        import re

        other = _user("fac_on_other")
        foreign = make_online_session(seq=2, faculty=other)
        blended = make_online_session(seq=3, faculty=self.faculty,
                                      modality=Modality.BLENDED)
        self.client.force_login(self.faculty)
        resp = self.client.get("/faculty/online")
        self.assertEqual(resp.status_code, 200)
        rendered = set(re.findall(r'id="online-card-(\d+)"',
                                  resp.content.decode()))
        self.assertEqual(rendered, {str(self.session.pk)})
        self.assertNotIn(str(foreign.pk), rendered)
        self.assertNotIn(str(blended.pk), rendered)

    def test_declared_online_overrides_a_non_online_schedule(self):
        """Effective modality is `declared_modality or schedule.modality` -- the
        override rule used consistently across this codebase."""
        s = make_online_session(username="fac_dec", seq=4,
                                modality=Modality.F2F)
        s.declared_modality = Modality.ONLINE
        s.save(update_fields=["declared_modality"])
        self.client.force_login(s.faculty)
        resp = self.client.post(f"/faculty/online/{s.pk}/start",
                                {"teams_link": GOOD_LINK})
        self.assertEqual(resp.status_code, 200)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ACTIVE)


class OnlineStartValidationTests(TestCase):
    """The validation ladder, every rung refusing at 400 with nothing written."""

    def setUp(self):
        self.session = make_online_session()
        self.faculty = self.session.faculty
        self.url = f"/faculty/online/{self.session.pk}/start"
        self.client.force_login(self.faculty)

    def _assert_refused(self, link):
        resp = self.client.post(self.url, {"teams_link": link})
        self.assertEqual(resp.status_code, 400, f"expected refusal for {link!r}")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, SessionStatus.SCHEDULED)
        self.assertEqual(self.session.teams_link, "")
        self.assertIsNone(self.session.actual_start)
        self.assertEqual(self.session.checkin_method, "")

    def test_non_teams_url_refused(self):
        self._assert_refused("https://zoom.us/j/12345")

    def test_http_teams_url_refused(self):
        """http is refused: a Checker is asked to click this link."""
        self._assert_refused("http://teams.microsoft.com/l/meetup-join/19%3aX/0")

    def test_teams_domain_in_the_path_refused(self):
        """T-07-48: a crafted URL whose PATH contains a Teams domain satisfies a
        substring search while pointing elsewhere. The host is what is matched."""
        self._assert_refused("https://example.com/teams.microsoft.com/meet")

    def test_lookalike_host_refused(self):
        """Host matching is exact-or-dot-boundary, so a lookalike is not a match."""
        self._assert_refused("https://eviltteams.microsoft.com.attacker.test/x")

    def test_empty_link_refused(self):
        self._assert_refused("")

    def test_foreign_session_cannot_be_started(self):
        """T-07-47 IDOR: posting another faculty member's session pk starts
        nothing on that session."""
        victim = make_online_session(username="fac_victim", seq=5)
        resp = self.client.post(f"/faculty/online/{victim.pk}/start",
                                {"teams_link": GOOD_LINK})
        self.assertEqual(resp.status_code, 404)
        victim.refresh_from_db()
        self.assertEqual(victim.status, SessionStatus.SCHEDULED)
        self.assertEqual(victim.teams_link, "")

    def test_blended_and_f2f_refused_and_point_at_qr(self):
        for modality, seq in ((Modality.BLENDED, 6), (Modality.F2F, 7)):
            s = make_online_session(username=f"fac_m{seq}", seq=seq,
                                    modality=modality)
            self.client.force_login(s.faculty)
            resp = self.client.post(f"/faculty/online/{s.pk}/start",
                                    {"teams_link": GOOD_LINK})
            self.assertEqual(resp.status_code, 400)
            self.assertIn("QR", resp.content.decode())
            s.refresh_from_db()
            self.assertEqual(s.status, SessionStatus.SCHEDULED)

    def test_already_active_session_refused(self):
        """Re-starting an already-started session with a different link is refused
        and the stored link is unchanged."""
        self.client.post(self.url, {"teams_link": GOOD_LINK})
        resp = self.client.post(self.url, {"teams_link": OTHER_LINK})
        self.assertEqual(resp.status_code, 400)
        self.session.refresh_from_db()
        self.assertEqual(self.session.teams_link, GOOD_LINK)

    def test_absent_session_refused(self):
        """ABSENT is final (CHK-06 was removed; Absent is the sweep's decision),
        so a late start must not quietly undo it (T-07-50)."""
        s = make_online_session(username="fac_abs", seq=8,
                                status=SessionStatus.ABSENT)
        self.client.force_login(s.faculty)
        resp = self.client.post(f"/faculty/online/{s.pk}/start",
                                {"teams_link": GOOD_LINK})
        self.assertEqual(resp.status_code, 400)
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)
        self.assertEqual(s.teams_link, "")

    def test_past_grace_refused_and_matches_the_shared_predicate(self):
        """T-07-52: this surface must agree with the scan resolver and the sweep,
        so the boundary is asserted against `is_no_show_past_grace` itself rather
        than against a number hard-coded here."""
        grace = get_policy("grace_minutes")
        late = make_online_session(username="fac_late", seq=9,
                                   minutes_from_now=-(grace + 5))
        early = make_online_session(username="fac_early", seq=10,
                                    minutes_from_now=-(grace - 5))
        now = timezone.now()
        self.assertTrue(is_no_show_past_grace(late.scheduled_start, now, grace))
        self.assertFalse(is_no_show_past_grace(early.scheduled_start, now, grace))

        self.client.force_login(late.faculty)
        refused = self.client.post(f"/faculty/online/{late.pk}/start",
                                   {"teams_link": GOOD_LINK})
        self.assertEqual(refused.status_code, 400)
        late.refresh_from_db()
        self.assertEqual(late.status, SessionStatus.SCHEDULED)

        self.client.force_login(early.faculty)
        allowed = self.client.post(f"/faculty/online/{early.pk}/start",
                                   {"teams_link": GOOD_LINK})
        self.assertEqual(allowed.status_code, 200)
        early.refresh_from_db()
        self.assertEqual(early.status, SessionStatus.ACTIVE)

    def test_refusal_writes_no_audit_row(self):
        self.client.post(self.url, {"teams_link": "https://zoom.us/j/1"})
        self.assertEqual(
            AuditLog.objects.filter(event_type="session.teams_link_set").count(), 0)


class OnlineStartAuthzTests(TestCase):
    """Three-way authz on both views, plus the method contract."""

    def setUp(self):
        self.session = make_online_session()
        self.faculty = self.session.faculty
        self.start_url = f"/faculty/online/{self.session.pk}/start"

    def test_faculty_allowed(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get("/faculty/online").status_code, 200)

    def test_non_faculty_authenticated_denied(self):
        self.client.force_login(_user("chk_authz", role="checker"))
        self.assertEqual(self.client.get("/faculty/online").status_code, 403)
        self.assertEqual(
            self.client.post(self.start_url, {"teams_link": GOOD_LINK}).status_code,
            403)

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get("/faculty/online")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])

    def test_get_on_start_is_405(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(self.start_url).status_code, 405)

    def test_post_on_list_is_405(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.post("/faculty/online").status_code, 405)


class OnlineSelfStartMergePropagationTests(TestCase):
    """Audit H1 (2026-07-19): ONE self-start covers the co-scheduled online group.

    The room-scan and checker-Verify seams already ran propagate_merged_present;
    before this fix the self-start seam did not, so the sweep falsely absented
    the sibling section of a merged online meeting the instructor was actually
    holding (~27% of instructors have co-scheduled slots)."""

    def setUp(self):
        self.anchor = make_online_session(username="fac_merge", seq=13)
        self.faculty = self.anchor.faculty
        room = _room("F8M14", 14)
        sch = Schedule.objects.create(
            term=_term(), course_code="F8M14", section="B", faculty=self.faculty,
            room=room,
            day_of_week=timezone.localtime(self.anchor.scheduled_start).weekday(),
            start_time=time(8, 0), end_time=time(9, 30),
            modality=Modality.ONLINE, enrolled_count=30)
        # The sibling copies the anchor's EXACT scheduled_start (the D-01 online
        # merge key is faculty + exact instant, so a fresh timezone.now() would
        # never merge).
        self.sibling = Session.objects.create(
            schedule=sch, faculty=self.faculty, room=room,
            date=self.anchor.date,
            scheduled_start=self.anchor.scheduled_start,
            scheduled_end=self.anchor.scheduled_end,
            status=SessionStatus.SCHEDULED)

    def test_start_fills_the_online_sibling(self):
        self.client.force_login(self.faculty)
        resp = self.client.post(f"/faculty/online/{self.anchor.pk}/start",
                                {"teams_link": GOOD_LINK})
        self.assertEqual(resp.status_code, 200)
        self.anchor.refresh_from_db()
        self.sibling.refresh_from_db()
        # Anchor keeps its real method; only the sibling is stamped MERGED.
        self.assertEqual(self.anchor.checkin_method, CheckinMethod.ONLINE_SELF)
        self.assertEqual(self.sibling.status, SessionStatus.ACTIVE)
        self.assertEqual(self.sibling.checkin_method, CheckinMethod.MERGED)
        self.assertEqual(self.sibling.actual_start, self.anchor.actual_start)
        log = AuditLog.objects.filter(event_type="session.merged_present",
                                      target_id=str(self.sibling.pk)).get()
        self.assertEqual(log.payload, {"merged_from": self.anchor.pk})
        # D-09 still holds: a merge-filled sibling gets NO CheckerValidation.
        self.assertEqual(
            CheckerValidation.objects.filter(session=self.sibling).count(), 0)

    def test_sweep_no_longer_absents_the_sibling_after_a_start(self):
        grace = get_policy("grace_minutes")
        self.client.force_login(self.faculty)
        self.client.post(f"/faculty/online/{self.anchor.pk}/start",
                         {"teams_link": GOOD_LINK})
        sweep_no_shows(now=timezone.now() + timedelta(minutes=grace + 60))
        self.sibling.refresh_from_db()
        self.assertEqual(self.sibling.status, SessionStatus.ACTIVE)


class OnlineSweepInteractionTests(TestCase):
    """D-02: self-start needs NO change to the JOB-02 sweep."""

    def test_sweep_leaves_a_self_started_session_alone(self):
        """The sweep only moves SCHEDULED rows to ABSENT, so a session a faculty
        member self-started (and which is therefore ACTIVE) is naturally skipped
        even though its start is now well past grace."""
        grace = get_policy("grace_minutes")
        s = make_online_session(username="fac_sweep", seq=11,
                                minutes_from_now=-(grace - 5))
        self.client.force_login(s.faculty)
        self.client.post(f"/faculty/online/{s.pk}/start",
                         {"teams_link": GOOD_LINK})
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ACTIVE)

        # Run the sweep at a clock well past this session's grace window.
        sweep_no_shows(now=timezone.now() + timedelta(minutes=grace + 60))
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ACTIVE)
        self.assertEqual(s.checkin_method, CheckinMethod.ONLINE_SELF)

    def test_sweep_still_absents_an_unstarted_online_session(self):
        """The control for the test above: an online session nobody started IS
        swept, so the skip above is the ACTIVE status doing the work, not the
        sweep having stopped looking at online sessions."""
        grace = get_policy("grace_minutes")
        s = make_online_session(username="fac_nostart", seq=12,
                                minutes_from_now=-(grace + 60))
        sweep_no_shows(now=timezone.now())
        s.refresh_from_db()
        self.assertEqual(s.status, SessionStatus.ABSENT)

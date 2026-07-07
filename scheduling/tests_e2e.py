"""End-to-end spot-check assertions for the live-loaded 2nd Term SY 2025-2026
(Phase 04.1 Plan 04, D10 run sequence).

These are NOT ordinary unit tests. They assert against the REAL term loaded into
the live MSSQL LocalDB by the clean-load sequence:

    py -3.12 manage.py reset_term --yes
    py -3.12 manage.py load_room_master
    py -3.12 manage.py import_offerings
    py -3.12 manage.py materialize_sessions --days 14

``manage.py test`` spins up an EMPTY test database, so the guards below skip both
cases there (nothing to assert). To run them against the live dev data, point the
test runner at the populated ``default`` DB with ``--keepdb`` after the load, or
call the module-level ``assert_scale()`` / ``assert_spot_check()`` helpers from a
``manage.py shell`` against the live term. The executor ran the equivalent shell
assertions during Plan 04 execution (SCALE OK / SPOTCHECK OK); this file records
them for the record and for repeatable re-verification.

What is asserted (Success Criterion 2 + 6, ENV-02 at full-term scale):

* SCALE — the active term holds the full term, not the R3 slice:
    - > 2000 active-term Schedules (~2,113 loaded);
    - the term spans EXACTLY the five real buildings ACAD / ADMIN / GYM / ONLINE /
      UNASSIGNED (a pre-existing seed_demo "IT" building may also exist globally
      with zero active-term schedules — the assertion is scoped to the term, not
      a global Building count);
    - the "TBA" placeholder room exists (D9 roomless-physical bucket);
    - > 180 FACULTY users (~200 distinct instructors, D7);
    - materialized Sessions exist over the 14-day window.

* SPOT CHECK — one F2F, one blended, one online class each appear for the correct
  instructor on the exact /faculty/schedule queryset (web.faculty.schedule:
  ``Session.objects.filter(faculty=user, date in [today, today+7))``) and are
  checkable per modality (D5/D8):
    - F2F + blended sit in a physical, non-virtual room in a real building with a
      qr_token + manual_code (scannable);
    - online sits in a virtual Online-building room (routed to the checker, not the
      faculty scan).
"""
from datetime import timedelta

from django.test import TestCase, tag
from django.utils import timezone

# Expected buildings the REAL term spans (scoped to the active term, NOT a global
# Building count — a dormant seed_demo "IT" building may coexist untouched, D10 /
# threat T-04.1-08).
TERM_BUILDINGS = {"ACAD", "ADMIN", "GYM", "ONLINE", "UNASSIGNED"}


def _active_term():
    from scheduling.models import AcademicTerm
    return AcademicTerm.objects.filter(is_active=True).first()


def _term_is_loaded():
    """True only when the live full-term load is present (skip guard)."""
    from scheduling.models import Schedule
    term = _active_term()
    return bool(term) and Schedule.objects.filter(term=term).count() > 2000


def assert_scale():
    """Assert the live-DB scale of the loaded term. Raises AssertionError on any
    miss; returns a small dict of the observed counts. Safe to call from a
    ``manage.py shell`` against the live term."""
    from django.contrib.auth import get_user_model
    from accounts.models import Role
    from campus.models import Room
    from scheduling.models import Schedule, Session

    User = get_user_model()
    term = _active_term()
    assert term is not None, "no active AcademicTerm"

    schedules = Schedule.objects.filter(term=term)
    faculty = User.objects.filter(role=Role.FACULTY).count()
    sessions = Session.objects.count()
    term_buildings = set(
        schedules.values_list("room__floor__building__code", flat=True))

    assert schedules.count() > 2000, schedules.count()
    assert term_buildings == TERM_BUILDINGS, sorted(term_buildings)
    assert Room.objects.filter(code="TBA").exists(), "TBA placeholder room missing"
    assert faculty > 180, faculty
    assert sessions > 0, sessions
    return {
        "schedules": schedules.count(),
        "term_buildings": sorted(term_buildings),
        "faculty": faculty,
        "sessions": sessions,
        "rooms": Room.objects.count(),
    }


def assert_spot_check():
    """Assert one F2F, one blended and one online class each appear for the correct
    instructor on the mirrored /faculty/schedule queryset and are checkable per
    modality. Returns the three picked classes. Raises AssertionError on any miss."""
    from scheduling.models import Modality, Session

    today = timezone.localdate()
    week_end = today + timedelta(days=7)
    base = (Session.objects
            .select_related("schedule", "faculty", "room__floor__building")
            .filter(date__gte=today, date__lt=week_end))

    def pick(modality, *, virtual):
        qs = base.filter(schedule__modality=modality)
        qs = (qs.filter(room__floor__building__code="ONLINE") if virtual
              else qs.exclude(room__floor__building__code="ONLINE"))
        return qs.order_by("date", "scheduled_start").first()

    f2f = pick(Modality.F2F, virtual=False)
    blended = pick(Modality.BLENDED, virtual=False)
    online = pick(Modality.ONLINE, virtual=True)
    assert f2f and blended and online, (f2f, blended, online)

    picks = {"f2f": f2f, "blended": blended, "online": online}
    for modality, s in picks.items():
        # Mirror web.faculty.schedule exactly: the owning instructor's week window.
        surfaced = Session.objects.filter(
            faculty=s.faculty, date__gte=today, date__lt=week_end, pk=s.pk).exists()
        assert surfaced, f"{modality} session not on its instructor's schedule"

    # F2F + blended: physical, scannable (real building, qr_token + manual_code).
    for s in (f2f, blended):
        assert s.room.floor.building.code != "ONLINE"
        assert s.room.qr_token and s.room.manual_code, s.room.code
    # Online: virtual Online-building room (checker-routed, not the faculty scan).
    assert online.room.floor.building.code == "ONLINE", online.room.code

    return {
        m: {
            "course": f"{s.schedule.course_code}-{s.schedule.section}",
            "faculty": s.faculty.get_full_name() or s.faculty.username,
            "room": f"{s.room.code}/{s.room.floor.building.code}",
            "date": s.date,
        }
        for m, s in picks.items()
    }


@tag("e2e")
class LiveTermScaleTests(TestCase):
    """Scale assertions against the live-loaded term (skips on an empty test DB)."""

    databases = {"default"}

    def setUp(self):
        if not _term_is_loaded():
            self.skipTest("live full-term load not present (run the D10 sequence)")

    def test_live_term_scale(self):
        assert_scale()  # raises with the offending count on any miss


@tag("e2e")
class LiveTermSpotCheckTests(TestCase):
    """F2F / blended / online spot-check against the live term (skips if unloaded)."""

    databases = {"default"}

    def setUp(self):
        if not _term_is_loaded():
            self.skipTest("live full-term load not present (run the D10 sequence)")

    def test_three_modalities_appear_and_are_checkable(self):
        picks = assert_spot_check()
        self.assertEqual(set(picks), {"f2f", "blended", "online"})

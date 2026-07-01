"""Unit tests for the pure scan resolver (SCAN-01/02, §6.6)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from django.test import SimpleTestCase

from scheduling import resolver as R


@dataclass
class FakeSchedule:
    modality: str = "f2f"


@dataclass
class FakeSession:
    id: int
    room_id: int
    scheduled_start: datetime
    scheduled_end: datetime
    status: str = "scheduled"
    declared_modality: str = ""
    schedule: FakeSchedule = field(default_factory=FakeSchedule)


T0 = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)  # scheduled start


def sess(**kw):
    defaults = dict(id=1, room_id=10, scheduled_start=T0,
                    scheduled_end=T0 + timedelta(minutes=90))
    defaults.update(kw)
    return FakeSession(**defaults)


def resolve(sessions, room_id=10, occupying=None, now=T0, **kw):
    policy = dict(grace_min=15, early_end_min=15)
    policy.update(kw)
    return R.resolve_faculty_scan(sessions, room_id, occupying, now, **policy)


class FacultyResolverTests(SimpleTestCase):
    def test_checkin_at_start_is_present(self):
        r = resolve([sess()])
        self.assertEqual(r.outcome, R.CHECKED_IN)
        self.assertFalse(r.needs_confirm)

    def test_checkin_within_grace_is_present(self):
        r = resolve([sess()], now=T0 + timedelta(minutes=14))
        self.assertEqual(r.outcome, R.CHECKED_IN)

    def test_checkin_after_grace_is_absent(self):
        r = resolve([sess()], now=T0 + timedelta(minutes=16))
        self.assertEqual(r.outcome, R.ABSENT)

    def test_checkin_slightly_early_is_allowed(self):
        r = resolve([sess()], now=T0 - timedelta(minutes=10))
        self.assertEqual(r.outcome, R.CHECKED_IN)

    def test_checkin_far_too_early(self):
        r = resolve([sess()], now=T0 - timedelta(hours=2))
        self.assertEqual(r.outcome, R.TOO_EARLY)

    def test_no_schedule_in_other_room(self):
        r = resolve([sess()], room_id=99, now=T0 - timedelta(hours=2))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_wrong_room_needs_confirm(self):
        r = resolve([sess(room_id=20)], room_id=10)
        self.assertEqual(r.outcome, R.WRONG_ROOM)
        self.assertTrue(r.needs_confirm)

    def test_room_occupied_needs_confirm_and_carries_prior(self):
        r = resolve([sess()], occupying=77)
        self.assertEqual(r.outcome, R.ROOM_OCCUPIED)
        self.assertTrue(r.needs_confirm)
        self.assertEqual(r.prior_session_id, 77)

    def test_online_session_rejects_qr(self):
        r = resolve([sess(schedule=FakeSchedule(modality="online"))])
        self.assertEqual(r.outcome, R.ONLINE_REJECT)

    def test_declared_modality_overrides_scheduled(self):
        r = resolve([sess(declared_modality="online")])
        self.assertEqual(r.outcome, R.ONLINE_REJECT)

    def test_rescan_active_session_near_end_checks_out(self):
        s = sess(status="active")
        r = resolve([s], now=T0 + timedelta(minutes=80))
        self.assertEqual(r.outcome, R.CHECKED_OUT)

    def test_rescan_active_session_early_needs_confirm(self):
        s = sess(status="active")
        r = resolve([s], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.EARLY_END)
        self.assertTrue(r.needs_confirm)

    def test_active_session_scanning_other_room_is_wrong_room(self):
        s = sess(status="active")
        r = resolve([s], room_id=99, now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.WRONG_ROOM)

    def test_completed_session_gives_no_schedule(self):
        r = resolve([sess(status="completed")], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_absent_session_stays_absent_no_new_start(self):
        r = resolve([sess(status="absent")], now=T0 + timedelta(minutes=30))
        self.assertEqual(r.outcome, R.NO_SCHEDULE)

    def test_second_session_of_day_resolves(self):
        s1 = sess(id=1, status="completed")
        s2 = sess(id=2, scheduled_start=T0 + timedelta(hours=3),
                  scheduled_end=T0 + timedelta(hours=4, minutes=30))
        r = resolve([s1, s2], now=T0 + timedelta(hours=3))
        self.assertEqual(r.outcome, R.CHECKED_IN)
        self.assertEqual(r.session_id, 2)

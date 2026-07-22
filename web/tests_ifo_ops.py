"""IFO operational-action tests: manual room release (IFO-08, plan 07-05) and
ad-hoc bookings (IFO-05, plan 07-06).

Its own module rather than another class in web/tests.py, following the
larger-surface convention set by web/tests_ifo_board.py and web/tests_hr.py.

THE LOAD-BEARING TEST IN THIS MODULE is
`test_release_then_sweep_auto_resolves_the_flag`. It is the one that proves the
whole D-11 design end to end: IFO does exactly ONE thing -- release the session
that should not be holding the room -- and the RoomConflictFlag closes on the
next sweep because the CAUSE is gone, not because anything dismissed the
symptom. Every other test here can pass while the design is quietly wrong; that
one cannot. It is also the test that will catch a later "improvement" that adds
a manual flag-close path, which would be a second resolution route capable of
marking a flag resolved while the conflict was still live.

The second-most-skippable assertion is the audit COUNT. `release_room` writes
`session.room_released` itself, so the view must add none; asserting "an audit
row exists" would pass with two. The count is asserted exactly.

FOR THE BOOKING HALF, the two load-bearing cases are the ABUTTING window and
the ONLINE session. They are what prove the surface is asking the shared oracle
rather than a hand-rolled overlap query: a naive inclusive comparison refuses
the abutting booking that `ops/availability.py` allows, and a naive "is any
session in this room" query refuses the online booking that the same module
allows because an online class occupies no physical room. Both would look
correct in review and would only disagree with the scan and approval paths at
the boundary.

The three known pre-existing dev-login / home-redirect failures in web/tests.py
are unrelated to this module and are not chased here.

ASCII-only.
"""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from campus.services import room_delete_blockers
from ops.availability import room_is_free
from ops.models import AuditLog, Booking, RoomConflictFlag
from scheduling.jobs import detect_room_conflicts
from scheduling.models import Modality, Session, SessionStatus
from scheduling.tests import make_session


class _IfoOpsBase(TestCase):
    """One room, one schedule, and however many sessions a test needs on it.

    Built on `scheduling.tests.make_session` for the FK chain (the project's
    factory idiom) and then extended in place: make_session mints its own
    Building/Floor/Room/Term per call, so calling it twice would collide on the
    unique Building code. Calling it once and hanging siblings off the same
    schedule is what actually produces two sessions contending for ONE room --
    which is the shape every test here needs.
    """

    def setUp(self):
        User = get_user_model()
        self.ifo = User.objects.create(
            username="ifo_ops", email="ifo_ops@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.faculty = User.objects.create(
            username="fac_ops", email="fac_ops@mcm.edu.ph",
            role=Role.FACULTY, is_active=True)

        start = timezone.now() - timedelta(minutes=30)
        self.session = make_session(start, start + timedelta(hours=1))
        self.session.status = SessionStatus.ACTIVE
        self.session.save(update_fields=["status"])
        self.room = self.session.room
        self.schedule = self.session.schedule

    def _sibling(self, *, status=SessionStatus.ACTIVE):
        """A SECOND session holding the same room -- the conflict shape."""
        start = self.session.scheduled_start + timedelta(minutes=15)
        return Session.objects.create(
            schedule=self.schedule, faculty=self.session.faculty,
            room=self.room, date=self.session.date,
            scheduled_start=start, scheduled_end=start + timedelta(hours=1),
            status=status)

    def _release(self, session=None):
        session = session or self.session
        return self.client.post(
            reverse("ifo_session_release", args=[session.pk]))

    def _audit_rows(self, session=None):
        session = session or self.session
        return AuditLog.objects.filter(event_type="session.room_released",
                                       target_id=str(session.pk))


class ManualReleaseTests(_IfoOpsBase):
    """The release action itself: it stamps, it audits exactly once, it re-gates."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_release_stamps_room_released_at(self):
        self.assertIsNone(self.session.room_released_at)
        resp = self._release()
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.room_released_at)

    def test_release_writes_exactly_one_audit_row_with_the_ifo_actor(self):
        """`release_room` writes session.room_released itself. If the view adds
        its own AuditLog too, every release double-counts and "how many rooms
        did IFO release last week" stops being answerable. Exactly one."""
        self._release()
        rows = self._audit_rows()
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().actor_id, self.ifo.pk)
        self.assertEqual(rows.first().target_type, "session")

    def test_a_second_release_refuses_at_400_and_changes_nothing(self):
        """The button the operator clicked is a snapshot that may be minutes
        stale on a polled board. The server-side re-gate is the control."""
        self._release()
        self.session.refresh_from_db()
        first_stamp = self.session.room_released_at

        resp = self._release()
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "already released", status_code=400)

        self.session.refresh_from_db()
        self.assertEqual(self.session.room_released_at, first_stamp)
        self.assertEqual(self._audit_rows().count(), 1)

    def test_a_completed_session_is_not_holding_the_room(self):
        """COMPLETED and ABSENT sessions finished with the room on their own.
        Stamping a release instant for them would record an occupancy end that
        did not happen here."""
        self.session.status = SessionStatus.COMPLETED
        self.session.save(update_fields=["status"])

        resp = self._release()
        self.assertEqual(resp.status_code, 400)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)
        self.assertEqual(self._audit_rows().count(), 0)

    def test_a_get_on_the_release_url_is_405(self):
        resp = self.client.get(
            reverse("ifo_session_release", args=[self.session.pk]))
        self.assertEqual(resp.status_code, 405)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_releasing_an_unknown_session_is_a_404(self):
        resp = self.client.post(reverse("ifo_session_release", args=[999999]))
        self.assertEqual(resp.status_code, 404)

    def test_the_view_never_touches_the_conflict_flag(self):
        """D-11: no manual flag-close anywhere in this plan. The release fixes
        the CAUSE; the sweep closes the flag."""
        self._sibling()
        detect_room_conflicts()
        flag = RoomConflictFlag.objects.get(resolved_at__isnull=True)

        self._release()

        flag.refresh_from_db()
        self.assertIsNone(flag.resolved_at)


class ConflictSurfaceTests(_IfoOpsBase):
    """The open-conflicts page, and the D-11 release-then-sweep handoff."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_the_page_lists_an_open_flag_with_both_contending_sessions(self):
        sibling = self._sibling()
        detect_room_conflicts()

        resp = self.client.get(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.room.code)
        self.assertContains(resp, f'data-session="{self.session.pk}"')
        self.assertContains(resp, f'data-session="{sibling.pk}"')

    def test_release_then_sweep_auto_resolves_the_flag(self):
        """THE D-11 TEST. Two ACTIVE sessions hold one room; the sweep opens a
        flag; IFO releases one of them; the next sweep finds the conflict key
        absent and stamps resolved_at through the EXISTING JOB-02c auto-resolve
        path. No code in plan 07-05 writes resolved_at -- that is the point.
        """
        self._sibling()
        detect_room_conflicts()
        flag = RoomConflictFlag.objects.get(resolved_at__isnull=True)
        self.assertIsNone(flag.resolved_at)

        resp = self._release()
        self.assertEqual(resp.status_code, 200)

        detect_room_conflicts()

        flag.refresh_from_db()
        self.assertIsNotNone(flag.resolved_at)
        self.assertFalse(
            RoomConflictFlag.objects.filter(resolved_at__isnull=True).exists())

    def test_the_page_renders_its_empty_state_when_nothing_is_flagged(self):
        resp = self.client.get(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "No open room conflicts")
        self.assertContains(resp, 'data-empty="1"')

    def test_a_post_on_the_conflicts_page_is_405(self):
        resp = self.client.post(reverse("ifo_conflicts"))
        self.assertEqual(resp.status_code, 405)


class IfoOpsAuthzTests(_IfoOpsBase):
    """Three-way authz on both IFO-08 URLs."""

    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.checker = User.objects.create(
            username="chk_ops", email="chk_ops@mcm.edu.ph",
            role=Role.CHECKER, is_active=True)

    def test_ifo_reaches_the_conflicts_page(self):
        self.client.force_login(self.ifo)
        self.assertEqual(
            self.client.get(reverse("ifo_conflicts")).status_code, 200)

    def test_a_non_ifo_authenticated_user_gets_403(self):
        self.client.force_login(self.faculty)
        self.assertEqual(
            self.client.get(reverse("ifo_conflicts")).status_code, 403)
        self.assertEqual(self._release().status_code, 403)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_a_checker_cannot_release_either(self):
        self.client.force_login(self.checker)
        self.assertEqual(self._release().status_code, 403)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.room_released_at)

    def test_an_anonymous_user_is_redirected_to_login(self):
        for url in (reverse("ifo_conflicts"),
                    reverse("ifo_session_release", args=[self.session.pk]),
                    reverse("ifo_bookings"),
                    reverse("ifo_booking_create")):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login", resp["Location"])

    def test_a_non_ifo_user_cannot_reach_the_booking_urls(self):
        self.client.force_login(self.faculty)
        self.assertEqual(
            self.client.get(reverse("ifo_bookings")).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("ifo_booking_create"), {}).status_code,
            403)
        self.assertEqual(Booking.objects.count(), 0)


class _BookingBase(_IfoOpsBase):
    """Booking fixtures on the room `make_session` built.

    `self.session` is deliberately left SCHEDULED here rather than ACTIVE: the
    conflict tests need a scheduled class occupying the room in the way
    `ops/availability.py` counts it, and status is irrelevant to booking
    overlap beyond being one of the occupying statuses.
    """

    def setUp(self):
        super().setUp()
        self.session.status = SessionStatus.SCHEDULED
        self.session.save(update_fields=["status"])
        self.client.force_login(self.ifo)
        # A day with nothing on it, so the "free window" tests are unambiguous.
        self.free_day = self.session.date + timedelta(days=7)

    def _payload(self, **over):
        base = {"occupant_name": "Org Fair", "purpose": "Booth setup",
                "room": str(self.room.pk), "date": self.free_day.isoformat(),
                "start_time": "13:00", "end_time": "15:00"}
        base.update(over)
        return base

    def _create(self, **over):
        return self.client.post(reverse("ifo_booking_create"),
                                self._payload(**over))

    def _aware(self, day, hour, minute=0):
        return timezone.make_aware(
            datetime.combine(day, timezone.datetime.min.time().replace(
                hour=hour, minute=minute)))

    def _booking(self, *, start_hour, end_hour, status="active", day=None):
        day = day or self.free_day
        return Booking.objects.create(
            room=self.room, created_by=self.ifo, occupant_name="Existing",
            start_datetime=self._aware(day, start_hour),
            end_datetime=self._aware(day, end_hour), status=status)


class BookingCreateTests(_BookingBase):
    """Create: the happy path, the refusals, and the two boundary cases."""

    def test_a_free_window_creates_an_active_booking(self):
        resp = self._create()
        self.assertEqual(resp.status_code, 200)
        booking = Booking.objects.get(occupant_name="Org Fair")
        self.assertEqual(booking.status, "active")
        self.assertEqual(booking.created_by_id, self.ifo.pk)
        self.assertEqual(booking.room_id, self.room.pk)

    def test_a_successful_create_is_audited(self):
        self._create()
        booking = Booking.objects.get(occupant_name="Org Fair")
        log = AuditLog.objects.get(event_type="booking.created",
                                   target_id=str(booking.pk))
        self.assertEqual(log.actor_id, self.ifo.pk)
        self.assertEqual(log.payload["room"], self.room.code)

    def test_a_booking_over_a_scheduled_class_is_refused(self):
        """The session fixture is SCHEDULED, non-Online, un-released -- an
        occupant by ops/availability.py's own definition."""
        start = timezone.localtime(self.session.scheduled_start)
        resp = self.client.post(reverse("ifo_booking_create"), self._payload(
            date=self.session.date.isoformat(),
            start_time=start.strftime("%H:%M"),
            end_time=(start + timedelta(minutes=30)).strftime("%H:%M")))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "not free", status_code=400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_future_schedule_occurrence_blocks_booking_before_materialization(self):
        """A recurring class owns its future slot before JOB-01 creates Session.

        Booking availability must consult the active Schedule as well as dated
        Session rows or a booking accepted outside the materialization horizon
        will collide when the class is eventually materialized.
        """
        self.schedule.day_of_week = self.free_day.weekday()
        self.schedule.start_time = timezone.datetime.min.time().replace(hour=13)
        self.schedule.end_time = timezone.datetime.min.time().replace(hour=15)
        self.schedule.save(update_fields=["day_of_week", "start_time", "end_time"])
        self.assertFalse(Session.objects.filter(
            schedule=self.schedule, date=self.free_day).exists())

        resp = self._create(start_time="13:30", end_time="14:00")

        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "not free", status_code=400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_a_booking_over_an_active_booking_is_refused(self):
        self._booking(start_hour=13, end_hour=15)
        resp = self._create(start_time="14:00", end_time="16:00")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Booking.objects.count(), 1)

    def test_an_abutting_booking_is_allowed(self):
        """HALF-OPEN OVERLAP. New start == existing end does NOT collide, which
        is what ops/availability.py means by free. A naive inclusive comparison
        refuses this, and refusing it would make back-to-back bookings of the
        same room impossible."""
        self._booking(start_hour=13, end_hour=15)
        resp = self._create(start_time="15:00", end_time="17:00")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.filter(status="active").count(), 2)

    def test_a_booking_over_an_online_session_is_allowed(self):
        """An online class does not occupy a physical room. A naive "any
        session in this room" query would refuse this and needlessly lock a
        room nobody is in."""
        self.session.declared_modality = Modality.ONLINE
        self.session.save(update_fields=["declared_modality"])

        start = timezone.localtime(self.session.scheduled_start)
        resp = self.client.post(reverse("ifo_booking_create"), self._payload(
            date=self.session.date.isoformat(),
            start_time=start.strftime("%H:%M"),
            end_time=(start + timedelta(minutes=30)).strftime("%H:%M")))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)

    def test_a_cancelled_booking_does_not_block_the_same_window(self):
        self._booking(start_hour=13, end_hour=15, status="cancelled")
        resp = self._create()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Booking.objects.filter(status="active").count(), 1)

    # --- malformed input is a friendly 400, never a 500 -------------------

    def test_malformed_input_is_a_friendly_400_and_creates_nothing(self):
        """Each of these reaches the ORM as an unhandled ValidationError -- a
        500 -- unless FORMAT is settled before the write (CR-04)."""
        cases = {
            "bad date": {"date": "not-a-date"},
            "bad start time": {"start_time": "25:99"},
            "bad end time": {"end_time": "nope"},
            "non-numeric room pk": {"room": "abc"},
            "inverted window": {"start_time": "15:00", "end_time": "13:00"},
            "zero-length window": {"start_time": "13:00", "end_time": "13:00"},
            "missing occupant": {"occupant_name": ""},
        }
        for label, over in cases.items():
            with self.subTest(case=label):
                resp = self._create(**over)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(Booking.objects.count(), 0)

    def test_a_nonexistent_room_pk_is_a_friendly_400(self):
        resp = self._create(room="999999")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Booking.objects.count(), 0)

    def test_a_get_on_the_create_url_is_405(self):
        self.assertEqual(
            self.client.get(reverse("ifo_booking_create")).status_code, 405)


class BookingCancelTests(_BookingBase):
    """Cancel is a status flip, and the flip alone frees the room (D-10)."""

    def test_cancel_flips_status_and_audits(self):
        booking = self._booking(start_hour=13, end_hour=15)
        resp = self.client.post(
            reverse("ifo_booking_cancel", args=[booking.pk]))
        self.assertEqual(resp.status_code, 200)

        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        log = AuditLog.objects.get(event_type="booking.cancelled",
                                   target_id=str(booking.pk))
        self.assertEqual(log.actor_id, self.ifo.pk)

    def test_cancelling_frees_the_room_for_that_window(self):
        """Asserted against room_is_free directly, not against the status
        column -- freeing the room is the property D-10 promises, and the
        status flip is merely how it is achieved."""
        booking = self._booking(start_hour=13, end_hour=15)
        start = self._aware(self.free_day, 13)
        end = self._aware(self.free_day, 15)
        self.assertFalse(room_is_free(self.room, start, end))

        self.client.post(reverse("ifo_booking_cancel", args=[booking.pk]))

        self.assertTrue(room_is_free(self.room, start, end))

    def test_a_second_cancel_refuses_at_400_and_writes_no_second_audit_row(self):
        booking = self._booking(start_hour=13, end_hour=15)
        self.client.post(reverse("ifo_booking_cancel", args=[booking.pk]))

        resp = self.client.post(
            reverse("ifo_booking_cancel", args=[booking.pk]))
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "already", status_code=400)
        self.assertEqual(
            AuditLog.objects.filter(event_type="booking.cancelled",
                                    target_id=str(booking.pk)).count(), 1)

    def test_a_cancelled_booking_is_not_deleted(self):
        """Deleting the row would destroy the record that a booking existed
        AND silently change what blocks a room delete (07-02 PROTECT)."""
        booking = self._booking(start_hour=13, end_hour=15)
        self.client.post(reverse("ifo_booking_cancel", args=[booking.pk]))
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())

    def test_a_cancelled_booking_still_appears_in_the_list(self):
        booking = self._booking(start_hour=13, end_hour=15)
        self.client.post(reverse("ifo_booking_cancel", args=[booking.pk]))

        resp = self.client.get(reverse("ifo_bookings"))
        self.assertContains(resp, f'data-booking="{booking.pk}"')
        self.assertContains(resp, 'data-status="cancelled"')

    def test_a_cancelled_booking_still_blocks_a_room_delete(self):
        """D-19: all bookings count as blockers, including cancelled ones. An
        operator who cannot find the booking in the list cannot understand the
        refusal it causes -- which is why the list shows cancelled rows."""
        booking = self._booking(start_hour=13, end_hour=15)
        self.client.post(reverse("ifo_booking_cancel", args=[booking.pk]))

        blockers = room_delete_blockers(self.room)
        self.assertGreaterEqual(blockers.get("bookings", 0), 1)

    def test_a_get_on_the_cancel_url_is_405(self):
        booking = self._booking(start_hour=13, end_hour=15)
        resp = self.client.get(
            reverse("ifo_booking_cancel", args=[booking.pk]))
        self.assertEqual(resp.status_code, 405)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "active")

    def test_cancelling_an_unknown_booking_is_a_404(self):
        self.assertEqual(self.client.post(
            reverse("ifo_booking_cancel", args=[999999])).status_code, 404)


class BookingListTests(_BookingBase):
    """The list surface itself."""

    def test_the_list_renders_its_empty_state(self):
        resp = self.client.get(reverse("ifo_bookings"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-empty="1"')

    def test_the_list_shows_an_active_booking(self):
        booking = self._booking(start_hour=13, end_hour=15)
        resp = self.client.get(reverse("ifo_bookings"))
        self.assertContains(resp, f'data-booking="{booking.pk}"')
        self.assertContains(resp, 'data-status="active"')

    def test_a_post_on_the_list_url_is_405(self):
        self.assertEqual(
            self.client.post(reverse("ifo_bookings")).status_code, 405)

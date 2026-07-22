"""IFO room CRUD tests (IFO-01b): create, edit, the named delete refusal, authz.

Its own module rather than another class in web/tests.py, following the
larger-surface convention already set by web/tests_ifo_board.py,
web/tests_hr.py and web/tests_pagination.py.

The load-bearing assertions here are the REFUSAL ones, and they deliberately
read the RENDERED PAGE rather than the return value of
`campus.services.room_delete_blockers`. D-17's whole point is that the operator
is TOLD what is blocking the delete; a probe that computes the right answer and
never displays it satisfies the function and fails the requirement. The probe
itself is unit-tested in campus/tests.py -- these tests cover the surface.

Two cases are easy to under-test and are called out explicitly:

  * `reservations` (ModalityShiftItem.assigned_room) is SET_NULL, so PROTECT
    provably does NOT fire for it. The probe is the ONLY control that exists on
    that relation -- without it the delete succeeds and silently empties an
    approved reservation. Its test therefore uses a room with NO other blocker.
  * Editing a room must leave qr_token and manual_code BYTE-IDENTICAL. A
    silent remint would kill the poster taped to the door, and the failure
    would only surface when a faculty member could not check in.

The three known pre-existing dev-login / home-redirect failures in web/tests.py
are unrelated to this module and are not chased here.

ASCII-only.
"""
from datetime import time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from ops.models import AuditLog, Booking
from scheduling.models import (AcademicTerm, Modality, ModalityShiftItem,
                               ModalityShiftRequest, ModalityShiftStatus,
                               Schedule, Session)
from verification.models import CheckerValidation, ValidationAction


class _RoomCrudBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.today = timezone.localdate()
        self.building = Building.objects.create(name="Academic", code="ACAD")
        self.floor = Floor.objects.create(building=self.building, number=3)
        self.other_floor = Floor.objects.create(building=self.building, number=4)
        self.term = AcademicTerm.objects.create(
            name="T1", start_date=self.today - timedelta(days=30),
            end_date=self.today + timedelta(days=30),
            status=AcademicTerm.Status.ACTIVE)
        self.ifo = User.objects.create(
            username="ifo_rooms", email="ifo_rooms@mcm.edu.ph",
            role=Role.IFO_ADMIN, is_active=True)
        self.faculty = User.objects.create(
            username="fac_rooms", email="fac_rooms@mcm.edu.ph",
            role=Role.FACULTY, last_name="Reyes", is_active=True)
        self.checker = User.objects.create(
            username="chk_rooms", email="chk_rooms@mcm.edu.ph",
            role=Role.CHECKER, is_active=True)
        self._room_n = 0

    def _room(self, code=None):
        self._room_n += 1
        n = self._room_n
        return Room.objects.create(
            floor=self.floor, code=code or f"R40{n}",
            qr_token=f"tok-crud-{n}", manual_code=f"7100{n:02d}")

    def _schedule(self, room):
        return Schedule.objects.create(
            term=self.term, course_code="IT301", section="A",
            faculty=self.faculty, room=room, day_of_week=0,
            start_time=time(10, 0), end_time=time(11, 0), modality=Modality.F2F)

    def _session(self, room):
        start = timezone.make_aware(
            timezone.datetime.combine(self.today, time(10, 0)))
        return Session.objects.create(
            schedule=self._schedule(room), faculty=self.faculty, room=room,
            date=self.today, scheduled_start=start,
            scheduled_end=start + timedelta(hours=1))

    def _booking(self, room, status="active"):
        start = timezone.now()
        return Booking.objects.create(
            room=room, created_by=self.ifo, occupant_name="Org Fair",
            start_datetime=start, end_datetime=start + timedelta(hours=2),
            status=status)

    def _validation(self, room):
        return CheckerValidation.objects.create(
            room=room, checker=self.checker,
            action=ValidationAction.VERIFIED_EMPTY)

    def _reservation(self, room):
        """An APPROVED modality-shift reservation holding `room`.

        Built on a schedule in a DIFFERENT room on purpose: the shift moves a
        class OUT of its own room and reserves this one, so `room` picks up the
        `assigned_room` reference and nothing else. That isolation is the whole
        point -- it proves the probe, not PROTECT, is what refuses the delete.
        """
        origin = self._room()
        request = ModalityShiftRequest.objects.create(
            requester=self.faculty, target_modality=Modality.F2F,
            window_start=self.today, window_end=self.today,
            status=ModalityShiftStatus.APPROVED)
        return ModalityShiftItem.objects.create(
            request=request, schedule=self._schedule(origin),
            assigned_room=room)


class RoomCreateEditTests(_RoomCrudBase):
    """Create mints credentials from the shared minter; edit never touches them."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_create_form_renders(self):
        resp = self.client.get(reverse("ifo_room_new"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Room code")

    def test_new_room_is_born_scannable(self):
        """A room with no credentials is unusable -- it cannot be postered and
        cannot be scanned. Create must mint both halves, via campus.codes."""
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R501", "name": "Lecture Hall",
            "floor": self.floor.pk, "capacity": "45"})
        self.assertEqual(resp.status_code, 302)

        room = Room.objects.get(code="R501")
        self.assertEqual(room.name, "Lecture Hall")
        self.assertEqual(room.capacity, 45)
        self.assertEqual(room.floor_id, self.floor.pk)
        self.assertTrue(room.qr_token)
        self.assertEqual(len(room.manual_code), 6)
        self.assertTrue(room.manual_code.isdigit())

    def test_create_uppercases_the_code(self):
        self.client.post(reverse("ifo_room_new"), {
            "code": " r502 ", "floor": self.floor.pk, "capacity": "0"})
        self.assertTrue(Room.objects.filter(code="R502").exists())

    def test_create_audits(self):
        self.client.post(reverse("ifo_room_new"), {
            "code": "R503", "floor": self.floor.pk, "capacity": "30"})
        room = Room.objects.get(code="R503")
        log = AuditLog.objects.get(event_type="room.created",
                                   target_id=str(room.pk))
        self.assertEqual(log.actor, self.ifo)
        self.assertEqual(log.payload["code"], "R503")
        self.assertEqual(log.payload["capacity"], 30)

    def test_duplicate_code_is_a_400_and_creates_nothing(self):
        existing = self._room(code="R601")
        before = Room.objects.count()
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R601", "floor": self.floor.pk, "capacity": "10"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "already exists", status_code=400)
        self.assertEqual(Room.objects.count(), before)
        existing.refresh_from_db()
        self.assertEqual(existing.qr_token, "tok-crud-1")

    def test_duplicate_code_in_another_case_is_still_a_duplicate(self):
        """The code column is case-insensitive, so r601 and R601 are one key.
        Naming it up front beats surfacing a UNIQUE violation."""
        self._room(code="R602")
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "r602", "floor": self.floor.pk, "capacity": "10"})
        self.assertEqual(resp.status_code, 400)

    def test_non_numeric_floor_is_a_friendly_400_not_a_500(self):
        """A non-numeric pk reaches Floor.objects.filter(pk=...) as an
        unhandled ValidationError unless format is checked first (CR-04)."""
        before = Room.objects.count()
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R603", "floor": "not-a-floor", "capacity": "10"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Select a floor", status_code=400)
        self.assertEqual(Room.objects.count(), before)

    def test_non_numeric_capacity_is_a_friendly_400_not_a_500(self):
        before = Room.objects.count()
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R604", "floor": self.floor.pk, "capacity": "many"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "whole number", status_code=400)
        self.assertEqual(Room.objects.count(), before)

    def test_negative_capacity_is_a_friendly_400(self):
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R605", "floor": self.floor.pk, "capacity": "-5"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Room.objects.filter(code="R605").count(), 0)

    def test_missing_code_is_a_friendly_400(self):
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "", "floor": self.floor.pk, "capacity": "10"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, "Enter a room code", status_code=400)

    def test_a_nonexistent_floor_pk_is_a_friendly_400(self):
        resp = self.client.post(reverse("ifo_room_new"), {
            "code": "R606", "floor": "999999", "capacity": "10"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Room.objects.filter(code="R606").count(), 0)

    def test_edit_form_renders_bound_to_the_room(self):
        room = self._room()
        resp = self.client.get(reverse("ifo_room_edit", args=[room.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, room.code)

    def test_edit_changes_the_editable_fields(self):
        room = self._room()
        resp = self.client.post(reverse("ifo_room_edit", args=[room.code]), {
            "name": "Renamed Hall", "floor": self.other_floor.pk,
            "capacity": "80"})
        self.assertEqual(resp.status_code, 302)
        room.refresh_from_db()
        self.assertEqual(room.name, "Renamed Hall")
        self.assertEqual(room.capacity, 80)
        self.assertEqual(room.floor_id, self.other_floor.pk)

    def test_edit_never_rotates_the_credentials(self):
        """The poster taped to the door must survive an edit. Rotation is a
        separate, deliberate, confirmed act (IFO-02)."""
        room = self._room()
        before_token, before_code = room.qr_token, room.manual_code

        self.client.post(reverse("ifo_room_edit", args=[room.code]), {
            "name": "Still The Same Room", "floor": self.other_floor.pk,
            "capacity": "12"})

        room.refresh_from_db()
        self.assertEqual(room.qr_token, before_token)
        self.assertEqual(room.manual_code, before_code)

    def test_edit_audits_the_changed_fields_with_before_values(self):
        room = self._room()
        room.capacity = 20
        room.save(update_fields=["capacity"])

        self.client.post(reverse("ifo_room_edit", args=[room.code]), {
            "name": "", "floor": self.floor.pk, "capacity": "55"})

        log = AuditLog.objects.get(event_type="room.updated",
                                   target_id=str(room.pk))
        self.assertIn("capacity", log.payload["changed"])
        self.assertEqual(log.payload["before"]["capacity"], 20)

    def test_edit_with_a_bad_floor_is_a_400_and_changes_nothing(self):
        room = self._room()
        resp = self.client.post(reverse("ifo_room_edit", args=[room.code]), {
            "name": "Nope", "floor": "xyz", "capacity": "10"})
        self.assertEqual(resp.status_code, 400)
        room.refresh_from_db()
        self.assertEqual(room.name, "")

    def test_edit_of_an_unknown_room_is_a_404(self):
        resp = self.client.get(reverse("ifo_room_edit", args=["NOPE999"]))
        self.assertEqual(resp.status_code, 404)

    def test_new_is_not_swallowed_by_the_room_code_pattern(self):
        """`ifo/rooms/new` must resolve to the create form, not to a room
        whose code happens to be 'new'."""
        self.assertEqual(reverse("ifo_room_new"), "/ifo/rooms/new")
        resp = self.client.get("/ifo/rooms/new")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create room")


class RoomDeleteRefusalTests(_RoomCrudBase):
    """A blocked delete NAMES every blocking relation on screen and removes nothing.

    Every assertion below reads the rendered page. That is the requirement:
    D-17 is about what the operator is told, not about what the probe returns.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def _get_delete(self, room):
        return self.client.get(reverse("ifo_room_delete", args=[room.code]))

    def test_a_schedule_names_schedules(self):
        room = self._room()
        self._schedule(room)
        resp = self._get_delete(room)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Recurring class schedules")
        self.assertContains(resp, 'data-blocker="schedules"')

    def test_a_session_names_sessions(self):
        room = self._room()
        self._session(room)
        resp = self._get_delete(room)
        self.assertContains(resp, "Class sessions")
        self.assertContains(resp, 'data-blocker="sessions"')

    def test_a_booking_names_bookings(self):
        room = self._room()
        self._booking(room)
        resp = self._get_delete(room)
        self.assertContains(resp, "Ad-hoc bookings")
        self.assertContains(resp, 'data-blocker="bookings"')

    def test_a_cancelled_booking_still_blocks(self):
        """Availability and deletability are different questions: a cancelled
        booking no longer occupies the room, but it is still history the
        pre-D-19 CASCADE would have destroyed."""
        room = self._room()
        self._booking(room, status="cancelled")
        resp = self._get_delete(room)
        self.assertContains(resp, 'data-blocker="bookings"')

    def test_a_checker_validation_names_validations(self):
        room = self._room()
        self._validation(room)
        resp = self._get_delete(room)
        self.assertContains(resp, "Checker validations")
        self.assertContains(resp, 'data-blocker="validations"')

    def test_an_approved_reservation_alone_names_reservations(self):
        """assigned_room is SET_NULL, so PROTECT never fires here -- without
        the probe this delete SUCCEEDS and silently empties a live approved
        reservation. The probe is the only control on this relation."""
        room = self._room()
        self._reservation(room)
        self.assertEqual(room.schedules.count(), 0)
        self.assertEqual(room.sessions.count(), 0)
        self.assertEqual(room.bookings.count(), 0)
        self.assertEqual(room.validations.count(), 0)

        resp = self._get_delete(room)
        self.assertContains(resp, "Approved modality-shift reservations")
        self.assertContains(resp, 'data-blocker="reservations"')

    def test_an_approved_reservation_alone_actually_blocks_the_post(self):
        room = self._room()
        self._reservation(room)
        resp = self.client.post(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())

    def test_several_blockers_are_all_named_on_one_page(self):
        room = self._room()
        self._session(room)          # brings a schedule with it
        self._booking(room)
        self._validation(room)
        self._reservation(room)

        resp = self._get_delete(room)
        for relation in ("schedules", "sessions", "bookings", "validations",
                         "reservations"):
            self.assertContains(resp, f'data-blocker="{relation}"')

    def test_a_blocked_confirm_page_offers_no_delete_button(self):
        """The refusal is not advisory, so there is no delete-anyway control."""
        room = self._room()
        self._schedule(room)
        resp = self._get_delete(room)
        self.assertNotContains(resp, "uk-btn-destructive")
        self.assertContains(resp, "cannot be deleted")

    def test_post_on_a_blocked_room_deletes_nothing_and_returns_400(self):
        room = self._room()
        self._session(room)
        resp = self.client.post(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        self.assertContains(resp, "cannot be deleted", status_code=400)

    def test_a_refusal_is_audited_with_the_blocker_counts(self):
        room = self._room()
        self._session(room)
        self._booking(room)
        self.client.post(reverse("ifo_room_delete", args=[room.code]))

        log = AuditLog.objects.get(event_type="room.delete_refused",
                                   target_id=str(room.pk))
        self.assertEqual(log.actor, self.ifo)
        self.assertEqual(log.payload["code"], room.code)
        self.assertEqual(log.payload["blockers"]["sessions"], 1)
        self.assertEqual(log.payload["blockers"]["bookings"], 1)
        self.assertEqual(log.payload["blockers"]["schedules"], 1)

    def test_a_referenced_room_never_500s(self):
        """The whole point of the probe: a ProtectedError must never reach the
        operator as a server error."""
        room = self._room()
        self._validation(room)
        resp = self.client.post(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 400)

    def test_the_protected_error_backstop_catches_what_the_probe_misses(self):
        """The second of the two controls, exercised on its own.

        In production this path is a race -- a reference appearing between the
        POST-time probe and the .delete(). Blinding the probe reproduces that
        deterministically and proves the backstop is load-bearing rather than
        decorative: with a real PROTECT reference present and the probe
        returning nothing, the delete must STILL be refused as a friendly 400
        with nothing removed, never a ProtectedError 500.
        """
        room = self._room()
        self._schedule(room)

        with mock.patch("web.ifo.room_delete_blockers", return_value={}):
            resp = self.client.post(
                reverse("ifo_room_delete", args=[room.code]))

        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        log = AuditLog.objects.get(event_type="room.delete_refused",
                                   target_id=str(room.pk))
        self.assertTrue(log.payload["protected_error"])


class RoomDeleteAllowedTests(_RoomCrudBase):
    """A genuinely unused room deletes, and the deletion is audit-logged."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)

    def test_confirm_page_offers_the_delete_when_nothing_references_it(self):
        room = self._room()
        resp = self.client.get(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nothing references this room")
        self.assertContains(resp, "uk-btn-destructive")

    def test_an_unused_room_deletes_and_redirects(self):
        room = self._room()
        pk = room.pk
        resp = self.client.post(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("ifo_rooms"))
        self.assertFalse(Room.objects.filter(pk=pk).exists())

    def test_the_delete_is_audited(self):
        room = self._room()
        pk, code = room.pk, room.code
        self.client.post(reverse("ifo_room_delete", args=[code]))

        log = AuditLog.objects.get(event_type="room.deleted",
                                   target_id=str(pk))
        self.assertEqual(log.actor, self.ifo)
        self.assertEqual(log.payload["code"], code)

    def test_a_faculty_preference_does_not_block(self):
        """preferred_room is a faculty PREFERENCE, not a reservation -- the
        server re-resolves the room at approval, so a preference pointing at a
        deleted room is meaningless rather than lost data."""
        room = self._room()
        origin = self._room()
        request = ModalityShiftRequest.objects.create(
            requester=self.faculty, target_modality=Modality.F2F,
            window_start=self.today, window_end=self.today,
            status=ModalityShiftStatus.PENDING)
        ModalityShiftItem.objects.create(
            request=request, schedule=self._schedule(origin),
            preferred_room=room)

        resp = self.client.post(reverse("ifo_room_delete", args=[room.code]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Room.objects.filter(code=room.code).exists())

    def test_delete_of_an_unknown_room_is_a_404(self):
        resp = self.client.get(reverse("ifo_room_delete", args=["NOPE999"]))
        self.assertEqual(resp.status_code, 404)


class RoomCrudAuthzTests(_RoomCrudBase):
    """Three-way authz on every new URL: IFO ok, other role 403, anon to login."""

    def setUp(self):
        super().setUp()
        self.room = self._room()

    def _urls(self):
        return [
            reverse("ifo_room_new"),
            reverse("ifo_room_edit", args=[self.room.code]),
            reverse("ifo_room_delete", args=[self.room.code]),
        ]

    def test_ifo_reaches_every_room_crud_url(self):
        self.client.force_login(self.ifo)
        for url in self._urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_non_ifo_authenticated_user_gets_403(self):
        self.client.force_login(self.faculty)
        for url in self._urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_a_non_ifo_user_cannot_post_either(self):
        """A 403 on GET with an unguarded POST would be no gate at all."""
        self.client.force_login(self.checker)
        for url in self._urls():
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_an_anonymous_user_is_redirected_to_login(self):
        for url in self._urls():
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login", resp["Location"])


class RoomRotateTests(_RoomCrudBase):
    """IFO-02: rotating a room's scan credentials (plan 07-04).

    The load-bearing assertions here are the DEATH ones, not the difference
    ones. IFO-02 promises that rotating invalidates the poster on the door, and
    "the value changed" is a strictly weaker claim than "the old value no
    longer resolves to any room" -- an implementation that rotated only the QR
    token and left the six-digit code alone would pass an inequality check on
    one column and still leave a live credential printed on a poster the
    operator believes is dead.
    """

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ifo)
        self.room = self._room(code="R701")

    def _rotate(self, room=None):
        room = room or self.room
        return self.client.post(reverse("ifo_room_rotate", args=[room.code]))

    # --- the credentials actually change ---------------------------------

    def test_rotation_changes_both_credentials(self):
        before_token, before_code = self.room.qr_token, self.room.manual_code
        self._rotate()
        self.room.refresh_from_db()
        self.assertNotEqual(self.room.qr_token, before_token)
        self.assertNotEqual(self.room.manual_code, before_code)

    def test_the_old_credentials_no_longer_resolve_to_any_room(self):
        """The property IFO-02 actually promises. Asserted against the whole
        Room table, not against this row, because "invalidated" means the old
        poster resolves to NOTHING -- not merely to something else."""
        before_token, before_code = self.room.qr_token, self.room.manual_code
        self._rotate()
        self.assertFalse(Room.objects.filter(qr_token=before_token).exists())
        self.assertFalse(Room.objects.filter(manual_code=before_code).exists())

    def test_the_new_credentials_are_well_formed(self):
        self._rotate()
        self.room.refresh_from_db()
        self.assertTrue(self.room.qr_token)
        self.assertEqual(len(self.room.manual_code), 6)
        self.assertTrue(self.room.manual_code.isdigit())

    # --- the stamps and the audit trail ----------------------------------

    def test_rotation_stamps_who_and_when(self):
        self.assertIsNone(self.room.code_rotated_at)
        before = timezone.now()
        self._rotate()
        self.room.refresh_from_db()
        self.assertIsNotNone(self.room.code_rotated_at)
        self.assertGreaterEqual(self.room.code_rotated_at, before)
        self.assertEqual(self.room.code_rotated_by_id, self.ifo.pk)

    def test_rotation_writes_exactly_one_audit_row(self):
        self._rotate()
        logs = AuditLog.objects.filter(event_type="room.code_rotated",
                                       target_id=str(self.room.pk))
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().actor, self.ifo)
        self.assertEqual(logs.first().payload["code"], "R701")

    def test_the_audit_payload_leaks_no_credential_value(self):
        """qr_token and manual_code are resolver-only secrets (SCAN-07). The
        AuditLog table is read far more widely than the two columns it would be
        describing, so neither the dead nor the live pair may appear in it."""
        old_token, old_code = self.room.qr_token, self.room.manual_code
        self._rotate()
        self.room.refresh_from_db()

        payload = str(AuditLog.objects.get(
            event_type="room.code_rotated",
            target_id=str(self.room.pk)).payload)
        for secret in (old_token, old_code,
                       self.room.qr_token, self.room.manual_code):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, payload)

    # --- D-14: the destructive act lands on its remedy -------------------

    def test_rotation_redirects_to_that_rooms_poster(self):
        resp = self._rotate()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"],
                         reverse("ifo_room_poster", args=[self.room.code]))

    def test_the_poster_shows_the_rotation_stamp_after_a_rotation(self):
        self._rotate()
        resp = self.client.get(
            reverse("ifo_room_poster", args=[self.room.code]))
        self.assertContains(resp, "data-rotated-stamp")

    # --- method contract --------------------------------------------------

    def test_the_confirm_page_names_the_room_and_the_consequence(self):
        resp = self.client.get(
            reverse("ifo_room_rotate_confirm", args=[self.room.code]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "R701")
        self.assertContains(resp, "invalidates the current poster")

    def test_a_get_on_the_rotate_action_is_405(self):
        """A GET-reachable rotation would fire on a link prefetch or an
        accidental reload, silently killing a poster nobody asked about."""
        resp = self.client.get(
            reverse("ifo_room_rotate", args=[self.room.code]))
        self.assertEqual(resp.status_code, 405)
        self.room.refresh_from_db()
        self.assertIsNone(self.room.code_rotated_at)

    def test_a_post_on_the_confirm_page_is_405(self):
        resp = self.client.post(
            reverse("ifo_room_rotate_confirm", args=[self.room.code]))
        self.assertEqual(resp.status_code, 405)

    def test_rotating_an_unknown_room_is_a_404(self):
        resp = self.client.get(
            reverse("ifo_room_rotate_confirm", args=["NOPE999"]))
        self.assertEqual(resp.status_code, 404)

    # --- the collision the shared minter exists to absorb -----------------

    def test_a_colliding_first_draw_still_rotates_cleanly(self):
        """Deterministic, not probabilistic. The defect this guards was
        observed in the importer at roughly 2.3% per full room load; a random
        test would reproduce the bug's worst property (intermittence) rather
        than catch it. So the code source is forced to hand back a value
        another Room already holds, and the rotation must still succeed by
        drawing again -- which only happens if this view goes through
        campus.codes.generate_manual_code instead of minting inline.
        """
        taken = self._room(code="R702")
        collide = int(taken.manual_code)

        with mock.patch("campus.codes.secrets.randbelow",
                        side_effect=[collide, 424242]):
            resp = self._rotate()

        self.assertEqual(resp.status_code, 302)
        self.room.refresh_from_db()
        self.assertEqual(self.room.manual_code, "424242")
        taken.refresh_from_db()
        self.assertEqual(int(taken.manual_code), collide)


class RoomRotateAuthzTests(_RoomCrudBase):
    """Three-way authz on both rotation URLs."""

    def setUp(self):
        super().setUp()
        self.room = self._room(code="R703")

    def test_ifo_reaches_the_confirm_page(self):
        self.client.force_login(self.ifo)
        resp = self.client.get(
            reverse("ifo_room_rotate_confirm", args=[self.room.code]))
        self.assertEqual(resp.status_code, 200)

    def test_a_non_ifo_authenticated_user_gets_403_on_both(self):
        self.client.force_login(self.faculty)
        self.assertEqual(self.client.get(
            reverse("ifo_room_rotate_confirm", args=[self.room.code])
        ).status_code, 403)
        self.assertEqual(self.client.post(
            reverse("ifo_room_rotate", args=[self.room.code])
        ).status_code, 403)
        self.room.refresh_from_db()
        self.assertIsNone(self.room.code_rotated_at)

    def test_an_anonymous_user_is_redirected_to_login_on_both(self):
        for url in (reverse("ifo_room_rotate_confirm", args=[self.room.code]),
                    reverse("ifo_room_rotate", args=[self.room.code])):
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 302)
                self.assertIn("/login", resp["Location"])

"""Collation round-trip proofs (phase success criterion 3).

Proves both directions of the surgical collation strategy from
`campus/migrations/0002_cs_collation_tokens.py`, on the real SQL Server test DB:

- The two opaque token columns (`qr_token`, `manual_code`) are case-SENSITIVE:
  case-variant tokens stay distinct rows AND still enforce uniqueness (a duplicate
  raises IntegrityError — the hard proof the CS-collation migration did not drop
  the unique constraint).
- Faculty emails stay case-INsensitive (the DB default collation): case-variant
  emails dedupe to a single faculty via get_or_create. If this half fails, the
  server/DB default collation is `_CS_` (RESEARCH Pitfall 4), not a code bug here.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from campus.codes import (MANUAL_CODE_SPACE, ManualCodeExhausted,
                          generate_manual_code)
from campus.models import Building, Floor, Room


class CollationRoundTripTests(TestCase):
    def setUp(self):
        building = Building.objects.create(name="R", code="R")
        self.floor = Floor.objects.create(building=building, number=3)

    def test_qr_tokens_differing_only_in_case_stay_distinct(self):
        # CS collation on qr_token → "AbC" and "abc" are two distinct rows.
        Room.objects.create(code="R1", qr_token="AbC", manual_code="000001", floor=self.floor)
        Room.objects.create(code="R2", qr_token="abc", manual_code="000002", floor=self.floor)
        self.assertEqual(Room.objects.filter(qr_token__in=["AbC", "abc"]).count(), 2)
        # Exact-case lookup is case-sensitive → resolves to exactly the first room.
        self.assertEqual(Room.objects.get(qr_token="AbC").code, "R1")

    def test_duplicate_token_still_raises_integrityerror(self):
        # The hard gate: recollating a unique column must not silently drop
        # uniqueness. An identical token must still violate the constraint.
        Room.objects.create(code="R3", qr_token="DUP", manual_code="000003", floor=self.floor)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(code="R4", qr_token="DUP", manual_code="000004", floor=self.floor)

    def test_manual_code_mint_skips_a_taken_code(self):
        # The regression proof. Forcing the RNG to return an already-held code
        # twice must NOT produce a duplicate (which is how the real bug
        # surfaced: pyodbc IntegrityError on UQ_campus_room_manual_code, ~2.3%
        # of full-term loads). The helper must draw again and hand back the
        # first free code instead.
        Room.objects.create(code="R9", qr_token="tok-r9", manual_code="814918",
                            floor=self.floor)
        with mock.patch("campus.codes.secrets.randbelow",
                        side_effect=[814918, 814918, 123456]) as draw:
            code = generate_manual_code()
        self.assertEqual(code, "123456")
        self.assertEqual(draw.call_count, 3)

        # And the code it hands back is actually insertable — the property the
        # caller depends on and the one the old code violated.
        Room.objects.create(code="R10", qr_token="tok-r10", manual_code=code,
                            floor=self.floor)
        self.assertEqual(Room.objects.filter(manual_code="123456").count(), 1)

    def test_manual_code_mint_is_zero_padded_to_six_digits(self):
        # A small draw must not yield a 1-char code: manual_code is max_length=6
        # and the poster/keypad surfaces assume exactly six digits.
        with mock.patch("campus.codes.secrets.randbelow", return_value=7):
            self.assertEqual(generate_manual_code(), "000007")

    def test_manual_code_mint_raises_named_error_when_exhausted(self):
        # Fails loudly with a domain error rather than spinning inside the
        # importer's open transaction.
        Room.objects.create(code="R11", qr_token="tok-r11", manual_code="000042",
                            floor=self.floor)
        with mock.patch("campus.codes.secrets.randbelow", return_value=42):
            with self.assertRaises(ManualCodeExhausted):
                generate_manual_code(attempts=3)

    def test_manual_code_space_matches_column_width(self):
        # Guards the pair: widening the draw space without widening
        # manual_code(max_length=6) would truncate/500 on insert.
        self.assertEqual(MANUAL_CODE_SPACE, 1000000)
        field = Room._meta.get_field("manual_code")
        self.assertEqual(field.max_length, len(str(MANUAL_CODE_SPACE - 1)))

    def test_case_variant_emails_dedupe_to_one_faculty(self):
        # Default CI collation → get_or_create matches regardless of email case,
        # so a professor is never duplicated on a casing difference.
        User = get_user_model()
        User.objects.create(username="a", email="Jdoe@mcm.edu.ph", role="faculty")
        _, created = User.objects.get_or_create(
            email="jdoe@mcm.edu.ph", defaults={"username": "b", "role": "faculty"}
        )
        self.assertFalse(created)
        self.assertEqual(User.objects.filter(email__iexact="jdoe@mcm.edu.ph").count(), 1)


class RoomDeleteBlockerTests(TestCase):
    """`room_delete_blockers` must name EVERY relation that blocks a room delete.

    D-17 named three (Schedule, Session, Booking); D-20 added CheckerValidation.
    The fifth — ModalityShiftItem.assigned_room — is the one no decision named
    and the one PROTECT cannot catch, because that FK is SET_NULL: the delete
    SUCCEEDS and silently nulls a Dean-approved room reservation. This probe is
    the only control that sees it, so these tests assert on the specific key,
    not merely on truthiness.

    Cross-app models are imported method-locally (the ops/tests.py:128 idiom) so
    campus/tests.py stays import-light and campus gains no upward dependency.
    """

    def setUp(self):
        self.building = Building.objects.create(name="R", code="R")
        self.floor = Floor.objects.create(building=self.building, number=3)
        # The room under test — nothing references it until a test says so.
        self.room = Room.objects.create(
            floor=self.floor, code="R401", qr_token="tok-blk-401", manual_code="940401")
        # A second room to absorb the NOT NULL PROTECT room FK on the Schedule
        # rows the modality fixtures need, so the room under test can be left
        # referenced by assigned_room ALONE.
        self.other = Room.objects.create(
            floor=self.floor, code="R402", qr_token="tok-blk-402", manual_code="940402")

    def _faculty(self, username="fac_blk"):
        User = get_user_model()
        return User.objects.create(
            username=username, email=f"{username}@mcm.edu.ph", role="faculty")

    def _term(self):
        from datetime import date

        from scheduling.models import AcademicTerm
        return AcademicTerm.objects.create(
            name="Blocker Term", start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31), status=AcademicTerm.Status.ACTIVE)

    def _schedule(self, room, faculty=None, course="BLK101"):
        from datetime import time

        from scheduling.models import Schedule
        return Schedule.objects.create(
            term=self._term(), course_code=course, section="A",
            faculty=faculty or self._faculty(f"fac_{course.lower()}"), room=room,
            day_of_week=0, start_time=time(8, 0), end_time=time(9, 30))

    def test_unreferenced_room_returns_empty_dict(self):
        from campus.services import room_delete_blockers
        self.assertEqual(room_delete_blockers(self.room), {})

    def test_schedule_reference_is_named(self):
        from campus.services import room_delete_blockers
        self._schedule(self.room)
        self.assertEqual(room_delete_blockers(self.room).get("schedules"), 1)

    def test_session_reference_is_named(self):
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        from campus.services import room_delete_blockers
        from scheduling.models import Session
        fac = self._faculty("fac_sess")
        sch = self._schedule(self.other, faculty=fac, course="BLK201")
        start = dt(2026, 7, 6, 8, 0, tzinfo=ZoneInfo("Asia/Manila"))
        # Schedule points at `other`; only the Session points at the room under
        # test, so the assertion isolates the sessions relation.
        Session.objects.create(schedule=sch, faculty=fac, room=self.room,
                               date=start.date(), scheduled_start=start,
                               scheduled_end=start)
        blockers = room_delete_blockers(self.room)
        self.assertEqual(blockers.get("sessions"), 1)
        self.assertNotIn("schedules", blockers)

    def test_cancelled_booking_still_counts_as_a_blocker(self):
        """D-19: a cancelled booking is history CASCADE would have destroyed.

        D-10 treats status != "active" as not occupying the room for AVAILABILITY,
        but availability and deletability are different questions — this probe
        reads "referenced by any Booking" conservatively.
        """
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        from campus.services import room_delete_blockers
        from ops.models import Booking
        start = dt(2026, 7, 6, 8, 0, tzinfo=ZoneInfo("Asia/Manila"))
        Booking.objects.create(room=self.room, occupant_name="Guest",
                               start_datetime=start, end_datetime=start,
                               status="cancelled")
        self.assertEqual(room_delete_blockers(self.room).get("bookings"), 1)

    def test_checker_validation_reference_is_named(self):
        from campus.services import room_delete_blockers
        from verification.models import CheckerValidation, ValidationAction
        CheckerValidation.objects.create(
            room=self.room, checker=self._faculty("chk_blk"),
            action=ValidationAction.VERIFIED_EMPTY)
        self.assertEqual(room_delete_blockers(self.room).get("validations"), 1)

    def test_modality_assigned_room_is_the_fifth_blocker(self):
        """The blocker PROTECT cannot catch.

        assigned_room is SET_NULL, so the database will NOT refuse this delete —
        it succeeds and nulls a live Dean-approved reservation. Asserted on the
        `reservations` key specifically: a bare truthiness assertion would pass
        against a four-relation implementation, which is the exact failure mode
        this test exists to catch.
        """
        from datetime import date

        from campus.services import room_delete_blockers
        from scheduling.models import (Modality, ModalityShiftItem,
                                       ModalityShiftRequest)
        fac = self._faculty("fac_mod")
        req = ModalityShiftRequest.objects.create(
            requester=fac, target_modality=Modality.ONLINE,
            window_start=date(2026, 7, 6), window_end=date(2026, 7, 6))
        # The item's Schedule points at `other`, so assigned_room is the ONLY
        # reference to the room under test.
        ModalityShiftItem.objects.create(
            request=req, schedule=self._schedule(self.other, course="BLK301"),
            assigned_room=self.room)
        self.assertEqual(room_delete_blockers(self.room).get("reservations"), 1)

    def test_preferred_room_alone_is_not_a_blocker(self):
        """A faculty PREFERENCE is not a reservation (D-18 re-resolves at approval)."""
        from datetime import date

        from campus.services import room_delete_blockers
        from scheduling.models import (Modality, ModalityShiftItem,
                                       ModalityShiftRequest)
        fac = self._faculty("fac_pref")
        req = ModalityShiftRequest.objects.create(
            requester=fac, target_modality=Modality.ONLINE,
            window_start=date(2026, 7, 6), window_end=date(2026, 7, 6))
        ModalityShiftItem.objects.create(
            request=req, schedule=self._schedule(self.other, course="BLK401"),
            preferred_room=self.room)
        self.assertEqual(room_delete_blockers(self.room), {})

    def test_every_referencing_relation_is_reported_not_just_the_first(self):
        from datetime import datetime as dt
        from zoneinfo import ZoneInfo

        from campus.services import room_delete_blockers
        from ops.models import Booking
        from scheduling.models import Session
        from verification.models import CheckerValidation, ValidationAction
        fac = self._faculty("fac_multi")
        sch = self._schedule(self.room, faculty=fac, course="BLK501")
        start = dt(2026, 7, 6, 8, 0, tzinfo=ZoneInfo("Asia/Manila"))
        Session.objects.create(schedule=sch, faculty=fac, room=self.room,
                               date=start.date(), scheduled_start=start,
                               scheduled_end=start)
        Booking.objects.create(room=self.room, occupant_name="Guest",
                               start_datetime=start, end_datetime=start)
        CheckerValidation.objects.create(
            room=self.room, checker=fac, action=ValidationAction.VERIFIED_EMPTY)
        self.assertEqual(
            room_delete_blockers(self.room),
            {"schedules": 1, "sessions": 1, "bookings": 1, "validations": 1})

    def test_only_non_zero_relations_appear(self):
        """An empty relation must be ABSENT, not present with a 0 — the UI renders
        whatever it is handed, and "0 bookings" is not a refusal reason."""
        from campus.services import room_delete_blockers
        self._schedule(self.room)
        blockers = room_delete_blockers(self.room)
        self.assertEqual(list(blockers), ["schedules"])
        self.assertNotIn(0, blockers.values())

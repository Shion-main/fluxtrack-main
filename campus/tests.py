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

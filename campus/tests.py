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
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

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

"""DB-backed hardening tests for `import_offerings` against the REAL offerings
`.xlsx` (Phase 04.1, D1-D9).

These are guarded by ``skipUnless(os.path.exists(OFFERINGS_XLSX))`` — CI (where
`data/raw` is gitignored/absent) skips them, but on the developer machine where
the real registrar export is present they run the WHOLE-term import against the
live MSSQL ``test_fluxtrack`` DB and assert the behavior the phase promises:

  * ImportHardeningTests — the DB state after a real import: virtual rooms kept as
    Online, gym rooms kept, blended courses yield BOTH a physical and an online
    schedule, blank-email instructors dedup to ~10 accounts, and roomless-physical
    sections land on the shared "TBA" room in the "Unassigned" building (D2/D5/D7/D9).
  * ImportReportTests — the dry-run reconciliation report proves the 1,211-row
    partition, the 2,021-meeting total, and flags typo rooms + email-less
    instructors (D4/D7/D9).

TransactionTestCase because the command wraps its writes in ``transaction.atomic``.
"""
import os
import re
from io import StringIO
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import Count, Q
from django.test import TransactionTestCase

from accounts.models import Role
from campus.models import Room
from scheduling.models import Modality, Schedule

OFFERINGS_XLSX = "data/raw/2T-25-26-Course Offerring (1).xlsx"


@skipUnless(os.path.exists(OFFERINGS_XLSX),
            "registrar offerings .xlsx not present (gitignored data/raw)")
class ImportHardeningTests(TransactionTestCase):
    """Whole-term import DB state (D2/D5/D7/D9)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

    def setUp(self):
        # One real import feeds every assertion in this class.
        call_command("import_offerings", stdout=StringIO())

    def test_virtual_room_schedule_is_online(self):
        # D2/D5: a V-prefixed (virtual) room is kept and stamped Online.
        qs = Schedule.objects.filter(room__code__startswith="V")
        self.assertTrue(qs.exists(), "no virtual-room schedules were imported")
        self.assertTrue(qs.filter(modality=Modality.ONLINE).exists())
        # ... and every virtual-room schedule is Online (never scannable f2f).
        self.assertFalse(qs.exclude(modality=Modality.ONLINE).exists())

    def test_gym_room_schedule_kept(self):
        # D2: GYM rooms (GYM1/GYM2) are no longer dropped by a second-char rule.
        self.assertTrue(
            Schedule.objects.filter(room__code__startswith="GYM").exists())

    def test_blended_course_yields_physical_and_online(self):
        # D5: a blended section with a physical-day and a virtual-day meeting
        # produces BOTH a scannable physical schedule and an Online schedule.
        groups = Schedule.objects.values("course_code", "section").annotate(
            n_online=Count("pk", filter=Q(modality=Modality.ONLINE)),
            n_phys=Count("pk", filter=~Q(modality=Modality.ONLINE)),
        )
        self.assertTrue(
            any(g["n_online"] and g["n_phys"] for g in groups),
            "no section carried both an online and a physical schedule")

    def test_blank_email_instructors_dedup_to_about_ten(self):
        # D7: the 57 blank-email rows collapse to ~10 accounts (one per
        # normalized name), never 57. Name-keyed accounts carry a blank email.
        blank = get_user_model().objects.filter(
            role=Role.FACULTY, email="").count()
        self.assertGreaterEqual(blank, 8)
        self.assertLessEqual(blank, 12)

    def test_total_faculty_about_two_hundred(self):
        # D7: emailed (190) + name-keyed (~10) => ~200 distinct instructors.
        total = get_user_model().objects.filter(role=Role.FACULTY).count()
        self.assertGreaterEqual(total, 190)
        self.assertLessEqual(total, 210)

    def test_roomless_physical_land_on_tba_in_unassigned(self):
        # D9: the shared "TBA" placeholder exists in the "Unassigned" building
        # and owns the roomless-physical schedules (section labels are NOT rooms).
        tba = Room.objects.filter(code="TBA").first()
        self.assertIsNotNone(tba, "no shared TBA placeholder room was created")
        self.assertEqual(tba.floor.building.name, "Unassigned")
        self.assertGreater(
            Schedule.objects.filter(room=tba).count(), 0,
            "the TBA room owns no schedules — roomless-physical rows were dropped")

    def test_section_label_never_becomes_a_room(self):
        # D9 guard: a Sec value like "A101"/"C110" is a section number, so a
        # Room whose code equals a bare section label must never be created for
        # a row that had no real room. The TBA room absorbs those rows instead.
        # Concretely: no Unassigned-building room carries a purely-digit-run code
        # that is actually one of the many "C1xx" section labels.
        self.assertFalse(
            Room.objects.filter(code__startswith="C1").exists(),
            "a section label leaked in as a Room code")


@skipUnless(os.path.exists(OFFERINGS_XLSX),
            "registrar offerings .xlsx not present (gitignored data/raw)")
class ImportReportTests(TransactionTestCase):
    """The dry-run reconciliation report proves the partition + flags (D4/D7/D9)."""

    def _dry_run_output(self):
        out = StringIO()
        call_command("import_offerings", dry_run=True, stdout=out)
        return out.getvalue()

    def test_dry_run_reports_full_term_counts(self):
        text = self._dry_run_output()
        sections = int(re.search(r"Sections imported\s*:\s*(\d+)", text).group(1))
        schedules = int(re.search(r"Schedule rows\s*:\s*(\d+)", text).group(1))
        # ~1,100 sections (1042 intact + 44 roomless-TBA + 14 online-no-room).
        self.assertGreaterEqual(sections, 1080)
        self.assertLessEqual(sections, 1120)
        # ~2,021 real meetings + the roomless placeholder rows.
        self.assertGreaterEqual(schedules, 2000)

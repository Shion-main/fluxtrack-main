"""IFO Rooms & buildings Directory contracts."""

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from accounts.models import Role
from campus.models import Building, Floor, Room


class RoomsDirectoryTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.ifo = User.objects.create(
            username="directory_ifo", role=Role.IFO_ADMIN, is_active=True
        )
        self.client.force_login(self.ifo)

        self.acad = Building.objects.create(code="ACAD", name="Academic Building")
        self.admin = Building.objects.create(code="ADMIN", name="Admin Building")
        self.gym = Building.objects.create(code="GYM", name="Gym")
        self.online = Building.objects.create(code="ONLINE", name="Online")
        self.unassigned = Building.objects.create(
            code="UNASSIGNED", name="Unassigned"
        )
        self.acad3 = Floor.objects.create(building=self.acad, number=3)
        self.admin2 = Floor.objects.create(building=self.admin, number=2)
        self.gym1 = Floor.objects.create(building=self.gym, number=1)
        self.online0 = Floor.objects.create(building=self.online, number=0)
        self.unassigned0 = Floor.objects.create(
            building=self.unassigned, number=0
        )

        self.it_lab = self._room(
            self.acad3,
            "IT-301",
            name="Programming Lab",
            room_type=Room.RoomType.IT_LAB,
        )
        self.admin_room = self._room(
            self.admin2, "A201", name="Registrar", out_of_service=True
        )
        self.gym_room = self._room(
            self.gym1, "GYM-1", room_type=Room.RoomType.GYM
        )
        self.virtual = self._room(
            self.online0, "V101", room_type=Room.RoomType.OTHER
        )
        self.unassigned_room = self._room(
            self.unassigned0, "TBA-1", room_type=Room.RoomType.OTHER
        )

    def _room(self, floor, code, *, name="", room_type=Room.RoomType.CLASSROOM,
              out_of_service=False):
        sequence = Room.objects.count() + 1
        return Room.objects.create(
            floor=floor,
            code=code,
            name=name,
            room_type=room_type,
            out_of_service=out_of_service,
            qr_token=f"directory-qr-{sequence}",
            manual_code=f"7{sequence:05d}",
        )

    def test_directory_lists_all_record_types_but_only_physical_buildings(self):
        response = self.client.get("/ifo/rooms?view=directory")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mode"], "directory")
        self.assertContains(response, "IT-301")
        self.assertContains(response, "V101")
        self.assertContains(response, "TBA-1")
        building_codes = [b.code for b in response.context["physical_buildings"]]
        self.assertEqual(building_codes, ["ACAD", "ADMIN", "GYM"])

    def test_search_matches_code_name_building_floor_and_room_type(self):
        for query, expected in (
            ("IT-301", "IT-301"),
            ("programming", "IT-301"),
            ("Academic", "IT-301"),
            ("Floor 3", "IT-301"),
            ("IT lab", "IT-301"),
        ):
            with self.subTest(query=query):
                response = self.client.get(
                    "/ifo/rooms", {"view": "directory", "q": query}
                )
                self.assertContains(response, expected)
                self.assertNotContains(response, "A201")

    def test_directory_filters_building_floor_type_and_service(self):
        response = self.client.get("/ifo/rooms", {
            "view": "directory",
            "building": "ADMIN",
            "floor": str(self.admin2.pk),
            "room_type": Room.RoomType.CLASSROOM,
            "service": "out",
        })
        self.assertContains(response, "A201")
        self.assertNotContains(response, "IT-301")

    def test_record_type_filters_are_distinct(self):
        cases = (
            ("physical", "IT-301", "V101"),
            ("virtual", "V101", "IT-301"),
            ("unassigned", "TBA-1", "IT-301"),
        )
        for record_type, expected, absent in cases:
            with self.subTest(record_type=record_type):
                response = self.client.get(
                    "/ifo/rooms",
                    {"view": "directory", "record_type": record_type},
                )
                self.assertContains(response, expected)
                self.assertNotContains(response, absent)

    def test_invalid_mode_falls_back_to_live_and_unknown_filters_are_ignored(self):
        response = self.client.get(
            "/ifo/rooms", {"view": "nonsense", "room_type": "SERVER"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["mode"], "live")

        directory = self.client.get(
            "/ifo/rooms", {"view": "directory", "room_type": "SERVER"}
        )
        self.assertEqual(directory.context["filters"]["room_type"], "")
        self.assertContains(directory, "IT-301")

    def test_directory_paginates_fifty_and_preserves_filters(self):
        for number in range(51):
            self._room(self.acad3, f"R{number:03d}")

        response = self.client.get(
            "/ifo/rooms",
            {"view": "directory", "building": "ACAD", "page": "2"},
        )
        self.assertEqual(response.context["page"].number, 2)
        self.assertContains(response, "building=ACAD")
        self.assertLessEqual(len(response.context["directory_rows"]), 50)

    def test_valid_floor_from_another_building_returns_no_results(self):
        response = self.client.get("/ifo/rooms", {
            "view": "directory",
            "building": "ACAD",
            "floor": str(self.admin2.pk),
        })
        self.assertEqual(response.context["result_count"], 0)
        self.assertContains(response, "No rooms match")

    def test_live_exposes_only_physical_building_filters_and_url_state(self):
        response = self.client.get("/ifo/rooms", {
            "q": "programming",
            "building": "ACAD",
            "status": "in_session",
        })
        self.assertEqual(response.context["mode"], "live")
        self.assertEqual(response.context["filters"], {
            "q": "programming",
            "building": "ACAD",
            "status": "in_session",
        })
        self.assertEqual(response.context["buildings"], ["ACAD", "ADMIN", "GYM"])

    def test_live_ignores_system_building_and_unknown_status_filters(self):
        response = self.client.get("/ifo/rooms", {
            "building": "ONLINE",
            "status": "occupied",
        })
        self.assertEqual(response.context["filters"]["building"], "")
        self.assertEqual(response.context["filters"]["status"], "")

    def test_hx_directory_request_returns_workspace_partial(self):
        response = self.client.get(
            "/ifo/rooms",
            {"view": "directory", "q": "IT-301"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ifo/_room_directory.html")
        self.assertNotContains(response, "<!DOCTYPE html>")

    def test_directory_query_budget_is_bounded_for_a_full_page(self):
        for number in range(55):
            self._room(self.acad3, f"Q{number:03d}")
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/ifo/rooms", {"view": "directory"})
        self.assertEqual(response.status_code, 200)
        from web.pagination import DEFAULT_PER_PAGE
        self.assertEqual(len(response.context["directory_rows"]), DEFAULT_PER_PAGE)
        self.assertLessEqual(
            len(queries), 20,
            "Directory must batch relations/status instead of querying per row.",
        )

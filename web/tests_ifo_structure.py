"""Phase 10 building & floor CRUD (campus structure).

Closes the audit gap where buildings/floors were Django-admin-only, so IFO could
not stand up a new building without a superuser. Mirrors the room-CRUD discipline:
named, bottom-up PROTECT-aware delete (rooms -> floor -> building), every write
audited. ASCII-only.
"""
from datetime import date, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from campus.models import Building, Floor, Room
from campus.services import building_delete_blockers, floor_delete_blockers
from ops.models import AuditLog

User = get_user_model()


class StructureAuthzTests(TestCase):
    def setUp(self):
        self.fac = User.objects.create(username="s_fac", role=Role.FACULTY)

    def test_buildings_list_requires_ifo(self):
        self.client.force_login(self.fac)
        self.assertEqual(self.client.get("/ifo/buildings").status_code, 403)

    def test_building_create_requires_ifo(self):
        self.client.force_login(self.fac)
        resp = self.client.post("/ifo/buildings/create",
                                {"code": "X", "name": "Y"})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Building.objects.filter(code="X").exists())


class BuildingCrudTests(TestCase):
    def setUp(self):
        self.ifo = User.objects.create(username="s_ifo", role=Role.IFO_ADMIN)
        self.client.force_login(self.ifo)

    def test_create_building_upper_cases_and_audits(self):
        resp = self.client.post("/ifo/buildings/create",
                                {"code": "acad", "name": "Academic"})
        b = Building.objects.get(code="ACAD")
        self.assertRedirects(resp, f"/ifo/buildings/{b.pk}")
        self.assertEqual(b.name, "Academic")
        self.assertTrue(AuditLog.objects.filter(
            event_type="building.created", target_id=str(b.pk)).exists())

    def test_duplicate_code_is_400(self):
        Building.objects.create(code="ACAD", name="A")
        resp = self.client.post("/ifo/buildings/create",
                                {"code": "acad", "name": "B"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Building.objects.filter(code="ACAD").count(), 1)

    def test_missing_fields_is_400(self):
        self.assertEqual(self.client.post(
            "/ifo/buildings/create", {"code": "", "name": "X"}).status_code, 400)
        self.assertEqual(self.client.post(
            "/ifo/buildings/create", {"code": "X", "name": ""}).status_code, 400)

    def test_edit_building(self):
        b = Building.objects.create(code="OLD", name="Old")
        resp = self.client.post(f"/ifo/buildings/{b.pk}/edit",
                                {"code": "NEW", "name": "New name"})
        self.assertRedirects(resp, f"/ifo/buildings/{b.pk}")
        b.refresh_from_db()
        self.assertEqual((b.code, b.name), ("NEW", "New name"))

    def test_empty_building_deletes(self):
        b = Building.objects.create(code="EMP", name="Empty")
        resp = self.client.post(f"/ifo/buildings/{b.pk}/delete")
        self.assertRedirects(resp, "/ifo/rooms?view=directory")
        self.assertFalse(Building.objects.filter(pk=b.pk).exists())

    def test_building_with_floors_is_refused_not_cascaded(self):
        b = Building.objects.create(code="HAS", name="Has")
        Floor.objects.create(building=b, number=1)
        resp = self.client.post(f"/ifo/buildings/{b.pk}/delete")
        self.assertRedirects(resp, f"/ifo/buildings/{b.pk}")
        self.assertTrue(Building.objects.filter(pk=b.pk).exists())  # not deleted

    def test_legacy_building_list_redirects_to_directory(self):
        response = self.client.get("/ifo/buildings")
        self.assertRedirects(
            response, "/ifo/rooms?view=directory", fetch_redirect_response=False
        )

    def test_hx_detail_returns_drawer_not_complete_console(self):
        b = Building.objects.create(code="ACAD", name="Academic")
        response = self.client.get(
            f"/ifo/buildings/{b.pk}", HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "ifo/_building_drawer.html")
        self.assertNotContains(response, "<!DOCTYPE html>")

    def test_hx_edit_validation_is_inline_and_sticky(self):
        b = Building.objects.create(code="ACAD", name="Academic")
        response = self.client.post(
            f"/ifo/buildings/{b.pk}/edit",
            {"code": "", "name": "Updated name"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Updated name", status_code=400)
        self.assertContains(response, "Code and name are both required", status_code=400)
        b.refresh_from_db()
        self.assertEqual(b.name, "Academic")

    def test_hx_floor_success_refreshes_drawer_and_triggers_workspace(self):
        b = Building.objects.create(code="ACAD", name="Academic")
        response = self.client.post(
            f"/ifo/buildings/{b.pk}/floors/create",
            {"number": "3"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["HX-Trigger"], "roomsStructureChanged")
        self.assertContains(response, "Floor 3")

    def test_reserved_system_buildings_are_read_only(self):
        b = Building.objects.create(code="ONLINE", name="Online")
        floor = Floor.objects.create(building=b, number=0)

        edit = self.client.post(
            f"/ifo/buildings/{b.pk}/edit",
            {"code": "RENAMED", "name": "Renamed"},
            HTTP_HX_REQUEST="true",
        )
        add_floor = self.client.post(
            f"/ifo/buildings/{b.pk}/floors/create",
            {"number": "1"},
            HTTP_HX_REQUEST="true",
        )
        delete_floor = self.client.post(
            f"/ifo/floors/{floor.pk}/delete", HTTP_HX_REQUEST="true"
        )

        for response in (edit, add_floor, delete_floor):
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "read-only system record", status_code=400)
        b.refresh_from_db()
        self.assertEqual(b.code, "ONLINE")
        self.assertTrue(Floor.objects.filter(pk=floor.pk).exists())

    def test_building_create_uniqueness_race_is_friendly(self):
        with patch("web.ifo.Building.objects.create", side_effect=IntegrityError):
            response = self.client.post(
                "/ifo/buildings/create", {"code": "NEW", "name": "New"}
            )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "already exists", status_code=400)

    def test_reserved_codes_cannot_be_created_or_claimed(self):
        create = self.client.post(
            "/ifo/buildings/create", {"code": "ONLINE", "name": "Fake physical"}
        )
        self.assertEqual(create.status_code, 400)
        self.assertFalse(Building.objects.filter(code="ONLINE").exists())

        b = Building.objects.create(code="ACAD", name="Academic")
        edit = self.client.post(
            f"/ifo/buildings/{b.pk}/edit",
            {"code": "UNASSIGNED", "name": "Academic"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(edit.status_code, 400)
        b.refresh_from_db()
        self.assertEqual(b.code, "ACAD")


class FloorCrudTests(TestCase):
    def setUp(self):
        self.ifo = User.objects.create(username="f_ifo", role=Role.IFO_ADMIN)
        self.client.force_login(self.ifo)
        self.b = Building.objects.create(code="BLD", name="Bld")

    def _room(self, floor):
        return Room.objects.create(floor=floor, code="RM1", qr_token="q1",
                                   manual_code="990001")

    def test_add_floor(self):
        resp = self.client.post(f"/ifo/buildings/{self.b.pk}/floors/create",
                                {"number": "3"})
        self.assertRedirects(resp, f"/ifo/buildings/{self.b.pk}")
        self.assertTrue(Floor.objects.filter(building=self.b, number=3).exists())

    def test_duplicate_floor_number_refused(self):
        Floor.objects.create(building=self.b, number=3)
        self.client.post(f"/ifo/buildings/{self.b.pk}/floors/create",
                         {"number": "3"})
        self.assertEqual(Floor.objects.filter(building=self.b, number=3).count(), 1)

    def test_non_numeric_floor_refused(self):
        self.client.post(f"/ifo/buildings/{self.b.pk}/floors/create",
                         {"number": "ground"})
        self.assertEqual(self.b.floors.count(), 0)

    def test_empty_floor_deletes(self):
        f = Floor.objects.create(building=self.b, number=2)
        resp = self.client.post(f"/ifo/floors/{f.pk}/delete")
        self.assertRedirects(resp, f"/ifo/buildings/{self.b.pk}")
        self.assertFalse(Floor.objects.filter(pk=f.pk).exists())

    def test_floor_with_rooms_is_refused(self):
        f = Floor.objects.create(building=self.b, number=2)
        self._room(f)
        resp = self.client.post(f"/ifo/floors/{f.pk}/delete")
        self.assertRedirects(resp, f"/ifo/buildings/{self.b.pk}")
        self.assertTrue(Floor.objects.filter(pk=f.pk).exists())


class BlockerServiceTests(TestCase):
    def test_blockers_report_only_nonzero(self):
        b = Building.objects.create(code="Z", name="Z")
        self.assertEqual(building_delete_blockers(b), {})
        f = Floor.objects.create(building=b, number=1)
        self.assertEqual(building_delete_blockers(b), {"floors": 1})
        self.assertEqual(floor_delete_blockers(f), {})
        Room.objects.create(floor=f, code="R", qr_token="qz", manual_code="990009")
        self.assertEqual(floor_delete_blockers(f), {"rooms": 1})
        self.assertEqual(building_delete_blockers(b), {"floors": 1, "rooms": 1})

"""Rooms & buildings model contracts."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.core.management import call_command
from django.test import TestCase, TransactionTestCase

from campus.models import Building, Floor, Room


class BuildingClassificationTests(TestCase):
    def test_only_reserved_operational_groups_are_system_records(self):
        acad = Building.objects.create(code="ACAD", name="Academic Building")
        online = Building.objects.create(code="ONLINE", name="Online")
        unassigned = Building.objects.create(code="UNASSIGNED", name="Unassigned")

        self.assertTrue(acad.is_physical)
        self.assertFalse(acad.is_system_record)
        self.assertFalse(online.is_physical)
        self.assertTrue(online.is_system_record)
        self.assertFalse(unassigned.is_physical)
        self.assertTrue(unassigned.is_system_record)


class RoomClassificationTests(TestCase):
    def _room(self, *, building_code, room_code, room_type=None):
        building = Building.objects.create(
            code=building_code, name=f"{building_code} Building"
        )
        floor = Floor.objects.create(building=building, number=1)
        values = {
            "floor": floor,
            "code": room_code,
            "qr_token": f"qr-{room_code}",
            "manual_code": f"{Room.objects.count() + 1:06d}",
        }
        if room_type is not None:
            values["room_type"] = room_type
        return Room.objects.create(**values)

    def test_room_type_defaults_to_classroom(self):
        room = self._room(building_code="ACAD", room_code="R101")
        self.assertEqual(room.room_type, Room.RoomType.CLASSROOM)

    def test_record_type_uses_existing_virtual_rule_before_building_group(self):
        virtual = self._room(building_code="ONLINE", room_code="V101")
        unassigned = self._room(building_code="UNASSIGNED", room_code="TBA")
        physical = self._room(building_code="ACAD", room_code="R102")

        self.assertEqual(virtual.record_type, Room.RecordType.VIRTUAL)
        self.assertEqual(unassigned.record_type, Room.RecordType.UNASSIGNED)
        self.assertEqual(physical.record_type, Room.RecordType.PHYSICAL)


class SeedDemoCampusTests(TestCase):
    def test_seed_places_it_labs_on_acad_floor_three_idempotently(self):
        call_command("seed_demo", force=True, verbosity=0)
        call_command("seed_demo", force=True, verbosity=0)

        self.assertFalse(Building.objects.filter(code="IT").exists())
        rooms = Room.objects.filter(code__in=("IT-301", "IT-302", "IT-303"))
        self.assertEqual(rooms.count(), 3)
        self.assertFalse(
            rooms.exclude(
                floor__building__code="ACAD",
                floor__number=3,
                room_type=Room.RoomType.IT_LAB,
            ).exists()
        )


class RoomsBuildingsMigrationTests(TransactionTestCase):
    migrate_from = [("campus", "0003_room_out_of_service")]
    migrate_to = [("campus", "0004_rooms_buildings")]

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _old_room(self, floor, code, sequence):
        OldRoom = self.old_apps.get_model("campus", "Room")
        return OldRoom.objects.create(
            floor= floor,
            code=code,
            name=code,
            capacity=40,
            qr_token=f"migration-qr-{sequence}",
            manual_code=f"8{sequence:05d}",
        )

    def _campus_fixture(self):
        OldBuilding = self.old_apps.get_model("campus", "Building")
        OldFloor = self.old_apps.get_model("campus", "Floor")
        acad = OldBuilding.objects.create(code="ACAD", name="Academic Building")
        it = OldBuilding.objects.create(code="IT", name="IT Building")
        gym = OldBuilding.objects.create(code="GYM", name="Gym")
        online = OldBuilding.objects.create(code="ONLINE", name="Online")
        unassigned = OldBuilding.objects.create(code="UNASSIGNED", name="Unassigned")
        return {
            "acad3": OldFloor.objects.create(building=acad, number=3),
            "it3": OldFloor.objects.create(building=it, number=3),
            "gym1": OldFloor.objects.create(building=gym, number=1),
            "online0": OldFloor.objects.create(building=online, number=0),
            "unassigned0": OldFloor.objects.create(building=unassigned, number=0),
        }

    def _migrate_forward(self):
        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        return self.executor.loader.project_state(self.migrate_to).apps

    def test_forward_moves_exact_it_rooms_and_backfills_all_room_types(self):
        floors = self._campus_fixture()
        it_rooms = [
            self._old_room(floors["it3"], code, i)
            for i, code in enumerate(("IT-301", "IT-302", "IT-303"), start=1)
        ]
        gym = self._old_room(floors["gym1"], "GYM-1", 10)
        virtual = self._old_room(floors["online0"], "V101", 11)
        unassigned = self._old_room(floors["unassigned0"], "TBA", 12)

        new_apps = self._migrate_forward()
        NewBuilding = new_apps.get_model("campus", "Building")
        NewRoom = new_apps.get_model("campus", "Room")

        self.assertFalse(NewBuilding.objects.filter(code="IT").exists())
        for old in it_rooms:
            moved = NewRoom.objects.get(pk=old.pk)
            self.assertEqual(moved.floor.building.code, "ACAD")
            self.assertEqual(moved.floor.number, 3)
            self.assertEqual(moved.room_type, "IT_LAB")
            self.assertEqual(moved.qr_token, old.qr_token)
            self.assertEqual(moved.manual_code, old.manual_code)
        self.assertEqual(NewRoom.objects.get(pk=gym.pk).room_type, "GYM")
        self.assertEqual(NewRoom.objects.get(pk=virtual.pk).room_type, "OTHER")
        self.assertEqual(NewRoom.objects.get(pk=unassigned.pk).room_type, "OTHER")

    def test_unexpected_it_room_aborts_without_moving_or_deleting(self):
        floors = self._campus_fixture()
        expected = self._old_room(floors["it3"], "IT-301", 1)
        unexpected = self._old_room(floors["it3"], "IT-999", 2)

        try:
            with self.assertRaisesMessage(RuntimeError, "unexpected room"):
                self._migrate_forward()
            expected.refresh_from_db()
            unexpected.refresh_from_db()
            self.assertEqual(expected.floor_id, floors["it3"].pk)
            self.assertEqual(unexpected.floor_id, floors["it3"].pk)
        finally:
            type(unexpected).objects.filter(pk=unexpected.pk).delete()

    def test_reverse_moves_only_rooms_still_in_the_migrated_state(self):
        floors = self._campus_fixture()
        first = self._old_room(floors["it3"], "IT-301", 1)
        second = self._old_room(floors["it3"], "IT-302", 2)
        new_apps = self._migrate_forward()
        NewBuilding = new_apps.get_model("campus", "Building")
        NewFloor = new_apps.get_model("campus", "Floor")
        NewRoom = new_apps.get_model("campus", "Room")
        admin = NewBuilding.objects.create(code="ADMIN", name="Admin Building")
        admin_floor = NewFloor.objects.create(building=admin, number=2)
        NewRoom.objects.filter(pk=second.pk).update(floor=admin_floor)

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_from)
        old_apps = self.executor.loader.project_state(self.migrate_from).apps
        OldRoom = old_apps.get_model("campus", "Room")

        self.assertEqual(OldRoom.objects.get(pk=first.pk).floor.building.code, "IT")
        self.assertEqual(OldRoom.objects.get(pk=second.pk).floor.building.code, "ADMIN")

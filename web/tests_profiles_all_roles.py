"""Shared self-profile contract for every FluxTrack role."""
from datetime import date, time

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from scheduling.models import (
    AcademicTerm,
    Modality,
    Schedule,
)


class AllRoleProfileTests(TestCase):
    url = "/profile"

    def setUp(self):
        self.department = Department.objects.create(
            name="School of Test Engineering", code="STE")

    def _user(self, role, suffix=""):
        return get_user_model().objects.create(
            username=f"{role}{suffix}",
            first_name="Taylor",
            last_name="User",
            email=f"{role}{suffix}@mcm.edu.ph",
            role=role,
            department=self.department,
            is_active=True,
        )

    def test_every_role_can_open_own_profile_with_identity_information(self):
        for role in Role.values:
            with self.subTest(role=role):
                user = self._user(role)
                self.client.force_login(user)

                response = self.client.get(self.url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Taylor User")
                self.assertContains(response, user.email)
                self.assertContains(response, user.get_role_display())
                self.assertContains(response, self.department.name)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_faculty_profile_lists_only_their_active_term_schedules(self):
        faculty = self._user(Role.FACULTY, "one")
        other = self._user(Role.FACULTY, "two")
        term = AcademicTerm.objects.create(
            name="Profile term",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            status=AcademicTerm.Status.ACTIVE,
        )
        building = Building.objects.create(name="Main Hall", code="MH")
        floor = Floor.objects.create(building=building, number=3)
        room = Room.objects.create(
            floor=floor, code="MH301", qr_token="profile-qr",
            manual_code="765401")
        Schedule.objects.create(
            term=term, course_code="OWN101", section="A",
            faculty=faculty, room=room, day_of_week=0,
            start_time=time(8, 0), end_time=time(9, 30),
            modality=Modality.F2F,
        )
        Schedule.objects.create(
            term=term, course_code="OTHER202", section="B",
            faculty=other, room=room, day_of_week=1,
            start_time=time(10, 0), end_time=time(11, 30),
            modality=Modality.BLENDED,
        )
        self.client.force_login(faculty)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Teaching schedule")
        self.assertContains(response, "OWN101-A")
        self.assertContains(response, "Monday")
        self.assertContains(response, "MH301")
        self.assertNotContains(response, "OTHER202")

    def test_dean_faculty_workspace_lists_only_active_own_department_members(self):
        dean = self._user(Role.DEAN, "roster")
        local_one = self._user(Role.FACULTY, "local-one")
        local_two = self._user(Role.FACULTY, "local-two")
        inactive = self._user(Role.FACULTY, "inactive")
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        other_department = Department.objects.create(
            name="School of Other Studies", code="SOS")
        foreign = get_user_model().objects.create(
            username="foreign-faculty",
            first_name="Foreign",
            last_name="Faculty",
            email="foreign-faculty@mcm.edu.ph",
            role=Role.FACULTY,
            department=other_department,
            is_active=True,
        )
        self.client.force_login(dean)

        response = self.client.get("/dean/faculty")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, local_one.username)
        self.assertContains(response, local_two.username)
        self.assertContains(
            response, reverse("dean_faculty_detail", args=(local_one.pk,)))
        self.assertContains(
            response, reverse("dean_faculty_detail", args=(local_two.pk,)))
        self.assertNotContains(response, inactive.username)
        self.assertNotContains(response, foreign.username)
        self.assertNotContains(
            response, reverse("dean_faculty_detail", args=(foreign.pk,)))

    def test_profile_is_linked_from_each_application_shell(self):
        surfaces = (
            (Role.FACULTY, "/faculty/home"),
            (Role.GUARD, "/guard/monitor"),
            (Role.DEAN, "/dean/dashboard"),
            (Role.HR_ADMIN, "/"),
        )
        for index, (role, url) in enumerate(surfaces):
            with self.subTest(role=role):
                user = self._user(role, f"nav{index}")
                self.client.force_login(user)

                response = self.client.get(url, follow=True)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'href="/profile"')

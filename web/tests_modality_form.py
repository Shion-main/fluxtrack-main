"""Tests for the three-step Request-a-shift form (MOD-01 presentation layer).

These cover the FORM SURFACE, not the shift domain rules -- scheduling/tests.py
owns those. What matters here is that a rejected submit does not punish the user:

  - **Input survives a 400.** The old view re-rendered a blank form, so a small
    mistake meant retyping every choice the server already had. With a stepped
    flow that means re-walking all three steps, which turns a typo into a reason
    to give up.
  - **The error is in human words.** scheduling.services raises terse domain
    strings ("no in-window sessions to shift"); those are right for an exception
    and wrong for a faculty member on a phone between classes.
  - **The form reopens where the problem is**, not back at step 1.

Progressive enhancement is also locked: the markup must submit without JS, so
the panels are plain sections in one <form> and every field is present in the
GET render.

ASCII-only.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from scheduling.models import (AcademicTerm, Modality, Schedule, ScheduleStatus)
from web.faculty import _error_step, _friendly_error


class ErrorCopyTests(TestCase):
    """Domain vocabulary is translated at the presentation edge."""

    def test_terse_domain_strings_become_human(self):
        out = _friendly_error("no in-window sessions to shift")
        self.assertIn("meet again inside that window", out)
        self.assertNotIn("in-window", out)

    def test_lead_time_message_says_what_to_do(self):
        out = _friendly_error("request is past the lead-time cutoff")
        self.assertIn("too soon", out)
        self.assertIn("later date", out)

    def test_unmapped_message_passes_through_unchanged(self):
        """A new service error must surface as-is, never be swallowed."""
        self.assertEqual(_friendly_error("brand new failure"), "brand new failure")

    def test_class_selection_errors_reopen_step_one(self):
        self.assertEqual(_error_step("Select at least one class."), 1)
        self.assertEqual(_error_step("One or more selected classes are not yours."), 1)

    def test_other_errors_reopen_the_change_step(self):
        self.assertEqual(_error_step("request is past the lead-time cutoff"), 2)


class ModalityFormBase(TestCase):
    def setUp(self):
        User = get_user_model()
        today = timezone.localdate()
        self.term = AcademicTerm.objects.create(
            name="T", start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=30), is_active=True)
        self.dept = Department.objects.create(name="Computing", code="CCS")
        building = Building.objects.create(name="Academic", code="ACAD")
        floor = Floor.objects.create(building=building, number=1)
        self.room = Room.objects.create(
            floor=floor, code="R101", qr_token="tokmf", manual_code="MCF001")
        self.faculty = User.objects.create(
            username="fac_form", email="fac_form@mcm.edu.ph", role=Role.FACULTY,
            last_name="Cruz", department=self.dept, is_active=True)
        self.a = self._schedule("IT301", "A", 0)
        self.b = self._schedule("IT302", "B", 2)
        self.client.force_login(self.faculty)

    def _schedule(self, course, section, day):
        return Schedule.objects.create(
            term=self.term, course_code=course, section=section,
            faculty=self.faculty, room=self.room, day_of_week=day,
            start_time="10:00", end_time="11:00", modality=Modality.F2F,
            status=ScheduleStatus.ACTIVE)


class FormRenderTests(ModalityFormBase):
    def test_get_renders_all_three_steps_in_one_form(self):
        """No-JS fallback: every panel and field must be in the GET render, so
        the form works as one long page when modality.js never runs."""
        resp = self.client.get(reverse("faculty_modality_new"))
        self.assertEqual(resp.status_code, 200)
        for step in ("1", "2", "3"):
            self.assertContains(resp, f'data-step="{step}"')
        self.assertContains(resp, 'name="schedules"')
        self.assertContains(resp, 'name="target_modality"')
        self.assertContains(resp, 'name="window_mode"')
        self.assertContains(resp, 'type="submit"')

    def test_classes_come_before_the_change_in_document_order(self):
        """The whole point of the rework: pick classes first, then the change."""
        html = self.client.get(reverse("faculty_modality_new")).content.decode()
        self.assertLess(html.index('name="schedules"'), html.index('name="target_modality"'))

    def test_room_picker_is_not_rendered_up_front(self):
        """Availability cost 6.5s and 5488 queries when computed for every class
        on load. The page must not pay that to ask "which classes?"."""
        with self.assertNumQueries(7):
            resp = self.client.get(reverse("faculty_modality_new"))
        self.assertNotContains(resp, f'name="preferred_room_{self.a.pk}"')
        self.assertContains(resp, 'data-room-picker')

    def test_room_picker_endpoint_serves_only_the_picked_classes(self):
        resp = self.client.get(
            reverse("faculty_modality_rooms"), {"schedules": str(self.a.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'name="preferred_room_{self.a.pk}"')
        self.assertNotContains(resp, f'name="preferred_room_{self.b.pk}"')

    def test_room_picker_refuses_a_foreign_schedule(self):
        """A forged pk must yield nothing, never another faculty's rooms."""
        other = get_user_model().objects.create(
            username="fac_rooms_other", email="fro@mcm.edu.ph", role=Role.FACULTY,
            is_active=True)
        foreign = Schedule.objects.create(
            term=self.term, course_code="XX999", section="Z", faculty=other,
            room=self.room, day_of_week=1, start_time="08:00", end_time="09:00",
            modality=Modality.F2F, status=ScheduleStatus.ACTIVE)
        resp = self.client.get(
            reverse("faculty_modality_rooms"), {"schedules": str(foreign.pk)})
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f'name="preferred_room_{foreign.pk}"')

    def test_room_picker_ignores_garbage_ids(self):
        resp = self.client.get(
            reverse("faculty_modality_rooms"), {"schedules": "abc,,-1"})
        self.assertEqual(resp.status_code, 200)

    def test_room_picker_is_read_only(self):
        resp = self.client.post(reverse("faculty_modality_rooms"))
        self.assertEqual(resp.status_code, 405)

    def test_no_classes_shows_a_teaching_empty_state(self):
        Schedule.objects.filter(faculty=self.faculty).update(
            status=ScheduleStatus.ARCHIVED)
        resp = self.client.get(reverse("faculty_modality_new"))
        self.assertContains(resp, "no active classes to shift")
        self.assertNotContains(resp, 'data-step="2"')


class FormPreservationTests(ModalityFormBase):
    """A rejected submit must hand back what was typed, not a blank form."""

    def _post(self, **over):
        data = {
            "target_modality": "blended", "window_mode": "weeks", "weeks": "4",
            "schedules": [str(self.a.pk), str(self.b.pk)],
        }
        data.update(over)
        return self.client.post(reverse("faculty_modality_new"), data)

    def test_rejected_submit_is_400_not_500(self):
        self.assertEqual(self._post().status_code, 400)

    def test_selected_classes_are_re_checked(self):
        html = self._post().content.decode()
        self.assertEqual(html.count("checked data-pick"), 2)

    def test_target_modality_survives(self):
        self.assertContains(self._post(), 'value="blended"', status_code=400)
        html = self._post().content.decode()
        blended = html.index('value="blended"')
        self.assertIn("checked", html[blended:blended + 160])

    def test_week_count_survives(self):
        self.assertContains(self._post(weeks="7"), 'value="7"', status_code=400)

    def test_single_date_mode_survives(self):
        html = self._post(window_mode="single", on_date="2099-01-05").content.decode()
        self.assertIn('value="2099-01-05"', html)
        single = html.index('value="single"')
        self.assertIn("checked", html[single:single + 160])

    def test_error_step_is_exposed_for_the_client(self):
        self.assertContains(self._post(), "data-error-step=", status_code=400)

    def test_missing_class_selection_reopens_step_one(self):
        resp = self.client.post(reverse("faculty_modality_new"), {
            "target_modality": "online", "window_mode": "weeks", "weeks": "1"})
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'data-error-step="1"', status_code=400)
        self.assertContains(resp, "Select at least one class", status_code=400)

    def test_a_foreign_schedule_is_refused_and_reopens_step_one(self):
        other = get_user_model().objects.create(
            username="fac_other_form", email="fof@mcm.edu.ph", role=Role.FACULTY,
            is_active=True)
        foreign = Schedule.objects.create(
            term=self.term, course_code="XX999", section="Z", faculty=other,
            room=self.room, day_of_week=1, start_time="08:00", end_time="09:00",
            modality=Modality.F2F, status=ScheduleStatus.ACTIVE)
        resp = self._post(schedules=[str(foreign.pk)])
        self.assertEqual(resp.status_code, 400)
        self.assertContains(resp, 'data-error-step="1"', status_code=400)

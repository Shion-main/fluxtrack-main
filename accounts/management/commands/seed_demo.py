"""Seed demo data: departments, campus, term, one user per role, schedules, sessions."""
import secrets
from datetime import time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Building, Floor, Room
from ops.models import SystemSetting
from scheduling.models import (AcademicTerm, CheckinMethod, Modality, Schedule,
                               Session, SessionStatus)

User = get_user_model()


def rand_code():
    return f"{secrets.randbelow(1000000):06d}"


class Command(BaseCommand):
    help = "Seed demo data for local development."

    def handle(self, *args, **opts):
        # Policy settings from FLUXTRACK_POLICY (§8)
        for key, val in settings.FLUXTRACK_POLICY.items():
            SystemSetting.objects.get_or_create(key=key, defaults={"value": str(val)})

        dept, _ = Department.objects.get_or_create(code="CCIS",
            defaults={"name": "College of Computer and Information Science"})

        term, _ = AcademicTerm.objects.get_or_create(name="AY 2026 Term 1", defaults={
            "start_date": timezone.now().date() - timedelta(days=30),
            "end_date": timezone.now().date() + timedelta(days=90),
            "is_active": True,
        })

        bldg, _ = Building.objects.get_or_create(code="IT", defaults={"name": "IT Building"})
        floor, _ = Floor.objects.get_or_create(building=bldg, number=3)
        rooms = []
        for code, name, cap in [("IT-301", "Programming Lab 1", 40),
                                ("IT-302", "Programming Lab 2", 40),
                                ("IT-303", "Lecture Room A", 50)]:
            room, created = Room.objects.get_or_create(code=code, defaults={
                "floor": floor, "name": name, "capacity": cap,
                "qr_token": secrets.token_urlsafe(24), "manual_code": rand_code(),
            })
            rooms.append(room)

        # One user per role (dev-login). system_admin is a Django superuser.
        people = [
            ("faculty", "mayo", "Jane Mayo", Role.FACULTY),
            ("checker", "cruz", "Carlo Cruz", Role.CHECKER),
            ("ifo", "reyes", "Ivy Reyes", Role.IFO_ADMIN),
            ("hr", "santos", "Hana Santos", Role.HR_ADMIN),
            ("guard", "dela", "Gil Dela", Role.GUARD),
            ("dean", "ong", "Dean Ong", Role.DEAN),
            ("sysadmin", "admin", "Sy Admin", Role.SYSTEM_ADMIN),
        ]
        users = {}
        for uname, last, full, role in people:
            first = full.split()[0]
            u, created = User.objects.get_or_create(username=uname, defaults={
                "first_name": first, "last_name": last.title(),
                "email": f"{uname}@mcm.edu.ph", "role": role,
                "department": dept if role in (Role.FACULTY, Role.DEAN) else None,
            })
            if created:
                u.set_password("devpass123")
            if role == Role.SYSTEM_ADMIN:
                u.is_staff = True
                u.is_superuser = True
            elif role in (Role.IFO_ADMIN, Role.HR_ADMIN):
                u.is_staff = True
            u.save()
            users[role] = u

        # A schedule for the faculty user + today's session
        faculty = users[Role.FACULTY]
        sched, _ = Schedule.objects.get_or_create(
            term=term, course_code="CS131", section="A", faculty=faculty, room=rooms[0],
            day_of_week=timezone.now().weekday(),
            defaults={"enrolled_count": 35, "start_time": time(9, 0),
                      "end_time": time(10, 30), "modality": Modality.F2F},
        )
        today = timezone.now().date()
        start = timezone.make_aware(timezone.datetime.combine(today, time(9, 0)))
        Session.objects.get_or_create(schedule=sched, date=today, defaults={
            "faculty": faculty, "room": rooms[0],
            "scheduled_start": start, "scheduled_end": start + timedelta(minutes=90),
            "status": SessionStatus.SCHEDULED,
        })

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Department.objects.count()} dept, {Room.objects.count()} rooms, "
            f"{User.objects.count()} users, {Schedule.objects.count()} schedules, "
            f"{Session.objects.count()} sessions."))
        self.stdout.write("Dev users (password 'devpass123'): "
                          + ", ".join(u.username for u in users.values()))

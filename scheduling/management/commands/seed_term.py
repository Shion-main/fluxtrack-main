"""Reshape the imported offering data into a believable captured term.

The offering import gives real structure -- 2100+ schedules, 218 rooms, 200
faculty -- but a lopsided and half-empty picture: 65% of classes are online
because the importer parks every online section in a virtual room, only one
faculty member has a department, and every downstream surface (Dean queue, HR
attendance, weekly reports, checker verifications) is at zero. Nothing to look
at, and nothing for the reporting features to find.

This command turns that into a term that looks like it has been running for a
few weeks:

  1. Colleges + people   five real MMCM colleges, faculty routed to the one they
                         actually teach in, a Dean per college, plus HR admins,
                         Checkers and Guards.
  2. Modality mix        rebalanced to 60% face-to-face / 20% blended / 20%
                         online, with physical rooms assigned CLASH-FREE and
                         online classes moved to virtual rooms.
  3. Attendance history  sessions from term start to today with realistic
                         outcomes, including a handful of habitually absent
                         faculty so scorecards and flags surface someone.
  4. The rest            checker validations, duty rosters, modality-shift
                         requests across every status, weekly reports,
                         notifications and scheduler job history.

Deterministic: a fixed RNG seed means two runs produce the same term, so a
screenshot taken today still matches the data tomorrow. Re-runnable: it clears
what it owns (sessions, validations, requests, notifications, job runs) before
regenerating, and leaves the imported schedules/rooms/faculty in place.

Dev only -- it rewrites live rows, so it refuses to run with DEBUG off unless
--force is passed. ASCII-only.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Department, Role
from campus.models import Floor, Room
from ops.models import JobRun, Notification
from scheduling.models import (CheckinMethod, Modality,
                               ModalityShiftItem, ModalityShiftRequest,
                               ModalityShiftStatus, Schedule, ScheduleStatus,
                               Session, SessionStatus)
from scheduling.term_scope import (ArchivedTermError, NoActiveTermError,
                                   require_active_term,
                                   require_writable_term)
from verification.models import (Assignment, AssignmentScope, AssignmentType,
                                 CheckerValidation, DutyRole, ValidationAction)

User = get_user_model()

SEED = 20260718

# SQL Server caps a single statement at 2100 parameters, and both bulk helpers
# scale their parameter count with the batch: bulk_create sends roughly
# batch x fields, bulk_update roughly batch x (fields x 2 + 1) because of the
# CASE expression it builds. Session has ~15 fields, so the Django defaults blow
# the cap instantly ("07002 COUNT field incorrect"). These are sized to stay
# well under it -- the same 2100-param trap the HR filters are written around.
CREATE_BATCH = 100
UPDATE_BATCH = 40

# --- Colleges -----------------------------------------------------------------
# MMCM's actual college structure. Course-code prefixes map into the college that
# owns them, so a faculty member's department matches what they teach -- which is
# what makes a Dean's queue and a department report read as real rather than
# round-robin noise.
COLLEGES = [
    ("CCIS", "College of Computer and Information Science",
     ["IT", "CS", "IS", "DS", "NETA", "CAP", "TEC"]),
    ("CEA", "College of Engineering and Architecture",
     ["CE", "EE", "ECE", "CPE", "ME", "MEC", "CHE", "IE", "EECO", "EENV", "EMC",
      "EMGT", "AR", "DRAW", "ENV", "SAF", "MSE", "SGE", "BIOELEC", "VE", "RE",
      "REM", "TRM", "EMGT"]),
    ("CHS", "College of Health Sciences",
     ["PT", "MLS", "BIO", "PSY", "PH"]),
    ("ATYCB", "College of Business and Management",
     ["ACT", "ENT", "MGT", "FIN", "TAX", "MKT", "ECO", "THM", "LAW", "RES"]),
    ("CAS", "College of Arts and Sciences",
     ["SS", "MATH", "ENG", "HUM", "COMM", "PE", "NSTP", "MMA", "CHM", "PHY",
      "COR", "AWS"]),
]

DEAN_NAMES = [
    ("Ramon", "Villanueva"), ("Cecilia", "Ordonez"), ("Alfredo", "Bandoy"),
    ("Marilou", "Ancheta"), ("Ernesto", "Dagohoy"),
]
HR_NAMES = [("Hana", "Santos"), ("Miguel", "Uy")]
CHECKER_NAMES = [
    ("Andrea", "Lumbao"), ("Rico", "Belarmino"), ("Joy", "Maglinte"),
    ("Dennis", "Paragas"), ("Karla", "Sinsuat"), ("Elmer", "Tugade"),
]
GUARD_NAMES = [
    ("Bert", "Caliso"), ("Nena", "Rapadas"), ("Ador", "Piit"), ("Lito", "Bangoy"),
]


def _prefix(course_code):
    out = []
    for ch in course_code:
        if ch.isalpha():
            out.append(ch)
        else:
            break
    return "".join(out).upper()


def _purge(model, chunk=400):
    """Delete every row of `model` in small chunks.

    QuerySet.delete() collects the primary keys and issues DELETE ... WHERE pk IN
    (...), so wiping 4000+ sessions in one statement blows SQL Server's 2100
    parameter cap exactly like an oversized bulk_create does. Chunking keeps each
    statement small; cascades ride along per chunk.
    """
    while True:
        ids = list(model.objects.values_list("pk", flat=True)[:chunk])
        if not ids:
            return
        model.objects.filter(pk__in=ids).delete()


def _purge_queryset(qs, chunk=400):
    """Delete rows from an already-scoped queryset in small SQL Server-safe chunks."""
    while True:
        ids = list(qs.values_list("pk", flat=True)[:chunk])
        if not ids:
            return
        qs.model.objects.filter(pk__in=ids).delete()


class Command(BaseCommand):
    help = "Reshape the imported term into a realistic populated snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Run even when DEBUG is off. Rewrites live rows.")
        parser.add_argument("--keep-history", action="store_true",
                            help="Do not delete existing sessions before seeding.")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["force"]:
            raise CommandError(
                "seed_term rewrites data and DEBUG is off. Pass --force if you "
                "really mean it.")

        self.rng = random.Random(SEED)
        try:
            self.term = require_writable_term(require_active_term())
        except NoActiveTermError as exc:
            raise CommandError("No ACTIVE academic term. Activate a term first.") from exc
        except ArchivedTermError as exc:
            raise CommandError(str(exc)) from exc

        self.today = timezone.localdate()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"Seeding {self.term.name} ({self.term.start_date} -> {self.today})"))

        with transaction.atomic():
            self.step_colleges()
            self.step_staff()
            self.step_modality_mix()
            self.step_sessions(keep=opts["keep_history"])
            self.step_attendance()
            self.step_validations()
            self.step_duty()
            self.step_shift_requests()
            self.step_notifications()
            self.step_jobruns()

        self.summary()

    # -- 1. Colleges and faculty routing --------------------------------------
    def step_colleges(self):
        self.depts = {}
        for code, name, _prefixes in COLLEGES:
            dept, _ = Department.objects.get_or_create(
                code=code, defaults={"name": name})
            if dept.name != name:
                dept.name = name
                dept.save(update_fields=["name"])
            self.depts[code] = dept

        prefix_to_dept = {}
        for code, _n, prefixes in COLLEGES:
            for p in prefixes:
                prefix_to_dept[p] = self.depts[code]

        # A faculty member belongs to the college they teach the most classes in,
        # rather than an arbitrary assignment -- so a department report lists the
        # people you would expect to find in it.
        taught = defaultdict(lambda: defaultdict(int))
        for sch in Schedule.objects.filter(
                term=self.term, status=ScheduleStatus.ACTIVE
        ).select_related("faculty"):
            dept = prefix_to_dept.get(_prefix(sch.course_code))
            if dept is not None:
                taught[sch.faculty_id][dept.code] += 1

        fallback = self.depts["CAS"]
        updated = 0
        for user in User.objects.filter(role=Role.FACULTY):
            counts = taught.get(user.id)
            dept = (self.depts[max(counts, key=counts.get)] if counts else fallback)
            if user.department_id != dept.id:
                user.department = dept
                user.save(update_fields=["department"])
                updated += 1
        self.stdout.write(f"  colleges: {len(self.depts)} | faculty routed: {updated}")

    # -- 2. Deans, HR, Checkers, Guards ---------------------------------------
    def _person(self, username, first, last, role, dept=None):
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": f"{username}@mcm.edu.ph", "first_name": first,
                      "last_name": last, "role": role, "is_active": True})
        changed = []
        for field, value in (("first_name", first), ("last_name", last),
                             ("role", role), ("department", dept),
                             ("is_active", True)):
            if getattr(user, field if field != "department" else "department_id") != (
                    value.id if field == "department" and value else value):
                setattr(user, field, value)
                changed.append(field)
        if changed and not created:
            user.save()
        elif created:
            user.department = dept
            user.save()
        return user

    def step_staff(self):
        self.deans = {}
        for (code, _n, _p), (first, last) in zip(COLLEGES, DEAN_NAMES):
            self.deans[code] = self._person(
                f"dean.{code.lower()}", first, last, Role.DEAN, self.depts[code])

        for i, (first, last) in enumerate(HR_NAMES, start=1):
            self._person(f"hr{i}", first, last, Role.HR_ADMIN)

        self.checkers = [
            self._person(f"checker{i}", f, l, Role.CHECKER)
            for i, (f, l) in enumerate(CHECKER_NAMES, start=1)]
        self.guards = [
            self._person(f"guard{i}", f, l, Role.GUARD)
            for i, (f, l) in enumerate(GUARD_NAMES, start=1)]
        self.stdout.write(
            f"  staff: {len(self.deans)} deans, {len(HR_NAMES)} HR, "
            f"{len(self.checkers)} checkers, {len(self.guards)} guards")

    # -- 3. Modality mix, with clash-free rooms --------------------------------
    def step_modality_mix(self):
        """60% face-to-face / 20% blended / 20% online.

        The importer put every online section in a virtual room, which made 65%
        of the campus look online and left the physical board almost empty. Here
        the split is re-drawn and rooms follow the modality: a room-based class
        gets a real room that is FREE at its own day+time (no double-booking),
        an online class moves to a virtual room.
        """
        physical = list(Room.objects.exclude(code__startswith="V")
                        .order_by("floor__building__code", "code"))
        virtual = list(Room.objects.filter(code__startswith="V").order_by("code"))
        if not physical or not virtual:
            raise CommandError("Need both physical and virtual rooms.")

        schedules = list(Schedule.objects.filter(
            term=self.term, status=ScheduleStatus.ACTIVE).order_by("id"))
        self.rng.shuffle(schedules)

        n = len(schedules)
        n_f2f, n_blended = int(n * 0.60), int(n * 0.20)
        plan = ([Modality.F2F] * n_f2f
                + [Modality.BLENDED] * n_blended
                + [Modality.ONLINE] * (n - n_f2f - n_blended))

        # slot -> rooms already taken, so a physical room is never double-booked.
        taken = defaultdict(set)
        v_cursor = 0
        updates = []
        for sch, modality in zip(schedules, plan):
            sch.modality = modality
            slot = (sch.day_of_week, sch.start_time)
            if modality == Modality.ONLINE:
                sch.room = virtual[v_cursor % len(virtual)]
                v_cursor += 1
            else:
                room = next((r for r in physical if r.id not in taken[slot]), None)
                if room is None:
                    # Every physical room busy at this slot: fall back to online
                    # rather than invent a double-booking.
                    sch.modality = Modality.ONLINE
                    sch.room = virtual[v_cursor % len(virtual)]
                    v_cursor += 1
                else:
                    taken[slot].add(room.id)
                    sch.room = room
            updates.append(sch)

        Schedule.objects.bulk_update(updates, ["modality", "room"], batch_size=UPDATE_BATCH)

        counts = defaultdict(int)
        for s in updates:
            counts[s.modality] += 1
        self.stdout.write(
            "  modality: " + ", ".join(
                f"{k} {v} ({100 * v / n:.0f}%)" for k, v in sorted(counts.items())))

    # -- 4. Sessions from term start to today ----------------------------------
    def step_sessions(self, keep=False):
        if not keep:
            _purge_queryset(Session.objects.filter(schedule__term=self.term))

        schedules = list(Schedule.objects.filter(
            term=self.term, status=ScheduleStatus.ACTIVE
        ).select_related("room", "faculty"))

        # History up to today, plus the same 14-day forward horizon the
        # materialize job maintains -- so the board and timetable have a future
        # without contradicting how the scheduler actually behaves.
        start = max(self.term.start_date, self.today - timedelta(days=120))
        end = min(self.term.end_date, self.today + timedelta(days=14))

        rows = []
        for sch in schedules:
            day = start
            while day.weekday() != sch.day_of_week:
                day += timedelta(days=1)
            while day <= end:
                rows.append(Session(
                    schedule=sch, faculty_id=sch.faculty_id, room_id=sch.room_id,
                    date=day,
                    scheduled_start=timezone.make_aware(
                        datetime.combine(day, sch.start_time)),
                    scheduled_end=timezone.make_aware(
                        datetime.combine(day, sch.end_time)),
                    status=SessionStatus.SCHEDULED))
                day += timedelta(days=7)

        Session.objects.bulk_create(rows, batch_size=CREATE_BATCH)
        self.stdout.write(f"  sessions: {len(rows)} ({start} -> {end})")

    # -- 5. Attendance outcomes -------------------------------------------------
    def step_attendance(self):
        """~88% present, ~8% absent, ~4% late, plus a few habitual offenders.

        Without the offenders every faculty member scores the same and the
        scorecard, the HR flags and the board's red states have nothing to point
        at -- the features would look built but never demonstrate anything.
        """
        faculty_ids = list(
            Schedule.objects.filter(term=self.term, status=ScheduleStatus.ACTIVE)
            .values_list("faculty_id", flat=True).distinct())
        self.rng.shuffle(faculty_ids)
        self.problem_faculty = set(faculty_ids[:7])

        now = timezone.now()
        done, absent, late = [], [], []
        for s in Session.objects.filter(
                schedule__term=self.term,
                scheduled_end__lt=now).select_related("schedule").iterator():
            bad = s.faculty_id in self.problem_faculty
            roll = self.rng.random()
            absent_p = 0.45 if bad else 0.08
            late_p = 0.20 if bad else 0.04

            if roll < absent_p:
                s.status = SessionStatus.ABSENT
                absent.append(s)
                continue

            s.status = SessionStatus.COMPLETED
            if roll < absent_p + late_p:
                delay = self.rng.randint(16, 40)          # past the grace window
                late.append(s)
            else:
                delay = self.rng.randint(-4, 9)
            s.actual_start = s.scheduled_start + timedelta(minutes=delay)
            s.actual_end = s.scheduled_end - timedelta(
                minutes=self.rng.choice([0, 0, 0, 5, 12]))
            effective = s.declared_modality or s.schedule.modality
            s.checkin_method = (
                CheckinMethod.ONLINE_MANUAL if effective == Modality.ONLINE
                else self.rng.choice([CheckinMethod.QR_SCAN, CheckinMethod.QR_SCAN,
                                      CheckinMethod.MANUAL_CODE]))
            done.append(s)

        Session.objects.bulk_update(
            done, ["status", "actual_start", "actual_end", "checkin_method"],
            batch_size=UPDATE_BATCH)
        Session.objects.bulk_update(absent, ["status"], batch_size=UPDATE_BATCH)

        # Whatever is running right now should read as running.
        active = list(Session.objects.filter(
            schedule__term=self.term,
            scheduled_start__lte=now, scheduled_end__gt=now,
            status=SessionStatus.SCHEDULED)[:400])
        for s in active:
            if self.rng.random() < 0.85:
                s.status = SessionStatus.ACTIVE
                s.actual_start = s.scheduled_start + timedelta(
                    minutes=self.rng.randint(-3, 8))
                s.checkin_method = CheckinMethod.QR_SCAN
        Session.objects.bulk_update(
            active, ["status", "actual_start", "checkin_method"], batch_size=UPDATE_BATCH)

        self.stdout.write(
            f"  attendance: {len(done)} held ({len(late)} late), {len(absent)} absent, "
            f"{len(active)} in progress | {len(self.problem_faculty)} problem faculty")

    # -- 6. Checker validations -------------------------------------------------
    def step_validations(self):
        _purge_queryset(
            CheckerValidation.objects.filter(session__schedule__term=self.term)
        )
        rows = []
        held = (Session.objects
                .filter(schedule__term=self.term,
                        status__in=[SessionStatus.COMPLETED, SessionStatus.ACTIVE])
                .select_related("room")
                .order_by("-date")[:2500])
        for s in held:
            if self.rng.random() > 0.55:
                continue
            rows.append(CheckerValidation(
                session=s, room=s.room,
                checker=self.rng.choice(self.checkers),
                action=ValidationAction.VERIFIED,
                identity_match=True,
                scanned_at=s.actual_start or s.scheduled_start))
        # A few honest contradictions, so the flag path is not hypothetical.
        for s in Session.objects.filter(
                schedule__term=self.term, status=SessionStatus.ABSENT)[:60]:
            rows.append(CheckerValidation(
                session=s, room=s.room, checker=self.rng.choice(self.checkers),
                action=ValidationAction.FLAG_NOT_PRESENT, identity_match=False,
                note="Room empty at check.", scanned_at=s.scheduled_start))
        CheckerValidation.objects.bulk_create(rows, batch_size=CREATE_BATCH)
        self.stdout.write(f"  validations: {len(rows)}")

    # -- 7. Duty rosters ---------------------------------------------------------
    def step_duty(self):
        _purge_queryset(Assignment.objects.filter(term=self.term))
        floors = list(Floor.objects.select_related("building")
                      .exclude(building__code="ONLINE").order_by("building__code", "number"))
        made = 0
        for i, floor in enumerate(floors):
            person = self.checkers[i % len(self.checkers)]
            a = Assignment.objects.create(
                user=person, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
                scope=AssignmentScope.FLOOR, term=self.term, status="active")
            a.floors.add(floor)
            made += 1
        for i, floor in enumerate(floors[::2]):
            g = self.guards[i % len(self.guards)]
            a = Assignment.objects.create(
                user=g, role=DutyRole.GUARD, type=AssignmentType.STANDING,
                scope=AssignmentScope.FLOOR, term=self.term, status="active")
            a.floors.add(floor)
            made += 1
        # Online verification duty, so the Checker's online list is not empty.
        for c in self.checkers[:3]:
            Assignment.objects.create(
                user=c, role=DutyRole.CHECKER, type=AssignmentType.STANDING,
                scope=AssignmentScope.ONLINE, term=self.term, status="active")
            made += 1
        self.stdout.write(f"  duty assignments: {made} across {len(floors)} floors")

    # -- 8. Modality-shift requests ---------------------------------------------
    def step_shift_requests(self):
        """A spread across every status, so the Dean queue has something pending
        AND a decided history to page through."""
        _purge_queryset(
            ModalityShiftRequest.objects
            .filter(items__schedule__term=self.term)
            .distinct()
        )
        schedules = list(Schedule.objects.filter(
            term=self.term, status=ScheduleStatus.ACTIVE
        ).select_related("faculty", "faculty__department", "room")[:600])
        self.rng.shuffle(schedules)

        mix = ([ModalityShiftStatus.PENDING] * 14
               + [ModalityShiftStatus.APPROVED] * 16
               + [ModalityShiftStatus.REJECTED] * 5
               + [ModalityShiftStatus.WITHDRAWN] * 3
               + [ModalityShiftStatus.DENIED] * 2)
        reasons = {
            ModalityShiftStatus.REJECTED: "Section needs the lab equipment on site.",
            ModalityShiftStatus.DENIED: "No free room at that slot for the whole window.",
        }
        made = 0
        for sch, status in zip(schedules, mix):
            dept = sch.faculty.department
            dean = self.deans.get(dept.code) if dept else None
            if dean is None:
                continue
            target = self.rng.choice([Modality.ONLINE, Modality.ONLINE, Modality.F2F])
            offset = self.rng.randint(2, 16)
            start = self.today + timedelta(days=offset)
            req = ModalityShiftRequest.objects.create(
                requester=sch.faculty, dean=dean, department=dept,
                target_modality=target,
                window_start=start,
                window_end=start + timedelta(days=self.rng.choice([0, 7, 14])),
                status=status,
                decision_reason=reasons.get(status, ""),
            )
            if status not in (ModalityShiftStatus.PENDING,):
                req.decided_at = timezone.now() - timedelta(
                    days=self.rng.randint(1, 12))
                req.decided_by = (sch.faculty
                                  if status == ModalityShiftStatus.WITHDRAWN else dean)
                req.save(update_fields=["decided_at", "decided_by"])
            ModalityShiftItem.objects.create(
                request=req, schedule=sch,
                assigned_room=sch.room if (
                    status == ModalityShiftStatus.APPROVED
                    and target != Modality.ONLINE) else None)
            made += 1
        self.stdout.write(f"  modality-shift requests: {made}")

    # -- 9. Notifications ---------------------------------------------------------
    def step_notifications(self):
        _purge(Notification)
        rows = []
        pending = (ModalityShiftRequest.objects.filter(
            items__schedule__term=self.term,
            status=ModalityShiftStatus.PENDING)
            .select_related("dean", "requester")
            .distinct())
        for req in pending:
            if req.dean_id:
                rows.append(Notification(
                    user_id=req.dean_id, type="modality_request",
                    title="Shift request awaiting your approval",
                    body=f"{req.requester.get_full_name() or req.requester.username} "
                         f"requested a shift to {req.get_target_modality_display()}.",
                    link="/dean/requests"))
        decided = (ModalityShiftRequest.objects.filter(
            items__schedule__term=self.term)
            .exclude(status=ModalityShiftStatus.PENDING)
            .select_related("requester")
            .distinct()[:40])
        for req in decided:
            rows.append(Notification(
                user_id=req.requester_id, type="modality_decision",
                title=f"Your shift request was {req.get_status_display().lower()}",
                body=req.decision_reason or "See your requests for details.",
                link="/faculty/modality/mine",
                read_at=timezone.now() if self.rng.random() < 0.5 else None))
        Notification.objects.bulk_create(rows, batch_size=CREATE_BATCH)
        self.stdout.write(f"  notifications: {len(rows)}")

    # -- 10. Scheduler job history ------------------------------------------------
    def step_jobruns(self):
        _purge(JobRun)
        rows = []
        now = timezone.now()
        cadence = {"materialize": 1440, "sweep": 5, "weekly_report": 10080,
                   "push_outbox": 15}
        for name, minutes in cadence.items():
            stamp = now
            for i in range(40 if minutes <= 15 else 12):
                started = stamp - timedelta(minutes=minutes * i)
                if started < now - timedelta(days=21):
                    break
                failed = self.rng.random() < 0.04
                rows.append(JobRun(
                    job_name=name,
                    status="failed" if failed else "ok",
                    started_at=started,
                    finished_at=started + timedelta(
                        seconds=self.rng.uniform(0.2, 4.5)),
                    rows_affected=0 if failed else self.rng.randint(0, 240),
                    detail=("ConnectionError: RDS handshake timed out after 30s"
                            if failed else ""),
                ))
        JobRun.objects.bulk_create(rows, batch_size=CREATE_BATCH)
        self.stdout.write(f"  job runs: {len(rows)}")

    # -- summary --------------------------------------------------------------
    def summary(self):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Term seeded."))
        self.stdout.write(
            "  Generate weekly reports next:\n"
            "    manage.py generate_weekly_report\n"
            "  (run it once per completed week to fill IFO > Weekly reports)")

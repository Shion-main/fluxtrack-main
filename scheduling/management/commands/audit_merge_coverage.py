"""Empirical online D-01 coverage audit (Phase 04.2 Plan 04, criterion #3).

This is the READ-ONLY check an operator runs against the live loaded term to
prove that the pure D-01 detector (``scheduling.merge.merged_sibling_ids``)
catches every real online co-scheduled ("merged") group WITHOUT any ``teams_link``
clause. Per D-01 refinement #2 (owner decision after this audit first exposed the
gap -- 48/152 online groups were missed by the old room-OR-course key): two
effective-online sessions with the same faculty and exact start ARE a merge, so
the detector's ONLINE arm covers them regardless of room or course.

For every 2+ group of effective-online sessions sharing the SAME faculty and the
SAME exact ``scheduled_start`` in the ACTIVE term, it asks: does the union of one
anchor plus its D-01 siblings span the WHOLE group? Under the online arm the
answer is always yes, so a MISSED line now signals a REGRESSION (the online arm
was weakened) rather than an accepted gap -- criterion #3 must stay at 0 MISSED.

The command mutates NOTHING: it opens no ``transaction.atomic()``, calls no
``.update()``/``.save()``, and creates no ``AuditLog`` (T-04.2-06). Output is a
coverage summary plus a per-group MISSED escalation line; a non-empty MISSED set
raises ``CommandError`` so the process exits non-zero for CI/operator alerting.

ASCII-only by convention (Windows cp1252).

Usage:
    py -3.12 manage.py audit_merge_coverage
"""
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from scheduling.merge import merged_sibling_ids
from scheduling.models import AcademicTerm, Modality, Session


def _effective_modality(session):
    """Declared modality wins; otherwise the schedule's modality (SCAN-01 rule)."""
    return session.declared_modality or session.schedule.modality


class Command(BaseCommand):
    help = ("Audit that D-01 catches every online merged group in the active "
            "term (read-only, criterion #3).")

    def handle(self, *args, **o):
        term = AcademicTerm.objects.filter(is_active=True).first()
        if term is None:
            self.stdout.write("audit_merge_coverage: no active term -> nothing to audit.")
            return

        # READ-ONLY select: every session in the active term, joined to its
        # schedule so course_code / schedule.modality are available in Python.
        sessions = list(
            Session.objects.filter(schedule__term=term).select_related("schedule")
        )
        online = [s for s in sessions if _effective_modality(s) == Modality.ONLINE]
        for s in online:
            # Attach course_code + is_online so the pure D-01 detector can read
            # both arms. Every session here is effective-online by construction,
            # so is_online is True; the detector's online arm (D-01 refinement #2)
            # then merges same-faculty/same-start online rows regardless of room
            # or course. This command stays a live regression guard: if the online
            # arm is ever removed, distinct-both groups resurface as MISSED.
            s.course_code = s.schedule.course_code
            s.is_online = True

        # Group effective-online sessions by (faculty, exact scheduled_start).
        groups = defaultdict(list)
        for s in online:
            groups[(s.faculty_id, s.scheduled_start)].append(s)

        total_groups = 0
        caught = 0
        missed = []  # (faculty_id, scheduled_start, anchor, uncovered_ids)
        for (faculty_id, start), members in groups.items():
            if len(members) < 2:
                continue  # a lone online session is not a merged group
            total_groups += 1
            anchor = members[0]
            sib_ids = merged_sibling_ids(anchor, members[1:])
            covered = {anchor.id} | sib_ids
            member_ids = {m.id for m in members}
            if covered == member_ids:
                caught += 1
            else:
                missed.append((faculty_id, start, anchor, member_ids - covered))

        self.stdout.write(f"audit_merge_coverage: active term '{term.name}'")
        self.stdout.write(f"  online same-start groups (2+): {total_groups}")
        self.stdout.write(self.style.SUCCESS(f"  fully CAUGHT by D-01: {caught}"))
        self.stdout.write(f"  MISSED (share only teams_link / distinct-both): {len(missed)}")
        for faculty_id, start, anchor, uncovered in missed:
            self.stdout.write(self.style.ERROR(
                f"  MISSED faculty={faculty_id} start={start} "
                f"anchor_course={anchor.schedule.course_code} "
                f"uncovered_session_ids={sorted(uncovered)}"))

        if missed:
            # Non-zero exit surfaces the D-01 gap to the operator / CI.
            raise CommandError(
                f"{len(missed)} online merged group(s) NOT caught by D-01 "
                f"(criterion #3 gap) -- see MISSED lines above.")

        self.stdout.write(self.style.SUCCESS(
            "All online merged groups are CAUGHT by D-01 (criterion #3 holds)."))

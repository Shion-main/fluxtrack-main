"""
Run the JOB-02 status sweep once (JOB-02b + JOB-02c).

Thin ASCII-only wrapper around scheduling.jobs.sweep_no_shows +
detect_room_conflicts. The dedicated scheduler (Phase 2.5) registers
sweep_no_shows on an interval; this command is the manual / one-shot entry point.

It shares ONE collector across both sweep functions and then fans out once, so a
manual run behaves identically to a scheduled one -- the GRD-04 coalescing must
not depend on which entry point was used (D-06).

Usage:
    py -3.12 manage.py run_status_sweep
"""
from django.core.management.base import BaseCommand

from ops.guard_alerts import notify_floor_guards
from scheduling.jobs import detect_room_conflicts, sweep_no_shows


class Command(BaseCommand):
    help = "Mark unscanned no-shows Absent and flag room conflicts (JOB-02)."

    def handle(self, *args, **o):
        events = []
        marked = sweep_no_shows(collect=events)
        flagged = detect_room_conflicts(collect=events)
        guards = notify_floor_guards(events)
        self.stdout.write(self.style.SUCCESS(
            f"Sweep: marked {marked} absent -> flagged {flagged} conflicts "
            f"-> notified {guards} guards."))

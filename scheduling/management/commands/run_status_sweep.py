"""
Run the JOB-02 status sweep once (JOB-02b + JOB-02c).

Thin ASCII-only wrapper around scheduling.jobs.sweep_no_shows +
detect_room_conflicts. The dedicated scheduler (Phase 2.5) registers
sweep_no_shows on an interval; this command is the manual / one-shot entry point.

Usage:
    py -3.12 manage.py run_status_sweep
"""
from django.core.management.base import BaseCommand

from scheduling.jobs import detect_room_conflicts, sweep_no_shows


class Command(BaseCommand):
    help = "Mark unscanned no-shows Absent and flag room conflicts (JOB-02)."

    def handle(self, *args, **o):
        marked = sweep_no_shows()
        flagged = detect_room_conflicts()
        self.stdout.write(self.style.SUCCESS(
            f"Sweep: marked {marked} absent -> flagged {flagged} conflicts."))

"""Daily online-session round-robin assignment pass (IFO-06, 03-RESEARCH Pattern 3).

Runs ``verification.services.assign_online_sessions`` for each date across a window
(default today .. today + materialization_horizon_days). This is the lightweight
standalone pass so an online-duty roster set AFTER materialization still picks up
its sessions, even without an IFO save. Idempotent (already-owned sessions are
skipped by the service). ASCII-only output (no Unicode).

Usage:
    py -3.12 manage.py assign_online
    py -3.12 manage.py assign_online --from 2026-07-06 --days 7
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from ops.policy import get_policy
from scheduling.term_scope import get_active_term
from verification.services import assign_online_sessions


class Command(BaseCommand):
    help = "Round-robin assign online sessions to online-duty checkers (IFO-06)."

    def add_arguments(self, p):
        p.add_argument("--days", type=int, default=None,
                       help="Horizon in days (default materialization_horizon_days).")
        p.add_argument("--from", dest="start",
                       help="Start date YYYY-MM-DD (default today).")

    def handle(self, *args, **o):
        if get_active_term() is None:
            self.stdout.write(
                "assign_online: no ACTIVE academic term; no sessions assigned."
            )
            return

        start = (datetime.strptime(o["start"], "%Y-%m-%d").date()
                 if o["start"] else timezone.localdate())
        days = (o["days"] if o["days"] is not None
                else get_policy("materialization_horizon_days"))

        total_assigned = total_unassigned = 0
        d = start
        for _ in range(days + 1):
            result = assign_online_sessions(d)
            total_assigned += result["assigned"]
            total_unassigned += result["unassigned"]
            if result["assigned"] or result["unassigned"]:
                self.stdout.write(
                    f"  {d} -> assigned {result['assigned']}, "
                    f"unassigned {result['unassigned']}")
            d += timedelta(days=1)

        self.stdout.write(self.style.SUCCESS(
            f"assign_online {start} -> {d - timedelta(days=1)}: "
            f"{total_assigned} assigned, {total_unassigned} unassigned (flagged IFO)."))

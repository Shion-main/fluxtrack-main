"""One-off operator command: bind a seeded User to a real MMCM UPN (D-07).

Repoints a seeded user's ``email`` to a real Entra UPN so that the first Entra
login's ``associate_by_email`` step matches the seeded slot (D-05 email-match
bridge). Reversible (re-run with a different UPN) and idempotent (re-run with the
same UPN prints a no-change line and exits 0).

This command does NOT mutate ``seed_demo.py`` — the committed demo seed stays
synthetic (D-07). The email edit is a runtime data change only.

Output is ASCII-only (Convention #4 — the Windows console is cp1252): uses ``->``
arrows, no Unicode/emoji.

Usage:
    manage.py link_entra <username> <upn>
    manage.py link_entra mayo jane.mayo@mcm.edu.ph
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email


class Command(BaseCommand):
    help = ("Repoint a seeded user's email to a real MMCM UPN so Entra email-match "
            "linking (associate_by_email) binds the seeded slot (D-07). Idempotent; "
            "does not mutate seed_demo.py.")

    def add_arguments(self, parser):
        parser.add_argument("username", help="Seeded username to link (e.g. mayo).")
        parser.add_argument("upn", help="Real MMCM UPN / email to bind (e.g. jane.mayo@mcm.edu.ph).")

    def handle(self, *args, **o):
        User = get_user_model()

        try:
            validate_email(o["upn"])
        except ValidationError:
            raise CommandError(f"Invalid UPN/email: {o['upn']}")

        try:
            user = User.objects.get(username=o["username"])
        except User.DoesNotExist:
            raise CommandError(f"No user with username '{o['username']}'")

        clash = User.objects.filter(email__iexact=o["upn"]).exclude(pk=user.pk)
        if clash.exists():
            raise CommandError(f"UPN already used by: {clash.first().username}")

        if user.email == o["upn"]:
            self.stdout.write(self.style.SUCCESS(
                f"No change -> {user.username} already {o['upn']}"))
            return

        user.email = o["upn"]
        user.save(update_fields=["email"])
        self.stdout.write(self.style.SUCCESS(f"Linked {user.username} -> {o['upn']}"))

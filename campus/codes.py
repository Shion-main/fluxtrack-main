"""The single minting path for a Room's opaque manual code.

`Room.manual_code` is `unique=True` (campus/models.py) — a six-digit code a
faculty member types when the QR will not scan. Minting it as a bare
`secrets.randbelow(1000000)` and inserting straight into the unique column is a
live defect, not a theoretical one: with ~218 rooms in a 10**6 space the
birthday probability of a collision is ~2.3% per full-term room load, and it
was observed failing `LoadRoomMasterTests` with

    Violation of UNIQUE KEY constraint 'UQ_campus_room_manual_code'.
    Cannot insert duplicate key ... (814918)

Intermittent at that rate, which is exactly why it read as a flaky test rather
than a bug for several phases.

`generate_manual_code()` is the ONE place a manual code is minted, mirroring the
project's existing shared-atom convention (`is_no_show_past_grace`, `csv_safe`):
the room-master importer and the IFO-02 rotation surface must never disagree
about how a code is produced, or rotation reintroduces the collision the
importer just fixed.

**Why a pre-check and not catch-IntegrityError-and-retry.** The importer runs
its whole load inside one `@transaction.atomic` block. On SQL Server an
IntegrityError inside an atomic block poisons the transaction — recovering
would require an explicit savepoint per room. The realistic collision is
between rows created in the SAME run, and a `.exists()` probe inside that
transaction DOES see rows already inserted by it, so a pre-check resolves the
observed failure without any savepoint machinery.

`qr_token` needs no equivalent helper: `secrets.token_urlsafe(24)` is 192 bits
of entropy and its collision probability is negligible.
"""
import secrets

MANUAL_CODE_DIGITS = 6
MANUAL_CODE_SPACE = 10 ** MANUAL_CODE_DIGITS

# Bounded so a pathologically full/degenerate code space fails loudly with a
# named domain error instead of spinning forever inside a DB transaction.
MAX_ATTEMPTS = 10


class ManualCodeExhausted(RuntimeError):
    """No free manual code found within MAX_ATTEMPTS draws."""


def generate_manual_code(attempts=MAX_ATTEMPTS):
    """Return a six-digit manual code not currently held by any Room.

    Raises ManualCodeExhausted if every draw collided — at realistic occupancy
    that is effectively impossible, so it signals a degenerate code space (or a
    caller looping on a poisoned transaction) rather than bad luck.
    """
    # Imported lazily: this module is imported from management commands and
    # views, and a module-level model import would couple it to app-registry
    # readiness for no benefit.
    from campus.models import Room

    for _ in range(attempts):
        candidate = f"{secrets.randbelow(MANUAL_CODE_SPACE):0{MANUAL_CODE_DIGITS}d}"
        if not Room.objects.filter(manual_code=candidate).exists():
            return candidate
    raise ManualCodeExhausted(
        f"No free manual code after {attempts} attempts "
        f"({Room.objects.count()} rooms in a {MANUAL_CODE_SPACE} code space)."
    )


def new_room_credentials():
    """Return a fresh ``(qr_token, manual_code)`` pair for a Room.

    The single place both halves of a room's scan credentials are minted, so
    room-create (IFO-01b) and code rotation (IFO-02) cannot drift apart from
    the importers.

    Only the manual code retries. `token_urlsafe(24)` is 192 bits of entropy,
    so its collision probability is negligible — the retry effort is spent
    deliberately on the six-digit code, where the birthday arithmetic actually
    bites.
    """
    return secrets.token_urlsafe(24), generate_manual_code()

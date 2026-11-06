"""Safe readers for untrusted request values.

Two traps made these necessary. ``parse_date``/``parse_time`` return None only for
text of the wrong shape; "2026-02-31" and "25:99" have the right shape and raise
ValueError. ``str.isdigit`` is true for characters such as a superscript two, which
``int()`` rejects, and it accepts numbers too large for the database driver.
"""
from django.utils.dateparse import parse_date, parse_time

_MAX_DB_ID = 2 ** 63 - 1


def safe_parse_date(raw):
    """The date in ``raw``, or None for any bad input."""
    try:
        return parse_date(raw)
    except ValueError:
        return None


def safe_parse_time(raw):
    """The time in ``raw``, or None for any bad input."""
    try:
        return parse_time(raw)
    except ValueError:
        return None


def is_id(raw):
    """True when ``raw`` is a plain whole number a database key could hold."""
    text = str(raw if raw is not None else "")
    return text.isascii() and text.isdigit() and int(text) <= _MAX_DB_ID

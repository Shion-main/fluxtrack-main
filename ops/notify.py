"""Shared notification write path (NOTIF-00).

`notify()` is the single place a `Notification` row is created. It targets EITHER
a role (fan out to every ACTIVE user of that role, reproducing the old
`_notify_ifo` query exactly) OR an explicit user iterable. Every later writer —
the sweep's room-conflict flags, job-failure alerts, and the Phase 4/5 notices —
routes through here so notification provenance stays centralized and auditable.

It deliberately does NOT emit its own `AuditLog`: the domain action that triggers
a notification (e.g. `session.room_changed`, `session.force_handover`) already
carries the audit row, so auditing here would double every event.
"""
from django.contrib.auth import get_user_model

from ops.models import Notification


def notify(*, type, title, body="", link="", role=None, users=None):
    """Create one Notification per recipient and return the created list (NOTIF-00).

    Recipients are the explicit ``users`` iterable (if given) PLUS every active
    user of ``role`` (if given: ``filter(role=role, is_active=True)``). Passing
    neither ``role`` nor ``users`` creates nothing and returns an empty list.

    Keyword-only by design so call sites read self-documenting. This is the only
    permitted caller of the Notification-model create path.
    """
    recipients = list(users) if users is not None else []
    if role is not None:
        recipients += list(
            get_user_model().objects.filter(role=role, is_active=True))
    return [
        Notification.objects.create(
            user=u, type=type, title=title, body=body, link=link)
        for u in recipients
    ]

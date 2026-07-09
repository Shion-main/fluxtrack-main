"""Global template context for the notification bell (NOTIF-01).

The bell is a GLOBAL surface: it renders on every authenticated page across BOTH
shells (the faculty app-shell and the standard header shell), so its context
CANNOT be supplied per-view -- it must come from a context processor
(RESEARCH Pitfall 4). This module exposes exactly the three values every page
needs: the htmx poll cadence, the current unread count, and the VAPID public key
the 05-05 soft-prompt banner consumes.
"""
from django.conf import settings

from ops.notifications import unread_count
from ops.policy import get_policy


def notifications(request):
    """Supply poll_ms + unread + vapid_public_key to every rendered page (NOTIF-01).

    - `poll_ms`: the checker/IFO poll cadence in milliseconds, reusing the single
      policy value (Convention #3, D-02) -- never a hardcoded interval.
    - `unread`: the user's visible unread count (mute-filtered via visible_qs),
      or 0 for AnonymousUser so the login page never hits the DB (guarded).
    - `vapid_public_key`: empty-safe key exposed for the 05-05 push subscribe flow.
    """
    user = getattr(request, "user", None)
    unread = unread_count(user) if user is not None and user.is_authenticated else 0
    return {
        "poll_ms": get_policy("poll_interval_seconds") * 1000,
        "unread": unread,
        "vapid_public_key": getattr(settings, "VAPID_PUBLIC_KEY", ""),
    }

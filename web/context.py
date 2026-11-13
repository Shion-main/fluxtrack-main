"""Global template context for the notification bell (NOTIF-01).

The bell is a GLOBAL surface: it renders on every authenticated page across BOTH
shells (the faculty app-shell and the standard header shell), so its context
CANNOT be supplied per-view -- it must come from a context processor
(RESEARCH Pitfall 4). This module exposes exactly the three values every page
needs: the htmx poll cadence, the current unread count, and the VAPID public key
the 05-05 soft-prompt banner consumes.
"""
from django.conf import settings

from accounts.models import Role

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
        "app_is_production": settings.IS_PRODUCTION,
        "poll_ms": get_policy("poll_interval_seconds") * 1000,
        "unread": unread,
        "vapid_public_key": getattr(settings, "VAPID_PUBLIC_KEY", ""),
    }



# The ONE rule for which console shell a desk user gets ("Share one rule").
# Floor roles (Faculty, Checker, Guard) and anonymous users get None: they use
# the navy floor shell. A superuser with no role is a system administrator.
_CONSOLE_BY_ROLE = {
    Role.IFO_ADMIN: "ifo/_console.html",
    Role.DEAN: "dean/_console.html",
    Role.HR_ADMIN: "hr/_console.html",
    Role.SYSTEM_ADMIN: "sys/_console.html",
}


def role_console(request):
    """Supply `console_template` (str | None) to every rendered page."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {"console_template": None}
    template = _CONSOLE_BY_ROLE.get(user.role)
    if template is None and user.is_superuser and not user.role:
        template = "sys/_console.html"
    return {"console_template": template}

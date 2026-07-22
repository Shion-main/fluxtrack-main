"""Notification read surface (NOTIF-01) + mute settings (NOTIF-03).

One module per surface (Convention): the polled bell, the auto-read-on-open
dropdown and full-page history, and the per-user mute settings. Every view is
`@login_required` and strictly scoped to `request.user` -- notifications are
queried only through `visible_qs(request.user)`, never by a client-supplied PK,
so a user can never read another user's rows (threat T-05-09, access-control V4).

Read semantics (D-02/D-03): the bell POLL is READ-ONLY and never clears the
badge; only OPENING the dropdown or the full page marks the shown rows read. All
mark-read and mute writes are AUDIT-SILENT by design -- a sanctioned exception to
Convention #2 mirroring notify()'s own no-audit rule (the domain actions that
spawned these notifications already carry their own AuditLog).
"""
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import Role
from ops.models import NotificationMute
from ops.notifications import (NotificationCategory, _mark_read, unread_count,
                               visible_qs)

# UI slice sizes for the bell preview and the full-page history. These are
# presentation limits, not tunable business policy (grace/rate/horizon/poll),
# so they live as module constants (Convention #Constants), not SystemSetting.
PREVIEW_LIMIT = 5
LIST_LIMIT = 50

_FLOOR_HOME_BY_ROLE = {
    Role.FACULTY: "/faculty/home",
    Role.CHECKER: "/checker/floor",
    Role.GUARD: "/guard/monitor",
}


def _page_context(user, **context):
    """Add role-aware chrome data to full-page notification surfaces."""
    floor_home_url = _FLOOR_HOME_BY_ROLE.get(user.role)
    return {
        **context,
        "floor_shell": floor_home_url is not None,
        "floor_home_url": floor_home_url,
    }


@login_required
def bell(request):
    """READ-ONLY poll endpoint: badge count + a compact preview (D-02).

    MUST NOT mark anything read -- the badge only clears on OPEN, never on the
    poll (RESEARCH Anti-Pattern: never mark read on the poll).
    """
    rows = list(visible_qs(request.user)[:PREVIEW_LIMIT])
    return render(request, "notifications/_bell_inner.html", {
        "unread": unread_count(request.user),
        "rows": rows,
    })


@login_required
def dropdown(request):
    """Open the dropdown: render the latest rows, THEN mark them read (D-03).

    Auto-read on open clears the badge for the shown rows. Audit-silent.
    """
    rows = list(visible_qs(request.user)[:PREVIEW_LIMIT])
    response = render(request, "notifications/_rows.html", {"rows": rows})
    _mark_read(request.user.notifications.filter(id__in=[n.id for n in rows]))
    return response


@login_required
def list_page(request):
    """Full-page history over the recent visible rows, THEN mark read (D-03)."""
    rows = list(visible_qs(request.user)[:LIST_LIMIT])
    response = render(
        request,
        "notifications/list.html",
        _page_context(request.user, rows=rows),
    )
    _mark_read(request.user.notifications.filter(id__in=[n.id for n in rows]))
    return response


def _settings_groups(user):
    """The three mute groups with each group's current muted state for `user`."""
    muted = set(user.notification_mutes.values_list("category", flat=True))
    return [
        {"value": c.value, "label": c.label, "muted": c.value in muted}
        for c in NotificationCategory
    ]


@login_required
def settings_page(request):
    """Mute settings: the three category groups + whether each is muted (NOTIF-03)."""
    return render(
        request,
        "notifications/settings.html",
        _page_context(request.user, groups=_settings_groups(request.user)),
    )


@login_required
@require_http_methods(["POST"])
def mute_toggle(request):
    """Toggle a category mute for request.user (NOTIF-03/D-05, presence-as-mute).

    Presence of a NotificationMute row = muted; create if absent, delete if
    present. The posted category is validated against NotificationCategory
    (T-05-11 tampering); an unknown value is rejected 400. Acts only on
    request.user. Audit-silent (deliberate, consistent with the read surface).
    """
    category = request.POST.get("category", "")
    if category not in NotificationCategory.values:
        return HttpResponseBadRequest("invalid category")
    existing = NotificationMute.objects.filter(user=request.user, category=category)
    if existing.exists():
        existing.delete()
    else:
        NotificationMute.objects.create(user=request.user, category=category)
    # Post/Redirect/Get; htmx re-selects #mute-controls from the settings page.
    return redirect("notif_settings")

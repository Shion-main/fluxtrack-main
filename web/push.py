"""Web-push subscription endpoints (NOTIF-02): subscribe / unsubscribe / key.

One module per surface (Convention): the client's push-subscribe flow posts a
PushManager subscription here to persist a PushSubscription row that the 05-03
outbox sender later delivers to. Every endpoint is `@login_required` and acts
ONLY on `request.user`'s own rows -- a client can never create, read, or delete
another user's subscription (threat T-05-09).

State-changing endpoints are `@require_http_methods(["POST"])` and CSRF-protected;
the client sends `X-CSRFToken` explicitly on the raw fetch (RESEARCH Pitfall 5,
T-05-15). subscribe VALIDATES the payload (endpoint must be an https URL, keys
must carry p256dh + auth) and rejects junk with a 400 (T-05-14) so only clean,
sendable rows enter the outbox. Persistence is `update_or_create(endpoint=...)`
so re-subscribing the same endpoint updates rather than duplicates (Pitfall 6).
"""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.views.decorators.http import require_http_methods

from ops.models import PushSubscription


def _parse_json(request):
    """Parse the request body as JSON; return {} on any malformed input."""
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


@login_required
@require_http_methods(["POST"])
def subscribe(request):
    """Persist the caller's PushManager subscription (NOTIF-02, T-05-14).

    Body: {endpoint, keys: {p256dh, auth}}. The endpoint MUST be an https URL and
    keys MUST carry both p256dh and auth, else 400 -- this keeps junk / SSRF-shaped
    rows out of the outbox (T-05-14). Deduped on endpoint via update_or_create so a
    re-subscribe of the same endpoint updates rather than duplicates (Pitfall 6),
    and the row is always (re)bound to request.user.
    """
    data = _parse_json(request)
    endpoint = data.get("endpoint", "")
    keys = data.get("keys", {})
    if (not isinstance(endpoint, str) or not endpoint.startswith("https://")
            or not isinstance(keys, dict)
            or not keys.get("p256dh") or not keys.get("auth")):
        return HttpResponseBadRequest("invalid subscription")
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={"user": request.user, "keys": keys},
    )
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
def unsubscribe(request):
    """Delete the caller's PushSubscription for the posted endpoint (T-05-09).

    Acts ONLY on request.user's own rows -- never a cross-user endpoint deletion.
    Idempotent: unsubscribing an unknown/absent endpoint is a no-op ok.
    """
    data = _parse_json(request)
    endpoint = data.get("endpoint", "")
    if not endpoint:
        return HttpResponseBadRequest("missing endpoint")
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
def vapid_public_key(request):
    """Return the base64url VAPID public key (05-02) the client builds the
    applicationServerKey from. Empty string when push is unconfigured."""
    return JsonResponse({"key": getattr(settings, "VAPID_PUBLIC_KEY", "")})

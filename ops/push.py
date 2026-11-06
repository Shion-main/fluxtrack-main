"""Web-push outbox sender + dead-endpoint pruning (NOTIF-02, criterion #4).

The scan/approval/scheduler code that emits notify() only WRITES Notification
rows; it never sends a push. send_push_outbox() below is invoked ONLY by the
dedicated scheduler process (the runscheduler push_outbox job, D-09), which drains
unpushed key-event rows (D-08 PUSH_TYPES), sends via pywebpush, prunes dead
endpoints, and stamps pushed_at. Because the entire send path lives in the
scheduler -- never in a web worker -- a hung or dead push endpoint is structurally
incapable of touching the triggering web request (criterion #4).

The key-event filter (PUSH_TYPES) and the mute filter (muted_types) are imported
from ops.notifications -- the SAME single source of truth (D-06) the in-app list
uses -- so the push surface and the list surface can never disagree about what a
key event or a muted category is. VAPID crypto is owned entirely by pywebpush
(do-not-hand-roll).
"""
import json
from datetime import timedelta
import requests

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from pywebpush import WebPushException, webpush

from ops.models import Notification
from ops.notifications import PUSH_TYPES, muted_types
from ops.push_validation import valid_endpoint, valid_subscription

# Bound retry work and expire undelivered notifications after one day.
MAX_ATTEMPTS = 6
MAX_AGE = timedelta(days=1)
BATCH_SIZE = 100


class ProviderSession(requests.Session):
    """Never follow a provider redirect to an arbitrary outbound destination."""
    def request(self, method, url, **kwargs):
        if not valid_endpoint(url):
            raise ValueError("Invalid push destination")
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


def _send_one(sub, payload):
    """Return delivered, dead, permanent, or retry; no transient data loss."""
    if not valid_subscription(sub.endpoint, sub.keys):
        return "dead"
    try:
        with ProviderSession() as transport:
            response = webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
                data=json.dumps(payload),
                vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,
                vapid_claims={"sub": settings.VAPID_SUB},
                ttl=600, timeout=10, requests_session=transport)
        status = getattr(response, "status_code", 201)
        if isinstance(status, int) and not 200 <= status < 300:
            return "permanent" if status < 500 and status not in (408, 429) else "retry"
        return "delivered"
    except WebPushException as exc:
        # response may be None (a transport-level failure with no HTTP status).
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return "dead"
        if isinstance(status, int) and 300 <= status < 500 and status not in (408, 429):
            return "permanent"
        return "retry"
    except Exception:     # noqa: BLE001 -- a failed send must never reach the caller
        return "retry"


def send_push_outbox():
    """Drain unpushed key-event Notification rows to web push; return sent count.

    Invoked ONLY by the scheduler's push_outbox job (never inline in a web
    request) -- the structural guarantee behind criterion #4. Selects rows whose
    type is a key event (PUSH_TYPES, D-08), not yet pushed (pushed_at IS NULL),
    and due for delivery. For each row: if the recipient has muted
    the row's category the send is suppressed but pushed_at is still stamped
    (D-05); otherwise the payload is pushed to every subscription and any dead
    endpoint is pruned (D-09). Successful devices are recorded separately while
    transient failures retry with backoff until expiry or the attempt limit.
    Short-circuits to 0 when VAPID is unconfigured (push disabled).
    """
    if not settings.VAPID_PRIVATE_KEY_PATH:
        return 0  # push disabled -- an empty key path means no VAPID configured

    now = timezone.now()
    Notification.objects.filter(type__in=PUSH_TYPES, pushed_at__isnull=True,
        created_at__lt=now-MAX_AGE).update(pushed_at=now, push_error="expired")
    rows = list(Notification.objects
            .filter(type__in=PUSH_TYPES, pushed_at__isnull=True)
            .filter(Q(next_push_at__isnull=True) | Q(next_push_at__lte=now))
            .select_related("user").order_by("created_at", "pk")[:BATCH_SIZE])

    sent = 0
    for n in rows:
        if n.type in muted_types(n.user):
            # D-05: a muted category suppresses the push, but stamp pushed_at so
            # the row is never re-scanned -- no webpush is attempted.
            n.pushed_at = timezone.now()
            n.save(update_fields=["pushed_at"])
            continue
        payload = {"title": n.title, "body": n.body,
                   "link": n.link or "/notifications"}
        delivered = set(n.push_delivered_subscriptions)
        pending, permanent = False, "permanent" in n.push_error
        for sub in list(n.user.push_subscriptions.all().order_by("pk")):
            if sub.pk in delivered:
                continue
            result = _send_one(sub, payload)
            if result == "dead":
                sub.delete()
            elif result == "retry":
                pending = True
            else:
                delivered.add(sub.pk)
                permanent |= result == "permanent"
                n.push_delivered_subscriptions = sorted(delivered)
                n.save(update_fields=["push_delivered_subscriptions"])
        n.push_attempts += 1
        n.push_delivered_subscriptions = sorted(delivered)
        if pending and n.push_attempts < MAX_ATTEMPTS:
            n.next_push_at = now + timedelta(seconds=min(3600, 60 * 2 ** (n.push_attempts-1)))
            n.push_error = "transient and permanent failure" if permanent else "transient failure"
        else:
            n.pushed_at, n.next_push_at = now, None
            n.push_error = "attempt limit" if pending else ("permanent failure" if permanent else "")
            sent += 1
        n.save(update_fields=["pushed_at", "push_attempts", "next_push_at",
                              "push_error", "push_delivered_subscriptions"])
    return sent

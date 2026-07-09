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

from django.conf import settings
from django.utils import timezone
from pywebpush import WebPushException, webpush

from ops.models import Notification
from ops.notifications import PUSH_TYPES, muted_types

# Recent-window bound (D-09): keep-all retention means the outbox must never
# re-scan ancient rows. 15 minutes comfortably covers the ~15s push cadence plus
# misfire grace while keeping every pass O(recent) instead of O(all-time). A
# discretionary constant (mirrors runscheduler's _MATERIALIZE_INTERVAL_HOURS),
# not a tunable policy knob.
_WINDOW_MINUTES = 15


def _send_one(sub, payload):
    """Deliver one push. True = handled (keep the subscription); False = prune.

    Returns False ONLY on a WebPushException whose HTTP status is 404 or 410 (a
    dead endpoint the vendor has expired -- D-09 pruning). Any other failure
    (429/5xx/timeout/network) returns True: the row is treated as handled this
    pass so it is never retried forever, and a merely-flaky vendor never causes a
    live subscription to be dropped (T-05-08). NEVER raises -- a failed send must
    not be able to reach the caller (criterion #4 / T-05-05).
    """
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": sub.keys},
            data=json.dumps(payload),
            vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,
            vapid_claims={"sub": settings.VAPID_SUB},
            ttl=600,
            timeout=10,  # hard cap so a hung endpoint can never stall the job (T-05-05)
        )
        return True
    except WebPushException as exc:
        # response may be None (a transport-level failure with no HTTP status).
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return False  # dead endpoint -> prune (D-09)
        return True       # transient (429/5xx) -> keep for a later pass (T-05-08)
    except Exception:     # noqa: BLE001 -- a failed send must never reach the caller
        return True       # timeout/network -> keep, treat as handled this pass


def send_push_outbox():
    """Drain unpushed key-event Notification rows to web push; return sent count.

    Invoked ONLY by the scheduler's push_outbox job (never inline in a web
    request) -- the structural guarantee behind criterion #4. Selects rows whose
    type is a key event (PUSH_TYPES, D-08), not yet pushed (pushed_at IS NULL),
    and created within the recent window. For each row: if the recipient has muted
    the row's category the send is suppressed but pushed_at is still stamped
    (D-05); otherwise the payload is pushed to every subscription and any dead
    endpoint is pruned (D-09). pushed_at is stamped exactly once per row so it is
    never re-sent. Short-circuits to 0 when VAPID is unconfigured (push disabled).
    """
    if not settings.VAPID_PRIVATE_KEY_PATH:
        return 0  # push disabled -- an empty key path means no VAPID configured

    window = timezone.now() - timedelta(minutes=_WINDOW_MINUTES)
    rows = (Notification.objects
            .filter(type__in=PUSH_TYPES, pushed_at__isnull=True,
                    created_at__gte=window)
            .select_related("user"))

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
        for sub in n.user.push_subscriptions.all():
            if not _send_one(sub, payload):
                sub.delete()  # prune dead endpoint (D-09)
        n.pushed_at = timezone.now()
        n.save(update_fields=["pushed_at"])
        sent += 1
    return sent

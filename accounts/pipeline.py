"""Custom SOCIAL_AUTH_PIPELINE steps: FluxTrack's app-level identity policy.

Encodes the "provisioned-users-only" rule (D-06/AUTH-03/AUTH-05) and the durable
Entra object-id persistence (D-05). The library supplies the OAuth/JWKS/PKCE/linking
primitives; these two steps are the ~all of the app-owned auth logic:

- ``deny_unprovisioned`` runs AFTER ``associate_by_email`` and (because
  ``create_user`` is removed from the pipeline in config/settings.py, Plan 01)
  refuses any tenant identity that has no pre-provisioned, active seeded User by
  raising ``AuthForbidden`` — routed to ``SOCIAL_AUTH_LOGIN_ERROR_URL`` by
  ``SocialAuthExceptionMiddleware`` (D-06/AUTH-03; ``is_active`` covers AUTH-05).
- ``write_azure_oid`` persists ``User.azure_oid`` from ``response['oid']`` — the
  durable Entra object id, NOT the social uid (which is the pairwise ``sub`` claim)
  — idempotently on first successful link and thereafter (D-05).

Both auth security events emit an ``AuditLog`` row (Convention #2 — every
security-relevant event is a durable AuditLog row, not a log line): a refusal
writes ``auth.entra_refused`` (actor=None), a success writes ``auth.entra_login``.
"""
from social_core.exceptions import AuthForbidden

from ops.models import AuditLog


def deny_unprovisioned(strategy, backend, details, user=None, *args, **kwargs):
    """Refuse any tenant identity with no pre-provisioned, active User (D-06/AUTH-03/AUTH-05).

    Sits AFTER ``associate_by_email`` with ``create_user`` removed, so ``user`` is
    None here exactly when the tenant-verified identity matched no seeded User.
    ``not user.is_active`` refuses a deactivated account (AUTH-05 reactivation
    bypass). On refusal, writes an ``auth.entra_refused`` AuditLog row (actor=None,
    attempted email in payload) then raises ``AuthForbidden`` so
    ``SocialAuthExceptionMiddleware`` redirects to ``SOCIAL_AUTH_LOGIN_ERROR_URL``.
    Returns None (pipeline continues) for a provisioned, active user.
    """
    if user is None or not user.is_active:
        AuditLog.objects.create(
            actor=None,
            event_type="auth.entra_refused",
            payload={"email": (details or {}).get("email")},
        )
        raise AuthForbidden(backend)
    return None


def write_azure_oid(strategy, backend, details, response, user=None, *args, **kwargs):
    """Persist the durable Entra object id and audit the successful login (D-05).

    Reads ``response['oid']`` explicitly — the backend's social uid is the pairwise
    ``sub`` claim, NOT the Entra object id. Idempotent: writes ``User.azure_oid``
    only when present and changed. No-ops when ``user`` is None (a refused identity
    never reaches here after ``deny_unprovisioned``, but guard defensively). On a
    non-None-user call, writes an ``auth.entra_login`` AuditLog row (Convention #2).
    ``oid`` may be absent for some tokens (Assumption A1) — then the write is a safe
    no-op and the login still succeeds via the UserSocialAuth uid.
    """
    if user is None:
        return
    oid = (response or {}).get("oid")
    if oid and user.azure_oid != oid:
        user.azure_oid = oid
        user.save(update_fields=["azure_oid"])
    AuditLog.objects.create(
        actor=user,
        event_type="auth.entra_login",
        target_type="user",
        target_id=str(user.pk),
    )
